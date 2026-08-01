"""Browser-based QBO OAuth flow.

Flow:
  1. Frontend calls POST /oauth/qbo/start?client_id=N → returns auth URL
  2. User is redirected there (or opens in new tab), signs into Intuit, picks company
  3. Intuit redirects back to /oauth/qbo/callback with `code`, `realmId`, `state`
  4. We exchange the code for tokens, save them under the client_id (from state)
  5. Redirect the user back to the frontend with success/error indication
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes

from src import db
from src.config import (
    QBO_CLIENT_ID,
    QBO_CLIENT_SECRET,
    QBO_ENVIRONMENT,
    QBO_WEB_REDIRECT_URI,
    FRONTEND_URL,
)
from backend.deps import require_client_ownership

router = APIRouter(prefix="/oauth/qbo", tags=["oauth"])


def _make_auth_client() -> AuthClient:
    return AuthClient(
        client_id=QBO_CLIENT_ID,
        client_secret=QBO_CLIENT_SECRET,
        redirect_uri=QBO_WEB_REDIRECT_URI,
        environment=QBO_ENVIRONMENT,
    )


@router.get("/start")
def start(client_id: int = Depends(require_client_ownership)):
    """Generate the authorization URL. Frontend redirects the user to it."""
    auth_client = _make_auth_client()
    # `state` carries our client_id through the round trip so we know which row
    # to save tokens under when the callback fires.
    url = auth_client.get_authorization_url([Scopes.ACCOUNTING], state_token=str(client_id))
    return {"auth_url": url}


@router.get("/callback")
def callback(
    code: str = Query(...),
    realmId: str = Query(...),
    state: str = Query(...),
):
    """Intuit redirects here after the user authorizes."""
    try:
        client_id = int(state)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid state: {state}")

    auth_client = _make_auth_client()
    try:
        auth_client.get_bearer_token(code, realm_id=realmId)
    except Exception as e:
        return RedirectResponse(
            f"{FRONTEND_URL}/dashboard/clients/{client_id}?qbo_error={e}"
        )

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=auth_client.expires_in)

    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE clients
            SET qbo_realm_id = ?,
                qbo_access_token = ?,
                qbo_refresh_token = ?,
                qbo_token_expires_at = ?
            WHERE id = ?
            """,
            (
                realmId,
                auth_client.access_token,
                auth_client.refresh_token,
                expires_at.isoformat(),
                client_id,
            ),
        )

    return RedirectResponse(f"{FRONTEND_URL}/dashboard/clients/{client_id}?qbo_connected=1")
