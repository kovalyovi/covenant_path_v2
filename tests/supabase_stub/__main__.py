"""Run the Supabase stub standalone: python -m tests.supabase_stub [--port 8903]."""

from __future__ import annotations

import argparse

import uvicorn

from tests.supabase_stub import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="in-memory Supabase stub")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8903)
    args = parser.parse_args()
    print(f"supabase stub: http://{args.host}:{args.port}")
    print("  point the broker at it: SUPABASE_URL=http://%s:%s "
          "SUPABASE_SERVICE_ROLE_KEY=test-key" % (args.host, args.port))
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
