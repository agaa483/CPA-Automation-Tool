"""Chrome extension endpoints.

Two-part auth model:
- POST /extension/token — called by frontend (Clerk JWT) to mint a long-lived
  extension token bound to this firm.
- POST /extension/categorize — called by the extension (X-Extension-Token header)
  to categorize a batch of txns pulled from QBO's DOM.
"""
import secrets
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from src import db, auditor
from backend.deps import get_firm_id


router = APIRouter(prefix="/extension", tags=["extension"])


# ─── DB bootstrap ──────────────────────────────────────────────────────────

def _ensure_tokens_table() -> None:
    with db.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extension_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                firm_id INTEGER NOT NULL REFERENCES firms(id),
                clerk_user_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP,
                revoked INTEGER NOT NULL DEFAULT 0
            )
            """
        )


# ─── Models ────────────────────────────────────────────────────────────────

class TokenIssueResponse(BaseModel):
    token: str
    note: str


class ExtTxnIn(BaseModel):
    dom_id: str                    # Extension's own reference (e.g. row DOM id)
    vendor: Optional[str] = None
    amount: float
    date: Optional[str] = None     # ISO date string, best-effort
    description: Optional[str] = None
    current_category: Optional[str] = None


class ExtSuggestion(BaseModel):
    dom_id: str
    suggested_category: Optional[str]
    suggested_payee: Optional[str] = None
    suggested_payor: Optional[str] = None
    reasoning: str
    confidence: str                # "high" | "medium" | "low"
    error: Optional[str] = None


class CategorizeRequest(BaseModel):
    client_id: int
    txns: list[ExtTxnIn]


class CategorizeResponse(BaseModel):
    suggestions: list[ExtSuggestion]


# ─── Token issue (Clerk-authenticated, called from web app) ────────────────

@router.post("/token", response_model=TokenIssueResponse)
def issue_token(firm_id: int = Depends(get_firm_id)):
    _ensure_tokens_table()

    # Simple opaque token — 32 bytes URL-safe. Not a JWT; just a lookup key.
    token = "qbaext_" + secrets.token_urlsafe(32)

    # Pull the current user_id out of the firm row so we can associate the token.
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT clerk_user_id FROM firms WHERE id = ?", (firm_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Firm not found")
        user_id = row["clerk_user_id"]

        conn.execute(
            "INSERT INTO extension_tokens (token, firm_id, clerk_user_id) VALUES (?, ?, ?)",
            (token, firm_id, user_id),
        )

    return TokenIssueResponse(
        token=token,
        note="Store this token in the extension's Options page. It won't be shown again.",
    )


# ─── Categorize (extension-authenticated) ──────────────────────────────────

def _resolve_ext_token(x_extension_token: Optional[str] = Header(None)) -> int:
    """Look up firm_id from the extension token. Returns firm_id or 401."""
    if not x_extension_token:
        raise HTTPException(status_code=401, detail="Missing X-Extension-Token header")
    _ensure_tokens_table()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT firm_id, revoked FROM extension_tokens WHERE token = ?",
            (x_extension_token,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid extension token")
    if row["revoked"]:
        raise HTTPException(status_code=401, detail="Extension token has been revoked")

    # Touch last_used_at
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE extension_tokens SET last_used_at = CURRENT_TIMESTAMP WHERE token = ?",
            (x_extension_token,),
        )
    return row["firm_id"]


class ExtClient(BaseModel):
    id: int
    firm_name: str


@router.get("/clients", response_model=list[ExtClient])
def list_clients_for_extension(firm_id: int = Depends(_resolve_ext_token)):
    """List clients for the firm identified by the extension token.
    Lets the extension render a dropdown so the user doesn't have to memorize IDs.
    """
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, firm_name FROM clients WHERE firm_id = ? ORDER BY id",
            (firm_id,),
        ).fetchall()
    return [ExtClient(id=r["id"], firm_name=r["firm_name"]) for r in rows]


@router.post("/categorize", response_model=CategorizeResponse)
def categorize(
    payload: CategorizeRequest,
    firm_id: int = Depends(_resolve_ext_token),
):
    # Verify client belongs to this firm.
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM clients WHERE id = ? AND firm_id = ?",
            (payload.client_id, firm_id),
        ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Client {payload.client_id} not found in this firm",
        )

    suggestions: list[ExtSuggestion] = []

    for t in payload.txns:
        # Reuse the suggest_category pipeline (best fit for "give me a category
        # for this row" — same LLM + email pipeline as the Excel workflow).
        txn_dict = {
            "txn_date": _parse_date(t.date),
            "amount": abs(t.amount),
            "vendor_raw": t.vendor or t.description,
            "counterparty": t.vendor,
            "direction": "out" if t.amount < 0 else "in",
        }
        try:
            decision = auditor.suggest_category(payload.client_id, txn_dict)
        except Exception as e:
            suggestions.append(ExtSuggestion(
                dom_id=t.dom_id,
                suggested_category=None,
                reasoning="",
                confidence="low",
                error=f"{type(e).__name__}: {e}",
            ))
            continue

        # is_correct=True from suggest_category means "I don't know" (fallback).
        # is_correct=False + corrected_category means "here's my suggestion".
        if decision.is_correct:
            suggestions.append(ExtSuggestion(
                dom_id=t.dom_id,
                suggested_category=None,
                suggested_payee=decision.suggested_payee,
                suggested_payor=decision.suggested_payor,
                reasoning=decision.reasoning,
                confidence="low",
            ))
        else:
            confidence = "high" if decision.supporting_email_ids else "medium"
            suggestions.append(ExtSuggestion(
                dom_id=t.dom_id,
                suggested_category=decision.corrected_category,
                suggested_payee=decision.suggested_payee,
                suggested_payor=decision.suggested_payor,
                reasoning=decision.reasoning,
                confidence=confidence,
            ))

    return CategorizeResponse(suggestions=suggestions)


def _parse_date(s: Optional[str]) -> date:
    if not s:
        return date.today()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip()[:10], fmt).date()
        except ValueError:
            continue
    return date.today()
