import threading
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import msal
import requests

from . import db
from .config import (
    MS_CLIENT_ID,
    MS_CLIENT_SECRET,
    MS_REDIRECT_URI,
    MS_TENANT_ID,
)


REDIRECT_HOST = "localhost"
REDIRECT_PORT = 8000
OAUTH_TIMEOUT_SECONDS = 300
REFRESH_BUFFER_SECONDS = 300

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]  # msal automatically adds offline_access for refresh tokens

_TENANT = MS_TENANT_ID or "common"
AUTHORITY = f"https://login.microsoftonline.com/{_TENANT}"


def _make_msal_app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=MS_CLIENT_ID,
        client_credential=MS_CLIENT_SECRET,
        authority=AUTHORITY,
    )


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]
        error_desc = params.get("error_description", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if error or not code:
            self.wfile.write(b"<h1>Authorization failed.</h1> You can close this tab.")
            _CallbackHandler.result = {"error": error_desc or error or "missing code"}
        else:
            self.wfile.write(b"<h1>Authorization complete.</h1> You can close this tab.")
            _CallbackHandler.result = {"code": code}

    def log_message(self, format, *args):  # noqa: A002
        return


def start_auth_flow(client_id: int) -> None:
    app = _make_msal_app()
    auth_url = app.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=MS_REDIRECT_URI,
    )

    _CallbackHandler.result = {}
    server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _CallbackHandler)

    def _serve():
        while not _CallbackHandler.result:
            server.handle_request()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()

    webbrowser.open(auth_url)
    thread.join(timeout=OAUTH_TIMEOUT_SECONDS)
    server.server_close()

    result = _CallbackHandler.result
    if not result:
        raise RuntimeError("OAuth flow timed out waiting for redirect.")
    if "error" in result:
        raise RuntimeError(f"OAuth flow failed: {result['error']}")

    token_result = app.acquire_token_by_authorization_code(
        code=result["code"],
        scopes=SCOPES,
        redirect_uri=MS_REDIRECT_URI,
    )
    if "access_token" not in token_result:
        raise RuntimeError(
            f"Token exchange failed: {token_result.get('error_description') or token_result}"
        )

    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=int(token_result.get("expires_in", 3600))
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
                token_result["access_token"],
                token_result.get("refresh_token"),
                expires_at.isoformat(),
                client_id,
            ),
        )

    print(f"Connected Outlook for client {client_id}.")


def refresh_token_if_needed(client_id: int) -> str:
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT outlook_access_token, outlook_refresh_token, outlook_token_expires_at
            FROM clients WHERE id = ?
            """,
            (client_id,),
        ).fetchone()

    if not row or not row["outlook_refresh_token"]:
        raise RuntimeError(
            f"Client {client_id} has no Outlook tokens. Run outlook-connect first."
        )

    expires_at = datetime.fromisoformat(row["outlook_token_expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at - datetime.now(timezone.utc) > timedelta(seconds=REFRESH_BUFFER_SECONDS):
        return row["outlook_access_token"]

    app = _make_msal_app()
    token_result = app.acquire_token_by_refresh_token(
        refresh_token=row["outlook_refresh_token"],
        scopes=SCOPES,
    )
    if "access_token" not in token_result:
        raise RuntimeError(
            f"Token refresh failed: {token_result.get('error_description') or token_result}"
        )

    new_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=int(token_result.get("expires_in", 3600))
    )
    new_refresh = token_result.get("refresh_token") or row["outlook_refresh_token"]

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
                token_result["access_token"],
                new_refresh,
                new_expires_at.isoformat(),
                client_id,
            ),
        )

    return token_result["access_token"]


def fetch_from_sender(
    client_id: int,
    sender: str,
    centered_date: date,  # kept in signature for backwards-compat; not used
    window_days: int = 30,
    max_results: int = 50,
) -> list[dict]:
    """Pull every email from `sender` received in the last `window_days` from now.

    Anchored to the current time rather than the txn date because CPAs typically
    bulk-forward historical receipts in one dump — anchoring to the txn date
    would miss all those forwards for older txns.
    """
    access_token = refresh_token_if_needed(client_id)
    headers = {"Authorization": f"Bearer {access_token}"}

    sender_safe = sender.replace("'", "").strip()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=window_days)
    window_end = now + timedelta(days=1)  # future buffer for clock skew

    page_size = 100
    params = {
        "$filter": f"from/emailAddress/address eq '{sender_safe}'",
        "$top": page_size,
        "$select": "id,subject,from,receivedDateTime,bodyPreview,body",
    }
    url = f"{GRAPH_BASE}/me/messages"

    # Graph rejects $orderby combined with from/emailAddress/address as "too
    # complex", so we can't short-circuit on date order. Pull pages until either
    # we exhaust results or hit a safety cap, then filter + sort client-side.
    MAX_PAGES = 10  # 10 * 100 = 1000 emails from this sender max.
    raw: list[dict] = []
    for _ in range(MAX_PAGES):
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Graph fetch failed ({resp.status_code}): {resp.text}")
        body = resp.json()
        raw.extend(body.get("value", []))

        next_link = body.get("@odata.nextLink")
        if not next_link:
            break
        url = next_link
        params = None

    # Filter to date window + shape the dicts.
    in_window: list[dict] = []
    for m in raw:
        received_str = m.get("receivedDateTime")
        if not received_str:
            continue
        received = datetime.fromisoformat(received_str.replace("Z", "+00:00"))
        if not (window_start <= received <= window_end):
            continue
        from_field = m.get("from") or {}
        sender_addr = (from_field.get("emailAddress") or {}).get("address")

        # Prefer full body text over preview. Body arrives as either plain text or
        # HTML; strip tags crudely so Claude sees clean text. Cap length so prompts
        # don't explode on huge threads.
        body_obj = m.get("body") or {}
        body_content = body_obj.get("content") or ""
        if body_obj.get("contentType", "").lower() == "html":
            import re
            body_content = re.sub(r"<[^>]+>", " ", body_content)
            body_content = re.sub(r"\s+", " ", body_content).strip()
        body_content = (body_content[:8000] if body_content else m.get("bodyPreview") or "")

        in_window.append({
            "id": m.get("id"),
            "subject": m.get("subject"),
            "sender": sender_addr,
            "received_at": received_str,
            "body_preview": body_content,
        })

    # Newest-first, then trim to max_results.
    in_window.sort(key=lambda e: e["received_at"], reverse=True)
    return in_window[:max_results]


def search_by_query(
    client_id: int,
    query: str,
    centered_date: date,
    window_days: int = 14,
    max_results: int = 10,
) -> list[dict]:
    """Free-form Graph $search query, date-windowed around centered_date.
    Used by the auditor's agentic tool loop so Claude can phrase its own searches."""
    access_token = refresh_token_if_needed(client_id)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "ConsistencyLevel": "eventual",
    }
    # Quote the query for $search. Strip any user-supplied quotes to keep it simple.
    safe = query.replace('"', "").strip()
    params = {"$search": f'"{safe}"', "$top": max_results}

    resp = requests.get(
        f"{GRAPH_BASE}/me/messages",
        headers=headers,
        params=params,
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Graph search failed ({resp.status_code}): {resp.text}")

    messages = resp.json().get("value", [])

    window_start = datetime.combine(centered_date, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=window_days)
    window_end = datetime.combine(centered_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=window_days)

    results = []
    for m in messages:
        received_str = m.get("receivedDateTime")
        if not received_str:
            continue
        received = datetime.fromisoformat(received_str.replace("Z", "+00:00"))
        if not (window_start <= received <= window_end):
            continue

        from_field = m.get("from") or {}
        sender_addr = (from_field.get("emailAddress") or {}).get("address")

        results.append({
            "id": m.get("id"),
            "subject": m.get("subject"),
            "sender": sender_addr,
            "received_at": received_str,
            "body_preview": m.get("bodyPreview"),
        })

    return results


def search_emails(
    client_id: int,
    amount: float,
    txn_date: date,
    window_days: int = 7,
) -> list[dict]:
    access_token = refresh_token_if_needed(client_id)

    # Graph $search requires the ConsistencyLevel: eventual header.
    headers = {
        "Authorization": f"Bearer {access_token}",
        "ConsistencyLevel": "eventual",
    }
    params = {
        "$search": f'"{amount}"',
        "$top": 10,
    }

    resp = requests.get(
        f"{GRAPH_BASE}/me/messages",
        headers=headers,
        params=params,
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Graph search failed ({resp.status_code}): {resp.text}"
        )

    messages = resp.json().get("value", [])

    window_start = datetime.combine(txn_date, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=window_days)
    window_end = datetime.combine(txn_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=window_days)

    results = []
    for m in messages:
        received_str = m.get("receivedDateTime")
        if not received_str:
            continue
        received = datetime.fromisoformat(received_str.replace("Z", "+00:00"))
        if not (window_start <= received <= window_end):
            continue

        from_field = m.get("from") or {}
        sender_addr = (from_field.get("emailAddress") or {}).get("address")

        results.append({
            "id": m.get("id"),
            "subject": m.get("subject"),
            "sender": sender_addr,
            "received_at": received_str,
            "body_preview": m.get("bodyPreview"),
        })

    return results
