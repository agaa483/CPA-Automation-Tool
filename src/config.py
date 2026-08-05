import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


DB_PATH = os.getenv("DB_PATH", "data/app.db")

QBO_CLIENT_ID = _require("QBO_CLIENT_ID")
QBO_CLIENT_SECRET = _require("QBO_CLIENT_SECRET")
QBO_ENVIRONMENT = _require("QBO_ENVIRONMENT")
# Legacy CLI-only OAuth redirect (localhost:8000). Optional — web app uses
# QBO_WEB_REDIRECT_URI derived from BACKEND_URL.
QBO_REDIRECT_URI = os.getenv("QBO_REDIRECT_URI", "")

MS_CLIENT_ID = _require("MS_CLIENT_ID")
MS_CLIENT_SECRET = _require("MS_CLIENT_SECRET")
MS_TENANT_ID = _require("MS_TENANT_ID")
MS_REDIRECT_URI = os.getenv("MS_REDIRECT_URI", "")

ANTHROPIC_API_KEY = _require("ANTHROPIC_API_KEY").strip()

# Where the backend is reachable (used to construct OAuth callback URLs).
# Local dev: http://localhost:8001. Prod: https://api.your-domain.com.
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
# Where the frontend is reachable (redirect target after OAuth completes).
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Web OAuth callback URIs. Register these in the Intuit + Microsoft dev portals.
QBO_WEB_REDIRECT_URI = f"{BACKEND_URL}/oauth/qbo/callback"
MS_WEB_REDIRECT_URI = f"{BACKEND_URL}/oauth/outlook/callback"

# Clerk auth. Publishable key derives the JWKS URL for JWT verification.
CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "")


def _clerk_frontend_api() -> str | None:
    """Decode the frontend API host from the Clerk publishable key.
    e.g. 'pk_test_Z3JhdGVmdWwtZmlzaC0zLmNsZXJrLmFjY291bnRzLmRldiQ' -> 'grateful-fish-3.clerk.accounts.dev'
    """
    import base64
    if not CLERK_PUBLISHABLE_KEY:
        return None
    try:
        encoded = CLERK_PUBLISHABLE_KEY.split("_")[-1]
        # add padding
        padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
        return decoded.rstrip("$").strip()
    except Exception:
        return None


CLERK_FRONTEND_API = _clerk_frontend_api()
CLERK_JWKS_URL = f"https://{CLERK_FRONTEND_API}/.well-known/jwks.json" if CLERK_FRONTEND_API else None
CLERK_ISSUER = f"https://{CLERK_FRONTEND_API}" if CLERK_FRONTEND_API else None

# Optional: scope all receipt searches to a single sender address.
# When set, the auditor pre-fetches every email from this sender within a date
# window of the transaction and hands the full batch to Claude in one call.
RECEIPTS_FROM = (os.getenv("RECEIPTS_FROM") or "").strip() or None
