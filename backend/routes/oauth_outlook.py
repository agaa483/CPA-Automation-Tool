"""Browser-based Outlook OAuth flow.

Flow:
  1. Frontend calls GET /oauth/outlook/start?client_id=N → returns auth URL
  2. User is redirected there, signs into Microsoft, grants Mail.Read
  3. Microsoft redirects back to /oauth/outlook/callback with `code` and `state`
  4. We exchange for tokens, save under client_id (from state)
  5. Redirect back to frontend

Currently per-client. Later (Phase 3), we'll add a firm-level Outlook option
so a CPA firm connects once instead of per-client.
"""
from datetime import datetime, timedelta, timezone

import msal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from src import db
from src.config import (
    MS_CLIENT_ID,
    MS_CLIENT_SECRET,
    MS_TENANT_ID,
    MS_WEB_REDIRECT_URI,
    FRONTEND_URL,
)
from backend.deps import require_client_ownership

router = APIRouter(prefix="/oauth/outlook", tags=["oauth"])

SCOPES = ["Mail.Read"]  # msal adds offline_access automatically
_TENANT = MS_TENANT_ID or "common"
AUTHORITY = f"https://login.microsoftonline.com/{_TENANT}"


def _make_msal_app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=MS_CLIENT_ID,
        client_credential=MS_CLIENT_SECRET,
        authority=AUTHORITY,
    )


@router.get("/start")
def start(client_id: int = Depends(require_client_ownership)):
    app = _make_msal_app()
    url = app.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=MS_WEB_REDIRECT_URI,
        state=str(client_id),
    )
    return {"auth_url": url}


@router.get("/callback")
def callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
):
    if error or not code or not state:
        err = error_description or error or "missing code or state"
        return RedirectResponse(f"{FRONTEND_URL}/dashboard?outlook_error={err}")

    try:
        client_id = int(state)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid state: {state}")

    app = _make_msal_app()
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=SCOPES,
        redirect_uri=MS_WEB_REDIRECT_URI,
    )
    if "access_token" not in result:
        err = result.get("error_description") or result.get("error") or "token exchange failed"
        return RedirectResponse(
            f"{FRONTEND_URL}/dashboard/clients/{client_id}?outlook_error={err}"
        )

    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=int(result.get("expires_in", 3600))
    )

    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE clients
            SET outlook_access_token = ?,
                outlook_refresh_token = ?,
                outlook_token_expires_at = ?
            WHERE id = ?
            """,
            (
                result["access_token"],
                result.get("refresh_token"),
                expires_at.isoformat(),
                client_id,
            ),
        )

    return RedirectResponse(
        f"{FRONTEND_URL}/dashboard/clients/{client_id}?outlook_connected=1"
    )
