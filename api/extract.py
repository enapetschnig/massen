"""
Vercel Serverless: PDF Text Extraction with pdfplumber.
Extracts ALL text with exact positions, groups into rooms/fenster/dimensions.
Called after PDF upload, stores results in Supabase for the orchestrator.
"""
from __future__ import annotations
import json, os, re, math, tempfile

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
    client = anthropic.Anthropic(api_key=api_key)

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
        rad_x = 150 if is_code else 60
        rad_y_pos = 150 if is_code else 60
        rad_y_neg = -150 if is_code else -5
        candidates = []
        for s in spans_all:
            if s is rs: continue
            dx = s["cx"] - rx; dy = s["cy"] - ry
            if abs(dx) <= rad_x and rad_y_neg <= dy <= rad_y_pos:
                candidates.append((dy, dx, s))
        candidates.sort()
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
                # Tag each observation with its source tile index
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
        except Exception:
            pass

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
        confs = [float(o.get("konfidenz") or 0) for o in obs_list]
        merged["konfidenz"] = max(confs) if confs else 0.8
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

    # Fenster dedup: by bezeichnung, merge dimensions (highest confidence wins)
    fenster_groups = {}
    for f in all_fenster:
        key = _norm_name(f.get("bezeichnung"))
        if not key:
            continue
        if key not in fenster_groups:
            fenster_groups[key] = dict(f)
        else:
            existing = fenster_groups[key]
            if float(f.get("konfidenz") or 0) > float(existing.get("konfidenz") or 0):
                for fld, val in f.items():
                    if val not in (None, "", 0):
                        existing[fld] = val
            else:
                for fld, val in f.items():
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
oesterreichischen Bauplan (Maßstab 1:50). Bemaßungen sind als
KETTENBEMASSUNG dargestellt: Eine horizontale Linie mit kurzen vertikalen
Markern, zwischen denen die jeweiligen Wand-Längen in CENTIMETERN stehen
(z.B. "152", "300", "580").

Lies ALLE Maßzahlen in dieser Bemaßung der Reihe nach von links nach rechts
(bzw. von oben nach unten) ab. Maße aus mehreren parallelen Ketten gibst
du als separate Listen zurück.

JSON-Antwort (kein Markdown, keine Erklärung):
{
  "ketten": [
    [48, 152, 143, 543, 120, 231],
    [2, 44, 2, 301, 8, 576]
  ],
  "summe_cm_je_kette": [1237, 933],
  "konfidenz": 0.95
}

Wichtig:
- Werte sind cm-Zahlen (1-4-stellig). Niemals erfinden — nur was du klar liest.
- Wenn nur eine Kette: liefere ein einziges Array.
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

            # Aggregiere Wandlängen je Seite — Summe je Kette = Außenkante in cm
            for side, payload in wd["ketten_per_side"].items():
                summen = payload.get("summe_cm_je_kette") or []
                if not summen and payload.get("ketten"):
                    summen = [sum(k) for k in payload["ketten"]]
                if summen:
                    # Größte Summe ist üblicherweise die Außenkante
                    wd["wandlaengen_m"][side] = round(max(summen) / 100.0, 2)
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
Bestimme die AUSSENKONTUR der GEMAUERTEN HAUPTBAU-Huelle — also
die Aussenwand-Linie um die geheizten Innenraeume + Geraete-/
Abstellraum + Stiegenhaus. NICHT die Terrasse, NICHT den Parkplatz,
NICHT ueberdachte Carports — auch wenn sie ueberdacht sind, gehoeren
sie NICHT in die Bodenplatten-Aussenkontur, weil sie kein durchgehendes
Fundament/Mauerwerk haben.

Einfache Regel: wenn ein Bereich Aussen-Bodenbelag (Pflaster/Terrasse)
hat ohne 4 gemauerte Aussenwaende, gehoert er NICHT in die Kontur.

EFH haben fast IMMER eine L-/U-/T-Form mit Vor- und Ruecksprungeen.
Ein einfaches Rechteck ist die seltene Ausnahme.

Liefere zwei Sachen:
1) Polygon der Aussenkontur des Hauptbaus — JEDE Ecke einzeln auflisten.
   Bei einer L-Form sind das 6 Ecken, bei U-Form 8 Ecken. Nicht vereinfachen!
   Koordinaten in NORMIERTEN 0-1 relativ zur sichtbaren Plan-Flaeche.
2) Die Aussenmasse in METERN je Wand-Segment, abgelesen aus der
   Hauptbemassungskette am Plan-Rand. Pro Himmelsrichtung KANN es
   MEHRERE Werte geben (L-Form: Nordfassade hat z.B. 8m + 4m = 12m).

JSON-Antwort, kein Markdown:
{
  "polygon_norm": [[0.12,0.10],[0.85,0.10],[0.85,0.45],[0.62,0.45],[0.62,0.62],[0.12,0.62]],
  "seiten_m": {"N": 12.40, "S": 7.20, "S_b": 5.20, "W": 8.00, "E": 4.50, "E_b": 3.50},
  "umfang_m": 40.80,
  "flaeche_m2": 79.56,
  "konfidenz": 0.85
}
Wichtig:
- Polygon im Uhrzeigersinn beginnend oben-links.
- Bei jedem Versatz/Vorsprung: alle Ecken auflisten.
- "umfang_m" = Summe ALLER seiten_m-Werte (auch _b/_c-Suffix-Segmente).
- "flaeche_m2" = Polygon-Flaeche (Shoelace-Formel) des Hauptbaus.
- Plausi: EFH-Bodenplatte typisch 80-180 m², EFH-Umfang 50-80m.
- Wenn Bodenplatten-Flaeche > 200 m² oder Umfang > 90m: pruefe ob du
  Terrasse/Parkplatz mitgenommen hast — die gehoeren NICHT rein."""

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
                print(f"[aussenkontur] umfang={aussenkontur_vision.get('umfang_m')} m, "
                      f"flaeche={aussenkontur_vision.get('flaeche_m2')} m², "
                      f"konf={aussenkontur_vision.get('konfidenz')}")
        except Exception as _exc:
            print(f"[aussenkontur] failed: {_exc!r}")
            aussenkontur_vision = {}

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
    log["oenorm_lv"] = oenorm_lv
    if gewerke_result:
        log["gewerke"] = gewerke_result
    sb.table("plaene").update({"agent_log": log, "gesamt_konfidenz": 95}).eq("id", body.plan_id).execute()

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

    # 2) Alle Pläne des Projekts laden (mit agent_log für Baudaten + Fenster)
    plaene_res = sb.table("plaene").select(
        "id, dateiname, agent_log"
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
    def _nk(s):
        return re.sub(r"[\s\-_/]+", "", (s or "").lower())

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

    cleaned_rooms = []
    for idx, r in enumerate(merged_rooms):
        sn = _short_name(r.get("name"))
        if not sn:
            continue
        if idx in cousin_losers:
            continue
        my_quellen = len(r.get("_quellen_plaene") or [])
        # Halluzination: OG-Raum in EG-Plan — auch "obergeschoß" (ß) erkennen
        if re.search(r"\bobergeschoss\b|\bobergescho[ßs]+\b|\bog\b|\b[0-9]\.?\s?og\b", sn) \
                and _early_geschoss.upper().startswith("EG"):
            r["_hallucination"] = "OG-Suffix im EG-Plan"
            continue
        # Nummerierte Räume (Zimmer 1/2/3 ...) — wenn Nummer > Max andere
        # gleichnamiger Räume mit MEHR Quellen-Plänen → Halluzination
        m_zif = re.match(r"^([a-zäöü]+)\s*(\d+)$", sn)
        if m_zif and my_quellen < len(plaene):
            stamm, ziffer = m_zif.group(1), int(m_zif.group(2))
            max_andere = 0
            for other in merged_rooms:
                if other is r:
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

    # 4c) Höhen-Inferenz: Architekten beschriften nicht jeden Raum mit RH —
    # typisch fehlt H bei Wohnräumen (gleicher Standard-Wert) und Außen-
    # bereichen (Loggia/Terrasse). Wenn andere Räume H haben, übernimm
    # den Median für Räume ohne H. Damit rechnet die Putz-/Maler-LV
    # konsistent mit der echten Geschoss-Höhe statt mit Default 2,70m.
    rooms_with_h = [r for r in merged_rooms if r.get("hoehe_m")]
    if rooms_with_h:
        h_values = sorted(float(r["hoehe_m"]) for r in rooms_with_h)
        h_median = h_values[len(h_values) // 2]
        h_max = h_values[-1]
        # Für Räume ohne H: Median nehmen, als "inferred" markieren
        ergaenzte_h = 0
        for r in merged_rooms:
            if not r.get("hoehe_m"):
                r["hoehe_m"] = h_median
                r["_h_inferred"] = True
                ergaenzte_h += 1
    else:
        h_median = None
        h_max = None
        ergaenzte_h = 0

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
        # Sanity-Guard: Öffnungen < 30cm gibt es nicht (OCR/Vision-Artefakt)
        if d.get("breite_m") and d["breite_m"] < 0.30:
            d["breite_m"] = None
        if d.get("hoehe_m") and d["hoehe_m"] < 0.30:
            d["hoehe_m"] = None
        return d

    def _sig(d, bez):
        return (bez.strip().lower(), (d.get("raum") or "").strip().lower(),
                round(float(d.get("breite_m") or 0), 2),
                round(float(d.get("hoehe_m") or 0), 2))

    def _collect_oeffnungen(rows):
        # Erst alle einsammeln, dann leere Einträge raus wenn der Raum
        # bereits einen Eintrag MIT Maßen hat.
        items = []
        seen = set()
        for row in rows:
            d = _norm_dim(dict(row.get("daten") or {}))
            bez = row.get("bezeichnung") or d.get("bezeichnung") or ""
            sig = _sig(d, bez)
            if sig in seen:
                continue
            seen.add(sig)
            items.append(dict(d, bezeichnung=bez))
        # Räume mit mind. einem Maß-Eintrag identifizieren
        raeume_mit_massen = {
            (i.get("raum") or "").strip().lower()
            for i in items
            if i.get("breite_m") and i.get("hoehe_m")
        }
        raeume_mit_massen.discard("")
        cleaned = []
        for i in items:
            raum = (i.get("raum") or "").strip().lower()
            has_dims = bool(i.get("breite_m") and i.get("hoehe_m"))
            # Leeren Eintrag wegwerfen, wenn der Raum schon einen mit Maßen hat
            if not has_dims and raum in raeume_mit_massen:
                continue
            cleaned.append(i)
        return cleaned

    alle_fenster = _collect_oeffnungen(fenster_rows)
    alle_tueren = _collect_oeffnungen(tueren_rows)

    # 6) Baudaten aus allen Plänen sammeln — höchste Vision-Konfidenz gewinnt
    best_baudaten = {}
    best_konf = -1.0
    geschoss = "EG"
    # PASS-4-Daten + Außenkontur-Vision aus allen Plänen sammeln
    # (für gemessene Geometrie statt sqrt-Schätzung)
    aussenmasse_kandidaten = []  # Liste von {seiten:{N,S,W,E}, umfang, quelle}
    aussenpolygon_kandidaten = []  # Liste von {umfang_m, flaeche_m2, quelle}
    for p in plaene:
        log = p.get("agent_log") or {}
        gw = log.get("gewerke") or {}
        bd = gw.get("baudaten") or {}
        if bd:
            k = float(bd.get("konfidenz") or 0.0)
            if k > best_konf:
                best_konf = k
                best_baudaten = bd
        # Geschoss aus dem ersten Plan, der eines hat
        if not geschoss or geschoss == "EG":
            g = (log.get("geo") or {}).get("geschoss") or log.get("geschoss")
            if g:
                geschoss = g
        # PASS 4 — Bemaßungs-Vision: wandlaengen_m pro Seite
        wbv = log.get("wand_bemassung_vision") or {}
        for top_name, top_data in wbv.items():
            wl = (top_data or {}).get("wandlaengen_m") or {}
            if wl:
                # Nur Seiten mit echtem Wert
                seiten = {k: v for k, v in wl.items() if v and v > 0}
                if len(seiten) >= 2:  # min 2 Seiten für Umfang
                    aussenmasse_kandidaten.append({
                        "seiten_m": seiten,
                        "umfang_m": round(sum(seiten.values()), 2),
                        "plan": p.get("dateiname"),
                        "top": top_name,
                        "quelle": "pass4-bemassung",
                    })
        # Außenkontur-Vision (Polygon + Außenmaße + Fläche)
        ak = log.get("aussenkontur_vision") or {}
        if ak.get("umfang_m") and ak.get("flaeche_m2"):
            aussenpolygon_kandidaten.append({
                "umfang_m": float(ak["umfang_m"]),
                "flaeche_m2": float(ak["flaeche_m2"]),
                "seiten_m": ak.get("seiten_m") or {},
                "plan": p.get("dateiname"),
                "quelle": "vision-aussenkontur",
            })

    # Konsolidieren: Vision-Polygon ist primäre Quelle (es zeichnet die
    # ganze Kontur nach), PASS-4-Bemaßung dient als Cross-Check (liest
    # nur die Haupt-Außen-Achse, untersieht L-Form-Versätze).
    # PLAUSI-CHECK: Vision-Polygon-Fläche darf nicht >1.6× Σ F_innen sein,
    # sonst hat Vision überdachte Außenbereiche (Terrasse/Parkplatz) mit-
    # erfasst — die gehören nicht in die Bodenplatte.
    from massen_logic import kategorie_of as _kat_check
    f_innen_check = sum(r.get("flaeche_m2") or 0 for r in merged_rooms
                         if _kat_check(r.get("name") or "") == "Innenraum_warm")
    gemessen = None
    if aussenpolygon_kandidaten:
        ap = aussenpolygon_kandidaten[0]
        bp_flaeche = ap["flaeche_m2"]
        # Plausi: Bodenplatte sollte ~1.10-1.30 × Σ F_innen sein (Wand-Aufschlag)
        if f_innen_check > 0 and bp_flaeche > f_innen_check * 1.60:
            # Polygon zu groß — hat vermutlich Loggia/Terrasse mit drin
            bp_flaeche = round(f_innen_check * 1.15, 2)
            polygon_zu_gross = True
        else:
            polygon_zu_gross = False
        gemessen = {
            "aussenumfang_m": ap["umfang_m"],
            "bodenplatte_flaeche_m2": bp_flaeche,
            "quelle": "vision-aussenkontur" + ("-bp-korrigiert" if polygon_zu_gross else ""),
            "konfidenz": 0.70 if polygon_zu_gross else 0.80,
        }
        if polygon_zu_gross:
            gemessen["polygon_original_m2"] = ap["flaeche_m2"]
        # Cross-Check mit PASS-4 — wenn Polygon-Wert deutlich kleiner als
        # PASS-4-Summe, ist Polygon evtl unterschätzt
        if aussenmasse_kandidaten:
            pass4_max = max(c["umfang_m"] for c in aussenmasse_kandidaten)
            if pass4_max > ap["umfang_m"] * 1.15:
                # PASS-4 ist deutlich größer → Polygon korrigieren
                gemessen["aussenumfang_m"] = round(pass4_max, 2)
                gemessen["quelle"] = "polygon+pass4-korrigiert"
                gemessen["konfidenz"] = 0.85
            else:
                diff_pct = abs(pass4_max - ap["umfang_m"]) / max(ap["umfang_m"], 1)
                if diff_pct < 0.10:
                    # Beide nah beieinander → höchste Konfidenz
                    gemessen["konfidenz"] = 0.95
                    gemessen["quelle"] = "polygon+pass4-konsistent"
                gemessen["pass4_umfang_m"] = round(pass4_max, 2)
    elif aussenmasse_kandidaten:
        # Nur PASS-4 vorhanden — Max-Wert nehmen (umfasst eher die ganze Kontur)
        umfang_max = max(c["umfang_m"] for c in aussenmasse_kandidaten)
        gemessen = {
            "aussenumfang_m": umfang_max,
            "quelle": "pass4-bemassung",
            "konfidenz": 0.75,
            "details": aussenmasse_kandidaten,
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
                merged_rooms, alle_fenster, best_baudaten,
                override=body.materialliste_override, geschoss=geschoss,
                tueren=alle_tueren, gemessen=gemessen,
            )
        except Exception as e:
            materialliste_result = {"error": f"{type(e).__name__}: {e}"}

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
        "plaene_count": len(plaene),
        "plaene_total": len(plaene_all),
        "plaene": plaene_manifest,
        "raeume_count": len(merged_rooms),
        "fenster_count": len(alle_fenster),
        "tueren_count": len(alle_tueren),
        "merge_enrichments": enrichments,
        "h_inferred_count": ergaenzte_h,
        "h_inferred_value": h_median,
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
