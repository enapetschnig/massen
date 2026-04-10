"""
Vercel Serverless Function - FastAPI Backend für KI-Massenermittlung.
Vercel routet alle /api/* Requests hierher.
"""

import sys
import os

# Backend-Module im Python-Path verfügbar machen
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'massenermittlung', 'backend'))

from main import app  # noqa: E402
