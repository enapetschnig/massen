"""
Vercel Serverless Function - FastAPI Backend.
"""
from __future__ import annotations

import sys
import os

# Add backend to path
_dir = os.path.dirname(os.path.abspath(__file__))
_backend = os.path.join(_dir, '..', 'massenermittlung', 'backend')
if _backend not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend))

# Force dotenv to not crash if .env missing
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "")

from main import app  # noqa: E402

# Vercel needs this named 'app' for ASGI
handler = app
