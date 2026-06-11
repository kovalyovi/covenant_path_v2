"""In-memory Supabase (PostgREST + GoTrue) stub for the broker e2e suite.

Run standalone:  python -m tests.supabase_stub [--port 8903]
Embed in tests:  create_app() (optionally around your own Store for direct inspection).
"""

from tests.supabase_stub.app import create_app
from tests.supabase_stub.engine import Store

__all__ = ["Store", "create_app"]
