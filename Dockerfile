# Container for the Church-login auth broker (backend/auth_broker).
# Build context is the repo root so it can import lcr_client + backend.
# The broker uses the pure-requests Okta login (no browser), so a slim image is enough.
FROM python:3.12-slim

WORKDIR /app

# Only the deps the broker needs at runtime (skip Playwright browsers / Google libs).
# webauthn (py_webauthn) powers passwordless passkey login (server-side WebAuthn verify).
# CLIENT-07: exact pins (kept in sync with requirements.txt) instead of unbounded `>=`.
RUN pip install --no-cache-dir \
    "fastapi==0.136.3" "uvicorn==0.48.0" "requests==2.32.3" \
    "cryptography==48.0.0" "python-dotenv==1.0.1" "webauthn==2.7.1"

COPY lcr_client/ ./lcr_client/
COPY backend/ ./backend/
COPY covenant_path/ ./covenant_path/

ENV PORT=8787
EXPOSE 8787
# $PORT is provided by the host (Render/Fly/Railway); default 8787 for local runs.
CMD ["sh", "-c", "uvicorn backend.auth_broker.app:app --host 0.0.0.0 --port ${PORT:-8787}"]
