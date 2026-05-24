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
QBO_REDIRECT_URI = _require("QBO_REDIRECT_URI")
QBO_ENVIRONMENT = _require("QBO_ENVIRONMENT")

MS_CLIENT_ID = _require("MS_CLIENT_ID")
MS_CLIENT_SECRET = _require("MS_CLIENT_SECRET")
MS_TENANT_ID = _require("MS_TENANT_ID")
MS_REDIRECT_URI = _require("MS_REDIRECT_URI")

ANTHROPIC_API_KEY = _require("ANTHROPIC_API_KEY")
