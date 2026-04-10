"""
Supabase client and CRUD helpers for KI-Massenermittlung.

All functions use the service-role key so RLS is bypassed on the server side.
Column names match the actual DB schema (German names).
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY: str = os.environ.get("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    import logging
    logging.warning("SUPABASE_URL or SUPABASE_SERVICE_KEY not set - Supabase client unavailable")
    supabase = None  # type: ignore
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ---------------------------------------------------------------------------
# App Config (secrets stored in Supabase instead of env vars)
# ---------------------------------------------------------------------------

_config_cache: dict = {}

def get_config(key: str, default: str = "") -> str:
    """Read a config value from app_config table (cached after first load)."""
    if key in _config_cache:
        return _config_cache[key]
    # First check env var (local dev), then Supabase (production)
    env_val = os.environ.get(key, "")
    if env_val:
        _config_cache[key] = env_val
        return env_val
    try:
        result = supabase.table("app_config").select("value").eq("key", key).execute()
        if result.data:
            _config_cache[key] = result.data[0]["value"]
            return _config_cache[key]
    except Exception:
        pass
    return default


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _insert(table: str, data: dict) -> dict:
    result = supabase.table(table).insert(data).execute()
    return result.data[0] if result.data else {}


def _select(
    table: str,
    filters: dict | None = None,
    columns: str = "*",
    order: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    query = supabase.table(table).select(columns)
    if filters:
        for key, value in filters.items():
            query = query.eq(key, value)
    if order:
        query = query.order(order, desc=True)
    if limit:
        query = query.limit(limit)
    result = query.execute()
    return result.data or []


def _select_one(table: str, record_id: str, columns: str = "*") -> dict | None:
    result = supabase.table(table).select(columns).eq("id", record_id).execute()
    return result.data[0] if result.data else None


def _update(table: str, record_id: str, data: dict) -> dict:
    result = supabase.table(table).update(data).eq("id", record_id).execute()
    return result.data[0] if result.data else {}


def _delete(table: str, record_id: str) -> bool:
    supabase.table(table).delete().eq("id", record_id).execute()
    return True


# ---------------------------------------------------------------------------
# FIRMEN  (id, name, email, passwort_hash, erstellt_am)
# ---------------------------------------------------------------------------

def create_firma(name: str, email: str, passwort_hash: str) -> dict:
    return _insert("firmen", {
        "name": name,
        "email": email,
        "passwort_hash": passwort_hash,
    })


def get_firma_by_email(email: str) -> dict | None:
    rows = _select("firmen", filters={"email": email})
    return rows[0] if rows else None


def get_firma(firma_id: str) -> dict | None:
    return _select_one("firmen", firma_id)


# ---------------------------------------------------------------------------
# PROJEKTE  (id, firma_id, name, adresse, gewerk, status, erstellt_am)
# ---------------------------------------------------------------------------

def create_projekt(firma_id: str, name: str, adresse: str = "", gewerk: str = "") -> dict:
    return _insert("projekte", {
        "firma_id": firma_id,
        "name": name,
        "adresse": adresse,
        "gewerk": gewerk,
    })


def get_projekte(firma_id: str) -> list[dict]:
    return _select("projekte", filters={"firma_id": firma_id}, order="erstellt_am")


def get_projekt(projekt_id: str) -> dict | None:
    return _select_one("projekte", projekt_id)


def update_projekt(projekt_id: str, data: dict) -> dict:
    return _update("projekte", projekt_id, data)


def delete_projekt(projekt_id: str) -> bool:
    return _delete("projekte", projekt_id)


# ---------------------------------------------------------------------------
# PLAENE  (id, projekt_id, dateiname, storage_path, planbuero, geschoss,
#           agent_log, gesamt_konfidenz, verarbeitet, hochgeladen_am)
# ---------------------------------------------------------------------------

def create_plan(projekt_id: str, dateiname: str, storage_path: str) -> dict:
    return _insert("plaene", {
        "projekt_id": projekt_id,
        "dateiname": dateiname,
        "storage_path": storage_path,
    })


def get_plaene(projekt_id: str) -> list[dict]:
    return _select("plaene", filters={"projekt_id": projekt_id}, order="hochgeladen_am")


def get_plan(plan_id: str) -> dict | None:
    return _select_one("plaene", plan_id)


def update_plan(plan_id: str, data: dict) -> dict:
    return _update("plaene", plan_id, data)


def delete_plan(plan_id: str) -> bool:
    return _delete("plaene", plan_id)


# ---------------------------------------------------------------------------
# ELEMENTE  (id, plan_id, typ, bezeichnung, daten, konfidenz,
#             manuell_korrigiert, lernregel_angewendet)
# ---------------------------------------------------------------------------

def create_element(plan_id: str, typ: str, bezeichnung: str = "",
                   daten: dict | None = None, konfidenz: int = 0) -> dict:
    data: dict[str, Any] = {
        "plan_id": plan_id,
        "typ": typ,
        "bezeichnung": bezeichnung,
        "konfidenz": konfidenz,
    }
    if daten is not None:
        data["daten"] = daten
    return _insert("elemente", data)


def get_elemente(plan_id: str, typ: str | None = None) -> list[dict]:
    filters: dict[str, Any] = {"plan_id": plan_id}
    if typ:
        filters["typ"] = typ
    return _select("elemente", filters=filters)


def get_element(element_id: str) -> dict | None:
    return _select_one("elemente", element_id)


def update_element(element_id: str, data: dict) -> dict:
    return _update("elemente", element_id, data)


# ---------------------------------------------------------------------------
# MASSEN  (id, plan_id, pos_nr, beschreibung, gewerk, raum_referenz,
#           berechnung, endsumme, einheit, konfidenz, manuell_korrigiert)
# ---------------------------------------------------------------------------

def create_masse(plan_id: str, pos_nr: str, beschreibung: str, gewerk: str,
                 raum_referenz: str, berechnung: Any, endsumme: float,
                 einheit: str, konfidenz: int = 0) -> dict:
    return _insert("massen", {
        "plan_id": plan_id,
        "pos_nr": pos_nr,
        "beschreibung": beschreibung,
        "gewerk": gewerk,
        "raum_referenz": raum_referenz,
        "berechnung": berechnung,
        "endsumme": endsumme,
        "einheit": einheit,
        "konfidenz": konfidenz,
    })


def get_massen(plan_id: str, gewerk: str | None = None) -> list[dict]:
    filters: dict[str, Any] = {"plan_id": plan_id}
    if gewerk:
        filters["gewerk"] = gewerk
    return _select("massen", filters=filters)


def get_masse(masse_id: str) -> dict | None:
    return _select_one("massen", masse_id)


def update_masse(masse_id: str, data: dict) -> dict:
    return _update("massen", masse_id, data)


# ---------------------------------------------------------------------------
# LERNREGELN  (id, firma_id, planbuero, gueltig_fuer, agent, beschreibung,
#               korrektur_json, bestaetigt, aktiv, erstellt_am)
# ---------------------------------------------------------------------------

def create_lernregel(firma_id: str, planbuero: str = "", gueltig_fuer: str = "",
                     agent: str = "", beschreibung: str = "",
                     korrektur_json: dict | None = None) -> dict:
    return _insert("lernregeln", {
        "firma_id": firma_id,
        "planbuero": planbuero,
        "gueltig_fuer": gueltig_fuer,
        "agent": agent,
        "beschreibung": beschreibung,
        "korrektur_json": korrektur_json or {},
    })


def get_lernregeln(firma_id: str, planbuero: str | None = None) -> list[dict]:
    filters: dict[str, Any] = {"firma_id": firma_id, "aktiv": True}
    if planbuero:
        filters["planbuero"] = planbuero
    return _select("lernregeln", filters=filters, order="erstellt_am")


def update_lernregel(regel_id: str, data: dict) -> dict:
    return _update("lernregeln", regel_id, data)


# ---------------------------------------------------------------------------
# KORREKTUREN  (id, firma_id, masse_id, planbuero, feld, original_wert,
#                korrektur_wert, in_lernregel_umgewandelt, erstellt_am)
# ---------------------------------------------------------------------------

def create_korrektur(firma_id: str, masse_id: str, feld: str = "",
                     original_wert: str = "", korrektur_wert: str = "",
                     planbuero: str = "") -> dict:
    return _insert("korrekturen", {
        "firma_id": firma_id,
        "masse_id": masse_id,
        "feld": feld,
        "original_wert": original_wert,
        "korrektur_wert": korrektur_wert,
        "planbuero": planbuero,
    })


def get_korrekturen(firma_id: str | None = None, masse_id: str | None = None) -> list[dict]:
    filters: dict[str, Any] = {}
    if firma_id:
        filters["firma_id"] = firma_id
    if masse_id:
        filters["masse_id"] = masse_id
    return _select("korrekturen", filters=filters, order="erstellt_am")


# ---------------------------------------------------------------------------
# STORAGE helpers
# ---------------------------------------------------------------------------

def upload_file(bucket: str, path: str, file_bytes: bytes,
                content_type: str = "application/pdf") -> str:
    supabase.storage.from_(bucket).upload(path, file_bytes, {"content-type": content_type})
    return path


def get_file_url(bucket: str, path: str, expires_in: int = 3600) -> str:
    result = supabase.storage.from_(bucket).create_signed_url(path, expires_in)
    return result.get("signedURL", "") if isinstance(result, dict) else ""


def download_file(bucket: str, path: str) -> bytes:
    return supabase.storage.from_(bucket).download(path)
