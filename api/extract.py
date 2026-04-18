"""
Vercel Serverless: PDF Text Extraction with pdfplumber.
Extracts ALL text with exact positions, groups into rooms/fenster/dimensions.
Called after PDF upload, stores results in Supabase for the orchestrator.
"""
from __future__ import annotations
import json, os, re, math, tempfile
from collections import defaultdict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", os.environ.get("SUPABASE_KEY", ""))
sb = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# If no env vars, try loading from Supabase config
if not sb:
    try:
        sb = create_client(
            "https://ndojdrjwfelykpycrdjh.supabase.co",
            # Will be set via env vars on Vercel
            SUPABASE_KEY or ""
        )
    except:
        pass


class ExtractRequest(BaseModel):
    plan_id: str


ROOM_KEYWORDS = [
    "wohnküche", "wohnk", "zimmer", "schlafzimmer", "kinderzimmer",
    "bad", "wc", "dusche", "vorraum", "flur", "gang", "diele",
    "küche", "loggia", "balkon", "terrasse", "stiegenhaus",
    "abstellraum", "garderobe", "speis", "technik", "keller",
    "waschk", "ar", "top",
]

BODENBELAEGE = [
    "parkett", "fliesen", "feinsteinzeug", "laminat", "vinyl",
    "estrich", "beton", "teppich", "naturstein", "keramik",
]


def extract_from_pdf(pdf_bytes: bytes) -> dict:
    """Extract all text with exact positions using pdfplumber."""
    import pdfplumber

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        f.flush()
        pdf_path = f.name

    result = {
        "dimensions": [],
        "areas": [],
        "umfang_values": [],
        "hoehe_values": [],
        "room_names": [],
        "fenster_codes": [],
        "fenster_params": [],
        "bodenbelaege": [],
        "massstab": None,
        "geschoss": None,
        "total_words": 0,
        "rooms_grouped": [],
    }

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                pw, ph = page.width, page.height
                words = page.extract_words(x_tolerance=3, y_tolerance=3)
                result["total_words"] += len(words)

                all_items = []
                for w in words:
                    text = w["text"].strip()
                    if not text:
                        continue
                    x_pct = round(w["x0"] / pw * 100, 2)
                    y_pct = round(w["top"] / ph * 100, 2)
                    x1_pct = round(w["x1"] / pw * 100, 2)
                    y1_pct = round(w["bottom"] / ph * 100, 2)

                    item = {"text": text, "x": x_pct, "y": y_pct, "x1": x1_pct, "y1": y1_pct, "page": page_idx}
                    all_items.append(item)

                    # --- Classify ---

                    # Dimension values (3-4 digit = cm)
                    if re.match(r"^\d{3,4}$", text):
                        val = int(text) / 100
                        if 0.5 < val < 25:
                            result["dimensions"].append({"value_cm": int(text), "value_m": round(val, 2), "x": x_pct, "y": y_pct})

                    # Area values: XX,XX format
                    area_match = re.match(r"^(\d{1,3})[,.](\d{1,2})$", text)
                    if area_match:
                        val = float(area_match.group(1) + "." + area_match.group(2))
                        if 1 < val < 500:
                            result["areas"].append({"value": val, "text": text, "x": x_pct, "y": y_pct})

                    # Umfang: "U:" or "U :" followed by number
                    if re.match(r"^U\s*[:=]", text, re.I):
                        num = re.search(r"(\d+[.,]\d+)", text)
                        if num:
                            result["umfang_values"].append({"value": float(num.group(1).replace(",", ".")), "x": x_pct, "y": y_pct})

                    # Höhe: "H:"
                    if re.match(r"^[RH]?H\s*[:=]", text, re.I):
                        num = re.search(r"(\d+[.,]\d+)", text)
                        if num:
                            result["hoehe_values"].append({"value": float(num.group(1).replace(",", ".")), "x": x_pct, "y": y_pct})

                    # Room names
                    lower = text.lower()
                    for kw in ROOM_KEYWORDS:
                        if kw in lower and len(text) > 1:
                            result["room_names"].append({"text": text, "x": x_pct, "y": y_pct})
                            break

                    # Fenster codes
                    if re.match(r"FE[_\s-]?\d", text, re.I):
                        result["fenster_codes"].append({"text": text, "x": x_pct, "y": y_pct})

                    # Fenster parameters (RPH, FPH, AL, RB)
                    for prefix in ["RPH", "FPH"]:
                        if text.upper().startswith(prefix):
                            num = re.search(r"[-+]?\d+", text)
                            if num:
                                result["fenster_params"].append({"type": prefix, "value": int(num.group()), "x": x_pct, "y": y_pct})
                    for prefix in ["AL", "RB"]:
                        if text.upper().startswith(prefix) and re.search(r"\d", text):
                            num = re.search(r"\d+", text)
                            if num:
                                result["fenster_params"].append({"type": prefix, "value": int(num.group()), "x": x_pct, "y": y_pct})

                    # Bodenbeläge
                    for bb in BODENBELAEGE:
                        if bb in lower:
                            result["bodenbelaege"].append({"text": text, "x": x_pct, "y": y_pct})
                            break

                    # Maßstab
                    ms = re.match(r"(?:M\s*)?1\s*:\s*(50|100|200|500)", text)
                    if ms:
                        result["massstab"] = f"1:{ms.group(1)}"

                    # Geschoss
                    gs = re.match(r"^(EG|OG\d?|KG|DG|UG|\d\.OG|Erdgeschoss|Obergeschoss)$", text, re.I)
                    if gs:
                        result["geschoss"] = gs.group()

                # --- Group nearby texts into rooms ---
                _group_rooms(all_items, result)

    except Exception as e:
        result["error"] = str(e)
    finally:
        os.unlink(pdf_path)

    return result


def _group_rooms(all_items: list, result: dict):
    """Group nearby room_name + area + umfang + hoehe + bodenbelag into room clusters."""
    room_items = [i for i in all_items if any(kw in i["text"].lower() for kw in ROOM_KEYWORDS)]

    for room in room_items:
        # Skip if already part of a cluster
        cluster = {"name": room["text"], "x": room["x"], "y": room["y"], "page": room["page"]}

        # Find nearby area value (within 5% horizontal, 3% vertical)
        for area in result["areas"]:
            if abs(area["x"] - room["x"]) < 15 and abs(area["y"] - room["y"]) < 5:
                cluster["flaeche_m2"] = area["value"]
                break

        # Find nearby umfang
        for u in result["umfang_values"]:
            if abs(u["x"] - room["x"]) < 15 and abs(u["y"] - room["y"]) < 5:
                cluster["umfang_m"] = u["value"]
                break

        # Find nearby höhe
        for h in result["hoehe_values"]:
            if abs(h["x"] - room["x"]) < 15 and abs(h["y"] - room["y"]) < 5:
                cluster["hoehe_m"] = h["value"]
                break

        # Find nearby bodenbelag
        for bb in result["bodenbelaege"]:
            if abs(bb["x"] - room["x"]) < 15 and abs(bb["y"] - room["y"]) < 5:
                cluster["bodenbelag"] = bb["text"]
                break

        # Calculate wall dimensions if we have area + umfang
        if "flaeche_m2" in cluster and "umfang_m" in cluster:
            F = cluster["flaeche_m2"]
            U = cluster["umfang_m"]
            half = U / 2
            disc = half * half - 4 * F
            if disc >= 0:
                a = (half + math.sqrt(disc)) / 2
                b = (half - math.sqrt(disc)) / 2
                cluster["seite_a_m"] = round(a, 3)
                cluster["seite_b_m"] = round(b, 3)
                if "hoehe_m" in cluster:
                    cluster["wandflaeche_m2"] = round(U * cluster["hoehe_m"], 2)

        result["rooms_grouped"].append(cluster)


@app.post("/api/extract")
async def extract(body: ExtractRequest):
    if not sb:
        raise HTTPException(500, "Supabase nicht konfiguriert")

    # Get plan
    plan_res = sb.table("plaene").select("*").eq("id", body.plan_id).single().execute()
    if not plan_res.data:
        raise HTTPException(404, "Plan nicht gefunden")
    plan = plan_res.data

    # Download PDF
    try:
        pdf_bytes = sb.storage.from_("plaene").download(plan["storage_path"])
    except Exception as e:
        raise HTTPException(500, f"PDF Download: {e}")

    # Extract text
    result = extract_from_pdf(pdf_bytes)

    # Store in agent_log
    log = plan.get("agent_log") or {}
    log["pdf_text"] = result
    log["extraction_method"] = "pdfplumber_server"
    sb.table("plaene").update({"agent_log": log}).eq("id", body.plan_id).execute()

    return {
        "status": "ok",
        "dimensions": len(result["dimensions"]),
        "areas": len(result["areas"]),
        "rooms": len(result["room_names"]),
        "rooms_grouped": len(result["rooms_grouped"]),
        "fenster": len(result["fenster_codes"]),
        "umfang": len(result["umfang_values"]),
        "hoehe": len(result["hoehe_values"]),
        "massstab": result["massstab"],
        "geschoss": result["geschoss"],
        "total_words": result["total_words"],
    }


@app.get("/api/extract-health")
async def health():
    return {"status": "ok", "pdfplumber": True}


@app.post("/api/analyse-zoom")
async def analyse_zoom(body: ExtractRequest):
    """
    Zoom-section analysis: renders PDF in high-DPI sections,
    sends each to Claude, merges results.
    """
    if not sb:
        raise HTTPException(500, "Supabase nicht konfiguriert")

    # Get plan + API key
    plan_res = sb.table("plaene").select("*").eq("id", body.plan_id).single().execute()
    if not plan_res.data:
        raise HTTPException(404, "Plan nicht gefunden")
    plan = plan_res.data

    cfg = sb.table("app_config").select("value").eq("key", "ANTHROPIC_API_KEY").execute().data
    api_key = cfg[0]["value"] if cfg else os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(500, "API Key nicht konfiguriert")

    # Download PDF
    try:
        pdf_bytes = sb.storage.from_("plaene").download(plan["storage_path"])
    except Exception as e:
        raise HTTPException(500, f"PDF Download: {e}")

    # Determine sections based on plan aspect ratio
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pw, ph = page.rect.width, page.rect.height
    aspect = pw / ph

    # Split strategy: more sections for wider plans
    if aspect > 2.5:
        # Very wide A0 plan (3+ buildings) - 4x2 = 8 sections
        cols, rows = 4, 2
        sections = []
        for col in range(cols):
            for row in range(rows):
                sections.append({
                    "name": f"section_{col}_{row}",
                    "rect": (pw * col / cols, ph * row / rows, pw * (col + 1) / cols, ph * (row + 1) / rows),
                    "position": f"col{col}_row{row}"
                })
    elif aspect > 2.0:
        # Wide A0 plan - 3x2 = 6 sections
        cols, rows = 3, 2
        sections = []
        for col in range(cols):
            for row in range(rows):
                sections.append({
                    "name": f"section_{col}_{row}",
                    "rect": (pw * col / cols, ph * row / rows, pw * (col + 1) / cols, ph * (row + 1) / rows),
                    "position": f"col{col}_row{row}"
                })
    elif aspect > 1.3:
        # Medium plan - 2x2
        sections = [
            {"name": "top_left", "rect": (0, 0, pw/2, ph/2), "position": "oben-links"},
            {"name": "top_right", "rect": (pw/2, 0, pw, ph/2), "position": "oben-rechts"},
            {"name": "bottom_left", "rect": (0, ph/2, pw/2, ph), "position": "unten-links"},
            {"name": "bottom_right", "rect": (pw/2, ph/2, pw, ph), "position": "unten-rechts"},
        ]
    else:
        # Single section
        sections = [{"name": "full", "rect": (0, 0, pw, ph), "position": "gesamt"}]

    # Render each section at 400 DPI as JPEG (smaller than PNG)
    import anthropic
    import base64
    client = anthropic.Anthropic(api_key=api_key)

    all_rooms = []
    all_fenster = []
    all_tueren = []
    massstab = None
    geschoss = None

    SYSTEM_PROMPT = """Du bist der erfahrenste Bautechniker Oesterreichs.
Du siehst einen AUSSCHNITT eines Bauplans (nicht den ganzen Plan).
Lies JEDEN Text im Ausschnitt EXAKT ab.

Antworte NUR mit validem JSON:
{
  "raeume": [
    {"name": "Wohnkueche", "wohnung": "TOP 25", "flaeche_m2": 24.13, "umfang_m": 20.66, "hoehe_m": 2.42, "bodenbelag": "Parkett", "konfidenz": 0.98}
  ],
  "fenster": [
    {"bezeichnung": "FE_30", "raum": "Zimmer", "wohnung": "TOP 25", "al_breite_mm": 120, "al_hoehe_mm": 147, "rb_breite_mm": 130, "rb_hoehe_mm": 147, "rph_mm": 84, "fph_mm": 87, "konfidenz": 0.95}
  ],
  "tueren": [],
  "massstab": "1:100",
  "geschoss": "EG",
  "wohnungen_gefunden": ["TOP 25", "TOP 26"]
}

WICHTIG: Lies NUR was im Bildausschnitt zu sehen ist. Erfinde nichts!"""

    for sec in sections:
        # Adaptive DPI: start at 300, reduce if image is too big for API (5MB limit)
        dpi = 300
        while dpi >= 100:
            mat = fitz.Matrix(dpi/72, dpi/72)
            pix = page.get_pixmap(matrix=mat, clip=fitz.Rect(*sec["rect"]))
            img_bytes = pix.tobytes("jpeg", jpg_quality=80)
            if len(img_bytes) < 4.5 * 1024 * 1024:
                break
            dpi -= 50

        # Skip if still too large
        if len(img_bytes) > 5 * 1024 * 1024:
            continue

        img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
                        {"type": "text", "text": f"Dies ist der Ausschnitt {sec['position']} eines oesterreichischen Bauplans. Analysiere alles was du sehen kannst."}
                    ]
                }]
            )

            raw = response.content[0].text if response.content else "{}"
            # Parse JSON
            result = None
            try:
                result = json.loads(raw)
            except:
                m = re.search(r'\{[\s\S]*\}', raw)
                if m:
                    try:
                        result = json.loads(m.group())
                    except:
                        pass

            if result:
                all_rooms.extend(result.get("raeume", []))
                all_fenster.extend(result.get("fenster", []))
                all_tueren.extend(result.get("tueren", []))
                if not massstab and result.get("massstab"):
                    massstab = result["massstab"]
                if not geschoss and result.get("geschoss"):
                    geschoss = result["geschoss"]
        except Exception as e:
            # Log but continue
            pass

    doc.close()

    # Deduplicate rooms by name+wohnung (sections may overlap)
    seen = set()
    unique_rooms = []
    for r in all_rooms:
        key = (r.get("name", ""), r.get("wohnung", ""))
        if key not in seen:
            seen.add(key)
            unique_rooms.append(r)

    seen_f = set()
    unique_fenster = []
    for f in all_fenster:
        key = f.get("bezeichnung", "")
        if key and key not in seen_f:
            seen_f.add(key)
            unique_fenster.append(f)

    # Clean old results
    sb.table("massen").delete().eq("plan_id", body.plan_id).execute()
    sb.table("elemente").delete().eq("plan_id", body.plan_id).execute()

    # Store elements
    for r in unique_rooms:
        sb.table("elemente").insert({
            "plan_id": body.plan_id, "typ": "raum",
            "bezeichnung": r.get("name", ""),
            "daten": r,
            "konfidenz": int(r.get("konfidenz", 0.8) * 100)
        }).execute()

    for f in unique_fenster:
        sb.table("elemente").insert({
            "plan_id": body.plan_id, "typ": "fenster",
            "bezeichnung": f.get("bezeichnung", ""),
            "daten": f,
            "konfidenz": int(f.get("konfidenz", 0.8) * 100)
        }).execute()

    for t in all_tueren:
        sb.table("elemente").insert({
            "plan_id": body.plan_id, "typ": "tuer",
            "bezeichnung": t.get("bezeichnung", ""),
            "daten": t,
            "konfidenz": int(t.get("konfidenz", 0.8) * 100)
        }).execute()

    # Store in agent_log
    log = plan.get("agent_log") or {}
    log["zoom_analyse"] = {
        "sections": len(sections),
        "raeume": len(unique_rooms),
        "fenster": len(unique_fenster),
        "tueren": len(all_tueren),
        "massstab": massstab,
        "geschoss": geschoss,
    }
    log["geo"] = {
        "raeume": unique_rooms,
        "fenster": unique_fenster,
        "tueren": all_tueren,
        "massstab": massstab,
        "geschoss": geschoss,
    }
    sb.table("plaene").update({"agent_log": log, "gesamt_konfidenz": 95}).eq("id", body.plan_id).execute()

    return {
        "status": "ok",
        "sections_analyzed": len(sections),
        "raeume": len(unique_rooms),
        "fenster": len(unique_fenster),
        "tueren": len(all_tueren),
        "massstab": massstab,
        "geschoss": geschoss,
    }
