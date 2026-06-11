"""Run the mock identity + mock LCR hosts standalone (two uvicorn servers, one process).

  python -m tests.mock_lcr [--identity-port 8901] [--lcr-port 8902]

Point the real client/broker at them with:
  CP_TEST_MODE=1
  CP_TEST_IDENTITY_BASE=http://127.0.0.1:8901
  CP_TEST_LCR_BASE=http://127.0.0.1:8902
"""

from __future__ import annotations

import argparse
import threading

import uvicorn

from tests.mock_lcr import build_state, create_identity_app, create_lcr_app
from tests.mock_lcr.personas import MFA_CODE, PERSONAS


def main() -> int:
    parser = argparse.ArgumentParser(description="mock Church identity + LCR hosts")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--identity-port", type=int, default=8901)
    parser.add_argument("--lcr-port", type=int, default=8902)
    args = parser.parse_args()

    identity_base = f"http://{args.host}:{args.identity_port}"
    lcr_base = f"http://{args.host}:{args.lcr_port}"
    state = build_state(identity_base=identity_base, lcr_base=lcr_base)

    print(f"mock identity (Okta IDX): {identity_base}")
    print(f"mock LCR:                 {lcr_base}")
    print("personas (username / password / mfa):")
    for p in PERSONAS.values():
        print(f"  {p.username:<22} {p.password:<14} {p.mfa or '-':<8} {p.name} <{p.email}>")
    print(f"  user.locked            (any)          -        always-locked account")
    print(f"MFA test code: {MFA_CODE}")
    print('scenarios: POST /__test/control {"scenario": "healthy|lcr_5xx|identity_timeout|sso_reject"}')

    id_cfg = uvicorn.Config(create_identity_app(state), host=args.host,
                            port=args.identity_port, log_level="info")
    lcr_cfg = uvicorn.Config(create_lcr_app(state), host=args.host,
                             port=args.lcr_port, log_level="info")
    id_server = uvicorn.Server(id_cfg)
    lcr_server = uvicorn.Server(lcr_cfg)
    t = threading.Thread(target=id_server.run, daemon=True)
    t.start()
    lcr_server.run()  # foreground; Ctrl+C stops both (identity thread is a daemon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
