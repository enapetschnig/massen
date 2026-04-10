"""
KI-Massenermittlung - FastAPI Backend

Main application with authentication, project/plan management,
PDF upload, AI analysis trigger, and Excel export.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import uuid
import logging

# Ensure backend directory is in Python path (needed for Vercel deployment)
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import bcrypt
from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr

# Load .env from backend dir (local) or Vercel env vars (production)
load_dotenv(os.path.join(_backend_dir, '.env'))
load_dotenv()  # Also check current dir

from db.supabase_client import (  # noqa: E402
    create_firma,
    create_korrektur,
    create_plan,
    create_projekt,
    delete_plan,
    delete_projekt,
    get_config,
    get_elemente,
    get_firma,
    get_firma_by_email,
    get_masse,
    get_massen,
    get_plan,
    get_plaene,
    get_projekt,
    get_projekte,
    update_masse,
    update_plan,
    update_projekt,
    upload_file,
    download_file,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

JWT_SECRET: str = get_config("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRATION_HOURS: int = 24

logger = logging.getLogger("massenermittlung")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="KI-Massenermittlung API",
    version="1.0.0",
    description="AI-powered construction quantity surveying from Austrian building plan PDFs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    def __init__(self) -> None:
        self.active: dict[str, list[WebSocket]] = {}

    async def connect(self, plan_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self.active.setdefault(plan_id, []).append(ws)

    def disconnect(self, plan_id: str, ws: WebSocket) -> None:
        if plan_id in self.active:
            self.active[plan_id] = [c for c in self.active[plan_id] if c is not ws]
            if not self.active[plan_id]:
                del self.active[plan_id]

    async def broadcast(self, plan_id: str, message: dict) -> None:
        for ws in self.active.get(plan_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

security = HTTPBearer()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _create_token(firma_id: str, email: str) -> str:
    payload = {
        "sub": firma_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Ungültiger oder abgelaufener Token") from exc


async def get_current_firma(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    payload = _decode_token(credentials.credentials)
    firma_id = payload.get("sub")
    if not firma_id:
        raise HTTPException(status_code=401, detail="Token enthält keine Firmen-ID")
    firma = get_firma(firma_id)
    if not firma:
        raise HTTPException(status_code=401, detail="Firma nicht gefunden")
    return firma


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    passwort: str


class LoginRequest(BaseModel):
    email: EmailStr
    passwort: str


class ProjektCreate(BaseModel):
    name: str
    adresse: str = ""
    gewerk: str = ""


class ProjektUpdate(BaseModel):
    name: Optional[str] = None
    adresse: Optional[str] = None
    gewerk: Optional[str] = None


class MasseUpdate(BaseModel):
    endsumme: Optional[float] = None
    beschreibung: Optional[str] = None
    einheit: Optional[str] = None
    grund: str = ""


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@app.post("/api/auth/register", status_code=201)
async def register(body: RegisterRequest):
    existing = get_firma_by_email(body.email)
    if existing:
        raise HTTPException(status_code=409, detail="E-Mail bereits registriert")

    hashed = _hash_password(body.passwort)
    firma = create_firma(body.name, body.email, hashed)
    token = _create_token(firma["id"], firma["email"])

    return {
        "token": token,
        "firma": {"id": firma["id"], "name": firma["name"], "email": firma["email"]},
    }


@app.post("/api/auth/login")
async def login(body: LoginRequest):
    firma = get_firma_by_email(body.email)
    if not firma or not _verify_password(body.passwort, firma.get("passwort_hash", "")):
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")

    token = _create_token(firma["id"], firma["email"])
    return {
        "token": token,
        "firma": {"id": firma["id"], "name": firma["name"], "email": firma["email"]},
    }


# ---------------------------------------------------------------------------
# Projekt routes
# ---------------------------------------------------------------------------


@app.get("/api/projekte")
async def list_projekte(firma: dict = Depends(get_current_firma)):
    projekte = get_projekte(firma["id"])
    # Add plan count for each project
    for p in projekte:
        plaene = get_plaene(p["id"])
        p["plan_count"] = len(plaene)
    return projekte


@app.post("/api/projekte", status_code=201)
async def create_projekt_route(body: ProjektCreate, firma: dict = Depends(get_current_firma)):
    projekt = create_projekt(firma["id"], body.name, body.adresse, body.gewerk)
    return projekt


@app.get("/api/projekte/{projekt_id}")
async def get_projekt_detail(projekt_id: str, firma: dict = Depends(get_current_firma)):
    projekt = get_projekt(projekt_id)
    if not projekt:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    if projekt["firma_id"] != firma["id"]:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf dieses Projekt")

    plaene = get_plaene(projekt_id)
    return {**projekt, "plaene": plaene}


@app.put("/api/projekte/{projekt_id}")
async def update_projekt_route(
    projekt_id: str,
    body: ProjektUpdate,
    firma: dict = Depends(get_current_firma),
):
    projekt = get_projekt(projekt_id)
    if not projekt:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    if projekt["firma_id"] != firma["id"]:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf dieses Projekt")

    update_data: dict[str, Any] = {}
    if body.name is not None:
        update_data["name"] = body.name
    if body.adresse is not None:
        update_data["adresse"] = body.adresse
    if body.gewerk is not None:
        update_data["gewerk"] = body.gewerk

    if not update_data:
        raise HTTPException(status_code=400, detail="Keine Änderungen angegeben")

    updated = update_projekt(projekt_id, update_data)
    return updated


@app.delete("/api/projekte/{projekt_id}", status_code=204)
async def delete_projekt_route(
    projekt_id: str,
    firma: dict = Depends(get_current_firma),
):
    projekt = get_projekt(projekt_id)
    if not projekt:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    if projekt["firma_id"] != firma["id"]:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf dieses Projekt")

    delete_projekt(projekt_id)


# ---------------------------------------------------------------------------
# Upload route
# ---------------------------------------------------------------------------


@app.post("/api/projekte/{projekt_id}/upload", status_code=201)
async def upload_pdf(
    projekt_id: str,
    file: UploadFile = File(...),
    firma: dict = Depends(get_current_firma),
):
    projekt = get_projekt(projekt_id)
    if not projekt:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    if projekt["firma_id"] != firma["id"]:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf dieses Projekt")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Nur PDF-Dateien sind erlaubt")

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Leere Datei")

    # Upload to Supabase Storage
    storage_path = f"{firma['id']}/{projekt_id}/{uuid.uuid4().hex}_{file.filename}"
    try:
        upload_file("plaene", storage_path, file_bytes)
    except Exception as exc:
        logger.error("Upload fehlgeschlagen: %s", exc)
        raise HTTPException(status_code=500, detail="Datei-Upload fehlgeschlagen") from exc

    plan = create_plan(projekt_id, file.filename, storage_path)
    return plan


# ---------------------------------------------------------------------------
# Analysis route
# ---------------------------------------------------------------------------


async def run_analysis(plan_id: str, firma_id: str) -> None:
    """Background task: run the multi-agent orchestrator on a plan."""
    try:
        update_plan(plan_id, {"verarbeitet": False, "gesamt_konfidenz": 0})
        await manager.broadcast(plan_id, {
            "typ": "fortschritt", "schritt": "start", "fortschritt": 0,
            "details": "Analyse wird gestartet..."
        })

        plan = get_plan(plan_id)
        if not plan or not plan.get("storage_path"):
            raise ValueError("Plan oder Storage-Pfad nicht gefunden")

        # Download PDF from Supabase Storage to temp file
        pdf_bytes = download_file("plaene", plan["storage_path"])
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(pdf_bytes)
        tmp.close()
        pdf_path = tmp.name

        try:
            from orchestrator import Orchestrator

            orch = Orchestrator()
            # Pass the manager's websockets for this plan
            ws_set = set()
            for ws in manager.active.get(plan_id, []):
                ws_set.add(ws)
            orch.websockets = ws_set

            ergebnis = await orch.run(
                pdf_path=pdf_path,
                firma_id=firma_id,
                plan_id=plan_id,
            )

            update_plan(plan_id, {
                "verarbeitet": True,
                "gesamt_konfidenz": ergebnis.get("gesamt_qualitaet", 0),
                "agent_log": ergebnis,
            })

            await manager.broadcast(plan_id, {
                "typ": "fortschritt", "schritt": "abgeschlossen", "fortschritt": 100,
                "details": f"Analyse abgeschlossen - Qualität: {ergebnis.get('gesamt_qualitaet', 0)}%"
            })

        finally:
            os.unlink(pdf_path)

    except Exception as exc:
        logger.exception("Analyse fehlgeschlagen für Plan %s", plan_id)
        update_plan(plan_id, {"verarbeitet": False, "gesamt_konfidenz": 0})
        await manager.broadcast(plan_id, {
            "typ": "fehler", "details": str(exc)
        })


@app.post("/api/plaene/{plan_id}/analyse", status_code=202)
async def start_analyse(
    plan_id: str,
    background_tasks: BackgroundTasks,
    firma: dict = Depends(get_current_firma),
):
    plan = get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")

    projekt = get_projekt(plan["projekt_id"])
    if not projekt or projekt["firma_id"] != firma["id"]:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diesen Plan")

    background_tasks.add_task(run_analysis, plan_id, firma["id"])
    return {"message": "Analyse gestartet", "plan_id": plan_id}


# ---------------------------------------------------------------------------
# Plan status & deletion
# ---------------------------------------------------------------------------


@app.get("/api/plaene/{plan_id}/status")
async def get_plan_status(plan_id: str, firma: dict = Depends(get_current_firma)):
    plan = get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")

    projekt = get_projekt(plan["projekt_id"])
    if not projekt or projekt["firma_id"] != firma["id"]:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diesen Plan")

    return {
        "verarbeitet": plan.get("verarbeitet", False),
        "gesamt_konfidenz": plan.get("gesamt_konfidenz", 0),
        "agent_log": plan.get("agent_log", {}),
    }


@app.delete("/api/plaene/{plan_id}", status_code=204)
async def delete_plan_route(
    plan_id: str,
    firma: dict = Depends(get_current_firma),
):
    plan = get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")

    projekt = get_projekt(plan["projekt_id"])
    if not projekt or projekt["firma_id"] != firma["id"]:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diesen Plan")

    delete_plan(plan_id)


# ---------------------------------------------------------------------------
# Results route
# ---------------------------------------------------------------------------


@app.get("/api/plaene/{plan_id}/ergebnis")
async def get_ergebnis(plan_id: str, firma: dict = Depends(get_current_firma)):
    plan = get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")

    projekt = get_projekt(plan["projekt_id"])
    if not projekt or projekt["firma_id"] != firma["id"]:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diesen Plan")

    elemente = get_elemente(plan_id)
    massen = get_massen(plan_id)

    # Separate elements by type
    raeume = [e for e in elemente if e.get("typ") == "raum"]
    fenster = [e for e in elemente if e.get("typ") == "fenster"]
    tueren = [e for e in elemente if e.get("typ") == "tuer"]

    return {
        "plan": plan,
        "raeume": raeume,
        "fenster": fenster,
        "tueren": tueren,
        "massen": massen,
    }


# ---------------------------------------------------------------------------
# Masse update (manual correction)
# ---------------------------------------------------------------------------


@app.put("/api/massen/{masse_id}")
async def update_masse_route(
    masse_id: str,
    body: MasseUpdate,
    firma: dict = Depends(get_current_firma),
):
    masse = get_masse(masse_id)
    if not masse:
        raise HTTPException(status_code=404, detail="Masseneintrag nicht gefunden")

    plan = get_plan(masse["plan_id"])
    if not plan:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")
    projekt = get_projekt(plan["projekt_id"])
    if not projekt or projekt["firma_id"] != firma["id"]:
        raise HTTPException(status_code=403, detail="Kein Zugriff")

    update_data: dict[str, Any] = {"manuell_korrigiert": True}

    if body.endsumme is not None:
        # Record correction before updating
        create_korrektur(
            firma_id=firma["id"],
            masse_id=masse_id,
            feld="endsumme",
            original_wert=str(masse.get("endsumme", "")),
            korrektur_wert=str(body.endsumme),
        )
        update_data["endsumme"] = body.endsumme

    if body.beschreibung is not None:
        update_data["beschreibung"] = body.beschreibung
    if body.einheit is not None:
        update_data["einheit"] = body.einheit

    updated = update_masse(masse_id, update_data)
    return updated


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------


@app.get("/api/plaene/{plan_id}/export")
async def export_excel(plan_id: str, firma: dict = Depends(get_current_firma)):
    plan = get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")

    projekt = get_projekt(plan["projekt_id"])
    if not projekt or projekt["firma_id"] != firma["id"]:
        raise HTTPException(status_code=403, detail="Kein Zugriff")

    massen = get_massen(plan_id)
    elemente = get_elemente(plan_id)

    # Extract actual data from elemente JSONB "daten" field for Excel
    raeume_data = []
    for e in elemente:
        if e.get("typ") == "raum":
            d = e.get("daten", {}) or {}
            raeume_data.append({
                "name": e.get("bezeichnung", d.get("name", "")),
                "bodenbelag": d.get("bodenbelag", ""),
                "flaeche": d.get("flaeche_m2", 0),
                "umfang": d.get("umfang_m", 0),
                "hoehe": d.get("hoehe_m", 0),
                "wandflaeche": d.get("wandflaeche_m2", 0),
            })

    fenster_data = []
    for e in elemente:
        if e.get("typ") == "fenster":
            d = e.get("daten", {}) or {}
            fenster_data.append({
                "bezeichnung": e.get("bezeichnung", d.get("bezeichnung", "")),
                "raum": d.get("raum_id", ""),
                "al_breite": d.get("al_breite_mm", 0),
                "al_hoehe": d.get("al_hoehe_mm", 0),
                "rb_breite": d.get("rb_breite_mm", 0),
                "rb_hoehe": d.get("rb_hoehe_mm", 0),
                "flaeche": d.get("flaeche_m2", 0),
            })

    # Massen already have correct column names
    massen_data = []
    for m in massen:
        massen_data.append({
            "pos_nr": m.get("pos_nr", ""),
            "beschreibung": m.get("beschreibung", ""),
            "raum": m.get("raum_referenz", ""),
            "berechnung": str(m.get("berechnung", "")),
            "endsumme": m.get("endsumme", 0),
            "einheit": m.get("einheit", ""),
            "gewerk": m.get("gewerk", ""),
            "konfidenz": m.get("konfidenz", 0),
        })

    from export.excel_export import generate_excel
    excel_bytes = generate_excel(
        massen=massen_data,
        raeume=raeume_data,
        fenster=fenster_data,
        projekt_name=projekt.get("name", "Export"),
    )

    filename = f"Massenermittlung_{plan.get('dateiname', 'export').replace('.pdf', '')}.xlsx"

    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# WebSocket for real-time analysis progress
# ---------------------------------------------------------------------------


@app.websocket("/ws/{plan_id}")
async def websocket_endpoint(websocket: WebSocket, plan_id: str):
    await manager.connect(plan_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"typ": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(plan_id, websocket)
    except Exception:
        manager.disconnect(plan_id, websocket)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "KI-Massenermittlung"}


# ---------------------------------------------------------------------------
# Frontend serving - serve index.html for root and HTML files
# ---------------------------------------------------------------------------


@app.get("/")
async def serve_index():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse("<h1>KI-Massenermittlung</h1><p>Frontend nicht gefunden.</p>")


@app.get("/{filename}.html")
async def serve_html(filename: str):
    html_path = FRONTEND_DIR / f"{filename}.html"
    if html_path.exists():
        return FileResponse(str(html_path))
    raise HTTPException(status_code=404, detail="Seite nicht gefunden")


# Mount static files last (CSS, JS)
if FRONTEND_DIR.is_dir():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")


# ---------------------------------------------------------------------------
# Run with uvicorn
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
