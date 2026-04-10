"""
Vercel Serverless Function - FastAPI Backend.
Returns actual errors so we can debug.
"""
from __future__ import annotations

import sys
import os
import traceback

# Add backend to path
_dir = os.path.dirname(os.path.abspath(__file__))
_backend = os.path.abspath(os.path.join(_dir, '..', 'massenermittlung', 'backend'))
sys.path.insert(0, _backend)

try:
    from main import app
except Exception as e:
    # If main.py fails to import, create a minimal app that shows the error
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    error_msg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"

    @app.get("/api/{path:path}")
    @app.post("/api/{path:path}")
    @app.put("/api/{path:path}")
    @app.delete("/api/{path:path}")
    async def error_handler(path: str):
        return {"error": "Backend konnte nicht geladen werden", "details": error_msg}
