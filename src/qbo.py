import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from quickbooks import QuickBooks
from quickbooks.objects.account import Account
from quickbooks.objects.deposit import Deposit
from quickbooks.objects.purchase import Purchase
from quickbooks.objects.transfer import Transfer

BANK_ACCOUNT_TYPES = {"Bank", "Credit Card"}

from . import db
from .config import (
    QBO_CLIENT_ID,
    QBO_CLIENT_SECRET,
    QBO_ENVIRONMENT,
    QBO_REDIRECT_URI,
)


REDIRECT_HOST = "localhost"
REDIRECT_PORT = 8000
OAUTH_TIMEOUT_SECONDS = 300
REFRESH_BUFFER_SECONDS = 300


def _make_auth_client() -> AuthClient:
    return AuthClient(
        client_id=QBO_CLIENT_ID,
        client_secret=QBO_CLIENT_SECRET,
        redirect_uri=QBO_REDIRECT_URI,
        environment=QBO_ENVIRONMENT,
    )


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        realm_id = params.get("realmId", [None])[0]
        error = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if error or not code or not realm_id:
            self.wfile.write(b"<h1>Authorization failed.</h1> You can close this tab.")
            _CallbackHandler.result = {"error": error or "missing code/realmId"}
        else:
            self.wfile.write(b"<h1>Authorization complete.</h1> You can close this tab.")
            _CallbackHandler.result = {"code": code, "realm_id": realm_id}

    def log_message(self, format, *args):  # noqa: A002
        return


def start_auth_flow(client_id: int) -> None:
    auth_client = _make_auth_client()
    auth_url = auth_client.get_authorization_url([Scopes.ACCOUNTING])

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

    auth_client.get_bearer_token(result["code"], realm_id=result["realm_id"])

    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=auth_client.expires_in
    )

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
                result["realm_id"],
                auth_client.access_token,
                auth_client.refresh_token,
                expires_at.isoformat(),
                client_id,
            ),
        )

    print(f"Connected QBO realm {result['realm_id']} for client {client_id}.")


def refresh_token_if_needed(client_id: int) -> str:
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT qbo_access_token, qbo_refresh_token, qbo_token_expires_at, qbo_realm_id
            FROM clients WHERE id = ?
            """,
            (client_id,),
        ).fetchone()

    if not row or not row["qbo_refresh_token"]:
        raise RuntimeError(f"Client {client_id} has no QBO tokens. Run qbo-connect first.")

    expires_at = datetime.fromisoformat(row["qbo_token_expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at - datetime.now(timezone.utc) > timedelta(seconds=REFRESH_BUFFER_SECONDS):
        return row["qbo_access_token"]

    auth_client = _make_auth_client()
    auth_client.refresh(refresh_token=row["qbo_refresh_token"])

    new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=auth_client.expires_in)

    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE clients
            SET qbo_access_token = ?,
                qbo_refresh_token = ?,
                qbo_token_expires_at = ?
            WHERE id = ?
            """,
            (
                auth_client.access_token,
                auth_client.refresh_token,
                new_expires_at.isoformat(),
                client_id,
            ),
        )

    return auth_client.access_token


PAGE_SIZE = 500


def _build_qb_client(client_id: int) -> QuickBooks:
    access_token = refresh_token_if_needed(client_id)
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT qbo_realm_id, qbo_refresh_token FROM clients WHERE id = ?",
            (client_id,),
        ).fetchone()

    auth_client = _make_auth_client()
    auth_client.access_token = access_token
    auth_client.refresh_token = row["qbo_refresh_token"]

    return QuickBooks(
        auth_client=auth_client,
        refresh_token=row["qbo_refresh_token"],
        company_id=row["qbo_realm_id"],
    )


def _paginated(model, where: str, qb_client: QuickBooks) -> list:
    out = []
    start = 1
    while True:
        if where:
            page = model.where(
                where, qb=qb_client, max_results=PAGE_SIZE, start_position=start
            )
        else:
            page = model.all(qb=qb_client, max_results=PAGE_SIZE, start_position=start)
        if not page:
            break
        out.extend(page)
        if len(page) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return out


def _entity_name(obj) -> str | None:
    for attr in ("EntityRef", "VendorRef", "CustomerRef"):
        ref = getattr(obj, attr, None)
        if ref is not None:
            return getattr(ref, "name", None)
    return None


def _expense_line_category(line) -> str | None:
    for detail_attr in ("AccountBasedExpenseLineDetail", "ItemBasedExpenseLineDetail"):
        detail = getattr(line, detail_attr, None)
        if detail is None:
            continue
        ref = getattr(detail, "AccountRef", None) or getattr(detail, "ItemRef", None)
        if ref is not None:
            return getattr(ref, "name", None)
    return None


def _income_line_category(line) -> str | None:
    for detail_attr in ("SalesItemLineDetail", "GroupLineDetail"):
        detail = getattr(line, detail_attr, None)
        if detail is None:
            continue
        ref = getattr(detail, "ItemRef", None)
        if ref is not None:
            return getattr(ref, "name", None)
    return None


def _deposit_line_category(line) -> str | None:
    detail = getattr(line, "DepositLineDetail", None)
    if detail is None:
        return None
    ref = getattr(detail, "AccountRef", None)
    return getattr(ref, "name", None) if ref else None


def _je_line_category(line) -> tuple[str | None, str | None]:
    """Returns (account_name, posting_type)."""
    detail = getattr(line, "JournalEntryLineDetail", None)
    if detail is None:
        return None, None
    ref = getattr(detail, "AccountRef", None)
    return (
        getattr(ref, "name", None) if ref else None,
        getattr(detail, "PostingType", None),
    )


def _row(txn, txn_type, line_num, category, line_amount, extra_vendor=None):
    amount = line_amount
    if amount is None and getattr(txn, "TotalAmt", None) is not None:
        amount = float(txn.TotalAmt)
    return {
        "qbo_txn_id": txn.Id,
        "txn_type": txn_type,
        "line_num": line_num,
        "txn_date": txn.TxnDate,
        "amount": float(amount) if amount is not None else None,
        "vendor_raw": extra_vendor or _entity_name(txn),
        "current_qbo_category": category,
    }


def _flatten_lines(txn, txn_type, line_category_fn) -> list[dict]:
    rows = []
    lines = getattr(txn, "Line", None) or []
    line_num = 0
    for line in lines:
        category = line_category_fn(line)
        # Skip subtotal/group wrapper lines that have no category
        if category is None:
            continue
        line_num += 1
        rows.append(_row(txn, txn_type, line_num, category, getattr(line, "Amount", None)))
    if not rows:
        # Fallback: a single row so the txn isn't silently dropped
        rows.append(_row(txn, txn_type, 1, None, None))
    return rows


def _flatten_transfer(txn) -> list[dict]:
    from_ref = getattr(txn, "FromAccountRef", None)
    to_ref = getattr(txn, "ToAccountRef", None)
    from_name = getattr(from_ref, "name", None) if from_ref else None
    to_name = getattr(to_ref, "name", None) if to_ref else None
    category = f"{from_name} -> {to_name}" if (from_name or to_name) else None
    amount = float(txn.Amount) if getattr(txn, "Amount", None) is not None else None
    return [{
        "qbo_txn_id": txn.Id,
        "txn_type": "Transfer",
        "line_num": 1,
        "txn_date": txn.TxnDate,
        "amount": amount,
        "vendor_raw": None,
        "current_qbo_category": category,
    }]


def fetch_recent_transactions(
    client_id: int,
    days_back: int | None = None,
    accounts_filter: list[str] | None = None,
) -> list[dict]:
    qb_client = _build_qb_client(client_id)

    # Build {account_id: account_type} map so we can filter to bank-tab txns only.
    accounts = _paginated(Account, "Active = true", qb_client)
    account_type_by_id = {a.Id: a.AccountType for a in accounts}
    account_name_by_id = {a.Id: a.Name for a in accounts}

    def _is_bank_account(account_id) -> bool:
        return account_type_by_id.get(account_id) in BANK_ACCOUNT_TYPES

    allowed_names = (
        {n.strip().lower() for n in accounts_filter if n.strip()}
        if accounts_filter
        else None
    )

    if allowed_names:
        known = {n.lower() for n in account_name_by_id.values()}
        unknown = allowed_names - known
        if unknown:
            raise RuntimeError(
                f"Unknown account name(s): {sorted(unknown)}. "
                f"Available bank/CC accounts: "
                f"{sorted(account_name_by_id[i] for i in account_type_by_id if _is_bank_account(i))}"
            )

    def _account_allowed(account_id) -> bool:
        if not _is_bank_account(account_id):
            return False
        if allowed_names is None:
            return True
        name = account_name_by_id.get(account_id, "").lower()
        return name in allowed_names

    results: list[dict] = []

    for txn in _paginated(Purchase, "", qb_client):
        acct_ref = getattr(txn, "AccountRef", None)
        if not acct_ref or not _account_allowed(acct_ref.value):
            continue
        results.extend(_flatten_lines(txn, "Purchase", _expense_line_category))

    for txn in _paginated(Deposit, "", qb_client):
        acct_ref = getattr(txn, "DepositToAccountRef", None)
        if not acct_ref or not _account_allowed(acct_ref.value):
            continue
        results.extend(_flatten_lines(txn, "Deposit", _deposit_line_category))

    for txn in _paginated(Transfer, "", qb_client):
        from_ref = getattr(txn, "FromAccountRef", None)
        to_ref = getattr(txn, "ToAccountRef", None)
        from_ok = from_ref and _account_allowed(from_ref.value)
        to_ok = to_ref and _account_allowed(to_ref.value)
        if not (from_ok or to_ok):
            continue
        results.extend(_flatten_transfer(txn))

    results.sort(key=lambda r: (r["txn_date"] or "", r["qbo_txn_id"], r["line_num"]), reverse=True)
    return results
