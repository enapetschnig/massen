"""
Vercel Serverless: PDF-Analyse via Claude Vision.
Minimal - nur Supabase + Anthropic, keine schweren PDF-Libraries.
Claude kann PDFs direkt als base64 lesen.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
import anthropic

# --- Setup ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", os.environ.get("SUPABASE_KEY", ""))
sb = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

def _get_anthropic_key():
    """Get API key from Supabase app_config table."""
    if not sb:
        return ""
    try:
        r = sb.table("app_config").select("value").eq("key", "ANTHROPIC_API_KEY").execute()
        return r.data[0]["value"] if r.data else ""
    except:
        return ""

# --- Claude Vision Prompt ---
VISION_PROMPT = """Du bist der beste Bautechniker Österreichs. Analysiere diesen Bauplan vollständig.

Extrahiere ALLES was du findest:

1. METADATEN: Maßstab (1:50, 1:100...), Geschoss (EG, OG...), Planungsbüro
2. RÄUME: Name, Bodenbelag, Fläche m², Umfang m, Höhe m
3. FENSTER: FE_[Nr] / RPH / FPH / AL[B] / AL[H] / RB[B] / RB[H] (alles in mm)
4. TÜREN: T[Nr] / Breite×Höhe / Typ
5. WANDSTÄRKEN: in mm

Antworte NUR mit validem JSON:
{
  "massstab": "1:100",
  "geschoss": "EG",
  "raeume": [{"name": "...", "bodenbelag": "...", "flaeche_m2": 0, "umfang_m": 0, "hoehe_m": 0, "wandflaeche_m2": 0, "konfidenz": 0.9}],
  "fenster": [{"bezeichnung": "FE_31", "raum": "...", "rph_mm": 0, "fph_mm": 0, "al_breite_mm": 0, "al_hoehe_mm": 0, "rb_breite_mm": 0, "rb_hoehe_mm": 0, "flaeche_m2": 0, "konfidenz": 0.9}],
  "tueren": [{"bezeichnung": "T1", "raum": "...", "breite_mm": 900, "hoehe_mm": 2100, "konfidenz": 0.85}],
  "gesamt_konfidenz": 0.85
}"""

class AnalyseRequest(BaseModel):
    plan_id: str

@app.post("/api/analyse")
async def analyse(body: AnalyseRequest):
    if not sb:
        raise HTTPException(500, "Supabase nicht konfiguriert")

    api_key = _get_anthropic_key()
    if not api_key:
        raise HTTPException(500, "Anthropic API Key nicht konfiguriert")

    # 1. Plan aus DB laden
    plan_res = sb.table("plaene").select("*").eq("id", body.plan_id).execute()
    if not plan_res.data:
        raise HTTPException(404, "Plan nicht gefunden")
    plan = plan_res.data[0]

    # 2. PDF aus Storage herunterladen
    try:
        pdf_bytes = sb.storage.from_("plaene").download(plan["storage_path"])
    except Exception as e:
        raise HTTPException(500, f"PDF Download fehlgeschlagen: {e}")

    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    # 3. An Claude Vision senden
    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": VISION_PROMPT,
                    },
                ],
            }],
        )
    except Exception as e:
        raise HTTPException(500, f"Claude API Fehler: {e}")

    raw = response.content[0].text if response.content else "{}"

    # Parse JSON
    import re
    result = None
    try:
        result = json.loads(raw)
    except:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group())
            except:
                pass

    if not result:
        raise HTTPException(500, "KI-Antwort konnte nicht geparst werden")

    # 4. Ergebnisse in Supabase speichern
    # Räume als Elemente
    for raum in result.get("raeume", []):
        sb.table("elemente").insert({
            "plan_id": body.plan_id,
            "typ": "raum",
            "bezeichnung": raum.get("name", ""),
            "daten": raum,
            "konfidenz": int(raum.get("konfidenz", 0.5) * 100),
        }).execute()

    # Fenster als Elemente
    for fenster in result.get("fenster", []):
        sb.table("elemente").insert({
            "plan_id": body.plan_id,
            "typ": "fenster",
            "bezeichnung": fenster.get("bezeichnung", ""),
            "daten": fenster,
            "konfidenz": int(fenster.get("konfidenz", 0.5) * 100),
        }).execute()

    # Türen als Elemente
    for tuer in result.get("tueren", []):
        sb.table("elemente").insert({
            "plan_id": body.plan_id,
            "typ": "tuer",
            "bezeichnung": tuer.get("bezeichnung", ""),
            "daten": tuer,
            "konfidenz": int(tuer.get("konfidenz", 0.5) * 100),
        }).execute()

    # Plan als verarbeitet markieren
    konfidenz = int(result.get("gesamt_konfidenz", 0.5) * 100)
    sb.table("plaene").update({
        "verarbeitet": True,
        "gesamt_konfidenz": konfidenz,
        "agent_log": result,
    }).eq("id", body.plan_id).execute()

    return {
        "status": "ok",
        "raeume": len(result.get("raeume", [])),
        "fenster": len(result.get("fenster", [])),
        "tueren": len(result.get("tueren", [])),
        "konfidenz": konfidenz,
    }

@app.get("/api/analyse-health")
async def health():
    return {"status": "ok", "supabase": bool(sb), "anthropic_key": bool(_get_anthropic_key())}
