"""FastAPI backend for QB Auditor web app.

Thin HTTP layer over the existing `src/` modules. Everything the CLI can do
is exposed as REST endpoints here so the Next.js frontend can call them.
"""
import sys
from pathlib import Path

# Add project root to Python path so `from src import ...` works from this file.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes import (
    clients,
    categories,
    receipt_senders,
    audits,
    excel,
    oauth_qbo,
    oauth_outlook,
    extension,
)

app = FastAPI(
    title="QB Auditor API",
    description="Backend for the QB Auditor web app.",
    version="0.1.0",
)

# CORS — allow local dev + any configured frontend URL. Also allow any *.vercel.app
# preview deploy so Vercel PR previews work.
_frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")
_allowed_origins = ["http://localhost:3000"]
if _frontend_url:
    _allowed_origins.append(_frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clients.router)
app.include_router(categories.router)
app.include_router(receipt_senders.router)
app.include_router(audits.router)
app.include_router(excel.router)
app.include_router(oauth_qbo.router)
app.include_router(oauth_outlook.router)
app.include_router(extension.router)


@app.get("/health")
def health():
    """Sanity check: is the backend up?"""
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "QB Auditor API — see /docs for OpenAPI browser"}
