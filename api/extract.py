"""
Vercel Serverless: PDF Text Extraction with pdfplumber.
Extracts ALL text with exact positions, groups into rooms/fenster/dimensions.
Called after PDF upload, stores results in Supabase for the orchestrator.
"""
from __future__ import annotations
import json, os, re, math, tempfile, time

# ÖNORM-Gewerk-Engine — robuster Import (Vercel bündelt api/ mit).
# Bei Fehler läuft die Pipeline ohne Gewerk-Berechnung weiter.
try:
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from massen_logic import berechne_gewerke as _berechne_gewerke
    _MASSEN_OK = True
except Exception as _e:  # pragma: no cover
    print(f"[massen_logic] Import fehlgeschlagen: {_e}")
    _MASSEN_OK = False

# Rohbau-Materialliste (Phase 1, Faustformel-basiert)
try:
    from materialliste import build_materialliste as _build_materialliste
    _MATERIAL_OK = True
except Exception as _e:  # pragma: no cover
    print(f"[materialliste] Import fehlgeschlagen: {_e}")
    _MATERIAL_OK = False

# Konsistenz-Engine (Bauphysik-Plausibilitätschecks)
try:
    from konsistenz import laufe_alle_checks as _konsistenz_checks
    from konsistenz import zusammenfassung as _konsistenz_summary
    _KONSISTENZ_OK = True
except Exception as _e:  # pragma: no cover
    print(f"[konsistenz] Import fehlgeschlagen: {_e}")
    _KONSISTENZ_OK = False

# Öffnungs-Extraktion aus STUK/FPH-Codes (Einreichplan-Beschriftung)
try:
    from oeffnungen import extract_oeffnungen_from_text as _extract_oeffnungen
    _OEFFNUNGEN_OK = True
except Exception as _e:  # pragma: no cover
    print(f"[oeffnungen] Import fehlgeschlagen: {_e}")
    _OEFFNUNGEN_OK = False

# Legende-Parser — liest Bauteil-Aufbau byte-exakt (Wandstärken, Decke, etc.)
try:
    from legende import (parse_legende as _parse_legende,
                         baudaten_aus_legende as _baudaten_aus_legende,
                         wand_verteilung_aus_counts as _wand_verteilung)
    _LEGENDE_OK = True
except Exception as _e:  # pragma: no cover
    print(f"[legende] Import fehlgeschlagen: {_e}")
    _LEGENDE_OK = False

try:
    from massketten import numeric_spans as _mk_spans, reconstruct_bbox as _mk_bbox
    _MASSKETTEN_OK = True
except Exception as _e:  # pragma: no cover
    print(f"[massketten] Import fehlgeschlagen: {_e}")
    _MASSKETTEN_OK = False

try:
    import opus_konsum as _ok
    _OPUS_KONSUM_OK = True
except Exception as _e:  # pragma: no cover
    print(f"[opus_konsum] Import fehlgeschlagen: {_e}")
    _OPUS_KONSUM_OK = False

try:
    import kalibrierung as _kalib
    _KALIB_OK = True
except Exception as _e:  # pragma: no cover
    print(f"[kalibrierung] Import fehlgeschlagen: {_e}")
    _KALIB_OK = False

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from supabase import create_client
import traceback

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Global handler so any uncaught exception becomes a JSON response with the
# real error message - otherwise Vercel returns plain-text "Internal Server
# Error" and the frontend shows nothing useful.
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    print(f"[uncaught {type(exc).__name__}] {exc}\n{tb}")
    return JSONResponse(
        status_code=500,
        content={"error": f"{type(exc).__name__}: {exc}", "where": str(request.url.path)},
    )

def _env(name):
    """Read env var and strip surrounding whitespace/newlines (common
    paste error in Vercel UI)."""
    return (os.environ.get(name) or "").strip()

SUPABASE_URL = _env("SUPABASE_URL")
# Accept any of these env var names (in priority order):
# SUPABASE_SERVICE_KEY > SUPABASE_KEY > SUPABASE_ANON_KEY
SUPABASE_KEY = (
    _env("SUPABASE_SERVICE_KEY")
    or _env("SUPABASE_SERVICE_ROLE_KEY")
    or _env("SUPABASE_KEY")
    or _env("SUPABASE_ANON_KEY")
)
SUPABASE_INIT_ERROR = None
sb = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as _e:
        SUPABASE_INIT_ERROR = f"create_client raised: {type(_e).__name__}: {_e}"
else:
    missing = []
    if not SUPABASE_URL: missing.append("SUPABASE_URL")
    if not SUPABASE_KEY: missing.append("SUPABASE_KEY/SUPABASE_SERVICE_KEY/SUPABASE_ANON_KEY")
    SUPABASE_INIT_ERROR = "Missing env vars: " + ", ".join(missing)


class ExtractRequest(BaseModel):
    plan_id: str
    force: bool = False   # True = neu auslesen, auch wenn der Plan unverändert ist


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


# ═══════════════════════════════════════════════════════════════════════════
# OPUS-4.8-BAUINGENIEUR-PASS (modul-level, wiederverwendbar) — liest den Plan
# GANZHEITLICH (Grundriss + Schnitte + Ansichten + Legende ZUSAMMEN), gegroundet
# an byte-exakten Text-Layer-Fakten (die er NIE überschreibt). Beurteilt NUR das
# Mehrdeutige (geschlossene gemauerte Garage? Platte unter Anbau? Rohbau-Höhe?
# Dachtyp?) — IMMER mit Beleg, sonst null (nichts raten). Wird PRO PROJEKT 1×
# aufgerufen (projekt_massen), optional pro Plan (env OPUS_PER_PLAN=1).
# ═══════════════════════════════════════════════════════════════════════════
OPUS_BAUINGENIEUR_PROMPT = """Du bist ein erfahrener österreichischer Bauingenieur/Polier mit 30 Jahren
Praxis im Lesen von Einreich- und Polierplänen. Du liest den Plan GANZHEITLICH
wie ein Mensch: Grundriss + Schnitte + Ansichten + Legende ZUSAMMEN.

══ DEINE BASIS (FAKTEN — NIEMALS ÄNDERN) ══
Du bekommst byte-exakt aus dem PDF-Text-Layer gelesene Fakten (Räume mit F/U/H,
Legende-Wandstärken, Maßketten-Hülle, Öffnungs-Anzahl). Diese sind WAHRHEIT. Du
misst KEINE Flächen/Maße neu. Du baust DARAUF AUF.

══ DEINE AUFGABE — NUR DAS MEHRDEUTIGE, IMMER MIT BELEG ══
Fälle nur die Urteile, die man NUR aus Grundriss+Schnitt zusammen treffen kann.
Für JEDES Urteil: gib eine kurze "evidenz" (was du WO siehst) + "konfidenz" 0–1.
KEIN Beleg sichtbar → Wert null + konfidenz < 0.4. NIEMALS raten.

1) ÜBERDACHTE BEREICHE (Parkplatz/Carport/Garage/Terrasse/Loggia/Eingang):
   - geschlossen_typ: "gemauert" (Wände rundum bis Dach, HLZ/Ziegel im Schnitt),
     "ständer" (nur Stützen/Säulen, offen), oder "offen" (nur Platte/Dach).
     REGEL: "Carport/Parkplatz/Terrasse überdacht" ist im Normalfall OFFEN
     (Dach auf Stützen → "ständer", zähle die Stützen in saeulen_anzahl). Nur als
     "gemauert" einstufen, wenn der SCHNITT eindeutig rundum gemauerte Wände bis
     zum Dach + ein Tor zeigt (= echte Garage). Im Zweifel "ständer"/"offen".
   - auf_slab: steht der Bereich auf DERSELBEN durchgehenden Bodenplatte wie der
     Hauptbau (kein eigenes Fundament, unter dem Hauptdach, an ≥1 Hauswand)?
   - mauerwerk_umfang_zusatz_m: zusätzliche GEMAUERTE Außenwand-Länge dieses
     Bereichs gegenüber der Hauptbau-Hülle (nur wenn geschlossen_typ="gemauert").
   - fundament_umfang_zusatz_m: zusätzlicher Bodenplatten-Rand (nur wenn auf_slab).

2) HÖHE: rohbau_m (FBOK bis Rohdecke-OK) und licht_m (FBOK bis Decke-UK) aus dem
   Schnitt. 3) DACH: dach_typ ("flach"/"pult"/"sattel"/"walm") + attika_hoehe_m
   bei Flach-/Pultdach. 4) saeulen_anzahl: freistehende tragende Stützen (0 wenn keine).

5) WANDSTÄRKEN-VERTEILUNG (NUR aus den SCHARFEN Grundriss-Kacheln): schätze, welcher
   ANTEIL (%) der Wände welche Stärke hat — Außenwände (dick, oft 50/38cm, oft
   wärmegedämmt-schraffiert) getrennt von Innenwänden (dünner, 25/20/12cm). Nutze die
   gezeichnete Wand-Dicke + Schraffur. Anteile je Gruppe summieren zu 100. Nur die
   Stärken aus der Legende-Fakten-Liste verwenden. KEIN sicheres Bild → konfidenz < 0.4.
6) ÖFFNUNGS-BREITEN (aus den scharfen Kacheln + Ansichten): liste die erkennbaren
   Fenster-/Tür-Breiten in cm mit Anzahl (z.B. Rolladen-/Fensterbreiten 124/184/214).
   Nur was du WIRKLICH ablesen/abmessen kannst; sonst leere Liste.

Antworte NUR mit JSON, kein Markdown:
{
  "ueberdachte_bereiche": [
    {"name": "Garage", "geschlossen_typ": "gemauert", "auf_slab": true,
     "mauerwerk_umfang_zusatz_m": 12.0, "fundament_umfang_zusatz_m": 8.0,
     "konfidenz": 0.85, "evidenz": "Schnitt: HLZ-Wände bis Dach + Tor"},
    {"name": "Parkplatz überdacht", "geschlossen_typ": "ständer", "auf_slab": true,
     "mauerwerk_umfang_zusatz_m": 0.0, "fundament_umfang_zusatz_m": 8.0,
     "konfidenz": 0.8, "evidenz": "Schnitt: nur Stützen, kein Mauerwerk"}
  ],
  "hoehe": {"rohbau_m": 2.95, "licht_m": 2.70, "konfidenz": 0.8, "evidenz": "Schnitt A-A"},
  "dach": {"dach_typ": "flach", "attika_hoehe_m": 0.4, "konfidenz": 0.8, "evidenz": "Attika XPS im Schnitt"},
  "saeulen_anzahl": 0,
  "wand_verteilung": {"aussen_pct": {"50": 85, "38": 8, "25": 7},
     "innen_pct": {"25": 30, "20": 39, "12": 31}, "konfidenz": 0.55,
     "evidenz": "Schraffur/Dicke in den scharfen Kacheln"},
  "oeffnungs_breiten": [{"breite_cm": 214, "anzahl": 3}, {"breite_cm": 124, "anzahl": 2}],
  "gesamtkonfidenz": 0.8
}"""


def _render_plan_bilder(pdf_bytes: bytes):
    """Rendert das erste Blatt für den Opus-Pass: 300 DPI adaptiv reduziert
    (Cap 8000px/4.5MB), sonst 2-Kachel-Fallback für A1/A0. Liefert [jpeg_bytes]."""
    import fitz
    doco = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pgo = doco[0]
        bilder, dpi_o = [], 300
        while dpi_o >= 120:
            pix = pgo.get_pixmap(matrix=fitz.Matrix(dpi_o / 72, dpi_o / 72))
            ib = pix.tobytes("jpeg", jpg_quality=85)
            if len(ib) < 4.5 * 1024 * 1024 and pix.width <= 8000 and pix.height <= 8000:
                return [ib]
            dpi_o -= 40
        hh = pgo.rect.height  # Kachel-Fallback für große Blätter (A1/A0)
        for y0, y1 in ((0, hh * 0.58), (hh * 0.42, hh)):
            pix = pgo.get_pixmap(matrix=fitz.Matrix(180 / 72, 180 / 72),
                                 clip=fitz.Rect(0, y0, pgo.rect.width, y1))
            bilder.append(pix.tobytes("jpeg", jpg_quality=82))
        return bilder
    finally:
        doco.close()


_RAUM_LABEL_RX = re.compile(
    r"\b(Wohn\w*|Küche|Kueche|Zimmer|Bad|WC|Diele|Flur|Vorraum|Abstell\w*|Technik|"
    r"Waschen|Speis|Schlaf|Kind\w*|Büro|Buero|Gang|Parkplatz|Carport|Garage|Terrasse|"
    r"Loggia|Eingang|Stiege|Esszimmer|Wohnraum)\b", re.I)


def _render_grundriss_tiles(pdf_bytes: bytes, max_px=1500, max_tiles=6):
    """SCHARFE Grundriss-Kacheln: lokalisiert die Grundriss-/Ansichts-Region byte-
    exakt über die Raum-Labels und rendert sie in Kacheln, deren lange Kante ~max_px
    füllt. Hintergrund: die Vision-API skaliert jedes Bild auf ~1568px → ein A1-
    Vollblatt landet bei ~47 DPI (Schraffur/Fenster-Breiten verloren). Pro Kachel
    erreicht der Grundriss 3-5× mehr Detail → Opus liest Wandtyp/Öffnungsbreite/Garage.
    Liefert [jpeg_bytes] (leer, wenn keine Raum-Labels gefunden)."""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pg = doc[0]
        xs, ys = [], []
        for w in pg.get_text("words"):
            if _RAUM_LABEL_RX.search(w[4]):
                xs += [w[0], w[2]]; ys += [w[1], w[3]]
        if not xs:
            return []
        x0 = max(0, min(xs) - 60); x1 = min(pg.rect.width, max(xs) + 60)
        y0 = max(0, min(ys) - 60); y1 = min(pg.rect.height, max(ys) + 60)
        bw, bh = x1 - x0, y1 - y0
        if bw < 50 or bh < 50:
            return []
        nx = min(3, max(1, round(bw / 850.0)))
        ny = min(3, max(1, round(bh / 850.0)))
        tw, th = bw / nx, bh / ny
        # ~8% Überlappung, damit Wände/Öffnungen an Kachelrändern nicht abgeschnitten werden
        ox, oy = tw * 0.08, th * 0.08
        tiles = []
        for iy in range(ny):
            for ix in range(nx):
                cx0 = max(x0, x0 + ix * tw - ox); cy0 = max(y0, y0 + iy * th - oy)
                cx1 = min(x1, x0 + (ix + 1) * tw + ox); cy1 = min(y1, y0 + (iy + 1) * th + oy)
                clip = fitz.Rect(cx0, cy0, cx1, cy1)
                long_pt = max(cx1 - cx0, cy1 - cy0)
                dpi = min(400, max_px / (long_pt / 72.0))
                pix = pg.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=clip)
                jb = pix.tobytes("jpeg", jpg_quality=88)
                if len(jb) < 4.5 * 1024 * 1024 and pix.width <= 8000 and pix.height <= 8000:
                    tiles.append(jb)
        return tiles[:max_tiles]
    finally:
        doc.close()


def _run_opus_pass(pdf_bytes: bytes, fakten: dict, api_key: str) -> dict:
    """Ruft den Opus-Bauingenieur-Pass 1× auf: rendert das Blatt, schickt die
    byte-exakten Fakten + Bild(er) an claude-opus-4-8 (temperature=0). Liefert das
    geparste Urteil ODER {"_fehler": ...} bei API-/Parse-Fehler (fallback-sicher).
    Zusätzlich opus_hash (sha1 des Roh-JSON) für Determinismus-Audit."""
    import anthropic
    import base64
    import hashlib
    try:
        bilder = _render_plan_bilder(pdf_bytes)        # Gesamtblatt (Übersicht/Schnitt)
        if not bilder:
            return {"_fehler": "kein Bild gerendert", "_quelle": "fallback"}
        tiles = _render_grundriss_tiles(pdf_bytes)     # SCHARFE Grundriss-/Ansichts-Kacheln
        client = anthropic.Anthropic(api_key=api_key, timeout=120.0, max_retries=3)
        content = [{"type": "text", "text": "BYTE-EXAKTE FAKTEN (nicht ändern):\n" +
                    json.dumps(fakten, ensure_ascii=False)}]
        content.append({"type": "text", "text": "GESAMTBLATT (Übersicht + Schnitte/Ansichten):"})
        for ib in bilder:
            content.append({"type": "image", "source": {"type": "base64",
                "media_type": "image/jpeg", "data": base64.standard_b64encode(ib).decode("utf-8")}})
        if tiles:
            content.append({"type": "text", "text": f"SCHARFE GRUNDRISS-KACHELN ({len(tiles)}, "
                "hohe Auflösung — hier Schraffur/Wandstärken + Fenster-/Tür-Breiten ablesen):"})
            for ib in tiles:
                content.append({"type": "image", "source": {"type": "base64",
                    "media_type": "image/jpeg", "data": base64.standard_b64encode(ib).decode("utf-8")}})
        content.append({"type": "text", "text": "Beurteile den Plan ganzheitlich (mit Beleg, nichts raten). Antworte NUR mit dem JSON."})
        # claude-opus-4-8 akzeptiert KEIN temperature (deprecated → 400) → weglassen.
        resp = client.messages.create(model="claude-opus-4-8", max_tokens=3000,
            system=OPUS_BAUINGENIEUR_PROMPT, messages=[{"role": "user", "content": content}])
        raw = resp.content[0].text if resp.content else "{}"
        try:
            urteil = json.loads(raw)
        except Exception:
            mjs = re.search(r"\{[\s\S]*\}", raw)
            urteil = json.loads(mjs.group()) if mjs else {}
        # Determinismus-Audit (KEINE Garantie — temperature=0 ist Absicht, nicht Zusage)
        urteil["_opus_hash"] = hashlib.sha1((raw or "").encode("utf-8")).hexdigest()[:16]
        print(f"[opus-bauingenieur] konf={urteil.get('gesamtkonfidenz')}, "
              f"bereiche={len(urteil.get('ueberdachte_bereiche') or [])}, "
              f"dach={(urteil.get('dach') or {}).get('dach_typ')}, hash={urteil['_opus_hash']}")
        return urteil
    except Exception as _exc:
        print(f"[opus-bauingenieur] failed: {_exc!r}")
        # Fehler EHRLICH signalisieren statt stilles {} (Audit-Trail).
        return {"_fehler": str(_exc)[:200], "_quelle": "fallback"}


# ═══════════════════════════════════════════════════════════════════════════
# OPUS-SCHLUSSPRÜFUNG (#3) — der erfahrene Polier schaut am ENDE auf die fertige
# Mengenliste + den SCHARFEN Plan und flaggt, was nicht zusammenpasst. Er MELDET
# (mit Beleg), er KORRIGIERT NICHT automatisch — der Mensch/die Kalibrierung
# entscheidet. Fängt grobe Fehler (fehlende Garage, unplausible Decke/Beton-Menge,
# fehlende Position), bevor die Liste rausgeht. Env OPUS_REVIEW=0 schaltet ab.
# ═══════════════════════════════════════════════════════════════════════════
OPUS_REVIEW_PROMPT = """Du bist ein erfahrener österreichischer Polier/Bauingenieur und prüfst die von
einem Lehrling erstellte ROHBAU-MENGENLISTE gegen den Plan — wie eine Endkontrolle.

Du bekommst: byte-exakte Plan-Fakten, die berechnete Mengenliste (Bauteil/Position/
Menge), das Gesamtblatt + SCHARFE Grundriss-Kacheln. Deine Aufgabe: finde NUR, was
NICHT zum Plan passt — fehlende Positionen, unplausible Mengen, übersehene Bauteile
(z.B. eine im Schnitt gemauerte Garage, die im Mauerwerk fehlt; eine zu hohe/niedrige
Beton-/Decken-Menge; fehlende Stützen/Attika). Rechne KEINE exakten Zahlen neu — flagge
PLAUSIBILITÄT, die ein Mensch prüfen sollte. Jeder Befund mit kurzer "evidenz" (was du
WO siehst) + "schwere". KEIN Beleg → nicht flaggen. NIEMALS raten/erfinden.

Antworte NUR mit JSON, kein Markdown:
{
  "pruefung": [
    {"bauteil": "Mauerwerk EG", "position": "HLZ 50cm", "problem": "zu niedrig — Garage gemauert, fehlt",
     "schwere": "hoch", "evidenz": "Schnitt zeigt HLZ-Wände um den Parkplatz", "vorschlag": "Garage-Wände ergänzen"}
  ],
  "gesamturteil": "pruefen",
  "konfidenz": 0.7
}"""


def _materialliste_kompakt(materialliste):
    """Verdichtet die Materialliste auf {bauteil: [{material, menge, einheit}]} für die
    Schlussprüfung (kompakt, nur das Nötige)."""
    out = {}
    for bauteil, positionen in ((materialliste or {}).get("bauteile") or {}).items():
        out[bauteil] = [{"m": p.get("material"), "menge": p.get("menge"), "e": p.get("einheit")}
                        for p in (positionen or [])]
    return out


def _run_opus_review(pdf_bytes: bytes, fakten: dict, materialliste: dict, api_key: str) -> dict:
    """Opus-Schlussprüfung: fertige Liste + scharfer Plan → Plausibilitäts-Befunde.
    Liefert {pruefung: [...], gesamturteil, konfidenz} ODER {"_fehler": ...}."""
    import anthropic
    import base64
    try:
        bilder = _render_plan_bilder(pdf_bytes)
        if not bilder:
            return {"_fehler": "kein Bild gerendert", "_quelle": "fallback"}
        tiles = _render_grundriss_tiles(pdf_bytes)
        client = anthropic.Anthropic(api_key=api_key, timeout=120.0, max_retries=3)
        content = [{"type": "text", "text": "BYTE-EXAKTE PLAN-FAKTEN:\n" +
                    json.dumps(fakten, ensure_ascii=False)},
                   {"type": "text", "text": "BERECHNETE MENGENLISTE (prüfen):\n" +
                    json.dumps(_materialliste_kompakt(materialliste), ensure_ascii=False)[:8000]},
                   {"type": "text", "text": "GESAMTBLATT:"}]
        for ib in bilder:
            content.append({"type": "image", "source": {"type": "base64",
                "media_type": "image/jpeg", "data": base64.standard_b64encode(ib).decode("utf-8")}})
        if tiles:
            content.append({"type": "text", "text": f"SCHARFE GRUNDRISS-KACHELN ({len(tiles)}):"})
            for ib in tiles:
                content.append({"type": "image", "source": {"type": "base64",
                    "media_type": "image/jpeg", "data": base64.standard_b64encode(ib).decode("utf-8")}})
        content.append({"type": "text", "text": "Prüfe die Liste gegen den Plan (mit Beleg, nichts raten). Antworte NUR mit dem JSON."})
        resp = client.messages.create(model="claude-opus-4-8", max_tokens=2000,
            system=OPUS_REVIEW_PROMPT, messages=[{"role": "user", "content": content}])
        raw = resp.content[0].text if resp.content else "{}"
        try:
            urteil = json.loads(raw)
        except Exception:
            mjs = re.search(r"\{[\s\S]*\}", raw)
            urteil = json.loads(mjs.group()) if mjs else {}
        print(f"[opus-review] befunde={len(urteil.get('pruefung') or [])}, urteil={urteil.get('gesamturteil')}")
        return urteil
    except Exception as _exc:
        print(f"[opus-review] failed: {_exc!r}")
        return {"_fehler": str(_exc)[:200], "_quelle": "fallback"}


def _lade_kalibrierung(sb, firma_id):
    """Lädt die gelernten Faktoren für eine Firma + die globale Basis (firma_id=NULL)
    aus der kalibrierungen-Tabelle und löst sie auf (Firma > Global). Liefert ein
    flaches {faktor_key: wert}-Dict für build_materialliste — oder {} bei Fehler/leer.
    Nur Faktoren mit n_belege >= MIN_BELEGE wurden überhaupt gelernt (Guard im Upload)."""
    if not (_KALIB_OK and sb):
        return {}
    try:
        glob_rows = sb.table("kalibrierungen").select(
            "faktor_key, wert, n_belege").is_("firma_id", "null").execute().data or []
        firma_rows = []
        if firma_id:
            firma_rows = sb.table("kalibrierungen").select(
                "faktor_key, wert, n_belege").eq("firma_id", firma_id).execute().data or []
        glob = {r["faktor_key"]: {"wert": r["wert"]} for r in glob_rows if r.get("wert") is not None}
        firma = {r["faktor_key"]: {"wert": r["wert"]} for r in firma_rows if r.get("wert") is not None}
        return _kalib.resolve_kalibrierung(firma, glob)
    except Exception as _exc:
        print(f"[kalibrierung] laden fehlgeschlagen: {_exc!r}")
        return {}


def _opus_fakten(rooms, leg_facts, massketten_bbox, n_fenster, n_tueren) -> dict:
    """Baut das byte-exakte Fakten-JSON, an dem der Opus-Pass gegroundet wird."""
    return {
        "text_layer_raeume": [{"name": r.get("name"), "flaeche_m2": r.get("flaeche_m2"),
                               "umfang_m": r.get("umfang_m"), "hoehe_m": r.get("hoehe_m"),
                               "bodenbelag": r.get("bodenbelag")} for r in (rooms or [])],
        "text_layer_legende": {"wand_typen": (leg_facts or {}).get("wand_typen"),
                               "decke_cm": (leg_facts or {}).get("decke_cm"),
                               "bodenplatte_cm": (leg_facts or {}).get("bodenplatte_cm")},
        "text_layer_massketten_huelle": massketten_bbox,
        "anzahl_fenster": int(n_fenster or 0), "anzahl_tueren": int(n_tueren or 0),
    }


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


@app.get("/api/diag")
async def diag():
    """Show which Supabase env vars are present + key prefix/length
    so user can verify the value got through correctly. Does not leak
    full secrets - only first 12 + last 6 chars."""
    def _redact(v):
        if not v:
            return None
        if len(v) <= 18:
            return "(too short - " + str(len(v)) + " chars)"
        return v[:12] + "..." + v[-6:] + " (" + str(len(v)) + " chars)"

    keys = ["SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY",
            "ANTHROPIC_API_KEY"]
    info = {}
    for k in keys:
        v = os.environ.get(k)
        if v is None:
            info[k] = "NOT SET"
        elif k == "SUPABASE_URL":
            info[k] = v  # url is not a secret
        else:
            info[k] = _redact(v)

    info["sb_initialized"] = sb is not None
    info["sb_init_error"] = SUPABASE_INIT_ERROR

    # Hash key value to detect hidden chars that prefix/length didn't catch
    import hashlib
    raw_key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or ""
    info["key_sha256_first8"] = hashlib.sha256(raw_key.encode()).hexdigest()[:8] if raw_key else None
    info["key_strip_diff"] = (len(raw_key) - len(raw_key.strip())) if raw_key else None

    # Live query test: does the configured client actually work?
    if sb:
        try:
            r = sb.table("plaene").select("id").limit(1).execute()
            info["live_query"] = "ok (" + str(len(r.data)) + " rows)"
        except Exception as e:
            info["live_query"] = "FAIL: " + type(e).__name__ + ": " + str(e)[:200]
    return info


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
    api_key = (cfg[0]["value"] if cfg else os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    if not api_key:
        raise HTTPException(500, "API Key nicht konfiguriert")

    # Download PDF
    try:
        pdf_bytes = sb.storage.from_("plaene").download(plan["storage_path"])
    except Exception as e:
        raise HTTPException(500, f"PDF Download: {e}")

    # ── KONSTANZ-FREEZE ──────────────────────────────────────────────────────
    # Gleicher Plan-INHALT → gleiche gespeicherte Auswertung. Ohne das würfelt
    # JEDER analyse-zoom-Aufruf neu (delete+insert der elemente) und der User
    # sieht „bei jedem Klick was anderes". Wir hängen einen Inhalts-Hash an den
    # Plan; stimmt er + es liegt schon ein Ergebnis vor + kein force → geben wir
    # das gespeicherte Ergebnis unverändert zurück, ohne die Vision-Pässe neu zu
    # würfeln. „Neu auslesen" (force=true) umgeht den Freeze bewusst.
    import hashlib as _hl
    input_hash = _hl.sha256(pdf_bytes).hexdigest()
    _za = (plan.get("agent_log") or {}).get("zoom_analyse")
    if (not body.force) and plan.get("input_hash") == input_hash and _za:
        return {
            "status": "ok", "cached": True,
            "sections_analyzed": _za.get("sections", 0),
            "raeume": _za.get("raeume", 0),
            "fenster": _za.get("fenster", 0),
            "tueren": _za.get("tueren", 0),
            "massstab": _za.get("massstab"),
            "geschoss": _za.get("geschoss"),
            "vision_wall_tops": _za.get("vision_wall_tops", 0),
            "hinweis": "unveraendert - gespeichertes Ergebnis (konstant). 'Neu auslesen' erzwingt eine frische Analyse.",
        }

    # DETERMINISTIC OVERLAPPING GRID + TEXT VERIFICATION + PASS 3 ULTRA ZOOM:
    # 1. Extract text tokens with positions from PDF layer.
    # 2. Tile-based Claude Vision (1800pt, 30% overlap, 300 DPI).
    # 3. Consensus grouping across overlapping tiles.
    # 4. Cross-verify every F/U/H against PDF text tokens near each room label.
    # 5. Pass 3: per-room ultra-zoom (500 DPI) for any remaining gaps.
    import fitz
    import anthropic
    import base64
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pw, ph = page.rect.width, page.rect.height
    # Timeout < Vercel-Limit (300s) und 429-Retries, damit ein hängender oder
    # ratenlimitierter API-Call die Extraktion nicht ins Vercel-Timeout laufen lässt.
    client = anthropic.Anthropic(api_key=api_key, timeout=120.0, max_retries=3)

    # ── Extract text spans with positions from PDF text layer ──
    spans_all = []  # each: {"text", "bbox", "size", "cx", "cy"}
    try:
        td = page.get_text("dict")
        for block in td.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    txt = (span.get("text") or "").strip()
                    if not txt:
                        continue
                    bbox = tuple(span.get("bbox") or (0, 0, 0, 0))
                    spans_all.append({
                        "text": txt,
                        "bbox": bbox,
                        "size": round(span.get("size", 0), 1),
                        "cx": (bbox[0] + bbox[2]) / 2.0,
                        "cy": (bbox[1] + bbox[3]) / 2.0,
                    })
    except Exception:
        pass

    # Numeric-token view for Vision verification
    text_tokens = []
    for s in spans_all:
        num_val = None
        for nm in re.finditer(r"[0-9]+[.,][0-9]+", s["text"].replace(" ", "")):
            try:
                num_val = float(nm.group(0).replace(",", "."))
                break
            except:
                pass
        text_tokens.append({"text": s["text"], "bbox": s["bbox"], "num": num_val})

    def _tok_center(bbox):
        return ((bbox[0]+bbox[2])/2.0, (bbox[1]+bbox[3])/2.0)

    def _norm_name(s):
        return re.sub(r"[\s\-_/]+", "", (s or "").lower())

    def find_label_pos(room_name):
        key = _norm_name(room_name)
        if not key or len(key) < 3:
            return None
        matches = []
        for tok in text_tokens:
            nt = _norm_name(tok.get("text"))
            if nt == key or (len(key) >= 4 and key in nt):
                matches.append(tok["bbox"])
        return matches

    def verify_value_near(pos_bbox, target, tolerance=0.04, radius_pt=300):
        if pos_bbox is None or target is None:
            return False
        cx, cy = _tok_center(pos_bbox)
        best_delta = float("inf")
        for tok in text_tokens:
            n = tok.get("num")
            if n is None:
                continue
            tx, ty = _tok_center(tok["bbox"])
            if abs(tx-cx) > radius_pt or abs(ty-cy) > radius_pt:
                continue
            rel = abs(n - target) / max(abs(target), 0.01)
            if rel < tolerance and rel < best_delta:
                best_delta = rel
        return best_delta < tolerance

    # ─────────────────────────────────────────────────────────────────
    # TEXT-FIRST ROOM EXTRACTION
    # If the PDF has a proper text layer, every room label is present
    # as spans: Name / [Bodenbelag] / "XX,XX m" + small "2" / "U: ..." / "H: ..."
    # Pulling these directly gives byte-exact ground truth.
    # ─────────────────────────────────────────────────────────────────
    # Strict exact-match list. Substring matching produced false positives
    # (e.g. "ar" matched inside other words). Architect labels use these
    # canonical spellings — anything else is annotation, not a room label.
    ROOM_NAMES_EXACT = {
        "Wohnküche","Wohnkueche","Wohnen","Wohnzimmer","Wohnraum","Esszimmer","Zimmer",
        "Schlafzimmer","Kinderzimmer","Bad","WC","Dusche","Sauna",
        "Vorraum","Vorzimmer","Flur","Gang","Diele","Küche","Kueche",
        "Loggia","Balkon","Terrasse","Stiegenhaus","Stiege","STGH","STG",
        "Abstellraum","Abstellr.","Garderobe","Speis","Speisekammer","Technik","Technikraum",
        "Keller","Kellerabteil","Kiwa","Waschküche","Waschkueche","Waschraum","Waschen",
        "Werkstätte","Werkstatt","Lager",
        "Büro","Buero","Atelier","Studio","Praxis","Arbeitszimmer",
        "Tiefgarage","Garage","Carport","Parkplatz","Fahrradraum","Kinderwagenraum","Schleuse",
        "Fitness","Treppenhaus","Müllraum","E-Technik","Elektroraum",
        "Pelletslagerraum","Pelletslager",
        "Windfang","Foyer","Eingang","Eingangsbereich",
        "AR","HWR","HSR","HAR",
    }
    BODENBELAG_KWS = {"parkett","fliesen","laminat","vinyl","estrich","teppich","feinsteinzeug","naturstein","keramik","beschichtung","beton"}
    # Geschoss-Code-Räume (EG301, OG214) für andere Architekt-Konventionen
    ROOM_CODE_RX_INNER = re.compile(r"^(EG|OG\d?|KG|UG|DG)\s*[._-]?\s*(\d{2,4})$", re.I)
    # Generalisierte Anker: matchen F:/Fl:/Fläche, U:/Um:/Umfang, H:/Hö:/RH/Höhe
    # U: kann Tausender-Leerzeichen + Einheit cm/m haben: "U: 1 098,0 cm"
    F_ANCHOR_RX = re.compile(r"^(?:F|Fl|Fläche|Flaeche)\s*[:=]?\s*([0-9]+[,.][0-9]+)", re.I)
    U_ANCHOR_RX = re.compile(r"^(?:U|Um|Umfang)\s*[:=]?\s*([0-9][0-9\s]*[,.][0-9]+)", re.I)
    H_ANCHOR_RX = re.compile(r"^(?:H|Hö|Hoe|Höhe|Hoehe|RH|LH)\s*[:=]?\s*([0-9]+[,.][0-9]+)", re.I)
    B_ANCHOR_RX = re.compile(r"^B\s*[:=]\s*(.+)$", re.I)

    # Legende-Pattern: "AR - Abstellraum" (Kürzel + " - " + Name). Leerzeichen
    # um den Bindestrich grenzt von echten Räumen wie "E-Technik" ab.
    LEGENDE_RX = re.compile(r"^[A-ZÄÖÜ]{1,4}\s+[-–]\s+\w", re.I)
    # TOP-Wohnungslabel allein ("TOP 25") ist kein Raum.
    TOP_ONLY_RX = re.compile(r"^TOP\s*\.?\s*\d+[a-z]?$", re.I)
    RAUM_REST_OK = {
        "süd","nord","ost","west","südost","südwest","nordost","nordwest",
        "links","rechts","oben","unten","mitte","gross","groß","klein",
        "überdacht","ueberdacht","offen","beheizt","unbeheizt","neu","alt",
    }

    def name_matches_room(t):
        """Prüft NUR den Text (ohne Größe), ob es ein Raumname ist."""
        if len(t) < 2:
            return False
        if LEGENDE_RX.match(t) or TOP_ONLY_RX.match(t):
            return False
        if t in ROOM_NAMES_EXACT:
            return True
        words = t.split()
        if len(words) > 1 and words[0] in ROOM_NAMES_EXACT:
            rest_ok = all(
                re.match(r"^\d+[a-z]?$", w, re.I)
                or w.lower() in RAUM_REST_OK
                or w in ROOM_NAMES_EXACT
                for w in words[1:]
            )
            if rest_ok:
                return True
        if "-" in t and not LEGENDE_RX.match(t):
            for part in t.split("-"):
                if part.strip() in ROOM_NAMES_EXACT:
                    return True
        return False

    # Adaptive Schrift-Schwelle: typische Raumlabel-Größe dieses Plans (Modus)
    _label_sizes = [round(s.get("size", 0), 1) for s in spans_all
                    if name_matches_room(s["text"].strip())]
    if _label_sizes:
        from collections import Counter as _Cnt
        _typ_size = _Cnt(_label_sizes).most_common(1)[0][0]
        MIN_LABEL_SIZE = max(4.0, _typ_size * 0.75)
    else:
        MIN_LABEL_SIZE = 6.0

    def is_room_name_span(s):
        t = s["text"].strip()
        # Geschoss-Code-Räume (EG301, OG214) — eigene Größenregel
        if ROOM_CODE_RX_INNER.match(t) and s.get("size", 0) >= max(4.0, MIN_LABEL_SIZE * 0.7):
            return True
        if s.get("size", 0) < MIN_LABEL_SIZE:
            return False
        return name_matches_room(t)

    def has_m2_superscript(s, tolerance_pt=20):
        sx_right = s["bbox"][2]
        sy = s["cy"]
        for o in spans_all:
            if o is s or o["text"] != "2":
                continue
            if o["size"] >= s["size"] * 0.8:
                continue
            if abs(o["cy"] - sy) > 8:
                continue
            if -2 <= (o["bbox"][0] - sx_right) <= tolerance_pt:
                return True
        return False

    def extract_room_from_label(rs):
        rx, ry = rs["cx"], rs["cy"]
        # Bei Code-Räumen (EG301) liegen F/U/H oft 100-150pt entfernt; bei
        # ArchiCAD-Beschriftungsblöcken stehen sie kompakt direkt unter dem Namen.
        is_code = bool(ROOM_CODE_RX_INNER.match(rs["text"].strip()))
        # Enges Fenster (60pt) gegen Stempel-Cross-Talk: ein weiteres Fenster
        # ließ den Flur den Umfang des Nachbar-Raums (Bad) greifen. Lieber eng
        # + die isoperimetrische Plausi-Sicherung unten als Netz.
        rad_x = 150 if is_code else 60
        rad_y_pos = 150 if is_code else 60
        rad_y_neg = -150 if is_code else -5
        candidates = []
        for s in spans_all:
            if s is rs: continue
            dx = s["cx"] - rx; dy = s["cy"] - ry
            if abs(dx) <= rad_x and rad_y_neg <= dy <= rad_y_pos:
                candidates.append((dy, dx, s))
        # nächster Wert zuerst (key-Funktion vermeidet Dict-Vergleich bei Gleichstand)
        candidates.sort(key=lambda c: (c[0], c[1]))
        f_val = u_val = h_val = None
        bodenbelag = None
        for dy, dx, s in candidates:
            t = s["text"]
            m = U_ANCHOR_RX.match(t)
            if m and u_val is None:
                raw = m.group(1).replace(" ", "").replace(",", ".")
                v = float(raw)
                # cm→m: "U: 1 098,0 cm" oder Wert > 50 → cm
                if ("cm" in t.lower()) or (v > 50):
                    v = v / 100.0
                if 1.0 <= v <= 200.0:
                    u_val = v
                continue
            m = H_ANCHOR_RX.match(t)
            if m and h_val is None:
                v = float(m.group(1).replace(",", "."))
                # cm→m: Raumhöhen real 2.2-4.5 m, in cm 220-450
                if 20 < v < 500:
                    v = v / 100.0
                if 2.0 <= v <= 5.0:
                    h_val = v
                continue
            m = F_ANCHOR_RX.match(t)
            if m and f_val is None:
                f_val = float(m.group(1).replace(",", "."))
                continue
            m = re.match(r"^([0-9]+[,.][0-9]+)\s*m\s*(²|2)?\s*$", t)
            if m and f_val is None and not t.startswith(("U", "H", "F")):
                val = float(m.group(1).replace(",", "."))
                if "²" in t or has_m2_superscript(s):
                    f_val = val
                    continue
            if bodenbelag is None and t.lower() in BODENBELAG_KWS:
                bodenbelag = t
                continue
            # B: Fliesen / B: Parkett (Bodenbelag mit Prefix)
            bm = B_ANCHOR_RX.match(t)
            if bm and bodenbelag is None:
                belag_text = bm.group(1).strip().split(",")[0].strip()
                if belag_text.lower() in BODENBELAG_KWS:
                    bodenbelag = belag_text
        return {
            "name": rs["text"],
            "flaeche_m2": f_val,
            "umfang_m": u_val,
            "hoehe_m": h_val,
            "bodenbelag": bodenbelag,
            "bbox": rs["bbox"],
            "cx": rs["cx"],
            "cy": rs["cy"],
        }

    text_first_rooms = []
    try:
        for s in spans_all:
            if is_room_name_span(s):
                text_first_rooms.append(extract_room_from_label(s))
    except Exception as _exc:
        print(f"[text-first] room extraction failed: {_exc!r}")
        text_first_rooms = []

    # ─── ROTATED-LABEL GLOBAL CLAIMS (handles ArchiCAD/GSPublisher plans) ───
    # Build a list of (kind, value, position) claims from the page:
    #   - Standalone "F:" / "U:" / "H:" / "B:" prefix spans with value above
    #   - Inline "F: 12,16 m" prefix+value spans
    # Then fill gaps in text_first_rooms via greedy assignment so each claim
    # is used at most once.
    def _value_above(label_s, x_tol=6, y_max=60):
        lx, ly = label_s["cx"], label_s["cy"]
        best = None; bd = float("inf")
        for o in spans_all:
            if o is label_s: continue
            if abs(o["cx"] - lx) > x_tol: continue
            dy = ly - o["cy"]
            if 0 < dy <= y_max:
                ot = o["text"].strip()
                if ot in ("F:", "U:", "H:", "B:"): continue
                if len(ot) <= 1 and o["size"] < 5.5: continue
                if dy < bd:
                    bd = dy
                    best = ot
        return best

    claims = []  # {"kind","value","cx","cy"}
    for s in spans_all:
        t = s["text"].strip()
        # Standalone label (rotated layout)
        if t in ("F:", "U:", "H:"):
            v_text = _value_above(s)
            if v_text:
                m = re.search(r"([0-9]+[,.][0-9]+)", v_text)
                if m:
                    claims.append({"kind": t[0], "value": float(m.group(1).replace(",", ".")),
                                   "cx": s["cx"], "cy": s["cy"]})
        elif t == "B:":
            v_text = _value_above(s)
            if v_text:
                vl = v_text.lower().strip()
                for b in BODENBELAG_KWS:
                    if vl == b or vl.startswith(b):
                        claims.append({"kind": "B", "value": b.title(),
                                       "cx": s["cx"], "cy": s["cy"]})
                        break
        # Inline (e.g. "F: 12,16 m" all in one span)
        for kind in ("F", "U", "H"):
            m = re.match(rf"^{kind}\s*[:=]\s*([0-9]+[,.][0-9]+)", t)
            if m:
                claims.append({"kind": kind, "value": float(m.group(1).replace(",", ".")),
                               "cx": s["cx"], "cy": s["cy"]})

    # Greedy fill gaps — each claim used at most once
    def _greedy_fill(rooms, claims, kind, attr):
        # Tight 150pt radius: typical label-block size. Wider radius yields
        # higher completeness but lets greedy assign WRONG claims from
        # neighbouring rooms (correctness > completeness).
        kc = [c for c in claims if c["kind"] == kind]
        if not kc:
            return
        missing = [(i, r) for i, r in enumerate(rooms) if not r.get(attr)]
        if not missing:
            return
        pairs = []
        for mi, (ri, r) in enumerate(missing):
            for ci, c in enumerate(kc):
                d = ((r["cx"] - c["cx"]) ** 2 + (r["cy"] - c["cy"]) ** 2) ** 0.5
                if d > 150:
                    continue
                pairs.append((d, mi, ci))
        pairs.sort()
        used_r = set()
        used_c = set()
        for d, mi, ci in pairs:
            if mi in used_r or ci in used_c:
                continue
            ri, r = missing[mi]
            r[attr] = kc[ci]["value"]
            used_r.add(mi)
            used_c.add(ci)

    try:
        _greedy_fill(text_first_rooms, claims, "F", "flaeche_m2")
        _greedy_fill(text_first_rooms, claims, "U", "umfang_m")
        _greedy_fill(text_first_rooms, claims, "H", "hoehe_m")
        _greedy_fill(text_first_rooms, claims, "B", "bodenbelag")
    except Exception as _exc:
        print(f"[greedy fill] failed: {_exc!r}")

    # Find TOP labels with positions; assign each room to nearest TOP by distance
    top_labels = []  # [{"name": "TOP 25", "cx":, "cy":}, ...]
    top_re = re.compile(r"^(TOP|Top|top)\s*\.?\s*([0-9]{1,3}[a-zA-Z]?)$")
    for s in spans_all:
        m = top_re.match(s["text"].strip())
        if m:
            top_labels.append({"name": f"TOP {m.group(2)}", "cx": s["cx"], "cy": s["cy"]})

    # Einfamilienhaus-Fallback: kein TOP-Label im Plan → ein virtuelles
    # "Haus"-Top über alle Räume legen. Sonst hätte jeder Raum wohnung=None
    # und PASS 4 (Bemaßungs-Vision) sowie die ÖNORM-A-2063-LV-Aggregation
    # würden komplett übersprungen (typisch für EFH/Einreichpläne).
    if not top_labels and text_first_rooms:
        xs = [r["cx"] for r in text_first_rooms if r.get("cx") is not None]
        ys = [r["cy"] for r in text_first_rooms if r.get("cy") is not None]
        if xs and ys:
            top_labels.append({
                "name": "Haus",
                "cx": sum(xs) / len(xs),
                "cy": sum(ys) / len(ys),
                "_synthetic": True,
            })

    def nearest_top(rx, ry, max_dist=99999):
        # Mit nur einem Top (Einfamilienhaus) muss max_dist gross sein,
        # sonst landen Räume in den Ecken des Plans bei wohnung=None.
        # Bei mehreren echten Tops bleibt 500pt eine sinnvolle Schwelle.
        if len(top_labels) > 1:
            max_dist = 500
        best = None; best_d = float("inf")
        for t in top_labels:
            d = ((t["cx"]-rx)**2 + (t["cy"]-ry)**2) ** 0.5
            if d < best_d and d < max_dist:
                best_d = d; best = t["name"]
        return best

    for r in text_first_rooms:
        r["wohnung"] = nearest_top(r["cx"], r["cy"])
        r["konfidenz"] = 1.0 if (r.get("flaeche_m2") and r.get("umfang_m") and r.get("hoehe_m")) else 0.7
        r["_text_first"] = True

    # ─── ÖFFNUNGEN AUS TEXT-LAYER (STUK + FPH + D-Codes) ───────────────
    # Einreichpläne kodieren Türen + Fenster über die STUK/FPH-Konvention
    # (ÖNORM A 6240-2): Sturz-Unter-Kante und Fenster-Parapet-Höhe als
    # Anker, Breite als nahegelegene Zahl, AW/IW als Wand-Typ-Marker.
    # Daraus rekonstruieren wir pro Öffnung Breite × Höhe × Raum.
    # Diese textbasierten Öffnungen sind viel präziser als Vision —
    # Vision wird nur noch als Fallback verwendet wenn dieser Pass leer ist.
    text_oeffnungen = []
    if _OEFFNUNGEN_OK and text_first_rooms:
        try:
            text_oeffnungen = _extract_oeffnungen(spans_all, text_first_rooms)
        except Exception as _exc:
            print(f"[oeffnungen text] failed: {_exc!r}")
            text_oeffnungen = []
    if text_oeffnungen:
        print(f"[oeffnungen text] {len(text_oeffnungen)} Öffnungen aus STUK/FPH-Codes "
              f"({sum(1 for o in text_oeffnungen if o['typ']=='fenster')} Fenster, "
              f"{sum(1 for o in text_oeffnungen if o['typ']=='tuer')} Türen)")

    # Dedup text_first: same physical label can produce two records if the
    # span loop visits the room name twice. Multiple identical rooms in
    # different apartments (e.g. three TOP units with same Wohnküche 26,37 m²)
    # must NOT be collapsed — they are real, distinct rooms. So dedup ONLY
    # by spatial position (within 5pt), not by (name + area).
    def _pos_key(r, grid=5):
        return (int(round((r.get("cx") or 0) / grid)),
                int(round((r.get("cy") or 0) / grid)))

    def _completeness(r):
        return (1 if r.get("flaeche_m2") else 0) + (1 if r.get("umfang_m") else 0) + \
               (1 if r.get("hoehe_m") else 0) + (1 if r.get("bodenbelag") else 0)

    tf_pos = {}
    for r in text_first_rooms:
        # Räume ohne F behalten, sofern sie einen Namen haben — Polierpläne
        # liefern oft nur H/U pro Raum; ein anderer Plan ergänzt das F.
        if not r.get("name"):
            continue
        k = _pos_key(r)
        ex = tf_pos.get(k)
        if ex is None or _completeness(r) > _completeness(ex):
            tf_pos[k] = r
    text_first_rooms = list(tf_pos.values())
    # Flag whether text-first produced enough data to trust over Vision.
    # WICHTIG: Ein Raum gilt als sauber gelesen, wenn er IRGENDEINEN Maßwert
    # hat (F, U oder H). Einreichpläne liefern F+U ohne H, Polierpläne H ohne
    # F — beide sind gültige Text-Layer. Würde man nur F zählen, übernähme bei
    # einem Polierplan die Vision-Pipeline und halluziniert Räume.
    text_first_count = sum(1 for r in text_first_rooms
                           if r.get("flaeche_m2") or r.get("umfang_m") or r.get("hoehe_m"))
    text_first_enough = text_first_count >= 5  # ≥5 Räume mit byte-exaktem Maßwert

    # Fixed-size overlapping tiles: 1800 pt per side guarantees DPI=300
    # (7500 px / 1800 pt * 72 = 300). 30% overlap ensures every apartment
    # is fully visible in at least one tile (with F/U/H label table intact).
    TILE_PT = 1800.0
    OVERLAP = 0.30
    STEP = TILE_PT * (1 - OVERLAP)

    if pw <= TILE_PT:
        col_positions = [0.0]
    else:
        n_cols = max(2, int(math.ceil((pw - TILE_PT) / STEP)) + 1)
        step_x = (pw - TILE_PT) / (n_cols - 1)
        col_positions = [i * step_x for i in range(n_cols)]

    if ph <= TILE_PT:
        row_positions = [0.0]
    else:
        n_rows = max(2, int(math.ceil((ph - TILE_PT) / STEP)) + 1)
        step_y = (ph - TILE_PT) / (n_rows - 1)
        row_positions = [i * step_y for i in range(n_rows)]

    sections = []
    for ci, x0 in enumerate(col_positions):
        for ri, y0 in enumerate(row_positions):
            x1 = min(x0 + TILE_PT, pw)
            y1 = min(y0 + TILE_PT, ph)
            sections.append({
                "name": f"tile_{ci}_{ri}",
                "rect": (x0, y0, x1, y1),
                "position": f"col{ci}_row{ri}",
            })

    all_rooms = []
    all_fenster = []
    all_tueren = []
    massstab = None
    geschoss = None

    SYSTEM_PROMPT = """Du bist der erfahrenste Bautechniker Oesterreichs.
Du siehst einen AUSSCHNITT eines oesterreichischen Bauplans.
Bei jedem Raum steht IMMER ein Beschriftungsblock mit DREI Werten:

  Raumname (z.B. "Wohnkueche")
  F: 24,13 m²     <- Flaeche (grosse Zahl mit m² Zeichen)
  U: 20,66 m      <- Umfang (kleinere Zeile, meist direkt darunter)
  H: 2,42 m       <- lichte Raumhoehe

Du MUSST fuer JEDEN Raum alle drei Werte (F, U, H) aus diesem Beschriftungsblock ablesen.
Schau GENAU hin - U und H stehen oft in kleinerer Schrift direkt unter F.
Die Formate koennen leicht variieren: "U=20,66", "U 20.66 m", "Umfang 20,66".
Kommas und Punkte als Dezimaltrenner beide moeglich - immer als Zahl zurueckgeben.

Antworte NUR mit validem JSON (keine Markdown-Fences, kein Prefix):
{
  "raeume": [
    {"name": "Wohnkueche", "wohnung": "TOP 25", "flaeche_m2": 24.13, "umfang_m": 20.66, "hoehe_m": 2.42, "bodenbelag": "Parkett", "konfidenz": 0.98}
  ],
  "fenster": [
    {"bezeichnung": "FE_30", "raum": "Zimmer", "wohnung": "TOP 25", "breite_cm": 120, "hoehe_cm": 147, "rph_cm": 84, "fph_cm": 87, "konfidenz": 0.95}
  ],
  "tueren": [],
  "massstab": "1:100",
  "geschoss": "EG",
  "wohnungen_gefunden": ["TOP 25", "TOP 26"]
}

REGELN:
- JEDE Zeile im Raum-Beschriftungsblock lesen, nicht nur die groesste.
- Wenn U oder H wirklich nicht im Ausschnitt zu sehen ist: Wert weglassen (nicht raten).
- Fuer Loggia/Balkon: U und H trotzdem eintragen falls sichtbar.
- Erfinde niemals Werte die du nicht siehst."""

    _t_tiles0 = time.time()
    # ── PHASE A (seriell): alle Tiles rendern. PyMuPDF (fitz) ist NICHT thread-
    # safe → das Rendern bleibt seriell (ist CPU-schnell, nicht der Engpass). ──
    tiles_to_call = []   # [(tile_idx, sec, img_b64)]
    for tile_idx, sec in enumerate(sections):
        # Adaptive DPI: balance image size (<3.5MB binary, <5MB base64)
        # AND pixel dimensions (max 8000 per side, Anthropic API limit)
        rect = fitz.Rect(*sec["rect"])
        sec_w_pt = rect.x1 - rect.x0
        sec_h_pt = rect.y1 - rect.y0
        max_dim_pt = max(sec_w_pt, sec_h_pt)
        max_dpi_by_dim = int(7500 / max_dim_pt * 72)
        dpi = min(300, max_dpi_by_dim)
        dpi = max(100, dpi)

        while dpi >= 80:
            mat = fitz.Matrix(dpi/72, dpi/72)
            pix = page.get_pixmap(matrix=mat, clip=rect)
            img_bytes = pix.tobytes("jpeg", jpg_quality=80)
            if len(img_bytes) < 3.5 * 1024 * 1024 and pix.width <= 7500 and pix.height <= 7500:
                break
            dpi -= 30

        if len(img_bytes) > 5 * 1024 * 1024 or pix.width > 8000 or pix.height > 8000:
            continue
        tiles_to_call.append((tile_idx, sec, base64.standard_b64encode(img_bytes).decode("utf-8")))

    # Ein Tile lesen (reiner I/O-Call + Parse) — wird parallel ausgeführt. KEINE
    # geteilte Mutation hier: liefert nur das geparste Ergebnis zurück.
    def _call_vision_tile(item):
        t_idx, sec, img_b64 = item
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8192,
                temperature=0,   # KONSTANZ: gleicher Plan → gleiche Raumliste (Tile-Backbone)
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
            try:
                return json.loads(raw)
            except Exception:
                m = re.search(r'\{[\s\S]*\}', raw)
                if m:
                    try:
                        return json.loads(m.group())
                    except Exception:
                        return None
            return None
        except Exception:
            return None

    # ── PHASE B (parallel): die langsamen Vision-Calls nebenläufig. Der anthropic-
    # Client ist thread-safe; die Ergebnisse werden tile-indiziert eingesammelt. ──
    _tile_results = [None] * len(tiles_to_call)
    try:
        _workers = max(1, min(int(os.environ.get("TILE_WORKERS", "4")), len(tiles_to_call) or 1))
        if _workers > 1 and len(tiles_to_call) > 1:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=_workers) as _ex:
                for _i, _res in enumerate(_ex.map(_call_vision_tile, tiles_to_call)):
                    _tile_results[_i] = _res
        else:
            for _i, item in enumerate(tiles_to_call):
                _tile_results[_i] = _call_vision_tile(item)
    except Exception as _exc:  # Parallelisierung fällt sauber auf seriell zurück
        print(f"[tiles] Parallel-Fallback (seriell): {_exc!r}")
        for _i, item in enumerate(tiles_to_call):
            if _tile_results[_i] is None:
                _tile_results[_i] = _call_vision_tile(item)

    # ── PHASE C (seriell, DETERMINISTISCH): in Tile-Reihenfolge zusammenführen.
    # massstab/geschoss = erster nicht-leerer Wert in Tile-Reihenfolge (stabil). ──
    for (tile_idx, sec, _), result in zip(tiles_to_call, _tile_results):
        if not result:
            continue
        for r in result.get("raeume", []):
            r["_tile"] = tile_idx
            all_rooms.append(r)
        for f in result.get("fenster", []):
            f["_tile"] = tile_idx
            all_fenster.append(f)
        for t in result.get("tueren", []):
            t["_tile"] = tile_idx
            all_tueren.append(t)
        if not massstab and result.get("massstab"):
            massstab = result["massstab"]
        if not geschoss and result.get("geschoss"):
            geschoss = result["geschoss"]
    _tiles_dauer_s = round(time.time() - _t_tiles0, 2)
    _tiles_ok = sum(1 for r in _tile_results if r)
    print(f"[tiles] {len(tiles_to_call)} Tiles, {_tiles_ok} mit Treffer, "
          f"{os.environ.get('TILE_WORKERS', '4')} Worker, {_tiles_dauer_s}s")

    # ═══ CONSENSUS GROUPING ═══
    # Key: (normalized name, normalized wohnung, F-bucket of 0.2m2).
    # Same identity seen in multiple tiles → consensus_count increases.
    def _fbucket(f):
        if not f:
            return 0
        return round(float(f) * 5) / 5  # 0.2 m2 bucket

    groups = {}
    for r in all_rooms:
        key = (_norm_name(r.get("name")), _norm_name(r.get("wohnung")), _fbucket(r.get("flaeche_m2")))
        if key not in groups:
            groups[key] = []
        groups[key].append(r)

    # For each group, merge into a single best observation keeping majority F/U/H
    def _merge_observations(obs_list):
        from collections import Counter
        merged = {}
        # Name/wohnung: take most common non-empty
        for fld in ("name", "wohnung", "bodenbelag"):
            vals = [o.get(fld) for o in obs_list if o.get(fld)]
            if vals:
                merged[fld] = Counter(vals).most_common(1)[0][0]
        # Numeric fields: median of non-null values (robust to outliers)
        for fld in ("flaeche_m2", "umfang_m", "hoehe_m"):
            vals = sorted([float(o.get(fld)) for o in obs_list if o.get(fld)])
            if vals:
                merged[fld] = vals[len(vals)//2]
        # KONSTANZ: Konfidenz deterministisch aus der Konsens-Anzahl ableiten —
        # NICHT max() über die lauf-variablen Einzel-Tile-Konfidenzen (das ließ den
        # Wert springen). F/U/H bleiben Median (unverändert). Text-verifizierte
        # Räume werden später ohnehin auf 1.0 gehoben (s. _verified).
        merged["konfidenz"] = round(min(0.95, 0.6 + 0.08 * min(len(obs_list), 4)), 2)
        merged["_consensus"] = len(obs_list)
        merged["_tile_sources"] = sorted({o.get("_tile") for o in obs_list if o.get("_tile") is not None})
        return merged

    merged_rooms = [_merge_observations(obs) for obs in groups.values()]

    # ═══ HALLUCINATION FILTER ═══
    # When PDF has a usable text layer, Vision rooms must have at least one
    # piece of text-layer evidence (room name OR F-value present in spans),
    # otherwise discard. Vision frequently invents typical-apartment rooms
    # (Wohnzimmer, Bad, Foyer) on technical plans where it can't read the
    # rotated/dense labels.
    try:
        if len(spans_all) > 100:  # only enforce on plans with real text layer
            full_text_lower = " ".join(s["text"] for s in spans_all).lower()

            def vision_has_evidence(r):
                # STRICT: room name must appear in PDF text layer.
                name = (r.get("name") or "").strip().lower()
                if len(name) < 4:
                    return False
                if name in full_text_lower:
                    return True
                for w in re.split(r"[\s/+\-]+", name):
                    if len(w) >= 5 and w in full_text_lower:
                        return True
                return False

            before = len(merged_rooms)
            merged_rooms = [r for r in merged_rooms if vision_has_evidence(r)]
            dropped = before - len(merged_rooms)
            if dropped:
                print(f"[hallucination filter] dropped {dropped}/{before} vision rooms without text-layer evidence")
    except Exception as _exc:
        print(f"[hallucination filter] failed: {_exc!r}")

    # ═══ TEXT-LAYER VERIFICATION ═══
    # Cross-check F/U/H for every room against numeric tokens near the room name.
    for r in merged_rooms:
        label_positions = find_label_pos(r.get("name", ""))
        r["_label_positions"] = label_positions  # list of bboxes
        verified = {"F": False, "U": False, "H": False}
        # Try verification against ANY of the label positions (multiple rooms with same name)
        for pos in (label_positions or []):
            if not verified["F"] and r.get("flaeche_m2"):
                verified["F"] = verify_value_near(pos, r["flaeche_m2"], 0.02, 400)
            if not verified["U"] and r.get("umfang_m"):
                verified["U"] = verify_value_near(pos, r["umfang_m"], 0.02, 400)
            if not verified["H"] and r.get("hoehe_m"):
                verified["H"] = verify_value_near(pos, r["hoehe_m"], 0.02, 400)
        r["_verified"] = verified
        # Boost confidence for fully text-verified rooms
        if verified["F"] and verified["U"] and verified["H"]:
            r["konfidenz"] = 1.0

    # ═══ PASS 3: PER-ROOM ULTRA ZOOM ═══
    # For rooms with missing F/U/H AND a known label position, re-query Claude
    # at 500 DPI on a tight rect around the label.
    ULTRA_PROMPT = """Du siehst den Beschriftungsblock eines einzelnen Raums eines Bauplans.
Gib NUR JSON zurueck - die drei Werte aus dem Block:
{"flaeche_m2": 24.13, "umfang_m": 20.66, "hoehe_m": 2.42}
Wenn ein Wert nicht zu sehen ist, feld weglassen. Keine Markdown, nur JSON."""

    max_pass3 = 25  # safety cap on extra API calls
    pass3_done = 0
    for r in merged_rooms:
        if pass3_done >= max_pass3:
            break
        missing = []
        if not r.get("flaeche_m2"): missing.append("F")
        if not r.get("umfang_m"): missing.append("U")
        if not r.get("hoehe_m"): missing.append("H")
        if not missing:
            continue
        positions = r.get("_label_positions") or []
        if not positions:
            continue
        # Use first position; render 500x500pt centered rect at 500 DPI
        bbox = positions[0]
        cx, cy = _tok_center(bbox)
        zoom_pt = 500.0
        x0 = max(0, cx - zoom_pt/2)
        y0 = max(0, cy - zoom_pt/2)
        x1 = min(pw, x0 + zoom_pt)
        y1 = min(ph, y0 + zoom_pt)
        rect = fitz.Rect(x0, y0, x1, y1)
        try:
            zoom_dpi = 500
            mat = fitz.Matrix(zoom_dpi/72, zoom_dpi/72)
            pix = page.get_pixmap(matrix=mat, clip=rect)
            zb = pix.tobytes("jpeg", jpg_quality=85)
            if len(zb) > 4 * 1024 * 1024 or pix.width > 7500 or pix.height > 7500:
                zoom_dpi = 400
                mat = fitz.Matrix(zoom_dpi/72, zoom_dpi/72)
                pix = page.get_pixmap(matrix=mat, clip=rect)
                zb = pix.tobytes("jpeg", jpg_quality=80)
            zb64 = base64.standard_b64encode(zb).decode("utf-8")
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                temperature=0,   # KONSTANZ: deterministischer Ultra-Zoom (PASS 3)
                system=ULTRA_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": zb64}},
                        {"type": "text", "text": f"Raum: {r.get('name','?')}. Lies F, U, H."}
                    ]
                }]
            )
            raw = response.content[0].text if response.content else "{}"
            sub = None
            try:
                sub = json.loads(raw)
            except:
                m = re.search(r'\{[\s\S]*\}', raw)
                if m:
                    try: sub = json.loads(m.group())
                    except: pass
            if sub:
                for fld in ("flaeche_m2", "umfang_m", "hoehe_m"):
                    if not r.get(fld) and sub.get(fld):
                        r[fld] = sub[fld]
                        r.setdefault("_verified", {})
                        # verify the new value against text layer
                        r["_verified"][fld[0].upper()] = verify_value_near(bbox, sub[fld], 0.02, 400)
                r["_pass3"] = True
            pass3_done += 1
        except Exception:
            continue

    # ═══ MERGE TEXT-FIRST GROUND TRUTH WITH VISION ═══
    # Text-first rooms carry byte-exact F/U/H from the PDF text layer.
    # Vision-only rooms (merged_rooms) contribute when text-layer is thin
    # and/or add wohnung/TOP assignment. For rooms present in both, text
    # values ALWAYS win; Vision fills in TOP if text couldn't.
    def _fkey(r):
        return (_norm_name(r.get("name")), round((r.get("flaeche_m2") or 0) * 10) / 10)

    unique_rooms = []
    used_vision = set()

    # Pass A: jeden text-first Raum mit MINDESTENS einem Maßwert (F, U oder H)
    # als Ground-Truth ausgeben. Polierpläne liefern Räume nur mit H — die
    # dürfen nicht verworfen werden, sonst springt Vision ein und halluziniert.
    for tr in text_first_rooms:
        if not (tr.get("flaeche_m2") or tr.get("umfang_m") or tr.get("hoehe_m")):
            continue
        tk = _fkey(tr)
        # Find a matching vision observation for TOP assignment
        best_vision = None
        for i, vr in enumerate(merged_rooms):
            if i in used_vision: continue
            if _fkey(vr) == tk:
                best_vision = vr
                used_vision.add(i)
                break
        rec = {
            "name": tr.get("name"),
            "wohnung": tr.get("wohnung") or (best_vision.get("wohnung") if best_vision else None),
            "flaeche_m2": tr.get("flaeche_m2"),
            "umfang_m": tr.get("umfang_m"),
            "hoehe_m": tr.get("hoehe_m"),
            "bodenbelag": tr.get("bodenbelag") or (best_vision.get("bodenbelag") if best_vision else None),
            "konfidenz": 1.0 if (tr.get("flaeche_m2") and tr.get("umfang_m") and tr.get("hoehe_m")) else 0.85,
            "_source": "text",
            "_verified": {"F": bool(tr.get("flaeche_m2")), "U": bool(tr.get("umfang_m")), "H": bool(tr.get("hoehe_m"))},
            "_bbox": list(tr.get("bbox") or []),
        }
        unique_rooms.append(rec)

    # Pass B: Vision-Räume, die text-first NICHT abgedeckt hat.
    # Bei gutem Text-Layer (text_first_enough) ist die byte-exakte Lesung
    # die Wahrheit — Vision darf dann KEINE zusätzlichen Räume erfinden
    # (sonst entstehen Duplikate wie "Zimmer 1" 3× mit geratenen Werten).
    # Einzige Ausnahme: ein Vision-Raum, dessen normalisierter Name in
    # KEINEM text-first Raum vorkommt (echte Lücke, kein Duplikat).
    if not text_first_enough:
        # Schwacher/kein Text-Layer → Vision liefert die Räume
        for i, vr in enumerate(merged_rooms):
            if i in used_vision:
                continue
            if not vr.get("flaeche_m2"):
                continue
            rec = {k: v for k, v in vr.items() if not k.startswith("_")}
            rec["_source"] = "vision"
            rec["_verified"] = vr.get("_verified", {})
            rec["_consensus"] = vr.get("_consensus", 1)
            rec["_pass3"] = vr.get("_pass3", False)
            unique_rooms.append(rec)
    else:
        # Guter Text-Layer → nur Vision-Räume mit komplett neuem Namen
        tf_names = {_norm_name(tr.get("name")) for tr in text_first_rooms}
        for i, vr in enumerate(merged_rooms):
            if i in used_vision or not vr.get("flaeche_m2"):
                continue
            if _norm_name(vr.get("name")) in tf_names:
                continue  # Name schon im Text-Layer → kein Vision-Duplikat
            rec = {k: v for k, v in vr.items() if not k.startswith("_")}
            rec["_source"] = "vision"
            rec["_verified"] = vr.get("_verified", {})
            rec["_consensus"] = vr.get("_consensus", 1)
            rec["_pass3"] = vr.get("_pass3", False)
            unique_rooms.append(rec)

    doc.close()

    # Einfamilienhaus-Fallback (post-hoc, deckt auch reine Vision-Räume ab):
    # Wenn nach allem Merge KEIN Raum eine wohnung hat → alle als "Haus"
    # markieren. Sonst übersprängen PASS 4 (Bemaßung) und LV-Aggregation
    # alle Räume (require wohnung != None).
    if unique_rooms and not any(r.get("wohnung") for r in unique_rooms):
        for r in unique_rooms:
            r["wohnung"] = "Haus"
        if not top_labels:
            xs = [r.get("cx") for r in unique_rooms if r.get("cx") is not None]
            ys = [r.get("cy") for r in unique_rooms if r.get("cy") is not None]
            if xs and ys:
                top_labels.append({
                    "name": "Haus", "cx": sum(xs)/len(xs), "cy": sum(ys)/len(ys),
                    "_synthetic": True,
                })

    # Fenster dedup — KONSTANZ: deterministisch. Vorher gewann „höchste Konfidenz",
    # was bei lauf-variablen Konfidenzen die Auswahl springen ließ. Jetzt: stabile
    # Sortierung (Konfidenz desc, dann Name/Maße) → der erste je Schlüssel ist der
    # Repräsentant, fehlende Felder werden ergänzt. Mit temperature=0 davor sind die
    # Vision-Funde selbst schon stabil; das hier sichert die Zusammenführung ab.
    fenster_groups = {}
    for f in sorted(all_fenster, key=lambda x: (
            -float(x.get("konfidenz") or 0),
            _norm_name(x.get("bezeichnung")),
            round(float(x.get("breite_m") or 0), 2),
            round(float(x.get("hoehe_m") or 0), 2))):
        key = _norm_name(f.get("bezeichnung"))
        if not key:
            continue
        if key not in fenster_groups:
            fenster_groups[key] = dict(f)
        else:
            existing = fenster_groups[key]
            for fld, val in f.items():   # erste (höchste Konf.) gewinnt, Rest ergänzt
                if val not in (None, "", 0) and not existing.get(fld):
                    existing[fld] = val
    unique_fenster = list(fenster_groups.values())

    # ─── ÖFFNUNGEN AUS TEXT-LAYER MERGEN ──────────────────────────────
    # Wenn text_oeffnungen welche enthält (STUK/FPH-Konvention), diese in
    # unique_fenster / all_tueren einreihen. Dedup gegen vorhandene
    # Vision-Funde nach (Raum + Maße).
    def _oeff_key(o):
        r = (o.get("raum") or "").strip().lower()
        bw = round(float(o.get("breite_m") or 0), 2)
        hh = round(float(o.get("hoehe_m") or 0), 2)
        return (r, bw, hh)
    existing_f_keys = {_oeff_key(f) for f in unique_fenster}
    existing_t_keys = {_oeff_key(t) for t in all_tueren}
    for o in text_oeffnungen:
        if not (o.get("breite_m") and o.get("hoehe_m")):
            continue
        rec = {
            "bezeichnung": f"{o['typ'][:1].upper()}-{int((o.get('breite_m') or 0)*100)}x{int((o.get('hoehe_m') or 0)*100)}",
            "raum": o.get("raum"),
            "breite_m": o["breite_m"],
            "hoehe_m": o["hoehe_m"],
            "flaeche_m2": round(o["breite_m"] * o["hoehe_m"], 3),
            "fph_m": o.get("fph_m"),
            "stuk_m": o.get("stuk_m"),
            "wand_typ": o.get("wand_typ"),
            "konfidenz": o.get("konfidenz", 0.9),
            "quelle": o.get("quelle", "text-layer-stuk-fph"),
        }
        k = _oeff_key(rec)
        if o["typ"] == "fenster":
            if k in existing_f_keys:
                continue
            existing_f_keys.add(k)
            unique_fenster.append(rec)
        else:
            if k in existing_t_keys:
                continue
            existing_t_keys.add(k)
            all_tueren.append(rec)

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

    # ═══════════════════════════════════════════════════════════════════
    # PASS 4 — VISION-WAND-BEMASSUNG PRO TOP (für ÖNORM-konforme Wandlängen)
    # Lokal verifiziert 2026-05-18: bei 800 DPI sind die ArchiCAD-Außen-
    # Bemaßungen (z.B. "580" cm = 5.80m) klar lesbar. Für Excel-1:1-Match
    # bei Innenputz-Wänden brauchen wir genau diese Bemaßungs-Werte —
    # die stehen NICHT im Text-Layer (sind Vektor-Grafik).
    # ═══════════════════════════════════════════════════════════════════
    wall_dims_per_top = {}
    BEMASSUNG_PROMPT = """Du siehst einen schmalen Bemaßungs-Streifen aus einem
oesterreichischen Bauplan (Maßstab 1:50). Bemaßungen sind als KETTENBEMASSUNG
dargestellt: eine Linie mit kurzen Markern, dazwischen die Wand-/Achs-Längen in
CENTIMETERN (z.B. "152", "300", "580"). Am ENDE oder über einer Kette steht oft
das GESAMTMASS — die große Zahl, die die GANZE Kette überspannt (= Summe aller
Segmente, z.B. "1389"). Dieses Gesamtmaß ist die eingebaute Selbst-Prüfung.

Lies pro Kette ZWEI Dinge:
1) ALLE Einzel-Segmente der Reihe nach (segmente_cm).
2) Das GESAMTMASS der Kette falls sichtbar (gesamt_cm), sonst null.

JSON-Antwort (kein Markdown, keine Erklärung):
{
  "ketten": [
    {"segmente_cm": [48, 152, 143, 543, 120, 231], "gesamt_cm": 1237},
    {"segmente_cm": [2, 44, 2, 301, 8, 576], "gesamt_cm": null}
  ],
  "konfidenz": 0.95
}

Wichtig:
- Werte sind cm-Zahlen (1-4-stellig). NIEMALS erfinden — nur was du klar liest.
- gesamt_cm ist die GESAMT-Länge der ganzen Kette (zur Prüfung Summe=Gesamt),
  NICHT ein einzelnes Segment. Wenn keins sichtbar: null.
- Mehrere parallele Ketten = mehrere Eintraege.
- Maßstabs-Code (z.B. "1:50") oder Achs-Buchstaben (O, P, Q) ignorieren."""

    try:
        # Gruppiere Räume pro Top
        rooms_per_top = {}
        for r in unique_rooms:
            tk = r.get("wohnung")
            if not tk:
                continue
            rooms_per_top.setdefault(tk, []).append(r)

        max_vision_tops = 12  # Cap auf 12 Tops × 4 Streifen = 48 Calls
        tops_done = 0
        for top_name, top_rooms in rooms_per_top.items():
            if tops_done >= max_vision_tops:
                break
            # Top-Bbox aus Raum-Centerpunkten (auf Plan-Koordinaten)
            xs = [r.get("cx") for r in top_rooms if r.get("cx") is not None]
            ys = [r.get("cy") for r in top_rooms if r.get("cy") is not None]
            if not xs or not ys:
                continue
            top_x0, top_x1 = min(xs), max(xs)
            top_y0, top_y1 = min(ys), max(ys)

            wd = {"top": top_name, "ketten_per_side": {}, "wandlaengen_m": {}}

            # 4 Bemaßungs-Streifen: N(orden), S(üden), W(esten), O(sten)
            STRIPS = {
                "N": (top_x0 - 100, top_y0 - 300, top_x1 + 100, top_y0 - 150),
                "S": (top_x0 - 100, top_y1 + 150, top_x1 + 100, top_y1 + 300),
                "W": (top_x0 - 350, top_y0 - 100, top_x0 - 150, top_y1 + 100),
                "E": (top_x1 + 150, top_y0 - 100, top_x1 + 350, top_y1 + 100),
            }
            for side, (sx0, sy0, sx1, sy1) in STRIPS.items():
                sx0, sy0 = max(0, sx0), max(0, sy0)
                sx1, sy1 = min(pw, sx1), min(ph, sy1)
                if sx1 - sx0 < 30 or sy1 - sy0 < 30:
                    continue
                # 800 DPI lokal verifiziert lesbar — aber Pixel-Limit beachten
                strip_w_pt = sx1 - sx0
                strip_h_pt = sy1 - sy0
                max_dim_pt = max(strip_w_pt, strip_h_pt)
                dpi = min(800, int(6000 / max_dim_pt * 72))
                dpi = max(200, dpi)

                while dpi >= 150:
                    mat = fitz.Matrix(dpi/72, dpi/72)
                    rect = fitz.Rect(sx0, sy0, sx1, sy1)
                    pix = page.get_pixmap(matrix=mat, clip=rect)
                    img_bytes = pix.tobytes("jpeg", jpg_quality=88)
                    if len(img_bytes) < 2.5 * 1024 * 1024 and pix.width <= 7500 and pix.height <= 7500:
                        break
                    dpi -= 80
                if dpi < 150:
                    continue
                img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")

                try:
                    resp = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=512,
                        temperature=0,   # KONSTANZ: deterministische Wandbemaßung (PASS 4)
                        system=BEMASSUNG_PROMPT,
                        messages=[{
                            "role": "user",
                            "content": [
                                {"type": "image", "source": {"type": "base64",
                                 "media_type": "image/jpeg", "data": img_b64}},
                                {"type": "text", "text": f"Top {top_name}, Seite {side}: lies alle Maße ab."}
                            ],
                        }],
                    )
                    raw = resp.content[0].text if resp.content else "{}"
                    parsed = None
                    try:
                        parsed = json.loads(raw)
                    except Exception:
                        m = re.search(r"\{[\s\S]*\}", raw)
                        if m:
                            try:
                                parsed = json.loads(m.group())
                            except Exception:
                                pass
                    if parsed:
                        wd["ketten_per_side"][side] = parsed
                except Exception as _exc:
                    print(f"[vision wall-dims] {top_name}/{side} failed: {_exc!r}")
                    continue

            # Aggregiere Wandlängen je Seite mit SELBST-PRÜFUNG (Σ Segmente =
            # Gesamtmaß → byte-exakt). Validierte Kette schlägt jede unvalidierte;
            # unter mehreren validierten/unvalidierten gewinnt die größte (Außenkante).
            # Die Segmente der Gewinner-Kette bleiben erhalten (für L-Form-BBox).
            wd["validiert"] = {}
            wd["segmente_m"] = {}
            wd["seite_konfidenz"] = {}
            for side, payload in wd["ketten_per_side"].items():
                ketten = payload.get("ketten") or []
                p_konf = float(payload.get("konfidenz") or 0.7)
                # Rückwärtskompatibel: alte Form war Liste von Zahlen-Arrays
                norm = []
                for k in ketten:
                    if isinstance(k, dict):
                        segs = [float(x) for x in (k.get("segmente_cm") or []) if x]
                        gesamt = k.get("gesamt_cm")
                    elif isinstance(k, list):
                        segs = [float(x) for x in k if x]
                        gesamt = None
                    else:
                        continue
                    if not segs:
                        continue
                    s = sum(segs)
                    # validiert, wenn das gedruckte Gesamtmaß zur Segment-Summe passt
                    validated = False
                    laenge = s
                    if gesamt:
                        try:
                            g = float(gesamt)
                            if abs(s - g) <= max(3.0, 0.015 * g):
                                validated = True
                                laenge = g
                        except (TypeError, ValueError):
                            pass
                    norm.append((laenge, validated, segs))
                if not norm:
                    continue
                # validierte zuerst, dann größte Länge
                norm.sort(key=lambda t: (1 if t[1] else 0, t[0]), reverse=True)
                best_len, best_val, best_segs = norm[0]
                wd["wandlaengen_m"][side] = round(best_len / 100.0, 2)
                wd["validiert"][side] = best_val
                wd["segmente_m"][side] = [round(x / 100.0, 2) for x in best_segs]
                wd["seite_konfidenz"][side] = round(p_konf if best_val else p_konf * 0.6, 2)
            wall_dims_per_top[top_name] = wd
            tops_done += 1
    except Exception as _exc:
        print(f"[vision wall-dims] global failure: {_exc!r}")

    # ═══════════════════════════════════════════════════════════════════
    # ÖNORM A 2063 LV-GENERATOR (vereinfacht — siehe scripts/oenorm_extract.py
    # für vollständige Variante mit Excel-Export)
    # ═══════════════════════════════════════════════════════════════════
    def _lv_build():
        from collections import defaultdict as _dd

        def kategorie_of(name):
            INNEN = {"Wohnküche","Wohnkueche","Wohnen","Wohnzimmer","Esszimmer","Zimmer",
                     "Schlafzimmer","Kinderzimmer","Küche","Kueche","Bad","WC","Dusche",
                     "Vorraum","Vorzimmer","Flur","Gang","Diele","Garderobe","Abstellraum",
                     "Speis","Speisekammer","AR","Büro","Buero"}
            LOGGIA = {"Loggia","Balkon","Terrasse"}
            STGH = {"Stiegenhaus","Stiege","STGH","STG","Treppenhaus"}
            base = name.split()[0] if " " in name else name
            if name in INNEN or base in INNEN: return "innen"
            if name in LOGGIA or base in LOGGIA: return "loggia"
            if name in STGH or base in STGH: return "stiegenhaus"
            return "sonstig"

        # Gruppiere pro Top
        by_top = _dd(list)
        for r in unique_rooms:
            if r.get("wohnung"):
                by_top[r["wohnung"]].append(r)

        positionen = []
        for idx, (top, top_rs) in enumerate(sorted(by_top.items()), start=1):
            innen = [r for r in top_rs if kategorie_of(r.get("name","")) == "innen"
                     and r.get("umfang_m") and r.get("hoehe_m")]
            # Innenputz Wände — via Σ(U×H) der Innenräume
            uh_sum = sum(r["umfang_m"] * r["hoehe_m"] for r in innen)
            # Innenputz Decken
            f_sum = sum(r.get("flaeche_m2", 0) or 0 for r in innen)
            # Bodenbeläge pro Material
            belag_map = _dd(float)
            for r in top_rs:
                if r.get("bodenbelag") and r.get("flaeche_m2"):
                    belag_map[r["bodenbelag"]] += r["flaeche_m2"]

            # Wenn Vision-Wandlängen verfügbar: zusätzliche Position mit Vision-Werten
            vision_dims = wall_dims_per_top.get(top, {}).get("wandlaengen_m", {})

            positionen.append({
                "top": top,
                "innenputz_waende_uxh_m2": round(uh_sum, 2),
                "innenputz_decken_m2": round(f_sum, 2),
                "boden_pro_material_m2": {k: round(v, 2) for k, v in belag_map.items()},
                "vision_wandlaengen_m": vision_dims,  # leer wenn Vision aus
                "vision_innenputz_waende_m2": (
                    round(sum(vision_dims.values()) * (sum(r.get("hoehe_m") or 0 for r in innen)/max(len(innen),1)), 2)
                    if vision_dims and innen else None
                ),
                "konfidenz_lese": 1.0,  # F/U/H byte-exakt
                "konfidenz_aggregation": 0.92 if not vision_dims else 0.97,
            })
        return positionen

    oenorm_lv = _lv_build()

    # ═══════════════════════════════════════════════════════════════════
    # ÖNORM-GEWERK-MASSENERMITTLUNG (Putz / Rohbau / Estrich / Maler)
    # Vision misst Baudaten (Wandstärken, Deckendicke, Geschosshöhe),
    # massen_logic erzeugt pro Gewerk die LV-Positionen in Buchform.
    # ═══════════════════════════════════════════════════════════════════
    gewerke_result = None
    if _MASSEN_OK:
        BAUDATEN_PROMPT = """Du bist erfahrener österreichischer Bautechniker.
Du siehst einen Bauplan-Grundriss. Bestimme die Bau-Kenndaten aus
Wanddicken, Bemaßungen, Schnitten und Material-Legende.

Erfasse AUSSERDEM jedes Fenster: Fenster sind im Grundriss als
Wandunterbrechung mit dünnen parallelen Linien (Glas) dargestellt,
oft mit Bemaßung der Öffnungsbreite. Ordne jedes Fenster dem Raum zu,
in dem es liegt, und schätze Breite × Höhe in cm.

Antworte NUR mit JSON (keine Markdown-Fences):
{"aussenwand_cm":50,"innenwand_tragend_cm":25,"innenwand_nichttragend_cm":12,
 "decke_cm":20,"bodenplatte_cm":25,"geschosshoehe_m":2.70,
 "anzahl_tueren_innen":7,"wandmaterial":"...","konfidenz":0.85,
 "fenster":[{"raum":"Wohnraum Küche","breite_cm":240,"hoehe_cm":210},
            {"raum":"Zimmer 1","breite_cm":120,"hoehe_cm":140}]}
Werte in cm bzw. m. Nicht erkennbar → null. Fenster nur eintragen wenn
im Grundriss sichtbar — niemals Fenster oder Maße erfinden."""
        baudaten = {}
        try:
            doc2 = fitz.open(stream=pdf_bytes, filetype="pdf")
            p2 = doc2[0]
            dpi_bd = 200
            bd_img = None
            while dpi_bd >= 90:
                mat = fitz.Matrix(dpi_bd / 72, dpi_bd / 72)
                pix = p2.get_pixmap(matrix=mat)
                bd_img = pix.tobytes("jpeg", jpg_quality=82)
                if len(bd_img) < 4.5 * 1024 * 1024 and pix.width <= 8000 and pix.height <= 8000:
                    break
                dpi_bd -= 40
            doc2.close()
            if bd_img:
                bd_b64 = base64.standard_b64encode(bd_img).decode("utf-8")
                resp = client.messages.create(
                    model="claude-sonnet-4-20250514", max_tokens=1024, temperature=0,
                    system=BAUDATEN_PROMPT,
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64",
                         "media_type": "image/jpeg", "data": bd_b64}},
                        {"type": "text", "text": "Bestimme die Bau-Kenndaten dieses Plans."}
                    ]}],
                )
                raw = resp.content[0].text if resp.content else "{}"
                try:
                    baudaten = json.loads(raw)
                except Exception:
                    m = re.search(r"\{[\s\S]*\}", raw)
                    baudaten = json.loads(m.group()) if m else {}
        except Exception as _exc:
            print(f"[baudaten] Vision-Messung fehlgeschlagen: {_exc!r}")
            baudaten = {}

        # Konfidenz-Schwelle: bei sehr unsicherer Vision (<0.5) Wandstärken
        # leeren → massen_logic greift auf Defaults zurück. 0.5 statt 0.7
        # weil Vision-Schätzungen aus Grundriss meist ~0.5-0.7 Konfidenz
        # liefern (Wandtypen sind aus oben schwer ablesbar) und der Default
        # 38cm Außenwand oft schlechter ist als die Vision-Schätzung 50cm.
        if (baudaten.get("konfidenz") or 0) < 0.5:
            for _k in ("aussenwand_cm", "innenwand_tragend_cm",
                       "innenwand_nichttragend_cm", "decke_cm", "bodenplatte_cm"):
                baudaten.pop(_k, None)

        # Räume für die Gewerk-Berechnung vorbereiten (cx/cy aus _bbox ableiten)
        rooms_fg = []
        for r in unique_rooms:
            rr = dict(r)
            if rr.get("cx") is None and rr.get("_bbox"):
                bb = rr["_bbox"]
                if len(bb) >= 4:
                    rr["cx"] = (bb[0] + bb[2]) / 2.0
                    rr["cy"] = (bb[1] + bb[3]) / 2.0
            rooms_fg.append(rr)

        # ═══════════════════════════════════════════════════════════════
        # DEDIZIERTER FENSTER-VISION-PASS
        # Der BAUDATEN-Call findet Fenster nur als Nebenprodukt. Hier
        # ein eigener Vision-Call NUR für Fenster — höhere DPI, fokussierter
        # Prompt, findet Fenster ohne FE_/F25_-Codes (z.B. Einreichpläne,
        # Einfamilienhäuser). Liefert pro Fenster: Raum, Breite × Höhe
        # in cm, optional Brüstungshöhe.
        # ═══════════════════════════════════════════════════════════════
        FENSTER_PROMPT = """Du siehst einen oesterreichischen Grundriss-Plan.
Finde JEDES einzelne Fenster im Grundriss. Fenster sind im Plan dargestellt als:
  - Wandunterbrechung mit DUENNEN parallelen Linien (Glasflaeche)
  - oft mit Bemassung 'XX cm' der Oeffnungsbreite ueber dem Fenster
  - oft mit Code-Bezeichnung wie 'FE_25', 'F25_1', oder ohne Code
  - Brüstungshoehe-Codes neben dem Fenster: RB/AL/RPH/FPH gefolgt von Wert

Wichtig:
- Vergiss KEIN Fenster — auch Bad/WC/Speisekammer-Fenster mitnehmen.
- Wenn mehrere Fenster in einem Raum sind, jedes EINZELN auflisten.
- Schiebetueren zu Terrasse/Loggia sind AUCH Fenster (oft 240cm breit).
- Tueren (Drehfluegel, dicker Bogen) sind KEINE Fenster.

JSON-Antwort, kein Markdown:
{
  "fenster": [
    {"bezeichnung": "F1", "raum": "Wohnraum Küche", "breite_cm": 240, "hoehe_cm": 210, "konfidenz": 0.9},
    {"bezeichnung": "F2", "raum": "Zimmer 1", "breite_cm": 120, "hoehe_cm": 140, "konfidenz": 0.85}
  ]
}
Werte in cm. Wenn Bemassung nicht lesbar: Wert schätzen aus Wand-Anteil
(z.B. Wand 4m, Fenster nimmt 1/3 ein → ca. 130cm Breite).
NIEMALS erfinden, nur was im Plan sichtbar ist."""

        vision_fenster = []
        try:
            doc3 = fitz.open(stream=pdf_bytes, filetype="pdf")
            p3 = doc3[0]
            # Höhere Standard-DPI für Fenster (250 statt 200) damit dünne
            # Glas-Linien lesbar sind
            dpi_f = 250
            f_img = None
            while dpi_f >= 100:
                mat = fitz.Matrix(dpi_f / 72, dpi_f / 72)
                pix = p3.get_pixmap(matrix=mat)
                f_img = pix.tobytes("jpeg", jpg_quality=85)
                if len(f_img) < 4.5 * 1024 * 1024 and pix.width <= 8000 and pix.height <= 8000:
                    break
                dpi_f -= 30
            doc3.close()
            if f_img:
                f_b64 = base64.standard_b64encode(f_img).decode("utf-8")
                resp = client.messages.create(
                    model="claude-sonnet-4-20250514", max_tokens=2048, temperature=0,
                    system=FENSTER_PROMPT,
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64",
                         "media_type": "image/jpeg", "data": f_b64}},
                        {"type": "text", "text": "Finde jedes Fenster in diesem Plan."}
                    ]}],
                )
                raw = resp.content[0].text if resp.content else "{}"
                try:
                    parsed = json.loads(raw)
                except Exception:
                    m = re.search(r"\{[\s\S]*\}", raw)
                    parsed = json.loads(m.group()) if m else {}
                vision_fenster = parsed.get("fenster") or []
                print(f"[fenster-vision] {len(vision_fenster)} Fenster aus Vision")
        except Exception as _exc:
            print(f"[fenster-vision] fehlgeschlagen: {_exc!r}")
            vision_fenster = []

        # Vision-erkannte Fenster (aus dediziertem Pass + Baudaten) ergänzen.
        # Dedup gegen unique_fenster nach (Raum, Breite, Höhe) — Vision findet
        # oft die selben Fenster, die schon im Text-Layer als FE_/F25_-Codes
        # stehen. Nur ECHT neue Fenster zu unique_fenster zufügen.
        def _fkey(f):
            r = (f.get("raum") or "").strip().lower()
            bw = round(float(f.get("breite_m") or (f.get("breite_cm") or 0) / 100.0), 2)
            hh = round(float(f.get("hoehe_m") or (f.get("hoehe_cm") or 0) / 100.0), 2)
            return (r, bw, hh)
        existing_keys = {_fkey(f) for f in unique_fenster}

        def _add_vision_fenster(_vf, quelle):
            _bw, _hw = _vf.get("breite_cm"), _vf.get("hoehe_cm")
            if not (_bw and _hw):
                return
            entry = {
                "bezeichnung": _vf.get("bezeichnung") or f"{quelle[:1].upper()}-{_bw}x{_hw}",
                "raum": _vf.get("raum"),
                "breite_m": round(_bw / 100.0, 2),
                "hoehe_m": round(_hw / 100.0, 2),
                "flaeche_m2": round(_bw * _hw / 10000.0, 2),
                "konfidenz": float(_vf.get("konfidenz") or 0.75),
                "quelle": quelle,
            }
            k = _fkey(entry)
            if k in existing_keys:
                return
            existing_keys.add(k)
            unique_fenster.append(entry)
            # Auch in elemente persistieren, damit Materialliste/Export sie sehen
            try:
                sb.table("elemente").insert({
                    "plan_id": body.plan_id, "typ": "fenster",
                    "bezeichnung": entry["bezeichnung"],
                    "daten": entry,
                    "konfidenz": int(entry["konfidenz"] * 100),
                }).execute()
            except Exception as _e:
                print(f"[fenster persist] {_e}")

        for _vf in vision_fenster:
            _add_vision_fenster(_vf, quelle="fenster-vision")
        for _vf in (baudaten.get("fenster") or []):
            _add_vision_fenster(_vf, quelle="baudaten-vision")

        alle_fenster = list(unique_fenster)

        # ═══════════════════════════════════════════════════════════════
        # MASSKETTEN-TEXT-LAYER-PASS (byte-exakt, KEIN Vision)
        # Die Außenmaße stehen als Kettenbemaßung im PDF-Text-Layer. Wir lesen
        # sie byte-exakt und rekonstruieren die Gebäude-Hülle (Bounding-Box),
        # verankert an der Σ-Innenraum-Fläche → stabil, kein Vision-Schwanken.
        # ═══════════════════════════════════════════════════════════════
        massketten_bbox = None
        if _MASSKETTEN_OK:
            try:
                docm = fitz.open(stream=pdf_bytes, filetype="pdf")
                spans_mk = _mk_spans(docm[0].get_text("words"))
                docm.close()
                from massen_logic import kategorie_of as _kat_mk
                fp = sum(r.get("flaeche_m2") or 0 for r in unique_rooms
                         if _kat_mk(r.get("name") or "") == "Innenraum_warm")
                if fp > 20 and spans_mk:
                    massketten_bbox = _mk_bbox(spans_mk, fp)
                print(f"[massketten] footprint={round(fp,1)} → {massketten_bbox}")
            except Exception as _exc:
                print(f"[massketten] failed: {_exc!r}")
                massketten_bbox = None

        # ═══════════════════════════════════════════════════════════════
        # AUSSENKONTUR-VISION-PASS
        # Vision sieht den gesamten Grundriss und liefert:
        #   - Außenkontur-Polygon in normalisierten 0-1-Koordinaten
        #   - Außenmaße pro Himmelsrichtung in Metern (N/S/W/O)
        #   - Außenumfang in Metern (Summe)
        #   - Bodenplatten-Fläche in m² (Polygon-Fläche)
        # Das ist DIE Größe die heute geschätzt wird (sqrt × 1.55) und
        # für ~25% Abweichung bei HLZ-Paletten und EKV-Bahnen sorgt.
        # ═══════════════════════════════════════════════════════════════
        AUSSENKONTUR_PROMPT = """Du siehst einen oesterreichischen EFH-Grundriss.
Ein Polier unterscheidet ZWEI verschiedene Aussenlinien — gib BEIDE zurueck:

══ LINIE A: GEMAUERTE HAUPTBAU-HUELLE ══
Die Aussenwand-Linie um die geheizten Innenraeume + Geraete-/Abstell-
raum + Stiegenhaus. Das ist die Linie fuer das MAUERWERK (Ziegel).
NICHT die Terrasse, NICHT ueberdachte Bereiche — nur die 4 gemauerten
Aussenwaende des Hauptbaus.

══ LINIE B: FUNDAMENTPLATTEN-AUSSENKANTE ══
Die Aussenkante der DURCHGEHENDEN BODENPLATTE / des Fundaments. Das ist
die Linie fuer FROSTSCHUERZE, RANDABSCHLUSS und Sockelabdichtung — sie
laeuft AUSSEN um ALLES, was auf DERSELBEN durchgehenden Platte steht:
  • den gemauerten Hauptbau (Linie A), UND
  • fest angebaute ueberdachte/auskragende Bereiche, die mit dem Haus auf
    EINER Platte stehen: Loggia, ueberdachte Terrasse unter dem Hauptdach,
    eingebundener ueberdachter Eingang, in den Baukoerper integrierter Carport.
AUSGENOMMEN von Linie B: freistehende Terrassen/Carports mit EIGENEM,
getrenntem Fundament (erkennbar an eigener Fundamentlinie / Fuge / nicht
unter dem Hauptdach). Im Zweifel: was unter dem durchgehenden Hauptdach
liegt und an >=1 Hauswand anschliesst, gehoert zu Linie B.

Linie B ist IMMER >= Linie A (oft 5-20% groesser). Wenn ein Plan keine
angebauten ueberdachten Bereiche zeigt, ist Linie B = Linie A.

EFH haben fast IMMER eine L-/U-/T-Form mit Vor- und Ruecksprungen.
Ein einfaches Rechteck ist die seltene Ausnahme. Lies die Masse aus der
Hauptbemassungskette am Plan-Rand. Pro Himmelsrichtung KANN es MEHRERE
Werte geben (L-Form: Nordfassade z.B. 8m + 4m = 12m → "N" und "N_b").

══ GESAMTMASS (am WICHTIGSTEN, separat lesen) ══
Am aeussersten Rand des Grundrisses steht meist je eine GESAMTMASS-Kette:
die GROESSTE Zahl entlang der oberen/unteren Kante = Gesamt-BREITE des Gebaeudes,
die GROESSTE Zahl entlang der linken/rechten Kante = Gesamt-TIEFE. Das sind die
zwei aeussersten, groessten Massketten-Werte (Aussenkante bis Aussenkante, ueber
ALLE Vor-/Ruecksprunge). Lies sie als "gesamt_breite_m" und "gesamt_tiefe_m".
Diese beiden Zahlen sind fuer den Umfang am verlaesslichsten — 2×(B+T) ist bei
rechtwinkligen Bauten der EXAKTE Umfang, auch bei L-Form.

JSON-Antwort, kein Markdown:
{
  "polygon_norm": [[0.12,0.10],[0.85,0.10],[0.85,0.45],[0.62,0.45],[0.62,0.62],[0.12,0.62]],
  "seiten_m": {"N": 12.40, "S": 7.20, "S_b": 5.20, "W": 8.00, "E": 4.50, "E_b": 3.50},
  "umfang_m": 40.80,
  "flaeche_m2": 79.56,
  "gesamt_breite_m": 12.40,
  "gesamt_tiefe_m": 8.00,
  "fundament_seiten_m": {"N": 12.40, "S": 12.40, "W": 10.20, "E": 10.20},
  "fundament_umfang_m": 45.20,
  "fundament_flaeche_m2": 126.50,
  "fundament_einschluss": ["ueberdachte Terrasse Sued"],
  "konfidenz": 0.85
}
Wichtig:
- "gesamt_breite_m"/"gesamt_tiefe_m" = aeusserste Gebaeude-Gesamtmasse (Aussenkante
  bis Aussenkante). NUR setzen wenn du eine klare Gesamtmass-Zahl liest, sonst null.
- "polygon_norm" + "seiten_m" + "umfang_m" + "flaeche_m2" = LINIE A (Hauptbau).
- "fundament_*" = LINIE B (Bodenplatten-Aussenkante inkl. angebauter ueberdachter Bereiche).
- Beide "umfang_m" = Summe ALLER zugehoerigen seiten_m-Werte (auch _b/_c-Segmente).
- Plausi: EFH-Hauptbau 80-180 m² / Umfang 45-75m. Fundamentkante bis ~30% groesser.
- Wenn fundament_flaeche_m2 > 1.6 × flaeche_m2: zu viel mitgenommen — nur fest
  angebaute, ueberdachte, auf der Platte stehende Bereiche zaehlen."""

        aussenkontur_vision = {}
        try:
            doc4 = fitz.open(stream=pdf_bytes, filetype="pdf")
            p4 = doc4[0]
            dpi_ak = 200
            ak_img = None
            while dpi_ak >= 100:
                mat = fitz.Matrix(dpi_ak / 72, dpi_ak / 72)
                pix = p4.get_pixmap(matrix=mat)
                ak_img = pix.tobytes("jpeg", jpg_quality=85)
                if len(ak_img) < 4.5 * 1024 * 1024 and pix.width <= 8000 and pix.height <= 8000:
                    break
                dpi_ak -= 30
            doc4.close()
            if ak_img:
                ak_b64 = base64.standard_b64encode(ak_img).decode("utf-8")
                resp = client.messages.create(
                    model="claude-sonnet-4-20250514", max_tokens=1024, temperature=0,
                    system=AUSSENKONTUR_PROMPT,
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64",
                         "media_type": "image/jpeg", "data": ak_b64}},
                        {"type": "text", "text": "Bestimme die Außenkontur und Außenmaße."}
                    ]}],
                )
                raw = resp.content[0].text if resp.content else "{}"
                try:
                    aussenkontur_vision = json.loads(raw)
                except Exception:
                    mjs = re.search(r"\{[\s\S]*\}", raw)
                    aussenkontur_vision = json.loads(mjs.group()) if mjs else {}
                # Konsistenz: Summe seiten_m sollte ≈ umfang_m sein
                seiten = aussenkontur_vision.get("seiten_m") or {}
                if seiten:
                    summe = sum(float(v or 0) for v in seiten.values())
                    if aussenkontur_vision.get("umfang_m"):
                        diff = abs(summe - float(aussenkontur_vision["umfang_m"]))
                        if diff > 2.0:  # >2m Abweichung → Umfang aus Summe korrigieren
                            aussenkontur_vision["umfang_m"] = round(summe, 2)
                            aussenkontur_vision["_umfang_korrigiert"] = True
                    else:
                        aussenkontur_vision["umfang_m"] = round(summe, 2)
                # LINIE B (Fundamentplatten-Außenkante): gleiche Konsistenz +
                # Plausi-Klemmung. Sie MUSS ≥ Linie A sein und darf nicht
                # absurd groß werden (Vision-Übererfassung) → Band [1.0, 1.30].
                f_seiten = aussenkontur_vision.get("fundament_seiten_m") or {}
                f_umfang = aussenkontur_vision.get("fundament_umfang_m")
                if f_seiten and not f_umfang:
                    f_umfang = round(sum(float(v or 0) for v in f_seiten.values()), 2)
                a_umf = aussenkontur_vision.get("umfang_m")
                a_fl = aussenkontur_vision.get("flaeche_m2")
                if f_umfang and a_umf:
                    f_umfang = float(f_umfang)
                    # Fundamentkante nie kleiner als Hauptbau, nie >30% größer
                    f_umfang = min(max(f_umfang, float(a_umf)), float(a_umf) * 1.30)
                    aussenkontur_vision["fundament_umfang_m"] = round(f_umfang, 2)
                f_fl = aussenkontur_vision.get("fundament_flaeche_m2")
                if f_fl and a_fl:
                    f_fl = min(max(float(f_fl), float(a_fl)), float(a_fl) * 1.60)
                    aussenkontur_vision["fundament_flaeche_m2"] = round(f_fl, 2)
                print(f"[aussenkontur] hauptbau_umfang={aussenkontur_vision.get('umfang_m')} m, "
                      f"fundament_umfang={aussenkontur_vision.get('fundament_umfang_m')} m, "
                      f"flaeche={aussenkontur_vision.get('flaeche_m2')} m², "
                      f"einschluss={aussenkontur_vision.get('fundament_einschluss')}, "
                      f"konf={aussenkontur_vision.get('konfidenz')}")
        except Exception as _exc:
            print(f"[aussenkontur] failed: {_exc!r}")
            aussenkontur_vision = {}

        # ═══════════════════════════════════════════════════════════════
        # SCHNITT-/ANSICHTS-VISION-PASS
        # Der Einreichplan zeigt NEBEN dem Grundriss auch Schnitte (A-A, B-B)
        # und Ansichten (Nord/Süd/...). Dort stehen Dinge, die im Grundriss
        # FEHLEN: Säulen/Stützen, echte Geschoss-Höhe, Dachtyp + Attika-Höhe,
        # Schichtdicken. Genau die Lücken aus dem Angerer-Abgleich.
        # ═══════════════════════════════════════════════════════════════
        SCHNITT_PROMPT = """Du siehst ein oesterreichisches Einreichplan-Blatt.
Darauf sind NEBEN dem Grundriss auch SCHNITTE (Querschnitte, z.B. "Schnitt A-A")
und ANSICHTEN (Nord/Sued/Ost/West) abgebildet. Lies Werte AUS DEN SCHNITTEN UND
ANSICHTEN (NICHT aus dem Grundriss):

1) Geschoss-Hoehe: lichte Raumhoehe (FBOK bis Decken-Unterkante) UND Rohbau-
   Geschosshoehe (Fussboden bis Rohdecke), in Metern.
2) Gebaeude-Hoehe gesamt (First bzw. Attika ueber Gelaende/EG-Fussboden), in Metern.
3) Dachtyp: "flach" | "pult" | "sattel" | "walm" | "zelt". Bei Flachdach: Attika-Hoehe in m.
4) Anzahl freistehender STUETZEN/SAEULEN (eigene tragende Stuetzen, sichtbar als
   schmale senkrechte Elemente in Schnitt/Ansicht oder ausgefuellte Punkte im
   Grundriss — NICHT Wandstuecke). 0 wenn keine.
5) Kamin sichtbar? Hoehe ueber Dach in m falls beschriftet.
6) Schicht-Dicken falls in einem Schnitt-Detail beschriftet: Bodenplatte, Decke,
   Estrich, Daemmung (in cm).

Antworte NUR mit JSON, kein Markdown:
{
  "geschosshoehe_licht_m": 2.62,
  "geschosshoehe_rohbau_m": 2.95,
  "gebaeudehoehe_m": 4.8,
  "dachtyp": "flach",
  "attika_hoehe_m": 0.5,
  "saeulen_anzahl": 2,
  "kamin_sichtbar": true,
  "schichten_cm": {"bodenplatte": 25, "decke": 20, "estrich": 7},
  "konfidenz": 0.7,
  "quelle": "Schnitt A-A + Suedansicht"
}
Regeln:
- Nur lesen was WIRKLICH beschriftet/sichtbar ist; unbekannte Felder = null.
- saeulen_anzahl konservativ: nur ZAEHLEN was eindeutig eine freistehende Stuetze ist.
- Wenn KEIN Schnitt/keine Ansicht auf dem Blatt ist: {"kein_schnitt": true}."""
        schnitt_vision = {}
        try:
            docs = fitz.open(stream=pdf_bytes, filetype="pdf")
            ps = docs[0]
            dpi_s = 230
            s_img = None
            while dpi_s >= 110:
                mat = fitz.Matrix(dpi_s / 72, dpi_s / 72)
                pix = ps.get_pixmap(matrix=mat)
                s_img = pix.tobytes("jpeg", jpg_quality=85)
                if len(s_img) < 4.5 * 1024 * 1024 and pix.width <= 8000 and pix.height <= 8000:
                    break
                dpi_s -= 30
            docs.close()
            if s_img:
                s_b64 = base64.standard_b64encode(s_img).decode("utf-8")
                resp = client.messages.create(
                    model="claude-sonnet-4-20250514", max_tokens=700, temperature=0,
                    system=SCHNITT_PROMPT,
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64",
                         "media_type": "image/jpeg", "data": s_b64}},
                        {"type": "text", "text": "Lies Geschoss-Höhe, Dachtyp/Attika, Säulen-Anzahl und Schichtdicken aus den Schnitten/Ansichten."}
                    ]}],
                )
                raw = resp.content[0].text if resp.content else "{}"
                try:
                    schnitt_vision = json.loads(raw)
                except Exception:
                    mjs = re.search(r"\{[\s\S]*\}", raw)
                    schnitt_vision = json.loads(mjs.group()) if mjs else {}
                # Plausi-Klemmung: Geschoss-Höhe 2.2–4.5m, Attika 0.2–1.5m, Säulen 0–40
                gh = schnitt_vision.get("geschosshoehe_rohbau_m")
                if gh and not (2.2 <= float(gh) <= 4.5):
                    schnitt_vision["geschosshoehe_rohbau_m"] = None
                sa = schnitt_vision.get("saeulen_anzahl")
                if sa is not None:
                    try:
                        schnitt_vision["saeulen_anzahl"] = max(0, min(40, int(sa)))
                    except (TypeError, ValueError):
                        schnitt_vision["saeulen_anzahl"] = None
                print(f"[schnitt] geschoss_rohbau={schnitt_vision.get('geschosshoehe_rohbau_m')} m, "
                      f"dachtyp={schnitt_vision.get('dachtyp')}, attika={schnitt_vision.get('attika_hoehe_m')} m, "
                      f"saeulen={schnitt_vision.get('saeulen_anzahl')}, konf={schnitt_vision.get('konfidenz')}")
        except Exception as _exc:
            print(f"[schnitt] failed: {_exc!r}")
            schnitt_vision = {}

        # ═══════════════════════════════════════════════════════════════
        # ÖFFNUNGS-SYMBOL-VISION-PASS
        # Zählt Tür-/Fenster-SYMBOLE rein nach Zeichnung (Schwenkbogen = Tür,
        # Wandöffnung mit Parallellinien = Fenster) — unabhängig von Text-Codes.
        # Dient als OBERGRENZE (Cap) + Doppelcheck gegen Über-Erkennung (z.B.
        # WC/WC1-Doppelzählung). NIE auffüllen, nie erfinden.
        # ═══════════════════════════════════════════════════════════════
        OEFFNUNGS_SYMBOL_PROMPT = """Du siehst einen oesterreichischen Geschoss-Grundriss.
Deine EINZIGE Aufgabe: zaehle die TUER- und FENSTER-SYMBOLE rein nach ihrer
ZEICHNUNG (NICHT nach Text-Codes — STUK/FPH werden separat gelesen).

TUER-SYMBOL — zaehle als "tuer":
- Drehfluegeltuer: kurze Tuerblatt-Linie senkrecht zur Wand + angehaengter
  Viertelkreis-Bogen (Schwenkbogen, zeigt Aufschlagrichtung). Hauptmerkmal.
- Doppel-/Pendeltuer: zwei spiegelbildliche Viertelkreis-Boegen = EINE Oeffnung.
- Schiebetuer: zwei parallele Linien laengs der Wand mit Versatz/Pfeil (KEIN Bogen).
- Eine Tuer sitzt IMMER in einer Wandluecke (Mauerwerk links+rechts unterbrochen).

FENSTER-SYMBOL — zaehle als "fenster":
- Wandunterbrechung mit 2-3 duennen PARALLELEN Linien laengs der Wand (aussen =
  Wandkanten, Mitte = Glas). Kein Schwenkbogen. Sitzt fast immer in der AUSSENWAND.
- Boden-/Terrassenfenster und Hebe-Schiebe-Elemente (oft ~240cm) auch als Fenster.

NICHT zaehlen: Moebel/Einbauten (Schrank-/Duschtuer MITTEN im Raum ohne Wandluecke),
Schraffuren, Daemmungs-Doppellinien, Treppen, Bemaszungs-/Hilfslinien,
Tuerrahmen-Doppellinien OHNE Bogen.

Regeln:
- KONSERVATIV zaehlen. Im Zweifel NICHT zaehlen. Lieber leicht zu wenig als zu
  viel — erfinde NIE eine Oeffnung. Jede physische Oeffnung genau EINMAL.
- Raum zuordnen wenn sicher, sonst raum=null (nicht raten).

Antworte NUR mit JSON, kein Markdown:
{
  "tueren_gesamt": 9,
  "fenster_gesamt": 11,
  "tueren": [{"raum": "WC", "typ": "dreh", "konfidenz": 0.9}],
  "fenster": [{"raum": "Bad", "konfidenz": 0.9}],
  "konfidenz": 0.75
}
Wenn KEIN Grundriss auf dem Blatt (nur Schnitte/Deckblatt): {"kein_grundriss": true}."""
        oeffnungs_symbole = {}
        try:
            doco = fitz.open(stream=pdf_bytes, filetype="pdf")
            po = doco[0]
            dpi_o = 250
            o_img = None
            while dpi_o >= 120:
                mat = fitz.Matrix(dpi_o / 72, dpi_o / 72)
                pix = po.get_pixmap(matrix=mat)
                o_img = pix.tobytes("jpeg", jpg_quality=85)
                if len(o_img) < 4.5 * 1024 * 1024 and pix.width <= 8000 and pix.height <= 8000:
                    break
                dpi_o -= 30
            doco.close()
            if o_img:
                o_b64 = base64.standard_b64encode(o_img).decode("utf-8")
                resp = client.messages.create(
                    model="claude-sonnet-4-20250514", max_tokens=2048, temperature=0,
                    system=OEFFNUNGS_SYMBOL_PROMPT,
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64",
                         "media_type": "image/jpeg", "data": o_b64}},
                        {"type": "text", "text": "Zähle die Tür- und Fenster-Symbole im Grundriss."}
                    ]}],
                )
                raw = resp.content[0].text if resp.content else "{}"
                try:
                    oeffnungs_symbole = json.loads(raw)
                except Exception:
                    mjs = re.search(r"\{[\s\S]*\}", raw)
                    oeffnungs_symbole = json.loads(mjs.group()) if mjs else {}
                for kk in ("tueren_gesamt", "fenster_gesamt"):
                    v = oeffnungs_symbole.get(kk)
                    if v is not None:
                        try:
                            oeffnungs_symbole[kk] = max(0, min(60, int(v)))
                        except (TypeError, ValueError):
                            oeffnungs_symbole[kk] = None
                print(f"[oeffnungs-symbole] tueren={oeffnungs_symbole.get('tueren_gesamt')}, "
                      f"fenster={oeffnungs_symbole.get('fenster_gesamt')}, "
                      f"konf={oeffnungs_symbole.get('konfidenz')}")
        except Exception as _exc:
            print(f"[oeffnungs-symbole] failed: {_exc!r}")
            oeffnungs_symbole = {}

        # OPUS-BAUINGENIEUR: läuft jetzt PRO PROJEKT (1× in projekt_massen, nach
        # dem Merge aller Pläne), NICHT mehr pro Plan — spart bei Multi-Plan-Projekten
        # N−1 teure Opus-Calls. Pro-Plan nur noch optional via env OPUS_PER_PLAN=1
        # (Dev/Fallback). OPUS_PASS=0 schaltet ganz ab. Der Prompt + Aufruf sind in
        # der modul-level _run_opus_pass()/_opus_fakten() gekapselt (DRY).
        _hat_schnitt = bool(schnitt_vision and not schnitt_vision.get("kein_schnitt"))
        _opus_an = os.environ.get("OPUS_PASS", "1") != "0"
        _opus_per_plan = os.environ.get("OPUS_PER_PLAN", "0") != "0"
        opus_bauingenieur = {}
        if _opus_an and _opus_per_plan and _hat_schnitt:
            _leg_facts = _parse_legende(spans_all) if _LEGENDE_OK else {}
            opus_bauingenieur = _run_opus_pass(
                pdf_bytes,
                _opus_fakten(unique_rooms, _leg_facts, massketten_bbox,
                             len(unique_fenster), len(all_tueren)),
                api_key)
        elif _opus_an and _opus_per_plan:
            opus_bauingenieur = {"_skipped": "kein_schnitt"}
        else:
            opus_bauingenieur = {"_skipped": "projekt_weit"}  # läuft in projekt_massen

        try:
            gewerke_result = _berechne_gewerke(
                rooms_fg, alle_fenster, baudaten, geschoss or "EG", None)
        except Exception as _exc:
            print(f"[gewerke] Berechnung fehlgeschlagen: {_exc!r}")
            gewerke_result = None

    # Store in agent_log
    log = plan.get("agent_log") or {}
    log["zoom_analyse"] = {
        "sections": len(sections),
        "raeume": len(unique_rooms),
        "fenster": len(unique_fenster),
        "tueren": len(all_tueren),
        "massstab": massstab,
        "geschoss": geschoss,
        "vision_wall_tops": len(wall_dims_per_top),
    }
    # Beobachtbarkeit: Tile-Phasen-Dauer + Worker-Zahl (Prod-Debugging der Latenz)
    log["_timing"] = {
        "tiles_s": _tiles_dauer_s,
        "tiles_n": len(tiles_to_call),
        "tiles_worker": int(os.environ.get("TILE_WORKERS", "4")),
    }
    log["geo"] = {
        "raeume": unique_rooms,
        "fenster": unique_fenster,
        "tueren": all_tueren,
        "massstab": massstab,
        "geschoss": geschoss,
    }
    log["wand_bemassung_vision"] = wall_dims_per_top
    # Außenkontur-Vision (Polygon + Außenmaße) für projekt-massen-Konsum
    if _MASSEN_OK:  # nur in dem Pfad existiert die Variable
        try:
            log["aussenkontur_vision"] = aussenkontur_vision
        except NameError:
            pass
        # Schnitt-/Ansichts-Lesung (Säulen, Geschoss-Höhe, Dachtyp, Attika)
        try:
            log["schnitt_vision"] = schnitt_vision
        except NameError:
            pass
        # Öffnungs-Symbol-Zählung (Cap/Doppelcheck gegen Über-Erkennung)
        try:
            log["oeffnungs_symbole"] = oeffnungs_symbole
        except NameError:
            pass
        # Maßketten-Text-Layer-BBox (byte-exakte Hülle, kein Vision)
        try:
            log["massketten_bbox"] = massketten_bbox
        except NameError:
            pass
        # Opus-4.8-Bauingenieur-Urteil (ganzheitlich, gegroundet) — eigene Quelle
        # für Kreuz-Kontrolle/Doppelcheck, byte-exaktes bleibt unangetastet.
        try:
            log["opus_bauingenieur"] = opus_bauingenieur
        except NameError:
            pass
    # Bauteil-Legende byte-exakt aus dem Text-Layer lesen (wie ein Mensch):
    # Wandstärken pro Code, Decke, Bodenplatte, Sauberkeit, Estrich.
    if _LEGENDE_OK:
        try:
            log["legende"] = _parse_legende(spans_all)
        except Exception as _exc:
            print(f"[legende] parse fehlgeschlagen: {_exc!r}")
    log["oenorm_lv"] = oenorm_lv
    if gewerke_result:
        log["gewerke"] = gewerke_result
    # ── DETERMINISTISCHE Plan-Konfidenz (statt hartem 95) ──
    # Anteil der gegen den PDF-Text-Layer verifizierten Raum-Werte (F/U/H). Reine
    # Funktion gespeicherter Daten → gleicher Plan ergibt IMMER dieselbe Zahl
    # (kein „gefühltes" 95/88). Nur anwendbare Felder zählen (Loggia hat keine Höhe).
    _FLD = {"F": "flaeche_m2", "U": "umfang_m", "H": "hoehe_m"}
    def _vscore(r):
        v = r.get("_verified") or {}
        applicable = [k for k in ("F", "U", "H") if r.get(_FLD[k])]
        if not applicable:
            return 0.5
        return sum(1 for k in applicable if v.get(k)) / len(applicable)
    _rooms_conf = [r for r in unique_rooms if (r.get("flaeche_m2") or r.get("umfang_m"))]
    _avg_v = (sum(_vscore(r) for r in _rooms_conf) / len(_rooms_conf)) if _rooms_conf else 0.5
    gesamt_konf = int(round(max(55, min(98, 60 + _avg_v * 38))))
    sb.table("plaene").update({
        "agent_log": log, "gesamt_konfidenz": gesamt_konf, "input_hash": input_hash,
    }).eq("id", body.plan_id).execute()

    return {
        "status": "ok",
        "sections_analyzed": len(sections),
        "raeume": len(unique_rooms),
        "fenster": len(unique_fenster),
        "tueren": len(all_tueren),
        "massstab": massstab,
        "geschoss": geschoss,
        "vision_wall_tops": len(wall_dims_per_top),
        "oenorm_positionen": len(oenorm_lv),
        "gewerke": list((gewerke_result or {}).get("gewerke", {}).keys()),
    }


class ProjektMassenRequest(BaseModel):
    """Eingang: entweder projekt_id ODER plan_id (dann wird projekt_id daraus ermittelt).

    Filter (alle optional):
      - gewerke_filter: Liste der Gewerk-Keys (putz/rohbau/estrich/maler).
        Leer/None = alle.
      - plan_ids: nur Räume aus diesen Plänen einbeziehen. Leer/None = alle.
      - baudaten_override: User-Werte für aussenwand_cm/decke_cm/
        geschosshoehe_m etc., überschreiben Vision-Werte 1:1.
    """
    projekt_id: str | None = None
    plan_id: str | None = None
    gewerke_filter: list[str] | None = None
    plan_ids: list[str] | None = None
    baudaten_override: dict | None = None
    # Override für die Materialliste-Faustformeln (Bodenplatten-Aufschlag,
    # HLZ-Verteilung, Frostschürze-Tiefe, etc.). Schlüssel siehe
    # materialliste.DEFAULTS.
    materialliste_override: dict | None = None
    # intern: firmenspezifische Kalibrierung NICHT anwenden (für den Ist-Default-
    # Vergleich beim Soll-Listen-Upload — sonst würde gegen schon korrigierte
    # Werte kalibriert).
    ohne_kalibrierung: bool = False
    # Export-Format: "rohbau" = nur die saubere Bestell-Materialliste (Bauteil/
    # Material/Menge/Einheit), sonst der vollständige Dump (Räume/ÖNORM/Detail).
    export_format: str | None = None


def _bbox_from_sides(seiten):
    """Bounding-Box (Breite/Tiefe/Umfang/Fläche) aus Fassaden-Maßen.

    Segmente DERSELBEN Fassade (N, N_b, N_c …) werden SUMMIERT (nicht max!) —
    sonst wird eine in Segmente zerlegte L-/U-Form-Fassade (S=7,2 + S_b=5,2 =
    12,4) auf das längste Einzelsegment (7,2) unterschätzt. Das war die
    Hauptursache der Umfang-Schwankung. Modul-Level → unit-testbar.
    """
    if not seiten:
        return None
    facade = {}  # "N"/"S"/"W"/"E" → Summe der Fassaden-Segmente
    for k, v in seiten.items():
        if not v or v <= 0:
            continue
        base = str(k).strip().upper()[:1]  # N/S/W/E/O
        if base == "O":
            base = "E"
        if base in ("N", "S", "W", "E"):
            facade[base] = facade.get(base, 0.0) + float(v)
    horiz = [facade[d] for d in ("N", "S") if d in facade]
    vert = [facade[d] for d in ("W", "E") if d in facade]
    breite = max(horiz) if horiz else (max(vert) if vert else None)
    tiefe = max(vert) if vert else (max(horiz) if horiz else None)
    if not breite or not tiefe:
        return None
    if not (4 <= breite <= 60 and 4 <= tiefe <= 60):  # EFH-Seiten-Plausi
        return None
    return {
        "breite_m": round(breite, 2), "tiefe_m": round(tiefe, 2),
        "umfang_m": round(2 * (breite + tiefe), 2),
        "flaeche_m2": round(breite * tiefe, 2),
    }


@app.post("/api/projekt-massen")
async def projekt_massen(body: ProjektMassenRequest):
    """Projekt-weite Massenermittlung: merged Räume aus ALLEN Plänen
    eines Projekts und ruft berechne_gewerke neu auf.

    Architekten teilen F/U/H typisch auf mehrere Pläne auf:
      • Einreichplan:  F, U, Bodenbelag (keine H)
      • Polierplan:   H (oft kein F/U)
    Pro-Plan-Berechnung liefert daher 0 m² Wandfläche, weil pro Plan ein
    Wert fehlt. Dieser Endpoint führt zusammen, was zusammengehört.
    """
    if not sb:
        raise HTTPException(500, "Supabase nicht konfiguriert")
    if not _MASSEN_OK:
        raise HTTPException(500, "massen_logic nicht verfügbar")

    # 1) projekt_id auflösen
    projekt_id = body.projekt_id
    if not projekt_id and body.plan_id:
        pl = sb.table("plaene").select("projekt_id").eq("id", body.plan_id).single().execute()
        if not pl.data:
            raise HTTPException(404, "Plan nicht gefunden")
        projekt_id = pl.data["projekt_id"]
    if not projekt_id:
        raise HTTPException(400, "projekt_id oder plan_id erforderlich")

    # 1b) firma_id des Projekts ermitteln + firmenspezifische Selbst-Kalibrierung
    # laden (Firma > globale Basis > Default). Fehlt etwas → leeres Dict, byte-exakt
    # bleibt unangetastet. Das ist der Moat: die Liste wird firmen-genauer.
    firma_id = None
    try:
        _pr = sb.table("projekte").select("firma_id").eq("id", projekt_id).single().execute()
        firma_id = (_pr.data or {}).get("firma_id")
    except Exception as _exc:
        print(f"[kalibrierung] firma_id-Lookup fehlgeschlagen: {_exc!r}")
    kalibrierung_faktoren = {} if body.ohne_kalibrierung else _lade_kalibrierung(sb, firma_id)

    # 2) Alle Pläne des Projekts laden (mit agent_log für Baudaten + Fenster)
    plaene_res = sb.table("plaene").select(
        "id, dateiname, agent_log, storage_path"
    ).eq("projekt_id", projekt_id).execute()
    plaene_all = plaene_res.data or []
    if not plaene_all:
        return {"status": "empty", "raeume_count": 0, "gewerke": {}}

    # Plan-Filter: User kann z.B. einen Bestandsplan ausschließen
    if body.plan_ids:
        plan_filter = set(body.plan_ids)
        plaene = [p for p in plaene_all if p["id"] in plan_filter]
    else:
        plaene = plaene_all
    if not plaene:
        return {"status": "empty", "raeume_count": 0, "gewerke": {},
                "hinweis": "Alle Pläne durch plan_ids-Filter ausgeschlossen"}

    plan_ids = [p["id"] for p in plaene]

    # 3) Räume und Fenster aus elemente sammeln
    raeume_res = sb.table("elemente").select(
        "plan_id, bezeichnung, daten, typ"
    ).in_("plan_id", plan_ids).eq("typ", "raum").execute()
    raum_rows = raeume_res.data or []

    fenster_res = sb.table("elemente").select(
        "plan_id, bezeichnung, daten, typ"
    ).in_("plan_id", plan_ids).eq("typ", "fenster").execute()
    fenster_rows = fenster_res.data or []

    # Türen werden separat geladen — die Pipeline speichert Tür-Erkennungen
    # aus dem STUK/FPH-Cluster getrennt unter typ="tuer".
    tueren_res = sb.table("elemente").select(
        "plan_id, bezeichnung, daten, typ"
    ).in_("plan_id", plan_ids).eq("typ", "tuer").execute()
    tueren_rows = tueren_res.data or []

    # 4) Räume mergen — name-basiert (Einfamilienhaus) bzw. name+wohnung (Mehrwohnungs-Bau).
    def _deumlaut(s):
        # Umlaute/ß vereinheitlichen, damit "Küche" (Einreichplan) und "Kueche"
        # (Polierplan) als DERSELBE Raum mergen statt doppelt gezählt zu werden.
        return ((s or "").lower().replace("ä", "ae").replace("ö", "oe")
                .replace("ü", "ue").replace("ß", "ss"))
    def _nk(s):
        return re.sub(r"[\s\-_/]+", "", _deumlaut(s))

    # EFH-Erkennung: wenn das Projekt nur 1-2 einzigartige "Wohnungen" hat
    # (z.B. "Haus" + "TOP 25" wegen Vision-Halluzination eines TOP-Labels),
    # mergen wir nur über NAME — sonst entstehen Duplikate wie zwei
    # "Abstellraum"-Einträge, einer mit wohnung="Haus", einer mit wohnung="TOP 25".
    wohnungen_im_projekt = set()
    for row in raum_rows:
        d = row.get("daten") or {}
        w = (d.get("wohnung") or "").strip().lower()
        wohnungen_im_projekt.add(w or "_default_")
    is_efh = len(wohnungen_im_projekt) <= 2

    def _tokens(s):
        return [t for t in re.findall(r"[a-z0-9]+", _deumlaut(s)) if t]
    def _trailing_int(s):
        m = re.search(r"(\d+)\s*$", (s or "").strip())
        return m.group(1) if m else None

    def _fuzzy_merge_key(name, wohnung, mergedmap, efh):
        # Findet einen bestehenden Schlüssel, der DENSELBEN Raum bezeichnet,
        # auch wenn die Pläne ihn unterschiedlich benennen ("Wohnraum Küche"
        # im Einreichplan, "Küche" im Polierplan). Sonst landet die Höhe im
        # einen, Fläche/Umfang im anderen Eintrag und der Cousin-Filter
        # verwirft den kürzeren BEVOR die Werte zusammenfinden.
        # Sicher gehalten: Token-Teilmenge MIT gleichem Kopf-Nomen (letztes
        # Wort), gleiche trailing-Nummer (Zimmer 1 ≠ Zimmer 2) und — bei MFH —
        # gleiche Wohnung.
        toks_new = _tokens(name)
        if not toks_new:
            return None
        ti_new = _trailing_int(name)
        nkw = _nk(wohnung)
        for k, ex in mergedmap.items():
            if not efh and len(k) > 1 and k[1] != nkw:
                continue
            ex_name = ex.get("name") or ""
            toks_ex = _tokens(ex_name)
            if not toks_ex:
                continue
            if _trailing_int(ex_name) != ti_new:
                continue
            # gleiches Kopf-Nomen (letztes Wort) — "küche" == "küche"
            if toks_new[-1] != toks_ex[-1]:
                continue
            # eine Token-Menge ist Teilmenge der anderen (Qualifizierer-Präfix)
            sn, se = set(toks_new), set(toks_ex)
            if sn <= se or se <= sn:
                return k
        return None

    merged = {}  # key -> raum-dict
    for row in raum_rows:
        d = row.get("daten") or {}
        name = row.get("bezeichnung") or d.get("name") or ""
        wohnung = d.get("wohnung") or ""
        key = (_nk(name),) if is_efh else (_nk(name), _nk(wohnung))
        if not key[0]:
            continue
        ex = merged.get(key)
        if ex is None:
            fk = _fuzzy_merge_key(name, wohnung, merged, is_efh)
            if fk is not None:
                ex = merged[fk]
                # längeren, spezifischeren Namen behalten
                if len(_tokens(name)) > len(_tokens(ex.get("name") or "")):
                    ex["name"] = name
        if ex is None:
            merged[key] = dict(d)
            merged[key]["name"] = name
            merged[key]["_quellen_plaene"] = [row["plan_id"]]
            continue
        # Lücken füllen — wer einen Wert hat, gewinnt
        for fld in ("flaeche_m2", "umfang_m", "hoehe_m", "bodenbelag", "cx", "cy"):
            if ex.get(fld) in (None, "", 0) and d.get(fld) not in (None, "", 0):
                ex[fld] = d[fld]
                ex.setdefault("_merged_from", []).append(fld)
        if row["plan_id"] not in ex["_quellen_plaene"]:
            ex["_quellen_plaene"].append(row["plan_id"])

    merged_rooms = list(merged.values())

    # Geschoss früh ermitteln (für die Dedup-Heuristik), wird unten ggf. überschrieben
    _early_geschoss = "EG"
    for p in plaene:
        log = p.get("agent_log") or {}
        g = (log.get("geo") or {}).get("geschoss") or log.get("geschoss")
        if g:
            _early_geschoss = g
            break

    # 4b) Aggressivere De-Halluzinations-Dedup gegen Vision-Mehrfachfunde:
    # Wenn ein Raum-Name eine ECHTE Teilmenge eines anderen (längeren) Raumnamens
    # ist, ist es meistens dieselbe Räumlichkeit — Vision hat das Label
    # zweimal gelesen (z.B. "Wohnraum Küche" UND "Küche" aus dem
    # Beschriftungs-Block). Behalte den vollständigeren Eintrag.
    # Ebenso: Räume mit Suffix "Obergeschoss" / "OG" in einem EG-Plan
    # sind oft Halluzinationen aus dem Plan-Titel/Schnitt.
    def _short_name(n):
        return re.sub(r"[\s\-_/]+", " ", (n or "").strip().lower())
    # Für Cousin-Heuristik: das LETZTE Wort (nicht das erste) — bei Komposita
    # wie "Geräte-Abstellraum" ist "abstellraum" das semantisch relevante Wort,
    # nicht "geräte". Sonst rutscht "Abstellraum" (3,70m²) durch den Filter,
    # weil sein first_word "abstellraum" nicht zu "geräte" passt.
    def _last_word(n):
        sn = _short_name(n)
        if not sn:
            return ""
        return sn.split()[-1]
    # Cousin-Gruppen vorab bilden (statt pairwise-Filter): alle Räume mit
    # gleichem 4-char-first-word-Präfix ODER gleichem last_word kommen in
    # die selbe Gruppe. Pro Gruppe wird der BESTE behalten — sonst riskiert
    # pairwise-Logik dass ALLE Cousins als Hallu markiert werden und kein
    # einziger echter Raum übrig bleibt.
    PREFERRED_NORMS = {"wohnraumkuche","wohnraumküche","wohnraum","wohnen",
                       "wohnzimmer","kuche","küche","wohnkuche","wohnküche"}
    def _norm_for_pref(n):
        return re.sub(r"[\s\-_/]+", "", _short_name(n))
    def _cousin_key(name):
        sn = _short_name(name)
        if not sn:
            return None, set()
        # Nummerierte Räume (Zimmer 1/2/3, Top 04) sind EIGENSTÄNDIG — nie
        # untereinander Cousins. Eindeutiger Key inkl. Nummer, damit das
        # last-word nicht auf den Stamm kollabiert (sonst würden Zimmer 1/3
        # fälschlich gruppiert und der echte Raum verworfen).
        m_num = re.match(r"^([a-zäöüß]+)\s*(\d+)$", sn)
        if m_num:
            stamm, nr = m_num.group(1), m_num.group(2)
            return (stamm[:4], f"{stamm}{nr}"), {stamm}
        # "Küche + WZ" → ["küche", "+", "wz"] — Sonderzeichen filtern
        words = [w for w in sn.split() if len(w) >= 2 and re.match(r"^[a-zäöüß]", w)]
        if not words:
            return None, set()
        first = words[0]
        last = words[-1]
        # Set aller "Bedeutungs-Wörter" (≥4 Buchstaben), für unscharfe
        # Cousin-Verbindung. "Küche + WZ" hat {küche}; "Wohnraum Küche"
        # hat {wohnraum, küche} → Schnittmenge {küche} → Cousin.
        bedeutungs_woerter = {w for w in words if len(w) >= 4}
        return (first[:4] if len(first) >= 4 else first,
                last if len(last) >= 4 else ""), bedeutungs_woerter
    def _score(r):
        sn = _short_name(r.get("name"))
        norm = _norm_for_pref(r.get("name"))
        score = 0
        score += len(r.get("_quellen_plaene") or []) * 100  # mehr Quellen
        score += sum(1 for k in ("flaeche_m2","umfang_m","hoehe_m","bodenbelag") if r.get(k)) * 10  # mehr Daten
        if norm in PREFERRED_NORMS:
            score += 50  # Standard-Bauterminologie
        score += len(sn.split()) * 3  # mehr Wörter = präziser Name
        return score

    # Gruppen-Index aufbauen — flexibel: Räume die in ZWEI Achsen verbunden sind
    # (zB. erste 4 Chars passen, last_word passt) gehören zur selben Familie.
    # Dafür Union-Find.
    parent = list(range(len(merged_rooms)))
    def _find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def _union(i, j):
        ri, rj = _find(i), _find(j)
        if ri != rj:
            parent[ri] = rj
    # Generische Adjektive die KEIN Cousin-Trigger sein dürfen — z.B.
    # "überdacht" verbindet sonst Parkplatz + Terrasse fälschlich.
    GENERIC_LAST_WORDS = {"überdacht","ueberdacht","unten","oben","links","rechts",
                          "vorne","hinten","gross","groß","klein","mitte",
                          "links","rechts","sued","nord","ost","west","süd",
                          "süden","norden","osten","westen"}
    def _similar_size(a, b, tol=0.30):
        """F und U müssen innerhalb tol für Cousin-Mergen."""
        for k in ("flaeche_m2", "umfang_m"):
            va, vb = a.get(k), b.get(k)
            if not va or not vb:
                continue
            if abs(va - vb) / max(va, vb) > tol:
                return False
        return True

    keys = [_cousin_key(r.get("name")) for r in merged_rooms]
    for i in range(len(merged_rooms)):
        ki, wi = keys[i]
        if not ki:
            continue
        import difflib
        sni = _short_name(merged_rooms[i].get("name"))
        # stamm+ziffer-Pattern (Zimmer 1/2/3) — diese NICHT als Typo mergen
        zi = re.match(r"^([a-zäöüß]+)\s*(\d+)$", sni)
        for j in range(i + 1, len(merged_rooms)):
            kj, wj = keys[j]
            if not kj:
                continue
            # ZUERST: nie über verschiedene Wohnungen/TOPs mergen (MFH!) —
            # "Wohnküche" in TOP1 und TOP2 sind echte eigene Räume, auch wenn
            # der Name identisch ist. Gilt für ALLE Merge-Pfade (auch Typo).
            wi_w = _nk(merged_rooms[i].get("wohnung") or "")
            wj_w = _nk(merged_rooms[j].get("wohnung") or "")
            if wi_w and wj_w and wi_w != wj_w:
                continue
            snj = _short_name(merged_rooms[j].get("name"))
            # ── TYPO-MERGE (vor Größen-Guard): fast identische Namen sind
            # OCR/Vision-Tippfehler desselben Raums ("Terasse"/"Terrasse").
            # Generalisiert auf beliebige Tippfehler ohne feste Liste.
            zj = re.match(r"^([a-zäöüß]+)\s*(\d+)$", snj)
            both_numbered = zi and zj and zi.group(1) == zj.group(1)
            if not both_numbered and sni and snj:
                ratio = difflib.SequenceMatcher(None, sni, snj).ratio()
                if ratio >= 0.88:
                    _union(i, j)
                    continue
            # Last-word nur als Cousin-Trigger wenn nicht generisch
            i_last = ki[1] if ki[1] not in GENERIC_LAST_WORDS else ""
            j_last = kj[1] if kj[1] not in GENERIC_LAST_WORDS else ""
            same_first = ki[0] and ki[0] == kj[0]
            same_last = i_last and i_last == j_last
            # Bedeutungs-Wörter-Schnittmenge (ohne generische):
            common_words = (wi & wj) - GENERIC_LAST_WORDS
            # (Wohnungs-Guard steht oben in der Schleife — gilt für alle Pfade.)
            # Nur in selbe Gruppe wenn Größen ähnlich (sonst sind es zwei
            # verschiedene reale Räume mit ähnlichem Namen).
            if not _similar_size(merged_rooms[i], merged_rooms[j]):
                continue
            if same_first and same_last:
                _union(i, j)
            elif same_last and i_last:  # Komposita gleicher Endung
                _union(i, j)
            elif same_first and ki[0] and ki[0] not in {"zimm","bad","wc"}:
                # Gleicher Präfix (≥4 Buchstaben) — z.B. "Wohnen Küche" + "Wohnraum"
                _union(i, j)
            elif common_words and any(w in {"küche","kueche","wohnen","wohnraum",
                                              "wohnzimmer","wohnkueche","wohnküche"} for w in common_words):
                # "Küche + WZ" und "Wohnraum Küche" teilen das Wort "küche" →
                # gleicher Hauptraum, nur unterschiedlich beschriftet
                _union(i, j)
    groups = {}
    for i, r in enumerate(merged_rooms):
        groups.setdefault(_find(i), []).append(i)

    # Pro Gruppe: behalte den BESTEN. Alle anderen als "Cousin-Hallu" markieren.
    cousin_losers = set()
    for grp in groups.values():
        if len(grp) <= 1:
            continue
        # Sortiere absteigend nach Score
        grp_sorted = sorted(grp, key=lambda i: _score(merged_rooms[i]), reverse=True)
        winner = grp_sorted[0]
        winner_name = merged_rooms[winner].get("name")
        winner_score = _score(merged_rooms[winner])
        for i in grp_sorted[1:]:
            r2 = merged_rooms[i]
            r2["_hallucination"] = (
                f"Cousin-Gruppe von '{winner_name}' "
                f"(Score {_score(r2)} < {winner_score})")
            cousin_losers.add(i)

    # Text-Layer-Räume sind byte-exakt (Ground Truth). Wenn der Plan einen
    # starken Text-Layer hat (≥5 Text-Räume), sind Vision-ERFUNDENE Räume mit
    # Namen, die NIRGENDS im Text vorkommen, Halluzinationen. Genau so erklärt
    # sich "Zimmer 3/4 / W02": die stehen in KEINEM Plan-Text, Vision hat sie
    # erfunden. Ein Mensch verlässt sich auf die gedruckten Raumlabel.
    def _is_text_room(r):
        return r.get("_source") == "text" or r.get("_text_first")
    text_namen = {_short_name(r.get("name")) for r in merged_rooms if _is_text_room(r)}
    starker_textlayer = len(text_namen) >= 5

    # VORAB-PASS: Vision-Halluzinationen markieren, BEVOR die anderen Filter
    # laufen. Sonst kann ein erfundener Vision-Raum ("Zimmer 7") einen echten
    # Text-Raum ("Zimmer") in der Substring-/Cousin-Dedup verdrängen — eine
    # Halluzination darf NIE einen Ground-Truth-Raum schlagen. Reihenfolge-Bug.
    if starker_textlayer:
        for r in merged_rooms:
            sn = _short_name(r.get("name"))
            if sn and not _is_text_room(r) and sn not in text_namen:
                r["_hallucination"] = "Vision-Raum ohne Text-Layer-Beleg (erfunden)"

    cleaned_rooms = []
    for idx, r in enumerate(merged_rooms):
        sn = _short_name(r.get("name"))
        if not sn:
            continue
        if idx in cousin_losers:
            continue
        # Im Vorab-Pass bereits als Vision-Halluzination markiert → verwerfen.
        if r.get("_hallucination"):
            continue
        my_quellen = len(r.get("_quellen_plaene") or [])
        # Halluzination: OG-Raum in EG-Plan — auch "obergeschoß" (ß) erkennen
        if re.search(r"\bobergeschoss\b|\bobergescho[ßs]+\b|\bog\b|\b[0-9]\.?\s?og\b", sn) \
                and _early_geschoss.upper().startswith("EG"):
            r["_hallucination"] = "OG-Suffix im EG-Plan"
            continue
        # Nummerierte Räume (Zimmer 1/2/3 ...) — wenn Nummer > Max andere
        # gleichnamiger Räume mit MEHR Quellen-Plänen → Halluzination.
        # ABER NUR wenn die Daten UNVOLLSTÄNDIG sind: ein voll bemaßter Raum
        # (F+U+H) ist real, egal welche Nummer — ein Bautechniker verwirft
        # keinen vollständig vermaßten Raum (sonst Untererfassung).
        _vollstaendig = bool(r.get("flaeche_m2") and r.get("umfang_m") and r.get("hoehe_m"))
        m_zif = re.match(r"^([a-zäöü]+)\s*(\d+)$", sn)
        if m_zif and my_quellen < len(plaene) and not _vollstaendig:
            stamm, ziffer = m_zif.group(1), int(m_zif.group(2))
            max_andere = 0
            for other in merged_rooms:
                if other is r:
                    continue
                if other.get("_hallucination"):  # Halluzination darf nicht "gewinnen"
                    continue
                on = _short_name(other.get("name"))
                m2 = re.match(r"^([a-zäöü]+)\s*(\d+)$", on)
                if m2 and m2.group(1) == stamm:
                    other_q = len(other.get("_quellen_plaene") or [])
                    if other_q >= my_quellen + 1:
                        max_andere = max(max_andere, int(m2.group(2)))
            if max_andere > 0 and ziffer > max_andere:
                r["_hallucination"] = (
                    f"Höhere {stamm}-Nummer ({ziffer}) als alle {stamm} in mehr Plänen "
                    f"(max {max_andere})")
                continue
        # Substring-Dedup: kürzerer Name ist Teilstring eines längeren mit
        # höherer Datenqualität (mehr F/U/H-Werte) → kürzeren verwerfen.
        is_subset = False
        my_completeness = sum(1 for k in ("flaeche_m2","umfang_m","hoehe_m") if r.get(k))
        for other in merged_rooms:
            if other is r:
                continue
            if other.get("_hallucination"):  # Halluzination darf nicht "gewinnen"
                continue
            on = _short_name(other.get("name"))
            if not on or on == sn:
                continue
            # echte Teilmenge (mit Wort-Grenze, nicht z.B. "bad" in "badewanne")
            if (" " + sn + " ") in (" " + on + " ") or sn in on.split():
                other_completeness = sum(1 for k in ("flaeche_m2","umfang_m","hoehe_m") if other.get(k))
                if other_completeness >= my_completeness:
                    is_subset = True
                    break
        if is_subset:
            r["_hallucination"] = f"Teilmenge eines längeren Raumnamens"
            continue

        # Annotations-Wörter im Raum-Name = typische Plan-Annotation, kein
        # Raum (z.B. "Terrasse Richtung Süd", "Bad WC vorne").
        ANNO_WORDS = {"richtung", "rtg", "norden", "süden", "osten", "westen",
                      "sued", "nord", "ost", "west", "ne", "nw", "se", "sw"}
        my_words = set(sn.split())
        if my_words & ANNO_WORDS:
            r["_hallucination"] = "Annotations-Wort im Raum-Name (vermutlich Anmerkung)"
            continue

        # Cousin-Halluzination: gleicher 4-char-Präfix im ersten Wort, aber
        # verschiedene Vollnamen — z.B. "Wohnzimmer" vs "Wohnraum Küche",
        # oder "Wohnen Küche" vs "Wohnraum Küche".
        #
        # Drei Wege Hallu zu erkennen:
        #   1. Cousin hat MEHR Plan-Quellen → eigener Raum ist Hallu
        #   2. Cousin hat MEHR Wörter im Namen (zusammengesetzte Namen
        #      sind seltener Vision-Halluzinationen)
        #   3. Cousin hat ähnlichen Umfang (Δ U < 10%) → derselbe Raum,
        #      Vision hat den Namen leicht falsch erkannt — der mit mehr
        #      Daten (F+U+H) bzw. eindeutigem Namen gewinnt.
        # Cousin-Filter läuft jetzt vor der Schleife in Gruppen — siehe oben.
        # Hier nur noch in cleaned_rooms aufnehmen.
        cleaned_rooms.append(r)

    halluzinationen = [r for r in merged_rooms if r.get("_hallucination")]
    merged_rooms = cleaned_rooms

    # 4b1) ISOPERIMETRISCHE PLAUSI PRO RAUM: ein Footprint der Fläche F kann
    # geometrisch keinen Umfang < 4·√F haben (Quadrat-Minimum). Ein kleinerer
    # U ist ein falsch zugeordneter Nachbar-Wert (Stempel-Cross-Talk, z.B. der
    # Flur erbt Bads Umfang) → verwerfen statt die Wandmengen zu verfälschen.
    # Der Wert wird zur Transparenz vermerkt; U bleibt leer (ehrlich „–").
    for r in merged_rooms:
        f, u = r.get("flaeche_m2"), r.get("umfang_m")
        if f and u and u < 4.0 * (float(f) ** 0.5) * 0.98:
            r["_umfang_implausibel"] = round(float(u), 2)
            r["umfang_m"] = None

    # 4b2) GESCHOSS/EINHEIT-TRENNUNG für die Rohbau-Mengen:
    # Die Bodenplatte/Decke/Mauerwerk ist EIN EG-Grundriss. Wenn der Plan
    # zusätzlich Räume einer ANDEREN Einheit/Geschoss enthält (eigene
    # Wohnungs-Bezeichnung wie "W02", andere Raumhöhe), gehören die NICHT in
    # dieselbe Bodenplatte. Ein Mensch erkennt "W02" als separate Einheit.
    # → Für die Bauteil-Mengen nur die DOMINANTE Wohnungs-Gruppe (das EG).
    #   Bei echtem MFH (>2 Wohnungen, nicht is_efh) wird NICHT gefiltert.
    def _wg(r):
        return _nk(r.get("wohnung") or "")
    def _median_h(rs):
        hs = sorted(r["hoehe_m"] for r in rs if r.get("hoehe_m"))
        return hs[len(hs) // 2] if hs else None
    _groups = {}
    for r in merged_rooms:
        _groups.setdefault(_wg(r), []).append(r)
    rohbau_rooms = merged_rooms
    ausgeschlossene_einheiten = []
    if is_efh and len(_groups) > 1:
        def _gscore(rs):
            return len(rs) + sum(len(r.get("_quellen_plaene") or []) for r in rs)
        dom_key = max(_groups, key=lambda k: _gscore(_groups[k]))
        dom = _groups[dom_key]
        dom_h = _median_h(dom)
        # Eine Nebengruppe wird NUR ausgeschlossen, wenn MEHRERE Indizien für
        # "andere Einheit/Geschoss" zusammenkommen — sonst Gefahr, einen echten
        # zweiten EG-Bereich zu verwerfen. Generalisiert über Pläne:
        #   (a) eigener Wohnungs-/Geschoss-Code (W02, TOP 3, OG, 1.OG …)
        #   (b) NUR aus einem Plan (nicht cross-validiert)
        #   (c) abweichende Raumhöhe (> 0.15m vom EG-Median = anderes Geschoss)
        # Mindestens 2 davon müssen zutreffen.
        rohbau_rooms = list(dom)
        for k, rs in _groups.items():
            if k == dom_key:
                continue
            hat_code = bool(re.search(r"(w\d|top\d|og|kg|ug|dg|\dog)", k))
            nur_ein_plan = all(len(r.get("_quellen_plaene") or []) <= 1 for r in rs)
            gh = _median_h(rs)
            hoehe_abweichend = bool(dom_h and gh and abs(gh - dom_h) > 0.15)
            indizien = sum([hat_code, nur_ein_plan, hoehe_abweichend])
            if indizien >= 2:
                ausgeschlossene_einheiten.append({
                    "einheit": k or "(ohne)", "raeume": [r.get("name") for r in rs],
                    "indizien": {"code": hat_code, "ein_plan": nur_ein_plan, "hoehe": hoehe_abweichend},
                })
            else:
                rohbau_rooms.extend(rs)   # gehört doch zum EG → behalten

    # 4c) Höhen-Inferenz mit QUELLEN-HIERARCHIE (Höhe geht linear in Σ(U×H)
    # aller Wand-/Putz-/Maler-Mengen → teuerste Größe, darf nicht geraten
    # werden). Prinzip:
    #   1) echte Raum-H aus dem Plan (bleibt)
    #   2) fehlt sie bei einem INNENRAUM → Geschoss-Höhe (Median der erkannten
    #      Innenraum-Höhen) übernehmen, als _h_inferred markieren
    #   3) ÜBERDACHTE AUSSENFLÄCHEN (Terrasse/Parkplatz/Loggia/Balkon/Carport)
    #      bekommen GRUNDSÄTZLICH keine beheizte Raumhöhe — _h_not_applicable.
    #      Ihre Höhe ist für keine Mengenberechnung definiert (sie fließen nur
    #      über die Fläche in Decke/Bodenaufbau). Vorher bekamen sie blind den
    #      Median → latente Fehlerquelle.
    try:
        from massen_logic import kategorie_of as _kat_h
    except Exception:
        _kat_h = lambda n: None
    def _ist_aussenflaeche(r):
        return _kat_h(r.get("name") or "") == "Loggia"

    inner_h = sorted(float(r["hoehe_m"]) for r in merged_rooms
                     if r.get("hoehe_m") and not _ist_aussenflaeche(r))
    ergaenzte_h = 0
    aussen_ohne_h = 0
    if inner_h:
        h_median = inner_h[len(inner_h) // 2]   # Geschoss-Höhe (robust, kein Outlier)
        h_max = inner_h[-1]
        for r in merged_rooms:
            if r.get("hoehe_m"):
                continue
            if _ist_aussenflaeche(r):
                r["_h_not_applicable"] = True
                aussen_ohne_h += 1
                continue
            r["hoehe_m"] = h_median
            r["_h_inferred"] = True
            ergaenzte_h += 1
    else:
        h_median = None
        h_max = None
        for r in merged_rooms:
            if not r.get("hoehe_m") and _ist_aussenflaeche(r):
                r["_h_not_applicable"] = True
                aussen_ohne_h += 1

    # 5) Öffnungen sammeln — Fenster und Türen, beide mit Dimensions-Normalisierung.
    def _to_meter(roh):
        """Magnitude-Heuristik statt fixer Einheit — robust gegen Architekt-
        Konventionen: Vision liefert das *_mm-Feld oft in cm (ArchiCAD-Stempel
        '120/147' = 120cm×147cm) oder mm (1200/1470). Statt blind /1000:
          < 4     → schon Meter (1.30)
          4-350   → Zentimeter (130cm → 1.30m); Fenster/Türen sind 0.5-3.5m breit
          >= 350  → Millimeter (1300mm → 1.30m)
        Damit funktioniert es egal ob der Plan cm oder mm beschriftet."""
        try:
            v = float(roh)
        except (TypeError, ValueError):
            return None
        if v <= 0:
            return None
        if v < 4:
            return round(v, 3)            # bereits Meter
        if v < 350:
            return round(v / 100.0, 3)    # Zentimeter
        return round(v / 1000.0, 3)       # Millimeter

    def _norm_dim(d):
        """Vereinheitlicht Breite/Höhe auf Meter aus beliebigem Quellfeld."""
        if not d.get("breite_m"):
            for src in ("breite_cm", "rb_breite_mm", "al_breite_mm", "breite_mm"):
                if d.get(src):
                    # breite_cm bleibt cm-semantisch, der Rest via Magnitude
                    m = (d[src] / 100.0) if src == "breite_cm" else _to_meter(d[src])
                    if m:
                        d["breite_m"] = m
                        break
        if not d.get("hoehe_m"):
            for src in ("hoehe_cm", "rb_hoehe_mm", "al_hoehe_mm", "hoehe_mm"):
                if d.get(src):
                    m = (d[src] / 100.0) if src == "hoehe_cm" else _to_meter(d[src])
                    if m:
                        d["hoehe_m"] = m
                        break
        # Sanity-Guard: echte OCR/Vision-Artefakte verwerfen, aber legale
        # Lüftungs-/Oberlicht-Fenster behalten. Höhen-Schwelle 0.25 (Kompromiss:
        # schmale Oberlichter ab 25cm bleiben, kleinere Artefakte raus).
        if d.get("breite_m") and d["breite_m"] < 0.30:
            d["breite_m"] = None
        if d.get("hoehe_m") and d["hoehe_m"] < 0.25:
            d["hoehe_m"] = None
        return d

    def _collect_oeffnungen(rows):
        # Dieselbe Öffnung wird mehrfach erkannt: als grober Vision-Fund
        # (FE_30, oft maßlos) UND als präziser STUK/FPH-Text-Fund (F-130x128),
        # und über zwei Pläne (Einreich+Polier) DESSELBEN Gebäudes doppelt.
        # → Toleranz-basiertes Clustering pro Raum (8cm auf Breite UND Höhe)
        # statt fragiler 10cm-Hartbuckets: 1.24m und 1.26m sprangen über die
        # Bucketgrenze (12 vs 13) → Doppelzählung. STUK gewinnt vor Vision,
        # fehlende Maße werden aus dem Partner gefüllt (analog Raum-Merge).
        TOL = 0.08  # 8cm: mergt Mess-Rauschen, trennt echte Nachbarn (60↔70cm)
        items = []
        for row in rows:
            d = _norm_dim(dict(row.get("daten") or {}))
            d["bezeichnung"] = row.get("bezeichnung") or d.get("bezeichnung") or ""
            items.append(d)

        def _rn(i):
            return (i.get("raum") or "").strip().lower()
        def _is_stuk(i):
            return "stuk" in (i.get("quelle") or "").lower()
        def _konf(i):
            try:
                return float(i.get("konfidenz") or 0)
            except (TypeError, ValueError):
                return 0.0
        def _bez(i):
            return (i.get("bezeichnung") or "").strip().lower()

        # Räume mit mind. einer bemaßten Öffnung (für Maßlos-Verwerfung)
        raeume_mit_massen = {_rn(i) for i in items if i.get("breite_m") and i.get("hoehe_m")}
        raeume_mit_massen.discard("")
        # STABILITÄT: der STUK/FPH-Text-Layer ist byte-exakt + deterministisch, reine
        # Vision-Funde schwanken jedem Lauf. Räume mit Text-Öffnungen merken — dort
        # werden reine Vision-Funde (kein STUK/FPH) verworfen (siehe Loop).
        def _ist_text(i):
            return bool(i.get("stuk_m") or i.get("fph_m") or _is_stuk(i))
        raeume_mit_text = {_rn(i) for i in items if _ist_text(i)}
        raeume_mit_text.discard("")

        # Reihenfolge: bemaßte zuerst (Cluster-Seed), STUK vor Vision, höhere Konf zuerst
        def _sortkey(i):
            return (0 if (i.get("breite_m") and i.get("hoehe_m")) else 1,
                    0 if _is_stuk(i) else 1,
                    -_konf(i))

        # Raum-Identität über Plan-Varianten: der Einreichplan nennt einen Raum
        # "WC", der Polierplan "WC1" → dieselbe Tür darf nicht doppelt zählen.
        # Gleiche Logik wie der Raum-Merge (Stamm ohne trailing-Zahl, Kopf-Nomen,
        # Token-Teilmenge), aber "Zimmer 1" ≠ "Zimmer 2" bleibt getrennt.
        def _stem(name):
            return re.sub(r"\d+\s*$", "", (name or "").strip().lower()).strip()
        def _raum_match(a, b):
            a, b = (a or "").strip().lower(), (b or "").strip().lower()
            if a == b:
                return True
            if not a or not b:
                return False
            ia, ib = _trailing_int(a), _trailing_int(b)
            if ia is not None and ib is not None and ia != ib:
                return False  # Zimmer 1 ≠ Zimmer 2
            sa, sb = _stem(a), _stem(b)
            if sa and sa == sb:
                return True  # "wc1"→"wc" == "wc"
            ta, tb = _tokens(sa), _tokens(sb)
            if not ta or not tb:
                return False
            if ta[-1] == tb[-1]:
                return True  # gleiches Kopf-Nomen
            return set(ta) <= set(tb) or set(tb) <= set(ta)

        clusters = []  # {"raum","breite_m","hoehe_m","rep"}
        for i in sorted(items, key=_sortkey):
            raum = _rn(i)
            b, h = i.get("breite_m"), i.get("hoehe_m")
            has_dims = bool(b and h)
            # maßloser Fund in einem Raum mit bereits bemaßten Öffnungen → redundant
            if not has_dims and any(_raum_match(raum, rm) for rm in raeume_mit_massen):
                continue
            # reiner Vision-Fund (kein STUK/FPH) in einem Raum, der Text-Öffnungen
            # hat → fast immer ein instabiler Doppel-/Fehlfund → verwerfen, damit das
            # Ergebnis lauf-zu-lauf STABIL bleibt (Text ist byte-exakt, Vision schwankt).
            if not _ist_text(i) and any(_raum_match(raum, rm) for rm in raeume_mit_text):
                continue
            match = None
            for c in clusters:
                if not _raum_match(raum, c["raum"]):
                    continue
                if has_dims and c["breite_m"] and c["hoehe_m"]:
                    # Toleranz: präzise×präzise ENG (8cm, trennt echte Nachbarn);
                    # präzise×Vision-unscharf WEIT (20cm), denn dieselbe Öffnung wird
                    # oft als grober Vision-Fund UND exakter STUK/FPH-Text gelesen —
                    # bei 10-15cm Differenz sind das KEINE zwei Fenster, sondern eins.
                    mixed = _is_stuk(i) != _is_stuk(c["rep"])
                    tol = 0.20 if mixed else TOL
                    if abs(b - c["breite_m"]) <= tol and abs(h - c["hoehe_m"]) <= tol:
                        match = c
                        break
                elif not has_dims and not (c["breite_m"] and c["hoehe_m"]):
                    # zwei maßlose im selben Raum mit gleicher Bezeichnung → dieselbe
                    if _bez(i) and _bez(i) == _bez(c["rep"]):
                        match = c
                        break
            if match is not None:
                rep = match["rep"]
                for fld in ("breite_m", "hoehe_m", "fph_m", "stuk_m", "wand_typ", "raum"):
                    if not rep.get(fld) and i.get(fld):
                        rep[fld] = i[fld]
                if has_dims and not (match["breite_m"] and match["hoehe_m"]):
                    match["breite_m"], match["hoehe_m"] = b, h
                continue
            clusters.append({"raum": raum, "breite_m": b, "hoehe_m": h, "rep": i})
        return [c["rep"] for c in clusters]

    alle_fenster = _collect_oeffnungen(fenster_rows)
    alle_tueren = _collect_oeffnungen(tueren_rows)

    # ── ÖFFNUNGS-SYMBOL-CAP: Vision-Symbol-Zählung als OBERGRENZE ──────────
    # Die Text/STUK-Funde sind die primäre Mengenquelle (byte-exakt). Die
    # Symbol-Zählung (Schwenkbögen/Wandöffnungen) ist die unabhängige Stückzahl.
    # Findet der Text MEHR als Symbole da sind (z.B. WC/WC1-Doppelzählung) →
    # auf die Symbol-Zahl KAPPEN, die UNSICHERSTEN zuerst entfernen. NIE
    # auffüllen, nie eine Öffnung erfinden. Konservativ: nur ab Konfidenz 0.6.
    oeff_cap = []  # doppelcheck-Einträge für Öffnungen
    def _symbol_max(key):
        vals = []
        for p in plaene:
            sym = (p.get("agent_log") or {}).get("oeffnungs_symbole") or {}
            if sym.get("kein_grundriss"):
                continue
            v = sym.get(key)
            k = sym.get("konfidenz")
            if v is not None and (k is None or float(k) >= 0.6):
                try:
                    vals.append(int(v))
                except (TypeError, ValueError):
                    pass
        return max(vals) if vals else None  # ein Plan = ganzes Geschoss → max, nicht Summe
    def _cap_liste(liste, symbol_n, label, key):
        if symbol_n is None or symbol_n <= 0 or len(liste) <= symbol_n:
            oeff_cap.append({"groesse": label, "key": key, "wert": len(liste),
                             "symbol": symbol_n,
                             "status": "bestätigt" if (symbol_n == len(liste)) else "info"})
            return liste
        # unsicherste zuerst entfernen: maßlos vor bemaßt, Vision vor STUK, niedrige Konf
        def _certain(o):
            has_dims = bool(o.get("breite_m") and o.get("hoehe_m"))
            is_stuk = "stuk" in (o.get("quelle") or "").lower()
            try:
                kf = float(o.get("konfidenz") or 0)
            except (TypeError, ValueError):
                kf = 0.0
            return (1 if has_dims else 0, 1 if is_stuk else 0, kf)
        gekappt = sorted(liste, key=_certain, reverse=True)[:symbol_n]
        oeff_cap.append({"groesse": label, "key": key, "wert": len(gekappt),
                         "symbol": symbol_n, "vorher": len(liste), "status": "gekappt"})
        return gekappt
    _sym_t = _symbol_max("tueren_gesamt")
    _sym_f = _symbol_max("fenster_gesamt")
    alle_tueren = _cap_liste(alle_tueren, _sym_t, "Türen", "tueren")
    alle_fenster = _cap_liste(alle_fenster, _sym_f, "Fenster", "fenster")

    # ── VEKTOR-POLYGON-BUILD (rechtwinklige Geometrie) ──────────────────
    # Für rechteckige + L-förmige Gebäude (≈99% aller EFH) gilt exakt:
    #   Umfang = 2 × (Gebäudebreite + Gebäudetiefe)
    #   (Vor-/Rücksprünge ändern den Umfang einer rechtwinkligen L-Form NICHT)
    # Breite = längste N/S-Fassade, Tiefe = längste W/E-Fassade — genau das
    # liest PASS-4 als äußerste Kettenbemaßung pro Seite. Fehlt eine Seite,
    # rekonstruiert die rechtwinklige Symmetrie sie (N≈S, W≈E).
    # 6) Baudaten aus allen Plänen sammeln — höchste Vision-Konfidenz gewinnt
    best_baudaten = {}
    best_konf = -1.0
    geschoss = "EG"
    best_legende = None  # Legende mit höchster Konfidenz (byte-exakt > Vision)
    best_schnitt = None   # Schnitt-/Ansichts-Lesung (Säulen, Geschoss-H, Dach)
    best_opus = None      # Opus-Bauingenieur-Urteil (geschlossene Garage, Slab, Höhe)
    opus_versuche = 0     # wie oft der Opus-Pass lief (über alle Pläne)
    opus_fehler = 0       # davon mit Crash/Timeout (ehrliches Fehler-Signal)
    best_schnitt_plan = None  # Plan-Datensatz mit dem besten Schnitt (für Projekt-Opus)
    best_content_plan = None  # Plan mit den meisten Räumen (Haupt-Grundriss-Blatt)
    best_content_n = -1
    # PASS-4-Daten + Außenkontur-Vision aus allen Plänen sammeln
    # (für gemessene Geometrie statt sqrt-Schätzung)
    aussenmasse_kandidaten = []  # Liste von {seiten, umfang, flaeche, breite, tiefe, quelle}
    aussenpolygon_kandidaten = []  # Liste von {umfang_m, flaeche_m2, quelle}
    fundament_kandidaten = []  # Linie B: Bodenplatten-Außenkante {umfang_m, flaeche_m2}
    for p in plaene:
        log = p.get("agent_log") or {}
        gw = log.get("gewerke") or {}
        bd = gw.get("baudaten") or {}
        if bd:
            k = float(bd.get("konfidenz") or 0.0)
            if k > best_konf:
                best_konf = k
                best_baudaten = bd
        # Haupt-Grundriss-Blatt = das mit den meisten Räumen (Fallback für Opus,
        # falls der separate Schnitt-Pass nicht anschlägt — Opus liest den Schnitt
        # ohnehin selbst aus dem Bild; er darf nicht an best_schnitt_plan hängen).
        _nr = len((log.get("geo") or {}).get("raeume") or [])
        if p.get("storage_path") and _nr > best_content_n:
            best_content_n = _nr
            best_content_plan = p
        # Bauteil-Legende (byte-exakt) — beste über alle Pläne
        leg = log.get("legende") or {}
        if leg.get("wand_typen") and (best_legende is None or
                (leg.get("konfidenz") or 0) > (best_legende.get("konfidenz") or 0)):
            best_legende = leg
        # Schnitt-/Ansichts-Lesung — beste über alle Pläne (Einreichplan trägt sie)
        sv = log.get("schnitt_vision") or {}
        if sv and not sv.get("kein_schnitt") and (best_schnitt is None or
                (sv.get("konfidenz") or 0) > (best_schnitt.get("konfidenz") or 0)):
            best_schnitt = sv
            best_schnitt_plan = p   # dieses Blatt trägt den besten Schnitt → Projekt-Opus
        # Opus-Bauingenieur-Urteil — bestes Blatt (klarste Schnitte) gewinnt.
        # Global unsicheres Urteil (gesamtkonfidenz < 0.45) → ganz verwerfen
        # ("nichts raten"); die Feld-Gates ≥0.6 sind die zweite Sicherung.
        ov = log.get("opus_bauingenieur")
        if ov:                       # nicht-leer → der Pass lief tatsächlich
            if ov.get("_fehler"):    # Crash/Timeout → zählt als Versuch UND Fehler
                opus_versuche += 1; opus_fehler += 1
                ov = None
            elif not ov.get("_skipped"):   # echtes Urteil (kein „kein Schnitt"-Skip)
                opus_versuche += 1
            else:
                ov = None            # bewusst übersprungen → kein Urteil, kein Fehler
        if ov and float(ov.get("gesamtkonfidenz") or 0) < 0.45:
            ov = dict(ov, unsicherheit_flag=True)
        if ov and (best_opus is None or
                (ov.get("gesamtkonfidenz") or 0) > (best_opus.get("gesamtkonfidenz") or 0)):
            best_opus = ov
        # Geschoss aus dem ersten Plan, der eines hat
        if not geschoss or geschoss == "EG":
            g = (log.get("geo") or {}).get("geschoss") or log.get("geschoss")
            if g:
                geschoss = g
        # MASSKETTEN-TEXT-LAYER-BBox — byte-exakte Hülle, höchste Priorität
        # (validiert: aus Kettenbemaßung gelesen + an Grundfläche verankert).
        mk = log.get("massketten_bbox")
        if mk and mk.get("umfang_m"):
            aussenmasse_kandidaten.append({
                "umfang_m": float(mk["umfang_m"]),
                "flaeche_m2": float(mk.get("flaeche_m2") or 0) or None,
                "breite_m": mk.get("breite_m"), "tiefe_m": mk.get("tiefe_m"),
                "plan": p.get("dateiname"), "quelle": "textlayer-kette",
                "validiert": True,
            })
        # PASS 4 — Bemaßungs-Vision: wandlaengen_m pro Seite
        wbv = log.get("wand_bemassung_vision") or {}
        for top_name, top_data in wbv.items():
            wl = (top_data or {}).get("wandlaengen_m") or {}
            seiten = {k: v for k, v in wl.items() if v and v > 0}
            valid = (top_data or {}).get("validiert") or {}
            bbox = _bbox_from_sides(seiten)
            if bbox:
                # Eine BBox aus per Gesamtmaß VALIDIERTEN Ketten ist byte-exakt —
                # die beiden maßgeblichen Seiten (Breite/Tiefe) müssen validiert sein.
                bt_validiert = bool(valid) and sum(1 for s in valid.values() if s) >= 2
                aussenmasse_kandidaten.append({
                    "seiten_m": seiten,
                    "umfang_m": bbox["umfang_m"],
                    "flaeche_m2": bbox["flaeche_m2"],
                    "breite_m": bbox["breite_m"], "tiefe_m": bbox["tiefe_m"],
                    "plan": p.get("dateiname"), "top": top_name,
                    "quelle": "pass4-bbox-validiert" if bt_validiert else "pass4-bbox",
                    "validiert": bt_validiert,
                })
        # Außenkontur-Vision (Polygon + Außenmaße + Fläche)
        ak = log.get("aussenkontur_vision") or {}
        # GESAMTMASS-Kandidat: 2×(Gesamt-Breite + Gesamt-Tiefe) ist bei recht-
        # winkligen Bauten der exakte Umfang — die verlässlichste Vision-Lesung,
        # weil es die zwei größten, klar beschrifteten Außenmaße sind.
        try:
            gb = float(ak.get("gesamt_breite_m")) if ak.get("gesamt_breite_m") else None
            gt = float(ak.get("gesamt_tiefe_m")) if ak.get("gesamt_tiefe_m") else None
        except (TypeError, ValueError):
            gb = gt = None
        if gb and gt and 4 <= gb <= 60 and 4 <= gt <= 60:
            aussenmasse_kandidaten.append({
                "umfang_m": round(2 * (gb + gt), 2),
                "flaeche_m2": round(gb * gt, 2),
                "breite_m": round(gb, 2), "tiefe_m": round(gt, 2),
                "plan": p.get("dateiname"), "quelle": "vision-gesamtmaß",
                "gesamtmass": True,
            })
        if ak.get("umfang_m") and ak.get("flaeche_m2"):
            aussenpolygon_kandidaten.append({
                "umfang_m": float(ak["umfang_m"]),
                "flaeche_m2": float(ak["flaeche_m2"]),
                "seiten_m": ak.get("seiten_m") or {},
                "plan": p.get("dateiname"),
                "quelle": "vision-aussenkontur",
            })
            # Linie B: Fundamentplatten-Außenkante (für Frostschürze/Randabschluss)
            # Auch die fundament_seiten_m mitnehmen → falls kein Umfang geliefert,
            # kann er aus den Fassaden-Maßen rekonstruiert werden (Schritt 4).
            if ak.get("fundament_umfang_m") or ak.get("fundament_seiten_m"):
                fundament_kandidaten.append({
                    "umfang_m": float(ak["fundament_umfang_m"]) if ak.get("fundament_umfang_m") else None,
                    "seiten_m": ak.get("fundament_seiten_m") or {},
                    "flaeche_m2": float(ak.get("fundament_flaeche_m2") or 0) or None,
                    "einschluss": ak.get("fundament_einschluss") or [],
                    "plan": p.get("dateiname"),
                })
            # Auch aus dem Vision-Polygon eine Bounding-Box rechnen (Cross-Check)
            akb = _bbox_from_sides(ak.get("seiten_m") or {})
            if akb:
                aussenmasse_kandidaten.append({
                    "seiten_m": ak.get("seiten_m"), "umfang_m": akb["umfang_m"],
                    "flaeche_m2": akb["flaeche_m2"], "breite_m": akb["breite_m"],
                    "tiefe_m": akb["tiefe_m"], "plan": p.get("dateiname"),
                    "quelle": "vision-bbox",
                })

    # ── OPUS-BAUINGENIEUR PRO PROJEKT (1× nach dem Merge) ──────────────────
    # Statt N× pro Plan: genau EIN ganzheitliches Urteil auf dem informativsten
    # Blatt (höchste Schnitt-Konfidenz), gegroundet an den GEMERGTEN byte-exakten
    # Fakten aller Pläne. Spart bei Multi-Plan-Projekten N−1 teure Opus-Calls.
    # Fallback-sicher: PDF-/API-Fehler → best_opus bleibt None, Materialliste
    # unberührt. Übersprungen, wenn schon ein Pro-Plan-Urteil existiert
    # (OPUS_PER_PLAN=1) oder kein Blatt einen Schnitt trägt.
    opus_projekt_plan = None
    _opus_review_pdf = None       # für die Schlussprüfung (#3) wiederverwenden
    _opus_review_api_key = None
    _opus_review_fakten = None
    # Bestes Blatt für Opus: das mit dem erkannten Schnitt, sonst das Haupt-Grundriss-
    # Blatt (meiste Räume). Opus liest den Schnitt selbst aus dem Bild → es darf NICHT
    # daran scheitern, dass der separate Schnitt-Pass leer blieb.
    _opus_plan = best_schnitt_plan or best_content_plan
    if os.environ.get("OPUS_PASS", "1") != "0" and best_opus is None and _opus_plan:
        try:
            _cfg = sb.table("app_config").select("value").eq("key", "ANTHROPIC_API_KEY").execute().data
            _api_key = (_cfg[0]["value"] if _cfg else os.environ.get("ANTHROPIC_API_KEY", "")).strip()
            _sp = _opus_plan.get("storage_path")
            if _api_key and _sp:
                _pdf = sb.storage.from_("plaene").download(_sp)
                _mk = (_opus_plan.get("agent_log") or {}).get("massketten_bbox")
                _fakten = _opus_fakten(merged_rooms, best_legende, _mk,
                                       len(alle_fenster), len(alle_tueren))
                _opus_review_pdf, _opus_review_api_key, _opus_review_fakten = _pdf, _api_key, _fakten
                _urteil = _run_opus_pass(_pdf, _fakten, _api_key)
                opus_versuche += 1
                if _urteil.get("_fehler"):
                    opus_fehler += 1
                else:
                    if float(_urteil.get("gesamtkonfidenz") or 0) < 0.45:
                        _urteil = dict(_urteil, unsicherheit_flag=True)
                    best_opus = _urteil
                    opus_projekt_plan = _opus_plan.get("dateiname")
        except Exception as _exc:
            print(f"[opus-projekt] failed: {_exc!r}")
            opus_versuche += 1
            opus_fehler += 1

    # Konsolidieren: Vision-Polygon ist primäre Quelle (es zeichnet die
    # ganze Kontur nach), PASS-4-Bemaßung dient als Cross-Check (liest
    # nur die Haupt-Außen-Achse, untersieht L-Form-Versätze).
    # PLAUSI-CHECK: Vision-Polygon-Fläche darf nicht >1.6× Σ F_innen sein,
    # sonst hat Vision überdachte Außenbereiche (Terrasse/Parkplatz) mit-
    # erfasst — die gehören nicht in die Bodenplatte.
    from massen_logic import kategorie_of as _kat_check
    # Footprint-Anker = NUR die dominante EG-Einheit (rohbau_rooms), nicht
    # zusätzliche Einheiten/Geschosse (W02 etc.) — sonst zu große Bodenplatte.
    f_innen_check = sum(r.get("flaeche_m2") or 0 for r in rohbau_rooms
                         if _kat_check(r.get("name") or "") == "Innenraum_warm")

    def _median(xs):
        s = sorted(x for x in xs if x and x > 0)
        if not s:
            return None
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0

    def _mad_filter(xs, iso_floor):
        """Verteilungsrobuste Outlier-Entfernung (MAD) statt blindem Median.
        Verwirft Kandidaten, die WEIT unter dem Median liegen UND physikalisch
        zu klein sind (< iso_floor) — fängt Vision-Unterschätzung, ohne echte
        Messungen wegzuwerfen. <3 Werte → unverändert (zu wenig Statistik)."""
        s = sorted(x for x in xs if x and x > 0)
        if len(s) < 3:
            return s, []
        m = s[len(s) // 2]
        mad = sorted(abs(x - m) for x in s)[len(s) // 2] or 1e-9
        keep, drop = [], []
        for x in s:
            if abs(x - m) > 1.5 * mad and x < iso_floor:
                drop.append(round(x, 2))
            else:
                keep.append(x)
        return (keep or s), drop

    # ── Robuste Geometrie-Konsolidierung (generalisiert, keine Plan-Hardcodes) ──
    # Prinzip 1: MEDIAN über alle Plan-Mess-Werte statt eines verrauschten
    #            Einzelwerts → stabil gegen Vision-Schwankung (46/55/62/68m).
    # Prinzip 2: ISOPERIMETRISCHE Grenzen — ein Footprint der Fläche A kann
    #            keinen Umfang < 4·√A haben (Quadrat-Minimum). Reale EFH liegen
    #            bei 1.2–2.2× davon. Korrigiert Vision-Unterschätzung + kappt
    #            Überschätzung — rein geometrisch, planunabhängig.
    poly_flaechen = [c["flaeche_m2"] for c in aussenpolygon_kandidaten if c.get("flaeche_m2")]
    poly_umfaenge = [c["umfang_m"] for c in aussenpolygon_kandidaten if c.get("umfang_m")]
    # BBox-Umfänge (Polygon-Build, 2×(B+T)) — geometrisch exakt für
    # rechtwinklige Gebäude. Das ist die PRIMÄRE Umfang-Quelle.
    bbox_umfaenge = [c["umfang_m"] for c in aussenmasse_kandidaten if c.get("umfang_m")]
    bbox_flaechen = [c["flaeche_m2"] for c in aussenmasse_kandidaten if c.get("flaeche_m2")]

    gemessen = None
    # Fläche: Bodenplatte aus Vision-Polygon ODER bbox ODER Σ F_innen
    bp_flaeche = _median(poly_flaechen) or _median(bbox_flaechen)
    if bp_flaeche is None and f_innen_check > 0:
        bp_flaeche = round(f_innen_check * 1.15, 2)

    if bp_flaeche:
        # ANKER = Σ F_innen (byte-exakt, kein Vision-Rauschen). Die Brutto-
        # Bodenplatte eines EFH ist physikalisch ~1.10–1.30× die Netto-Raum-
        # fläche (nur das Wand-Band kommt dazu — bei 50cm-Außenwand ~1.15).
        # Vision-Polygon schwankt von Lauf zu Lauf → nur INNERHALB dieses
        # engen, physikalisch begründeten Bandes vertrauen, sonst klemmen.
        # Mit bekannter Außenwandstärke (Legende) das Ziel-Band schärfen.
        bp_korrigiert = False
        if f_innen_check > 0:
            aw_cm = float((best_baudaten or {}).get("aussenwand_cm") or 38)
            # Empirischer Netto-Brutto-Faktor Wohnbau ~1.15 (Wände ~13%),
            # leicht höher bei dicker Außenwand.
            ziel = 1.13 + min(0.05, (aw_cm - 30) / 400.0)   # 38cm→1.15, 50cm→1.18
            untergrenze = f_innen_check * 1.04
            obergrenze = f_innen_check * 1.30
            if not (untergrenze <= bp_flaeche <= obergrenze):
                bp_flaeche = round(f_innen_check * ziel, 2)
                bp_korrigiert = True
        bp_flaeche = round(bp_flaeche, 2)

        # Physikalische Grenzen (ein Footprint kann keinen Umfang < 4√A haben)
        iso_min = 4.0 * (bp_flaeche ** 0.5)
        umfang_ceil = iso_min * 2.50   # großzügig (auch lange/zerklüftete Bauten)

        # VALIDIERTE Kettenbemaßung (Σ Segmente = gedrucktes Gesamtmaß) ist
        # byte-exakt → höchste Priorität, KEIN Mitteln mit verrauschten Quellen.
        validated_umfaenge = [c["umfang_m"] for c in aussenmasse_kandidaten
                              if c.get("validiert") and c.get("umfang_m")]
        m_valid = _median(validated_umfaenge)
        # GESAMTMASS-Kandidaten (2×(Gesamt-Breite+Tiefe)) — nur die, deren
        # Rechteck-Fläche zur byte-exakten Grundfläche passt (B×T ≥ 0.92×Footprint;
        # sonst wurde ein zu kleines Maß gelesen). Robust gegen L-Form.
        gesamt_umfaenge = [c["umfang_m"] for c in aussenmasse_kandidaten
                           if c.get("gesamtmass") and c.get("umfang_m")
                           and c.get("flaeche_m2", 0) >= bp_flaeche * 0.92]
        m_gesamt = _median(gesamt_umfaenge)
        # Outlier-Rejection statt blindem Median: Vision-Unterschätzung verwerfen
        bbox_kept, bbox_verworfen = _mad_filter(bbox_umfaenge, iso_min * 1.15)
        mbbox = _median(bbox_kept)
        mpoly = _median(poly_umfaenge)
        umfang_validiert = False
        cross_check_warnung = False

        if m_valid:
            # Byte-exakt aus dem Plan gelesen (Maßkette gegen Gesamtmaß geprüft).
            aussenumfang_m = round(min(max(m_valid, iso_min), umfang_ceil), 2)
            quelle = "kettenbemaßung-validiert"
            konf = 0.97
            umfang_validiert = True
        elif m_gesamt:
            # Gesamt-Breite × Gesamt-Tiefe vom Plan-Rand → 2×(B+T) exakt für
            # rechtwinklige Bauten. Verlässlicher als das verrauschte Polygon.
            aussenumfang_m = round(min(max(m_gesamt, iso_min), umfang_ceil), 2)
            quelle = "vision-gesamtmaß"
            konf = 0.92
            umfang_validiert = True
        elif mbbox:
            # POLYGON-BUILD: 2×(B+T) ist exakt für Rechteck/L-Form → direkt nutzen,
            # nur an physikalischen Grenzen clampen (NICHT künstlich aufblähen).
            aussenumfang_m = round(min(max(mbbox, iso_min), umfang_ceil), 2)
            quelle = "polygon-build-bbox"
            konf = 0.88
            # Vision-Polygon als Cross-Check für Konfidenz
            if mpoly:
                if abs(mpoly - mbbox) / max(mpoly, mbbox) < 0.12:
                    konf = 0.95; quelle = "polygon-build+vision-konsistent"
                else:
                    cross_check_warnung = True  # Quellen uneinig → Konf NICHT heben
        elif mpoly:
            # Nur Vision-Polygon → unterschätzt, isoperimetrischer Floor als Netz
            umfang_floor = iso_min * 1.20
            aussenumfang_m = round(min(max(mpoly, umfang_floor), umfang_ceil), 2)
            quelle = "vision-polygon" + ("+iso-korrigiert" if aussenumfang_m > mpoly + 0.5 else "")
            konf = 0.72
        else:
            # Keine Messung → isoperimetrische Schätzung aus Fläche
            aussenumfang_m = round(iso_min * 1.35, 2)
            quelle = "isoperimetrisch-geschätzt"; konf = 0.55

        if bp_korrigiert:
            quelle += "+bp-plausi"

        # OPUS-BAUINGENIEUR: geschlossene GEMAUERTE überdachte Bereiche (z.B. eine
        # als "Parkplatz" beschriftete, im Schnitt aber gemauerte GARAGE) gehören
        # zur Mauerwerks-Hülle → ihren Wand-Umfang auf Linie A addieren. Nur mit
        # Beleg + Konfidenz ≥0.6; die byte-exakte Grund-Hülle bleibt der Anker.
        # Original-Hülle VOR dem Garage-Zusatz festhalten: alle Plausi-/Verdachts-
        # Prüfungen und die Slab-Basis müssen sich auf die gemessene Grund-Hülle
        # beziehen, NICHT auf den durch Opus erhöhten Wert (sonst übertüncht der
        # Zusatz eine verdächtige Geometrie / verzerrt die Slab-Schwelle).
        aussenumfang_m_basis = aussenumfang_m
        opus_mw_zusatz, opus_garage = 0.0, []
        if _OPUS_KONSUM_OK:
            opus_mw_zusatz, opus_garage = _ok.mauerwerk_zusatz(best_opus, aussenumfang_m_basis)
        if opus_mw_zusatz > 0:
            aussenumfang_m = round(aussenumfang_m + opus_mw_zusatz, 2)
            quelle += "+opus-garage"

        # EHRLICHKEIT: ein UNVALIDIERTER Umfang nahe dem geometrischen Minimum
        # (< iso_min×1.22) ist verdächtig — reale EFH liegen bei 1.25–1.45×√A.
        # So niedrig heißt meist: Vision hat eine L-/U-Form als kompakt gelesen.
        # → Umfang-Konfidenz separat senken (Fläche bleibt byte-exakt hoch), damit
        #   Trust-Ring + Geo-Kasten die Unsicherheit ZEIGEN statt ✓ zu suggerieren.
        # gegen die ORIGINAL-Hülle prüfen — ein Opus-Garage-Zusatz darf eine
        # verdächtig kompakte Grund-Geometrie nicht als „ok" übertünchen.
        umfang_verdacht_niedrig = (not umfang_validiert) and (aussenumfang_m_basis < iso_min * 1.22)
        umfang_konfidenz = round(min(konf, 0.5) if umfang_verdacht_niedrig else konf, 2)

        # ── LINIE B: Fundamentplatten-Außenkante (Frostschürze/Randabschluss) ──
        # Vision-Umfang ODER aus fundament_seiten_m rekonstruiert; muss ≥ Hauptbau
        # sein und ≤ 1,30× Hauptbau. Fehlt Linie B → = aussenumfang_m (wie bisher).
        fund_umfaenge = [c["umfang_m"] for c in fundament_kandidaten if c.get("umfang_m")]
        m_fund = _median(fund_umfaenge)
        # Schritt 4: aus Fassaden-Maßen rekonstruieren, wenn kein Umfang direkt da
        if not (m_fund and m_fund > aussenumfang_m + 0.3):
            rekon = []
            for c in fundament_kandidaten:
                bb = _bbox_from_sides(c.get("seiten_m") or {})
                if bb and bb["umfang_m"] > aussenumfang_m + 0.3:
                    rekon.append(bb["umfang_m"])
            if rekon:
                m_fund = _median(rekon)
        fundament_einschluss = []
        for c in fundament_kandidaten:
            for e in (c.get("einschluss") or []):
                if e and e not in fundament_einschluss:
                    fundament_einschluss.append(e)
        # Überdachte Außenflächen (Terrasse/Parkplatz/Loggia) — byte-exakte Fläche
        ueberdacht_flaeche = sum(r.get("flaeche_m2") or 0 for r in merged_rooms
                                 if _kat_check(r.get("name") or "") == "Loggia")
        n_ueberdacht = sum(1 for r in merged_rooms if _kat_check(r.get("name") or "") == "Loggia")
        linie_b_erkannt = bool(m_fund and m_fund > aussenumfang_m + 0.3)
        vision_b = round(min(m_fund, aussenumfang_m * 1.30), 2) if linie_b_erkannt else None
        # SCHÄTZUNG aus byte-exakten überdachten Flächen: die Platte läuft mglw.
        # unter Terrasse/Carport weiter → Umfang isoperimetrisch hochskaliert
        # (Slab ≈ Grundfläche + überdachte Fläche), geklemmt ≤1,5× Hülle.
        slab_est = None
        if ueberdacht_flaeche > 4 and bp_flaeche:
            faktor = ((bp_flaeche + ueberdacht_flaeche) / bp_flaeche) ** 0.5
            # Basis = ORIGINAL-Hülle (vor Garage-Zusatz): der Garage-/Anbau-Effekt
            # auf die Platten-Kante steckt SCHON im Flächen-Faktor (überdachte Fläche).
            # Sonst doppelt — die Hülle ist um die Garage erhöht UND der Faktor zählt sie.
            slab_est = round(min(aussenumfang_m_basis * faktor, aussenumfang_m_basis * 1.5), 2)
        # OPUS: Bereiche, die laut Bauingenieur auf der DURCHGEHENDEN Platte stehen
        # → ihren Platten-Rand-Zusatz als eigenen (gegroundeten) Slab-Kandidaten.
        # Basis = ORIGINAL-Hülle (vor Garage-Zusatz), damit die interne 60%-Schwelle
        # und die globale Obergrenze nicht gegen einen schon erhöhten Wert rechnen.
        opus_slab = _ok.slab_zusatz(best_opus, aussenumfang_m_basis) if _OPUS_KONSUM_OK else None
        if opus_slab is not None:
            opus_slab = round(min(opus_slab, aussenumfang_m_basis * 1.5), 2)  # globale Plausi-Decke
        # GRÖSSERE plausible Schätzung gewinnt — Vision unterschätzt die Slab-Kante
        # systematisch; Opus + Flächen-Schätzung sind byte-exakt/beleg-verankert.
        cands = [c for c in (vision_b, slab_est, opus_slab) if c]
        if cands:
            fundament_umfang_m = max(cands)
            if opus_slab is not None and fundament_umfang_m == opus_slab:
                fundament_quelle = "opus-bauingenieur (Platte unter Anbau)"
                fundament_unsicher = False   # mit Plan-Beleg → nicht „unsicher"
            elif slab_est is not None and fundament_umfang_m == slab_est:
                fundament_quelle = "geschätzt aus überdachten Flächen (Polierplan prüfen)"
                fundament_unsicher = True
            else:
                fundament_quelle = "vision-fundamentkante"
                fundament_unsicher = False
        else:
            fundament_umfang_m = aussenumfang_m
            fundament_quelle = "= Hauptbau (keine angebaute überdachte Fläche)"
            fundament_unsicher = False

        # Schritt 5: strukturierter Geometrie-Qualitäts-Report (für Dashboard)
        poly_vs_bbox = None
        if mpoly and mbbox:
            poly_vs_bbox = round(abs(mpoly - mbbox) / max(mpoly, mbbox) * 100, 1)
        gemessen = {
            "aussenumfang_m": aussenumfang_m,
            "fundament_umfang_m": fundament_umfang_m,
            "fundament_quelle": fundament_quelle,
            "fundament_einschluss": fundament_einschluss,
            "bodenplatte_flaeche_m2": bp_flaeche,
            "quelle": quelle,
            "konfidenz": konf,                      # Flächen-Konfidenz (byte-exakt-Anker)
            "umfang_konfidenz": umfang_konfidenz,   # separat: sinkt bei verdächtigem Umfang
            "geometrie_qualitaet": {
                "umfang_quelle": quelle,
                "umfang_konfidenz": umfang_konfidenz,
                "umfang_validiert": umfang_validiert,
                "umfang_verdacht_niedrig": umfang_verdacht_niedrig,
                "poly_vs_bbox_diff_pct": poly_vs_bbox,
                "cross_check_warnung": cross_check_warnung,
                "linie_b_erkannt": linie_b_erkannt,
                "fundament_unsicher": fundament_unsicher,
                "ueberdachte_flaechen": n_ueberdacht,
                "kandidaten_n": len(bbox_umfaenge) + len(poly_umfaenge),
                "verworfen": bbox_verworfen,
                "physikalisch_plausibel": bool(iso_min <= aussenumfang_m <= umfang_ceil),
                "flaeche_anker": "Σ Innenraum-Fläche (byte-exakt)" if bp_korrigiert else "Vision-Polygon im Plausi-Band",
                "opus_garage": opus_garage,
                "opus_mauerwerk_zusatz_m": round(opus_mw_zusatz, 2) if opus_mw_zusatz else 0,
                "opus_slab_aktiv": bool(opus_slab is not None and fundament_umfang_m == opus_slab),
            },
            "_debug": {"bbox_umfaenge": bbox_umfaenge, "poly_umfaenge": poly_umfaenge,
                       "fund_umfaenge": fund_umfaenge, "bbox_verworfen": bbox_verworfen,
                       "iso_min": round(iso_min, 1), "ceil": round(umfang_ceil, 1)},
        }

    # 6b) Geschoss-Höhe aus den Raumhöhen ableiten — wichtig wenn Vision
    # keine Wandstärken liefert (Konfidenz <0.7) und Defaults greifen.
    # Der Maximalwert der Raumhöhen ist die richtige Annahme für die
    # Geschoss-Höhe (Lichte zum Putz/Maler-Bereich). Standard 2,70m ist
    # falsch wenn der Plan tatsächlich 2,95m hohe Räume hat.
    if h_max is not None and h_max > 0:
        best_baudaten["geschosshoehe_m"] = h_max
        best_baudaten.setdefault("_quellen", {})
        best_baudaten["_quellen"]["geschosshoehe_m"] = "raumhoehen-max"

    # 6c) LEGENDE schlägt Vision + Defaults (byte-exakt aus dem Plan gelesen,
    # wie ein Bautechniker). Wandstärken, Decke, Bodenplatte, Sauberkeit.
    wand_verteilung = None
    if _LEGENDE_OK and best_legende:
        leg_bd = _baudaten_aus_legende(best_legende)
        best_baudaten.setdefault("_quellen", {})
        for k, v in leg_bd.items():
            if k in ("konfidenz", "_quelle"):
                continue
            best_baudaten[k] = v
            best_baudaten["_quellen"][k] = "legende"
        if best_legende.get("sauberkeitsschicht_cm"):
            best_baudaten["sauberkeitsschicht_cm"] = best_legende["sauberkeitsschicht_cm"]
            best_baudaten["_quellen"]["sauberkeitsschicht_cm"] = "legende"
        if leg_bd:
            best_baudaten["konfidenz"] = max(float(best_baudaten.get("konfidenz") or 0),
                                             leg_bd.get("konfidenz", 0.9))
        wand_verteilung = _wand_verteilung(best_legende)
        # OPUS-VISION-VERTEILUNG (aus den scharfen Grundriss-Kacheln gelesen) schlägt
        # die unzuverlässigen Legende-Code-Counts (Codes stehen selten je Wand). Eine
        # firmen-Kalibrierung (wand_anteil_* im Override) schlägt weiterhin BEIDE.
        if _OPUS_KONSUM_OK:
            _opus_wv = _ok.wand_verteilung_aus_opus(best_opus)
            if _opus_wv and (_opus_wv.get("aussen") or _opus_wv.get("innen")):
                wand_verteilung = _opus_wv
        # Gezählte Wand-Codes ohne Legende-Eintrag → ehrlicher Prüf-Hinweis
        _unbek = (wand_verteilung or {}).get("unbekannte_codes") if wand_verteilung else None
        if _unbek:
            best_baudaten.setdefault("_warnungen", []).append(
                f"{len(_unbek)} Wand-Code(s) im Plan ohne Legende-Aufbau "
                f"({', '.join(_unbek)}) — Stärke am Plan prüfen")
        # Flachdach aus Legende erkannt → Attika automatisch aktivieren
        # (wie ein Polier: Sarnafil/Abdichtung im Dachaufbau ⇒ Attika).
        # User-Override via materialliste_override hat Vorrang.
        if best_legende.get("dach_typ") == "flach":
            ov = body.materialliste_override or {}
            if "attika_aktiv" not in ov:
                body.materialliste_override = dict(ov, attika_aktiv=1)

    # 6c2) SCHNITT-/ANSICHTS-LESUNG: Säulen, Geschoss-Höhe, Dachtyp aus den
    # Schnitten/Ansichten des Einreichplans — füllt Lücken, die der Grundriss
    # nicht hergibt (Polier liest genau dort Stützen/Höhen/Dach ab).
    saeulen_erkannt = None
    if best_schnitt:
        gh_s = best_schnitt.get("geschosshoehe_rohbau_m")
        if gh_s:
            try:
                gh_s = float(gh_s)
            except (TypeError, ValueError):
                gh_s = None
        if gh_s and 2.2 <= gh_s <= 4.5:
            best_baudaten["geschosshoehe_m"] = round(gh_s, 2)
            best_baudaten.setdefault("_quellen", {})["geschosshoehe_m"] = "schnitt"
        # Flachdach aus Schnitt → Attika (falls Legende es nicht schon tat)
        if best_schnitt.get("dachtyp") == "flach":
            ov = body.materialliste_override or {}
            if "attika_aktiv" not in ov:
                body.materialliste_override = dict(ov, attika_aktiv=1)
        # Säulen aus Schnitt/Ansicht erkannt → in die Materialliste übernehmen
        # (User-Override hat Vorrang). Macht den Säulen-Block sichtbar statt 0.
        sa = best_schnitt.get("saeulen_anzahl")
        try:
            sa = int(sa) if sa is not None else 0
        except (TypeError, ValueError):
            sa = 0
        if sa > 0:
            saeulen_erkannt = sa
            ov = body.materialliste_override or {}
            if "anzahl_saeulen" not in ov:
                body.materialliste_override = dict(ov, anzahl_saeulen=sa)

    # 6c2c) OPUS-BAUINGENIEUR: füllt nur, was NOCH NICHT byte-exakt/aus Schnitt
    # kam (Schnitt/Legende schlagen Opus). Höhe (Rohbau), Flachdach→Attika, Säulen.
    if _OPUS_KONSUM_OK and _ok.opus_usable(best_opus):
        o_roh = _ok.hoehe_rohbau(best_opus)
        _q = (best_baudaten.get("_quellen") or {}).get("geschosshoehe_m")
        if o_roh and _q not in ("schnitt", "legende"):
            best_baudaten["geschosshoehe_m"] = o_roh
            best_baudaten.setdefault("_quellen", {})["geschosshoehe_m"] = "opus"
        if _ok.dach_typ(best_opus) == "flach":
            ov = body.materialliste_override or {}
            if "attika_aktiv" not in ov:
                body.materialliste_override = dict(ov, attika_aktiv=1)
        o_sa = _ok.saeulen(best_opus)   # Säulen nur, falls Schnitt keine lieferte
        if o_sa > 0 and not saeulen_erkannt:
            saeulen_erkannt = o_sa
            ov = body.materialliste_override or {}
            if "anzahl_saeulen" not in ov:
                body.materialliste_override = dict(ov, anzahl_saeulen=o_sa)

    # 6c3) DOPPELCHECK: Quellen gegeneinander prüfen. ECHTE Unabhängigkeit zählt:
    # nur QUALITATIV unterschiedliche Methoden (Text-Layer vs Vision) dürfen sich
    # „bestätigen" → 0.97. Zwei Vision-Pässe desselben Bildes (Schnitt + Opus) sind
    # NICHT unabhängig → nur "verstaerkt" (Redundanz, gedeckelt). Quellen-Typ:
    # "text" = byte-exakt aus PDF (Legende-Maße, Raumhöhen); "vision" = Bild-Pass.
    doppelcheck = []
    _leg = best_legende or {}
    _sv = best_schnitt or {}
    # Opus als zusätzliche (Vision-)Lesart — bestätigt/widerspricht, ersetzt nie.
    _ov_h = _ok.hoehe_rohbau(best_opus) if _OPUS_KONSUM_OK else None
    _ov_dach = _ok.dach_typ(best_opus) if _OPUS_KONSUM_OK else None
    _schichten = _sv.get("schichten_cm") or {}
    def _dc_num_inline(label, key, einheit, quellen, tol):
        vv = []
        for item in quellen:
            q, v = item[0], item[1]
            t = item[2] if len(item) == 3 else "vision"
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0:
                vv.append((q, round(fv, 2), t))
        if len(vv) < 2:
            return None
        med = sorted(v for _, v, _ in vv)[len(vv) // 2]
        agree = all(abs(v - med) <= tol for _, v, _ in vv)
        typen = set(t for _, _, t in vv)
        status = ("widerspruch" if not agree else "bestätigt" if len(typen) >= 2 else "verstaerkt")
        return {"groesse": label, "key": key, "einheit": einheit, "wert": med,
                "quellen": [{"quelle": q, "wert": v, "typ": t} for q, v, t in vv],
                "typen_n": len(typen), "unabhaengig": len(typen) >= 2, "status": status}
    def _dc_num(label, key, einheit, quellen, tol):
        d = (_ok.doppelcheck_num(label, key, einheit, quellen, tol)
             if _OPUS_KONSUM_OK else _dc_num_inline(label, key, einheit, quellen, tol))
        if d:
            doppelcheck.append(d)
    _dc_num("Decke", "decke_cm", "cm",
            [("Legende", _leg.get("decke_cm"), "text"), ("Schnitt", _schichten.get("decke"), "vision")], 1.5)
    _dc_num("Bodenplatte", "bodenplatte_cm", "cm",
            [("Legende", _leg.get("bodenplatte_cm"), "text"), ("Schnitt", _schichten.get("bodenplatte"), "vision")], 2.0)
    _dc_num("Estrich", "estrich_cm", "cm",
            [("Legende", _leg.get("estrich_cm"), "text"), ("Schnitt", _schichten.get("estrich"), "vision")], 1.5)
    # Raumhöhen = byte-exakter Text-Layer (echte unabhängige Quelle); Schnitt + Opus
    # sind beide Vision (gleiche Methode) → „bestätigt" nur wenn die Text-Höhe mitzieht.
    _dc_num("Geschoss-Höhe", "geschosshoehe_m", "m",
            [("Schnitt", _sv.get("geschosshoehe_rohbau_m"), "vision"),
             ("Raumhöhen", h_max if (h_max and h_max > 0) else None, "text"),
             ("Opus", _ov_h, "vision")], 0.12)
    _dt_q = [("Legende", _leg.get("dach_typ"), "text"), ("Schnitt", _sv.get("dachtyp"), "vision"),
             ("Opus", _ov_dach, "vision")]
    if _OPUS_KONSUM_OK:
        _dt = _ok.doppelcheck_kat("Dachtyp", "dach_typ", _dt_q)
    else:
        _dd = [(q, str(v).lower(), t) for q, v, t in _dt_q if v]
        _dt_typen = set(t for _, _, t in _dd)
        _dt = ({"groesse": "Dachtyp", "key": "dach_typ", "einheit": "", "wert": _dd[0][1],
                "quellen": [{"quelle": q, "wert": v, "typ": t} for q, v, t in _dd],
                "typen_n": len(_dt_typen), "unabhaengig": len(_dt_typen) >= 2,
                "status": ("bestätigt" if len(set(v for _, v, _ in _dd)) == 1 and len(_dt_typen) >= 2
                           else "verstaerkt" if len(set(v for _, v, _ in _dd)) == 1 else "widerspruch")}
               if len(_dd) >= 2 else None)
    if _dt:
        doppelcheck.append(_dt)

    bestaetigt_keys = {d["key"] for d in doppelcheck if d["status"] == "bestätigt"}
    if bestaetigt_keys:
        best_baudaten.setdefault("_quellen", {})
        for k in bestaetigt_keys:
            if k in best_baudaten:
                cur = best_baudaten["_quellen"].get(k, "")
                if "doppelcheck" not in cur:
                    best_baudaten["_quellen"][k] = (cur + "+doppelcheck").lstrip("+")
        best_baudaten["konfidenz"] = max(float(best_baudaten.get("konfidenz") or 0), 0.97)
        # Zwei unabhängige Lesungen bestätigen die Legende → byte-exakt-Niveau,
        # hebt K_LEG (Decke/Bodenplatte/Bodenaufbau-Konfidenz in der Materialliste).
        if best_legende and bestaetigt_keys & {"decke_cm", "bodenplatte_cm", "estrich_cm"}:
            best_legende["konfidenz"] = max(float(best_legende.get("konfidenz") or 0), 0.97)

    # Öffnungs-Cap-Ergebnisse in den Doppelcheck aufnehmen (gekappt + bestätigt)
    for c in oeff_cap:
        if c.get("status") in ("gekappt", "bestätigt"):
            doppelcheck.append(c)

    # 6.5) Baudaten-Override: User-Werte schlagen Vision-Werte 1:1
    if body.baudaten_override:
        ov = body.baudaten_override
        # Nur erlaubte Schlüssel + plausible Werte übernehmen
        ALLOWED = {"aussenwand_cm","innenwand_tragend_cm","innenwand_nichttragend_cm",
                   "decke_cm","bodenplatte_cm","geschosshoehe_m",
                   "tuer_breite_m","tuer_hoehe_m"}
        applied = {}
        for k, v in (ov.items() if isinstance(ov, dict) else []):
            if k not in ALLOWED:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv <= 0 or fv > 1000:
                continue
            best_baudaten[k] = fv
            applied[k] = fv
        if applied:
            best_baudaten.setdefault("_quellen", {})
            for k in applied:
                best_baudaten["_quellen"][k] = "user"
            best_baudaten["konfidenz"] = max(float(best_baudaten.get("konfidenz") or 0), 0.95)
        # Direkter Außenumfang-Override (Polier hat am Plan gemessen) → schlägt
        # die Vision-Schätzung 1:1; setzt auch die Fundamentkante proportional nach.
        try:
            uo = float(ov.get("aussenumfang_m")) if isinstance(ov, dict) and ov.get("aussenumfang_m") else None
        except (TypeError, ValueError):
            uo = None
        if uo and 10 <= uo <= 400 and gemessen:
            alt_u = gemessen.get("aussenumfang_m") or uo
            verh = (gemessen.get("fundament_umfang_m") or alt_u) / alt_u if alt_u else 1.0
            gemessen["aussenumfang_m"] = round(uo, 2)
            gemessen["fundament_umfang_m"] = round(uo * max(1.0, verh), 2)
            gemessen["konfidenz"] = 0.98
            gemessen["umfang_konfidenz"] = 0.98
            gemessen["quelle"] = "user-gemessen"
            gq = gemessen.setdefault("geometrie_qualitaet", {})
            gq.update({"umfang_quelle": "user-gemessen", "umfang_konfidenz": 0.98,
                       "umfang_validiert": True, "umfang_verdacht_niedrig": False,
                       "cross_check_warnung": False})

    # 7) Gewerk-Berechnung neu mit gemergten Räumen — nur ausgewählte Gewerke
    gewerke_keys = body.gewerke_filter if body.gewerke_filter else None
    try:
        gewerke_result = _berechne_gewerke(
            merged_rooms, alle_fenster, best_baudaten, geschoss, gewerke_keys
        )
    except Exception as e:
        raise HTTPException(500, f"berechne_gewerke: {e}")

    # 7b) Rohbau-Materialliste (Phase 1, Faustformel-basiert).
    # Standalone, weil andere Einheiten als ÖNORM-LV (Paletten/Kanister/Stk).
    # Wird immer berechnet, aber UI kann sie ausblenden.
    materialliste_result = None
    if _MATERIAL_OK:
        try:
            materialliste_result = _build_materialliste(
                rohbau_rooms, alle_fenster, best_baudaten,
                override=body.materialliste_override, geschoss=geschoss,
                tueren=alle_tueren, gemessen=gemessen,
                wand_verteilung=wand_verteilung, legende=best_legende,
                kalibrierung=kalibrierung_faktoren,
            )
        except Exception as e:
            materialliste_result = {"error": f"{type(e).__name__}: {e}"}

    # 7b2) OPUS-SCHLUSSPRÜFUNG (#3): der Polier prüft die fertige Liste gegen den
    # scharfen Plan und flaggt Unstimmigkeiten (meldet, korrigiert nicht). Nutzt das
    # schon geladene PDF + den api_key der Projekt-Opus-Phase. Env OPUS_REVIEW=0 = aus.
    opus_pruefung = None
    if (os.environ.get("OPUS_REVIEW", "1") != "0" and _opus_review_pdf and _opus_review_api_key
            and materialliste_result and not materialliste_result.get("error")):
        try:
            _rev = _run_opus_review(_opus_review_pdf, _opus_review_fakten or {},
                                    materialliste_result, _opus_review_api_key)
            if _rev and not _rev.get("_fehler"):
                opus_pruefung = {
                    "befunde": _rev.get("pruefung") or [],
                    "gesamturteil": _rev.get("gesamturteil"),
                    "konfidenz": _rev.get("konfidenz"),
                }
        except Exception as _exc:
            print(f"[opus-review] consume failed: {_exc!r}")

    # 7c) Konsistenz-Engine: bauphysikalische Plausibilitätschecks
    konsistenz_findings = []
    konsistenz_summary = None
    if _KONSISTENZ_OK:
        try:
            from massen_logic import kategorie_of as _kat
            konsistenz_findings = _konsistenz_checks(
                merged_rooms, alle_fenster, alle_tueren, _kat
            )
            konsistenz_summary = _konsistenz_summary(konsistenz_findings)
        except Exception as _e:
            print(f"[konsistenz] failed: {_e!r}")

    # 8) Übersicht der Merge-Wirkung + Plan-Manifest für die UI
    enrichments = sum(len(r.get("_merged_from", [])) for r in merged_rooms)
    plaene_manifest = [{
        "id": p["id"],
        "dateiname": p.get("dateiname", ""),
        "selected": True,
    } for p in plaene]
    # Auch ausgeschlossene Pläne aufführen, damit das UI Checkboxen rendern kann
    if body.plan_ids:
        excluded_ids = [p["id"] for p in plaene_all if p["id"] not in set(body.plan_ids)]
        for p in plaene_all:
            if p["id"] in excluded_ids:
                plaene_manifest.append({
                    "id": p["id"],
                    "dateiname": p.get("dateiname", ""),
                    "selected": False,
                })
    return {
        "status": "ok",
        "projekt_id": projekt_id,
        "legende_warnungen": (best_baudaten or {}).get("_warnungen") or [],
        "plaene_count": len(plaene),
        "plaene_total": len(plaene_all),
        "plaene": plaene_manifest,
        "raeume_count": len(merged_rooms),
        "fenster_count": len(alle_fenster),
        "tueren_count": len(alle_tueren),
        "merge_enrichments": enrichments,
        "h_inferred_count": ergaenzte_h,
        "h_inferred_value": h_median,
        "aussen_ohne_h_count": aussen_ohne_h,
        "schnitt": best_schnitt,
        "opus_bauingenieur": best_opus,   # ganzheitliches Urteil + Belege (Transparenz)
        "opus_status": ("aus" if opus_versuche == 0
                        else "fehler" if (opus_fehler >= opus_versuche)
                        else "ok"),       # ehrlich: lief der Pass / ist er abgestürzt?
        "opus_quelle_plan": opus_projekt_plan,  # welches Blatt Opus gelesen hat
        "opus_pruefung": opus_pruefung,         # Schlussprüfung: Plausibilitäts-Befunde
        "kalibrierung": {                        # firmenspezifische Selbst-Kalibrierung
            "aktiv": bool(kalibrierung_faktoren),
            "faktoren": kalibrierung_faktoren,
            "anzahl": len(kalibrierung_faktoren),
        },
        "saeulen_erkannt": saeulen_erkannt,
        "doppelcheck": doppelcheck,
        "geschoss": geschoss,
        "raeume": merged_rooms,
        "fenster": alle_fenster,
        "tueren": alle_tueren,
        "halluzinationen": [
            {"name": h.get("name"), "grund": h.get("_hallucination")}
            for h in halluzinationen
        ],
        "konsistenz": {
            "summary": konsistenz_summary,
            "findings": konsistenz_findings,
        } if _KONSISTENZ_OK else None,
        "gemessen": gemessen,
        "legende": best_legende,
        "ausgeschlossene_einheiten": ausgeschlossene_einheiten,
        "materialliste": materialliste_result,
        **gewerke_result,
    }


@app.post("/api/projekt-export")
async def projekt_export(body: ProjektMassenRequest):
    """Projekt-weiter CSV-Export.
    Wiederverwendet die /api/projekt-massen-Berechnung — d.h. Räume aus
    allen Plänen gemergt, Vision-Baudaten, Materialliste — und produziert
    eine CSV mit BOM (Excel-kompatibel), die ALLE Bereiche enthält:
      - Räume (gemergt)
      - Fenster
      - ÖNORM-Gewerke (Putz/Estrich/Maler/Rohbau)
      - Rohbau-Materialliste (HLZ-Paletten, Beton m³ etc.)
    """
    # Wiederverwendung der Berechnungs-Logik
    data = await projekt_massen(body)
    if data.get("status") != "ok":
        raise HTTPException(400, "Keine Daten zum Exportieren")

    def fmt(v, dec=2):
        if v is None or v == "":
            return ""
        try:
            return f"{float(v):.{dec}f}".replace(".", ",")
        except (TypeError, ValueError):
            return str(v)

    def esc(v):
        if v is None:
            return ""
        s = str(v)
        if ";" in s or '"' in s or "\n" in s:
            return '"' + s.replace('"', '""') + '"'
        return s

    # CLEAN "ROHBAU"-FORMAT: nur die Bestell-Materialliste, wie ein Polier sie braucht
    # (Bauteil; Material; Menge; Einheit) — ohne Räume/ÖNORM/Formeln/Konfidenz.
    if (body.export_format or "").lower() == "rohbau":
        rl = ["Bauteil;Material;Menge;Einheit"]
        for bauteil, pps in ((data.get("materialliste") or {}).get("bauteile") or {}).items():
            for p in pps:
                rl.append(";".join([esc(bauteil), esc(p.get("material")),
                                    fmt(p.get("menge")), esc(p.get("einheit"))]))
        csv_r = "﻿" + "\r\n".join(rl) + "\r\n"
        fn_r = f"materialliste-{(data.get('projekt_id') or 'export')[:8]}.csv"
        return Response(content=csv_r, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{fn_r}"'})

    lines = []

    # Plan-Header
    plaene_namen = ", ".join(p["dateiname"] for p in data.get("plaene", []) if p.get("selected"))
    lines.append(f"Projekt-Export;{esc(plaene_namen) or '(alle Pläne)'}")
    lines.append(f"Geschoss;{esc(data.get('geschoss', 'EG'))}")
    lines.append(f"Pläne im Projekt;{data.get('plaene_count', 0)} von {data.get('plaene_total', 0)}")
    lines.append(f"Räume nach Merge;{data.get('raeume_count', 0)}")
    lines.append(f"Lücken durch Merge gefüllt;{data.get('merge_enrichments', 0)}")
    lines.append(f"Fenster erkannt;{data.get('fenster_count', 0)}")
    lines.append(f"Türen erkannt;{data.get('tueren_count', 0)}")
    if data.get("h_inferred_count", 0) > 0:
        lines.append(f"Höhen ergänzt (Median);{data['h_inferred_count']} Räume → {fmt(data.get('h_inferred_value'))} m")
    if data.get("halluzinationen"):
        lines.append("Vision-Halluzinationen gefiltert;" + esc(", ".join(
            h.get("name", "") for h in data["halluzinationen"])))
    konsistenz = data.get("konsistenz") or {}
    findings = konsistenz.get("findings") or []
    if findings:
        sm = konsistenz.get("summary") or {}
        sw = sm.get("schweren") or {}
        lines.append(f"Konsistenz-Status;{sm.get('status','ok')} "
                     f"({sw.get('fehler',0)} Fehler, {sw.get('warnung',0)} Warnungen, "
                     f"{sw.get('info',0)} Hinweise)")
    lines.append("")

    # Konsistenz-Checks (Bauphysik)
    if findings:
        lines.append("KONSISTENZ-CHECKS (Bauphysik-Plausibilität)")
        lines.append("Check;Schwere;Botschaft;Betroffene Elemente")
        for f in findings:
            lines.append(";".join([
                esc(f.get("check")),
                esc(f.get("schwere")),
                esc(f.get("msg")),
                esc(", ".join(f.get("betroffen") or [])),
            ]))
        lines.append("")

    # Räume — H-Quelle explizit: "Plan" wenn aus PDF, "Median X,XX m" wenn ergänzt
    lines.append("RÄUME (alle Pläne gemergt)")
    lines.append("Name;Fläche m²;Umfang m;Höhe m;H-Quelle;Bodenbelag;Quellen-Pläne;merged_fields")
    h_med = data.get("h_inferred_value")
    for r in data.get("raeume", []):
        h_quelle = ""
        if r.get("hoehe_m"):
            h_quelle = "aus Plan" if not r.get("_h_inferred") else f"Median {fmt(h_med)} m"
        lines.append(";".join([
            esc(r.get("name")),
            fmt(r.get("flaeche_m2")), fmt(r.get("umfang_m")), fmt(r.get("hoehe_m")),
            esc(h_quelle),
            esc(r.get("bodenbelag")),
            str(len(r.get("_quellen_plaene") or [])),
            esc(",".join(r.get("_merged_from") or [])),
        ]))
    lines.append("")

    # Fenster
    lines.append("FENSTER")
    lines.append("Bezeichnung;Raum;Breite m;Höhe m;FPH m;STUK m;Wand-Typ;Quelle")
    for f in data.get("fenster", []):
        lines.append(";".join([
            esc(f.get("bezeichnung")),
            esc(f.get("raum")),
            fmt(f.get("breite_m")),
            fmt(f.get("hoehe_m")),
            fmt(f.get("fph_m")),
            fmt(f.get("stuk_m")),
            esc(f.get("wand_typ")),
            esc(f.get("quelle") or f.get("_source") or ""),
        ]))
    lines.append("")

    # Türen
    lines.append("TÜREN")
    lines.append("Bezeichnung;Raum;Breite m;Höhe m;FPH m;STUK m;Wand-Typ;Quelle")
    for t in data.get("tueren", []):
        lines.append(";".join([
            esc(t.get("bezeichnung")),
            esc(t.get("raum")),
            fmt(t.get("breite_m")),
            fmt(t.get("hoehe_m")),
            fmt(t.get("fph_m")),
            fmt(t.get("stuk_m")),
            esc(t.get("wand_typ")),
            esc(t.get("quelle") or t.get("_source") or ""),
        ]))
    lines.append("")

    # Baudaten
    bd = data.get("baudaten") or {}
    bq = bd.get("_quellen") or {}
    lines.append("BAU-KENNDATEN")
    lines.append("Größe;Wert;Quelle")
    for key, label in [
        ("aussenwand_cm", "Außenwand cm"),
        ("innenwand_tragend_cm", "Innenwand tragend cm"),
        ("innenwand_nichttragend_cm", "Innenwand n.tragend cm"),
        ("decke_cm", "Decke cm"),
        ("bodenplatte_cm", "Bodenplatte cm"),
        ("geschosshoehe_m", "Geschoss-Höhe m"),
    ]:
        if bd.get(key) is not None:
            lines.append(";".join([label, fmt(bd[key]), esc(bq.get(key, "default"))]))
    lines.append("")

    # Bauteil-Legende (byte-exakt aus dem Plan gelesen)
    leg = data.get("legende") or {}
    if leg.get("wand_typen"):
        lines.append("BAUTEIL-LEGENDE (aus Plan gelesen)")
        lines.append("Code;Dicke cm;Material;Art;Vorkommen im Plan")
        counts = leg.get("wand_counts") or {}
        for code, w in leg["wand_typen"].items():
            lines.append(";".join([code, fmt(w.get("dicke_cm")), esc(w.get("material")),
                                   esc(w.get("art")), str(counts.get(code, 0))]))
        if leg.get("sauberkeitsschicht_cm"):
            lines.append(f"Sauberkeitsschicht;{fmt(leg['sauberkeitsschicht_cm'])};;;")
        if leg.get("estrich_cm"):
            lines.append(f"Estrich;{fmt(leg['estrich_cm'])};;;")
        lines.append("")

    # ÖNORM-Gewerke
    lines.append("ÖNORM-MASSEN (Putz/Estrich/Maler/Rohbau)")
    lines.append("Gewerk;Pos;Beschreibung;Endsumme;Einheit;Konfidenz")
    for gk, ginfo in (data.get("gewerke") or {}).items():
        label = (ginfo.get("label") or gk).split("(")[0].strip()
        for pos in ginfo.get("positionen") or []:
            lines.append(";".join([
                esc(label),
                esc(pos.get("posnr")),
                esc(pos.get("beschreibung")),
                fmt(pos.get("endsumme")),
                esc(pos.get("einheit")),
                fmt((pos.get("konfidenz") or 0) * 100, 0),
            ]))
    lines.append("")

    # ÖNORM-Detail-Zeilen (pro Position)
    lines.append("ÖNORM-DETAIL-ZEILEN")
    lines.append("Gewerk;Pos;Zeile;Länge;Höhe;Wert;Quelle")
    for gk, ginfo in (data.get("gewerke") or {}).items():
        label = (ginfo.get("label") or gk).split("(")[0].strip()
        for pos in ginfo.get("positionen") or []:
            for z in pos.get("zeilen") or []:
                lines.append(";".join([
                    esc(label), esc(pos.get("posnr")),
                    esc(z.get("text")),
                    fmt(z.get("laenge")), fmt(z.get("hoehe")), fmt(z.get("wert")),
                    esc(z.get("quelle")),
                ]))
    lines.append("")

    # Rohbau-Materialliste
    ml = data.get("materialliste") or {}
    if ml.get("bauteile"):
        lines.append("ROHBAU-MATERIALLISTE (Phase 1 — Faustformel-basiert)")
        lines.append("Bauteil;Material;Menge;Einheit;Konfidenz;Formel")
        for bauteil, pps in ml["bauteile"].items():
            for p in pps:
                lines.append(";".join([
                    esc(bauteil),
                    esc(p.get("material")),
                    fmt(p.get("menge")),
                    esc(p.get("einheit")),
                    fmt((p.get("konfidenz") or 0) * 100, 0),
                    esc(p.get("formel")),
                ]))
        lines.append("")

    csv = "﻿" + "\r\n".join(lines) + "\r\n"
    filename = f"projekt-massenermittlung-{(data.get('projekt_id') or 'export')[:8]}.csv"
    return Response(
        content=csv,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ═══════════════════════════════════════════════════════════════════════════
# SELBST-KALIBRIERUNG (MOAT) — Firma lädt Polier-Soll-Liste, System lernt
# firmenspezifische Faktoren (mit harten Guards). Auflösung: User > Firma >
# Global > Default. Tabellen: kalibrierungen, soll_listen (siehe db/kalibrierung.sql).
# ═══════════════════════════════════════════════════════════════════════════
class KalibrierungUploadRequest(BaseModel):
    projekt_id: str | None = None
    plan_id: str | None = None
    soll_text: str | None = None        # Polier-Soll-Liste (CSV/Freitext) — ODER:
    soll_storage_path: str | None = None  # PDF im 'plaene'-Bucket → Text server-seitig
    plan_ids: list[str] | None = None   # Ist nur aus DIESEN Plänen (Referenz-Paar)
    firma_id: str | None = None         # direkter Firma-Bezug (dedizierter Kalib-Bereich)
    titel: str | None = None            # Anzeigename des Referenz-Paars


class KalibrierungMerkenRequest(BaseModel):
    projekt_id: str | None = None
    plan_id: str | None = None
    overrides: dict                     # manuelle Materiallisten-Korrekturen der Firma


def _firma_id_von_projekt(projekt_id):
    try:
        pr = sb.table("projekte").select("firma_id").eq("id", projekt_id).single().execute()
        return (pr.data or {}).get("firma_id")
    except Exception:
        return None


def _firma_faktoren_neu_lernen(firma_id):
    """Lädt ALLE Soll-Listen der Firma und lernt: (a) Ratio-Faktoren aus den Belegen
    (Guards: ≥2 Belege, IQR, Median, Klemmung); (b) die WANDSTÄRKEN-VERTEILUNG (die
    schraffur-gebundene, nicht byte-exakt lesbare Größe) als Median über die Listen.
    Schreibt alles in kalibrierungen (firma_id, faktor_key, wert). Idempotent."""
    rows = sb.table("soll_listen").select(
        "belege, wand_verteilung").eq("firma_id", firma_id).execute().data or []
    ratios = {}
    verteilungen = []
    for r in rows:
        for b in (r.get("belege") or []):
            ratios.setdefault(b["faktor"], []).append(b["ratio"])
        if r.get("wand_verteilung"):
            verteilungen.append(r["wand_verteilung"])
    gelernt = _kalib.lerne_faktoren(ratios)
    wandvert = _kalib.aggregiere_verteilungen(verteilungen)   # {wand_anteil_*: pct}
    n_vert = len(verteilungen)
    # MANUELLE Korrekturen NICHT überschreiben: nur gelernte Zeilen ersetzen.
    manuell = sb.table("kalibrierungen").select("faktor_key").eq(
        "firma_id", firma_id).eq("quelle", "manuell").execute().data or []
    manuell_keys = {r["faktor_key"] for r in manuell}
    sb.table("kalibrierungen").delete().eq("firma_id", firma_id).eq("quelle", "gelernt").execute()
    for faktor, info in gelernt.items():
        if faktor in manuell_keys:
            continue   # die Firma hat das bewusst korrigiert → Vorrang
        sb.table("kalibrierungen").insert({
            "firma_id": firma_id, "faktor_key": faktor, "wert": info["wert"],
            "n_belege": info["n_belege"], "ratio_median": info["ratio_median"], "quelle": "gelernt",
        }).execute()
    for faktor, wert in wandvert.items():   # gelernte Wandverteilung (Anteil in %)
        if faktor in manuell_keys:
            continue
        sb.table("kalibrierungen").insert({
            "firma_id": firma_id, "faktor_key": faktor, "wert": wert, "n_belege": n_vert, "quelle": "gelernt",
        }).execute()
    return {**gelernt, **({"_wandverteilung": wandvert} if wandvert else {})}


def _soll_text_aus_storage(storage_path):
    """Lädt ein Polier-Listen-PDF aus dem 'plaene'-Bucket und extrahiert den Text-
    Layer (byte-exakt, dasselbe Format, für das parse_soll_liste getunt ist)."""
    import fitz
    raw = sb.storage.from_("plaene").download(storage_path)
    doc = fitz.open(stream=raw, filetype="pdf")
    try:
        return "\n".join(p.get_text() for p in doc)
    finally:
        doc.close()


@app.post("/api/kalibrierung-upload")
async def kalibrierung_upload(body: KalibrierungUploadRequest):
    """Polier-Soll-Liste (Text ODER PDF) hochladen → Ist↔Soll-Vergleich → Belege
    speichern → Firma-Faktoren neu lernen. Funktioniert sowohl projekt-intern als
    auch im dedizierten Kalibrierungs-Bereich (firma_id direkt, optional Plan-Paar)."""
    if not sb:
        raise HTTPException(500, "Supabase nicht konfiguriert")
    if not _KALIB_OK:
        raise HTTPException(500, "Kalibrierung nicht verfügbar")
    projekt_id = body.projekt_id
    if not projekt_id and body.plan_id:
        pl = sb.table("plaene").select("projekt_id").eq("id", body.plan_id).single().execute()
        projekt_id = (pl.data or {}).get("projekt_id")
    # Firma: aus Projekt, ODER direkt mitgegeben (dedizierter Kalib-Bereich)
    firma_id = _firma_id_von_projekt(projekt_id) if projekt_id else body.firma_id
    if not firma_id:
        raise HTTPException(400, "firma_id, projekt_id oder plan_id erforderlich")

    # Soll-Text: direkt ODER aus einem hochgeladenen PDF extrahiert
    soll_text = body.soll_text or ""
    if not soll_text and body.soll_storage_path:
        try:
            soll_text = _soll_text_aus_storage(body.soll_storage_path)
        except Exception as _exc:
            raise HTTPException(400, f"Polier-PDF nicht lesbar: {_exc}")
    soll = _kalib.parse_soll_liste(soll_text)
    if not soll:
        raise HTTPException(400, "Keine Positionen in der Soll-Liste erkannt")

    # Ist bei DEFAULT-Faktoren (NICHT kalibriert) — sonst kalibrieren wir gegen
    # schon korrigierte Werte. Nur wenn ein Plan-Kontext vorliegt; ohne Plan
    # lernen wir die Wandverteilung direkt aus der Soll-Liste (Belege brauchen Ist).
    ist_bauteile, belege = {}, []
    if projekt_id:
        ist = await projekt_massen(ProjektMassenRequest(
            projekt_id=projekt_id, plan_ids=body.plan_ids, ohne_kalibrierung=True))
        ist_bauteile = ((ist or {}).get("materialliste") or {}).get("bauteile") or {}
        belege = _kalib.belege_aus_vergleich(ist_bauteile, soll)
    # Wandstärken-Verteilung aus den HLZ-Paletten lernen (die Schraffur-Größe)
    wandvert = _kalib.hlz_verteilung_aus_soll(soll)

    sb.table("soll_listen").insert({
        "firma_id": firma_id, "projekt_id": projekt_id,
        "plan_id": (body.plan_ids or [None])[0] or body.plan_id,
        "titel": (body.titel or "")[:200] or None,
        "rohtext": soll_text[:20000], "positionen": len(soll),
        "belege": belege, "wand_verteilung": wandvert,
    }).execute()
    gelernt = _firma_faktoren_neu_lernen(firma_id)

    n_listen = len(sb.table("soll_listen").select("id").eq("firma_id", firma_id).execute().data or [])
    _wv = gelernt.get("_wandverteilung") if isinstance(gelernt, dict) else None
    _ratio_faktoren = {k: v for k, v in (gelernt or {}).items() if k != "_wandverteilung"}
    hinweise = []
    if _wv and ("wand_anteil_25cm_innen" in _wv):
        hinweise.append("Innenwand-Aufteilung aus deiner Liste übernommen "
                        f"(25cm {_wv.get('wand_anteil_25cm_innen')}% / "
                        f"20cm {_wv.get('wand_anteil_20cm')}% / 12cm {_wv.get('wand_anteil_12cm')}%).")
    if _ratio_faktoren:
        hinweise.append(f"{len(_ratio_faktoren)} Korrektur-Faktor(en) aktiv.")
    elif not _wv:
        hinweise.append("Noch keine Faktoren gelernt — Ratio-Faktoren brauchen ≥2 Soll-Listen "
                        "(Schutz vor Überanpassung); die Wandverteilung greift ab der 1. Liste mit HLZ-Paletten.")
    return {
        "status": "ok",
        "soll_positionen": len(soll),
        "belege": belege,
        "gelernte_faktoren": _ratio_faktoren,
        "gelernte_wandverteilung": _wv,
        "anzahl_soll_listen": n_listen,
        "hinweis": " ".join(hinweise),
    }


@app.get("/api/kalibrierung")
async def kalibrierung_status(projekt_id: str | None = None, firma_id: str | None = None):
    """Aktuelle Kalibrierung einer Firma (gelernte Faktoren + globale Basis)."""
    if not sb:
        raise HTTPException(500, "Supabase nicht konfiguriert")
    if not firma_id and projekt_id:
        firma_id = _firma_id_von_projekt(projekt_id)
    firma_rows, glob_rows = [], []
    try:
        glob_rows = sb.table("kalibrierungen").select("*").is_("firma_id", "null").execute().data or []
        if firma_id:
            firma_rows = sb.table("kalibrierungen").select("*").eq("firma_id", firma_id).execute().data or []
    except Exception as _exc:
        print(f"[kalibrierung] status fehlgeschlagen: {_exc!r}")
    n_listen = 0
    if firma_id:
        n_listen = len(sb.table("soll_listen").select("id").eq("firma_id", firma_id).execute().data or [])
    return {
        "firma_id": firma_id,
        "firma_faktoren": firma_rows,
        "global_faktoren": glob_rows,
        "aufgeloest": _kalib.resolve_kalibrierung(
            {r["faktor_key"]: {"wert": r["wert"]} for r in firma_rows},
            {r["faktor_key"]: {"wert": r["wert"]} for r in glob_rows}),
        "anzahl_soll_listen": n_listen,
    }


@app.get("/api/kalibrierung-referenzen")
async def kalibrierung_referenzen(firma_id: str | None = None, projekt_id: str | None = None):
    """Listet die hochgeladenen Referenz-Paare (Polier-Listen) einer Firma — für den
    dedizierten Kalibrierungs-Bereich. Je Eintrag: Titel, Positionen, Belege-Anzahl,
    gelernte Wandverteilung, Datum."""
    if not sb:
        raise HTTPException(500, "Supabase nicht konfiguriert")
    if not firma_id and projekt_id:
        firma_id = _firma_id_von_projekt(projekt_id)
    if not firma_id:
        raise HTTPException(400, "firma_id erforderlich")
    rows = sb.table("soll_listen").select(
        "id, titel, dateiname, positionen, belege, wand_verteilung, erstellt_am, plan_id"
    ).eq("firma_id", firma_id).order("erstellt_am", desc=True).execute().data or []
    refs = [{
        "id": r["id"],
        "titel": r.get("titel") or r.get("dateiname") or "Referenz-Liste",
        "positionen": r.get("positionen") or 0,
        "belege_anzahl": len(r.get("belege") or []),
        "wand_verteilung": r.get("wand_verteilung"),
        "erstellt_am": r.get("erstellt_am"),
    } for r in rows]
    return {"firma_id": firma_id, "referenzen": refs, "anzahl": len(refs)}


class KalibrierungLoeschenRequest(BaseModel):
    firma_id: str
    soll_liste_id: str


@app.post("/api/kalibrierung-referenz-loeschen")
async def kalibrierung_referenz_loeschen(body: KalibrierungLoeschenRequest):
    """Löscht ein einzelnes Referenz-Paar und lernt die Firma-Faktoren neu."""
    if not sb or not _KALIB_OK:
        raise HTTPException(500, "Kalibrierung nicht verfügbar")
    sb.table("soll_listen").delete().eq("id", body.soll_liste_id).eq(
        "firma_id", body.firma_id).execute()
    _firma_faktoren_neu_lernen(body.firma_id)
    n = len(sb.table("soll_listen").select("id").eq("firma_id", body.firma_id).execute().data or [])
    return {"status": "ok", "anzahl_soll_listen": n}


@app.post("/api/kalibrierung-reset")
async def kalibrierung_reset(body: KalibrierungUploadRequest):
    """Setzt die Firma-Kalibrierung zurück (löscht Soll-Listen + gelernte Faktoren).
    Die globale Basis bleibt unberührt. Reversibilität = Vertrauens-Guard."""
    if not sb:
        raise HTTPException(500, "Supabase nicht konfiguriert")
    projekt_id = body.projekt_id
    if not projekt_id and body.plan_id:
        pl = sb.table("plaene").select("projekt_id").eq("id", body.plan_id).single().execute()
        projekt_id = (pl.data or {}).get("projekt_id")
    firma_id = _firma_id_von_projekt(projekt_id) if projekt_id else body.firma_id
    if not firma_id:
        raise HTTPException(404, "Firma nicht gefunden")
    sb.table("kalibrierungen").delete().eq("firma_id", firma_id).execute()
    sb.table("soll_listen").delete().eq("firma_id", firma_id).execute()
    return {"status": "ok", "firma_id": firma_id, "hinweis": "Kalibrierung zurückgesetzt."}


# Nur bekannte, sinnvolle Materiallisten-Faktoren als manuelle Korrektur merken
# (keine beliebigen Keys; byte-exakte cm-Werte gehören nicht hierher).
_MERKBARE_KEYS = {
    "bodenplatte_aufschlag", "decke_aufschlag", "decke_auskragung", "ekv_decke_aufschlag",
    "aussenumfang_aufschlag", "frostgraben_aufschlag", "frostschuerze_tiefe_m",
    "frostschuerze_breite_m", "xps_frostschuerze_tiefe_m", "iso_korb_anteil",
    "wand_anteil_50cm", "wand_anteil_38cm", "wand_anteil_25cm_aussen",
    "wand_anteil_25cm_innen", "wand_anteil_20cm", "wand_anteil_12cm",
    "attika_aktiv", "attika_hoehe_m", "anzahl_saeulen", "anzahl_kamine",
    "aq65_m2_pro_matte", "pe_folie_m2_pro_rolle", "mauermoertel_paletten_pro_100m2",
}


@app.post("/api/kalibrierung-merken")
async def kalibrierung_merken(body: KalibrierungMerkenRequest):
    """Manuelle Korrekturen der Firma DAUERHAFT merken — die KI lernt mit, sobald
    der Betrieb Werte ausbessert. Gespeichert als quelle='manuell' (schlägt gelernte
    Faktoren, wird beim Soll-Listen-Lernen NICHT überschrieben). Gilt ab dann
    automatisch für künftige Projekte der Firma. Reset über /api/kalibrierung-reset."""
    if not sb or not _KALIB_OK:
        raise HTTPException(500, "Kalibrierung nicht verfügbar")
    projekt_id = body.projekt_id
    if not projekt_id and body.plan_id:
        pl = sb.table("plaene").select("projekt_id").eq("id", body.plan_id).single().execute()
        projekt_id = (pl.data or {}).get("projekt_id")
    firma_id = _firma_id_von_projekt(projekt_id) if projekt_id else None
    if not firma_id:
        raise HTTPException(404, "Firma nicht gefunden")
    gemerkt = {}
    for k, v in (body.overrides or {}).items():
        if k not in _MERKBARE_KEYS or v is None or v == "":
            continue
        try:
            wert = float(v)
        except (TypeError, ValueError):
            continue
        # vorhandene Zeile (egal welche Quelle) ersetzen → manuell gewinnt
        sb.table("kalibrierungen").delete().eq("firma_id", firma_id).eq("faktor_key", k).execute()
        sb.table("kalibrierungen").insert({
            "firma_id": firma_id, "faktor_key": k, "wert": wert, "n_belege": 0, "quelle": "manuell",
        }).execute()
        gemerkt[k] = wert
    return {"status": "ok", "gemerkt": gemerkt, "anzahl": len(gemerkt),
            "hinweis": (f"{len(gemerkt)} Korrektur(en) für deine Firma gemerkt — gilt ab jetzt automatisch."
                        if gemerkt else "Keine merkbaren Korrekturen gefunden.")}


# ═══════════════════════════════════════════════════════════════════════════
# SUPER-ADMIN (e-power) — Kunden-Accounts verwalten + globale Basis-Kalibrierung.
# Auth: admin_token muss app_config['ADMIN_TOKEN'] (oder env) entsprechen. Da die
# normale Auth client-seitig läuft, ist das die pragmatische, sichere MVP-Schranke.
# ═══════════════════════════════════════════════════════════════════════════
class AdminRequest(BaseModel):
    admin_token: str
    name: str | None = None
    email: str | None = None
    passwort: str | None = None
    firma_id: str | None = None
    gesperrt: bool | None = None
    faktoren: dict | None = None       # für globale Basis-Kalibrierung


def _admin_ok(token):
    try:
        cfg = sb.table("app_config").select("value").eq("key", "ADMIN_TOKEN").execute().data
        erwartet = (cfg[0]["value"] if cfg else os.environ.get("ADMIN_TOKEN", "")).strip()
    except Exception:
        erwartet = os.environ.get("ADMIN_TOKEN", "").strip()
    return bool(erwartet) and token == erwartet


@app.post("/api/admin/firmen")
async def admin_firmen(body: AdminRequest):
    """Alle Kunden-Accounts + Nutzungszahlen (Projekte, Soll-Listen)."""
    if not sb or not _admin_ok(body.admin_token):
        raise HTTPException(403, "Kein Admin-Zugriff")
    firmen = sb.table("firmen").select("id, name, email, gesperrt, erstellt_am").execute().data or []
    for f_ in firmen:
        f_["projekte"] = len(sb.table("projekte").select("id").eq("firma_id", f_["id"]).execute().data or [])
        f_["soll_listen"] = len(sb.table("soll_listen").select("id").eq("firma_id", f_["id"]).execute().data or [])
        f_.pop("passwort_hash", None)
    return {"firmen": firmen, "anzahl": len(firmen)}


@app.post("/api/admin/firma-anlegen")
async def admin_firma_anlegen(body: AdminRequest):
    """Legt einen Kunden-Account an (e-power steuert, wer das Produkt nutzt).
    Passwort wird über die bestehende register_firma-RPC gehasht."""
    if not sb or not _admin_ok(body.admin_token):
        raise HTTPException(403, "Kein Admin-Zugriff")
    if not (body.name and body.email and body.passwort):
        raise HTTPException(400, "name, email, passwort erforderlich")
    try:
        res = sb.rpc("register_firma", {"p_name": body.name, "p_email": body.email,
                                        "p_passwort": body.passwort}).execute()
        return {"status": "ok", "firma": res.data}
    except Exception as e:
        raise HTTPException(400, f"Anlegen fehlgeschlagen: {e}")


@app.post("/api/admin/firma-sperren")
async def admin_firma_sperren(body: AdminRequest):
    """Account sperren/entsperren."""
    if not sb or not _admin_ok(body.admin_token):
        raise HTTPException(403, "Kein Admin-Zugriff")
    if not body.firma_id:
        raise HTTPException(400, "firma_id erforderlich")
    sb.table("firmen").update({"gesperrt": bool(body.gesperrt)}).eq("id", body.firma_id).execute()
    return {"status": "ok", "firma_id": body.firma_id, "gesperrt": bool(body.gesperrt)}


@app.post("/api/admin/global-kalibrierung")
async def admin_global_kalibrierung(body: AdminRequest):
    """Globale Basis-Kalibrierung setzen — neue Accounts starten damit besser.
    faktoren = {faktor_key: wert}. Nur bekannte Faktor-Keys werden übernommen."""
    if not sb or not _admin_ok(body.admin_token):
        raise HTTPException(403, "Kein Admin-Zugriff")
    erlaubt = {r["faktor"] for r in _kalib.FAKTOR_REGELN} if _KALIB_OK else set()
    sb.table("kalibrierungen").delete().is_("firma_id", "null").execute()
    gesetzt = {}
    for k, v in (body.faktoren or {}).items():
        if k in erlaubt and v is not None:
            wert = max(_kalib.FAKTOR_MIN, min(_kalib.FAKTOR_MAX, float(v)))
            sb.table("kalibrierungen").insert({
                "firma_id": None, "faktor_key": k, "wert": wert, "n_belege": 0,
            }).execute()
            gesetzt[k] = wert
    return {"status": "ok", "global_faktoren": gesetzt}
