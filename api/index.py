"""
Vercel Serverless - Standalone FastAPI Backend.
No imports from massenermittlung/backend to avoid path issues.
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from fastapi import FastAPI, HTTPException, Depends, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from supabase import create_client

# ---------------------------------------------------------------------------
# Supabase Client
# ---------------------------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", os.environ.get("SUPABASE_KEY", ""))

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# JWT Secret from Supabase config table
JWT_SECRET = "massenermittlung-jwt-secret-2025"
try:
    if supabase:
        res = supabase.table("app_config").select("value").eq("key", "JWT_SECRET").execute()
        if res.data:
            JWT_SECRET = res.data[0]["value"]
except Exception:
    pass

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(title="KI-Massenermittlung API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()

# ---------------------------------------------------------------------------
# Models
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

class MasseUpdate(BaseModel):
    endsumme: Optional[float] = None
    beschreibung: Optional[str] = None
    einheit: Optional[str] = None

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def _hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def _check_pw(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())

def _make_token(firma_id: str, email: str) -> str:
    return jwt.encode(
        {"sub": firma_id, "email": email,
         "exp": datetime.now(timezone.utc) + timedelta(hours=24)},
        JWT_SECRET, algorithm="HS256",
    )

async def get_firma(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(401, "Ungültiger Token")
    fid = payload.get("sub")
    res = supabase.table("firmen").select("*").eq("id", fid).execute()
    if not res.data:
        raise HTTPException(401, "Firma nicht gefunden")
    return res.data[0]

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "supabase": "connected" if supabase else "not configured",
        "url_set": bool(SUPABASE_URL),
        "key_set": bool(SUPABASE_KEY),
    }

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.post("/api/auth/register", status_code=201)
async def register(body: RegisterRequest):
    if not supabase:
        raise HTTPException(500, "Supabase nicht konfiguriert")
    existing = supabase.table("firmen").select("id").eq("email", body.email).execute()
    if existing.data:
        raise HTTPException(409, "E-Mail bereits registriert")
    hashed = _hash_pw(body.passwort)
    res = supabase.table("firmen").insert({
        "name": body.name, "email": body.email, "passwort_hash": hashed
    }).execute()
    firma = res.data[0]
    token = _make_token(firma["id"], firma["email"])
    return {"token": token, "firma": {"id": firma["id"], "name": firma["name"], "email": firma["email"]}}

@app.post("/api/auth/login")
async def login(body: LoginRequest):
    if not supabase:
        raise HTTPException(500, "Supabase nicht konfiguriert")
    res = supabase.table("firmen").select("*").eq("email", body.email).execute()
    if not res.data or not _check_pw(body.passwort, res.data[0].get("passwort_hash", "")):
        raise HTTPException(401, "Ungültige Anmeldedaten")
    firma = res.data[0]
    token = _make_token(firma["id"], firma["email"])
    return {"token": token, "firma": {"id": firma["id"], "name": firma["name"], "email": firma["email"]}}

# ---------------------------------------------------------------------------
# Projekte
# ---------------------------------------------------------------------------
@app.get("/api/projekte")
async def list_projekte(firma: dict = Depends(get_firma)):
    res = supabase.table("projekte").select("*").eq("firma_id", firma["id"]).order("erstellt_am", desc=True).execute()
    projekte = res.data or []
    for p in projekte:
        plans = supabase.table("plaene").select("id").eq("projekt_id", p["id"]).execute()
        p["plan_count"] = len(plans.data) if plans.data else 0
    return projekte

@app.post("/api/projekte", status_code=201)
async def create_projekt(body: ProjektCreate, firma: dict = Depends(get_firma)):
    res = supabase.table("projekte").insert({
        "firma_id": firma["id"], "name": body.name,
        "adresse": body.adresse, "gewerk": body.gewerk,
    }).execute()
    return res.data[0]

@app.get("/api/projekte/{pid}")
async def get_projekt(pid: str, firma: dict = Depends(get_firma)):
    res = supabase.table("projekte").select("*").eq("id", pid).execute()
    if not res.data:
        raise HTTPException(404, "Projekt nicht gefunden")
    p = res.data[0]
    if p["firma_id"] != firma["id"]:
        raise HTTPException(403, "Kein Zugriff")
    plans = supabase.table("plaene").select("*").eq("projekt_id", pid).order("hochgeladen_am", desc=True).execute()
    p["plaene"] = plans.data or []
    return p

@app.delete("/api/projekte/{pid}", status_code=204)
async def delete_projekt(pid: str, firma: dict = Depends(get_firma)):
    res = supabase.table("projekte").select("firma_id").eq("id", pid).execute()
    if not res.data or res.data[0]["firma_id"] != firma["id"]:
        raise HTTPException(403, "Kein Zugriff")
    supabase.table("projekte").delete().eq("id", pid).execute()

# ---------------------------------------------------------------------------
# Pläne
# ---------------------------------------------------------------------------
@app.post("/api/projekte/{pid}/upload", status_code=201)
async def upload_pdf(pid: str, file: UploadFile = File(...), firma: dict = Depends(get_firma)):
    res = supabase.table("projekte").select("firma_id").eq("id", pid).execute()
    if not res.data or res.data[0]["firma_id"] != firma["id"]:
        raise HTTPException(403, "Kein Zugriff")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Nur PDF-Dateien")
    file_bytes = await file.read()
    import uuid
    storage_path = f"{firma['id']}/{pid}/{uuid.uuid4().hex}_{file.filename}"
    try:
        supabase.storage.from_("plaene").upload(storage_path, file_bytes, {"content-type": "application/pdf"})
    except Exception as e:
        raise HTTPException(500, f"Upload fehlgeschlagen: {e}")
    plan = supabase.table("plaene").insert({
        "projekt_id": pid, "dateiname": file.filename, "storage_path": storage_path,
    }).execute()
    return plan.data[0]

@app.get("/api/plaene/{plan_id}/status")
async def plan_status(plan_id: str, firma: dict = Depends(get_firma)):
    res = supabase.table("plaene").select("*").eq("id", plan_id).execute()
    if not res.data:
        raise HTTPException(404)
    plan = res.data[0]
    return {"verarbeitet": plan.get("verarbeitet", False), "gesamt_konfidenz": plan.get("gesamt_konfidenz")}

@app.get("/api/plaene/{plan_id}/ergebnis")
async def get_ergebnis(plan_id: str, firma: dict = Depends(get_firma)):
    plan_res = supabase.table("plaene").select("*").eq("id", plan_id).execute()
    if not plan_res.data:
        raise HTTPException(404)
    plan = plan_res.data[0]
    elemente = supabase.table("elemente").select("*").eq("plan_id", plan_id).execute().data or []
    massen = supabase.table("massen").select("*").eq("plan_id", plan_id).execute().data or []
    return {
        "plan": plan,
        "raeume": [e for e in elemente if e.get("typ") == "raum"],
        "fenster": [e for e in elemente if e.get("typ") == "fenster"],
        "tueren": [e for e in elemente if e.get("typ") == "tuer"],
        "massen": massen,
    }

@app.delete("/api/plaene/{plan_id}", status_code=204)
async def delete_plan(plan_id: str, firma: dict = Depends(get_firma)):
    supabase.table("plaene").delete().eq("id", plan_id).execute()

# ---------------------------------------------------------------------------
# Massen update
# ---------------------------------------------------------------------------
@app.put("/api/massen/{mid}")
async def update_masse(mid: str, body: MasseUpdate, firma: dict = Depends(get_firma)):
    data = {"manuell_korrigiert": True}
    if body.endsumme is not None:
        data["endsumme"] = body.endsumme
    if body.beschreibung is not None:
        data["beschreibung"] = body.beschreibung
    if body.einheit is not None:
        data["einheit"] = body.einheit
    res = supabase.table("massen").update(data).eq("id", mid).execute()
    return res.data[0] if res.data else {}
