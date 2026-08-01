"""FastAPI backend for QB Auditor web app.

Thin HTTP layer over the existing `src/` modules. Everything the CLI can do
is exposed as REST endpoints here so the Next.js frontend can call them.
"""
import sys
from pathlib import Path

# Add project root to Python path so `from src import ...` works from this file.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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
)

app = FastAPI(
    title="QB Auditor API",
    description="Backend for the QB Auditor web app.",
    version="0.1.0",
)

app.include_router(clients.router)
app.include_router(categories.router)
app.include_router(receipt_senders.router)
app.include_router(audits.router)
app.include_router(excel.router)
app.include_router(oauth_qbo.router)
app.include_router(oauth_outlook.router)

# CORS — allow the Next.js frontend to call us. In production, lock this to
# your Vercel domain via an env var.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Sanity check: is the backend up?"""
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "QB Auditor API — see /docs for OpenAPI browser"}
