"""
Massenermittlung AI Agents
Agentenbasiertes System zur automatischen Massenermittlung aus Bauplänen.
"""

import os
import sys

# Ensure db module is importable
_backend_dir = os.path.join(os.path.dirname(__file__), '..')
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


def get_anthropic_api_key() -> str:
    """Get Anthropic API key from env var (local) or Supabase config (production)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    try:
        from db.supabase_client import get_config
        return get_config("ANTHROPIC_API_KEY", "")
    except Exception:
        return ""


from .parser_agent import run as parser_run
from .geometrie_agent import run as geometrie_run
from .kalkulations_agent import run as kalkulations_run
from .kritik_agent import run as kritik_run
from .lern_agent import run as lern_run

__all__ = [
    "get_anthropic_api_key",
    "parser_run",
    "geometrie_run",
    "kalkulations_run",
    "kritik_run",
    "lern_run",
]
