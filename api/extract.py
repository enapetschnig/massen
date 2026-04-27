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
    ROOM_KWS = {
        "wohnküche","wohnkueche","wohnk","wohnen","zimmer","schlafzimmer","kinderzimmer",
        "bad","wc","dusche","vorraum","vorzimmer","flur","gang","diele",
        "küche","kueche","loggia","balkon","terrasse","stiegenhaus","stiege",
        "stiegenaufg","abstellraum","abstellr","garderobe","speis","technik","keller",
        "waschküche","waschkueche","waschraum","werkstätte","werkstatt","lager","kellerabteil",
        "büro","buero","atelier","studio","praxis",
        # Tiefgaragen/Allgemeinräume
        "tiefgarage","fahrrad","kinderwagen","fahrradraum","schleuse","fittness",
        "treppenhaus","e-technik","elektroraum","pelletslagerraum","müllraum",
        "ar","ar top","kiwa",
    }
    BODENBELAG_KWS = {"parkett","fliesen","laminat","vinyl","estrich","teppich","feinsteinzeug","naturstein","keramik","beschichtung","beton"}
    AR_TOP_RX = re.compile(r"^(ar\s+)?top\s*\d+\s*(ar)?\s*[a-z]?$", re.I)

    def is_room_name_span(s):
        t = s["text"].lower().strip()
        # AR TOP NN / Top N AR pattern
        if AR_TOP_RX.match(t): return True
        if re.search(r"\d", t):
            return False
        if len(t) < 2:
            return False
        for k in ROOM_KWS:
            if t == k or t.startswith(k + " ") or (k in t and len(t) <= len(k) + 6):
                return True
        return False

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
        candidates = []
        for s in spans_all:
            if s is rs: continue
            dx = s["cx"] - rx; dy = s["cy"] - ry
            if abs(dx) <= 60 and -5 <= dy <= 60:
                candidates.append((dy, dx, s))
        candidates.sort()
        f_val = u_val = h_val = None
        bodenbelag = None
        for dy, dx, s in candidates:
            t = s["text"]
            m = re.match(r"^U\s*[:=]?\s*([0-9]+[,.][0-9]+)", t)
            if m and u_val is None:
                u_val = float(m.group(1).replace(",", "."))
                continue
            m = re.match(r"^H\s*[:=]?\s*([0-9]+[,.][0-9]+)", t)
            if m and h_val is None:
                h_val = float(m.group(1).replace(",", "."))
                continue
            m = re.match(r"^F\s*[:=]?\s*([0-9]+[,.][0-9]+)", t)
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
    for s in spans_all:
        if is_room_name_span(s):
            text_first_rooms.append(extract_room_from_label(s))

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

    _greedy_fill(text_first_rooms, claims, "F", "flaeche_m2")
    _greedy_fill(text_first_rooms, claims, "U", "umfang_m")
    _greedy_fill(text_first_rooms, claims, "H", "hoehe_m")
    _greedy_fill(text_first_rooms, claims, "B", "bodenbelag")

    # Find TOP labels with positions; assign each room to nearest TOP by distance
    top_labels = []  # [{"name": "TOP 25", "cx":, "cy":}, ...]
    top_re = re.compile(r"^(TOP|Top|top)\s*\.?\s*([0-9]{1,3}[a-zA-Z]?)$")
    for s in spans_all:
        m = top_re.match(s["text"].strip())
        if m:
            top_labels.append({"name": f"TOP {m.group(2)}", "cx": s["cx"], "cy": s["cy"]})

    def nearest_top(rx, ry, max_dist=500):
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

    # Dedup text_first: merge incomplete duplicates into complete ones with same name+F
    def _rkey(r):
        return (_norm_name(r.get("name")), round((r.get("flaeche_m2") or 0)*10)/10)

    tf_map = {}
    for r in text_first_rooms:
        k = _rkey(r)
        if k[1] == 0:  # no F at all
            continue
        ex = tf_map.get(k)
        complete_new = bool(r.get("flaeche_m2") and r.get("umfang_m") and r.get("hoehe_m"))
        complete_old = bool(ex and ex.get("flaeche_m2") and ex.get("umfang_m") and ex.get("hoehe_m"))
        if ex is None or (complete_new and not complete_old):
            tf_map[k] = r
    text_first_rooms = list(tf_map.values())
    # Flag whether text-first produced enough data to skip / trust over Vision
    text_first_count = sum(1 for r in text_first_rooms if r.get("flaeche_m2") and r.get("umfang_m") and r.get("hoehe_m"))
    text_first_enough = text_first_count >= 5  # threshold: at least 5 solid rooms

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
    {"bezeichnung": "FE_30", "raum": "Zimmer", "wohnung": "TOP 25", "al_breite_mm": 120, "al_hoehe_mm": 147, "rb_breite_mm": 130, "rb_hoehe_mm": 147, "rph_mm": 84, "fph_mm": 87, "konfidenz": 0.95}
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
    if len(spans_all) > 100:  # only enforce on plans with real text layer
        full_text_lower = " ".join(s["text"] for s in spans_all).lower()
        all_numbers = set()
        for tok in text_tokens:
            if tok.get("num") is not None:
                all_numbers.add(round(tok["num"], 2))

        def vision_has_evidence(r):
            # STRICT: room name must appear in PDF text layer.
            # F-value alone isn't enough (plans have hundreds of numeric
            # dimension tokens, easily false-positive).
            name = (r.get("name") or "").strip().lower()
            if len(name) < 4:
                return False
            if name in full_text_lower:
                return True
            # Substring match for compound names (e.g. "Wohnkueche" -> "wohnk")
            for w in re.split(r"[\s/+\-]+", name):
                if len(w) >= 5 and w in full_text_lower:
                    return True
            return False

        before = len(merged_rooms)
        merged_rooms = [r for r in merged_rooms if vision_has_evidence(r)]
        dropped = before - len(merged_rooms)
        if dropped:
            print(f"[hallucination filter] dropped {dropped}/{before} vision rooms without text-layer evidence")

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

    # Pass A: emit every text-first room with F>0 as the ground-truth record.
    for tr in text_first_rooms:
        if not tr.get("flaeche_m2"):
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

    # Pass B: Vision rooms NOT matched by any text-first record (things the
    # text layer missed - e.g. outdoor annotations, rooms without a label block)
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

    doc.close()

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
