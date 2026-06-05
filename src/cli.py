from datetime import date as date_type, datetime

import typer
from tabulate import tabulate

from . import auditor, db, outlook, qbo
from .config import DB_PATH

app = typer.Typer()


@app.command("init-db")
def init_db() -> None:
    db.init_db()
    typer.echo(f"Database initialized at {DB_PATH}")


@app.command("add-client")
def add_client(firm_name: str = typer.Option(..., "--firm-name")) -> None:
    client_id = db.add_client(firm_name)
    typer.echo(client_id)


@app.command("qbo-connect")
def qbo_connect(client_id: int = typer.Option(..., "--client-id")) -> None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT qbo_refresh_token FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
    if row is None:
        typer.echo(f"No client with id {client_id}.", err=True)
        raise typer.Exit(code=1)
    if row["qbo_refresh_token"]:
        confirm = typer.confirm(
            f"Client {client_id} already has QBO tokens. Overwrite?"
        )
        if not confirm:
            typer.echo("Aborted.")
            raise typer.Exit()

    try:
        qbo.start_auth_flow(client_id)
    except RuntimeError as e:
        typer.echo(f"QBO connect failed: {e}", err=True)
        raise typer.Exit(code=1)


@app.command("qbo-pull")
def qbo_pull(
    client_id: int = typer.Option(..., "--client-id"),
    days_back: int = typer.Option(30, "--days-back"),
    account: list[str] = typer.Option(
        None,
        "--account",
        help="Bank/CC account name to include. Repeat for multiple. Omit to include all bank/CC accounts.",
    ),
) -> None:
    try:
        txns = qbo.fetch_recent_transactions(
            client_id, days_back=days_back, accounts_filter=account or None
        )
    except RuntimeError as e:
        typer.echo(f"QBO pull failed: {e}", err=True)
        raise typer.Exit(code=1)

    if not txns:
        typer.echo("No transactions found.")
        return

    headers = ["qbo_txn_id", "txn_type", "line_num", "txn_date", "amount", "vendor_raw", "current_qbo_category"]
    rows = [[t[h] for h in headers] for t in txns]
    typer.echo(tabulate(rows, headers=headers, tablefmt="simple"))


@app.command("outlook-connect")
def outlook_connect(client_id: int = typer.Option(..., "--client-id")) -> None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT outlook_refresh_token FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
    if row is None:
        typer.echo(f"No client with id {client_id}.", err=True)
        raise typer.Exit(code=1)
    if row["outlook_refresh_token"]:
        confirm = typer.confirm(
            f"Client {client_id} already has Outlook tokens. Overwrite?"
        )
        if not confirm:
            typer.echo("Aborted.")
            raise typer.Exit()

    try:
        outlook.start_auth_flow(client_id)
    except RuntimeError as e:
        typer.echo(f"Outlook connect failed: {e}", err=True)
        raise typer.Exit(code=1)


@app.command("outlook-search")
def outlook_search(
    client_id: int = typer.Option(..., "--client-id"),
    amount: float = typer.Option(..., "--amount"),
    date: str = typer.Option(..., "--date", help="YYYY-MM-DD"),
    window_days: int = typer.Option(7, "--window-days"),
) -> None:
    try:
        txn_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        typer.echo("Invalid --date. Use YYYY-MM-DD.", err=True)
        raise typer.Exit(code=1)

    try:
        emails = outlook.search_emails(
            client_id, amount=amount, txn_date=txn_date, window_days=window_days
        )
    except RuntimeError as e:
        typer.echo(f"Outlook search failed: {e}", err=True)
        raise typer.Exit(code=1)

    if not emails:
        typer.echo("No matching emails found.")
        return

    headers = ["received_at", "sender", "subject", "body_preview"]
    rows = [[e[h] for h in headers] for e in emails]
    typer.echo(tabulate(rows, headers=headers, tablefmt="simple"))


@app.command("qbo-sync-categories")
def qbo_sync_categories(client_id: int = typer.Option(..., "--client-id")) -> None:
    try:
        count = qbo.sync_categories(client_id)
    except RuntimeError as e:
        typer.echo(f"Sync failed: {e}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Synced {count} accounts into the categories table.")


@app.command("audit")
def audit(
    client_id: int = typer.Option(..., "--client-id"),
    txn_id: str = typer.Option(..., "--txn-id", help="QBO transaction ID"),
    line_num: int = typer.Option(
        1, "--line-num", help="Line number when the txn has multiple lines"
    ),
) -> None:
    # Pull all bank-tab txns and filter to the requested one.
    try:
        all_txns = qbo.fetch_recent_transactions(client_id)
    except RuntimeError as e:
        typer.echo(f"QBO fetch failed: {e}", err=True)
        raise typer.Exit(code=1)

    matches = [
        t for t in all_txns
        if str(t["qbo_txn_id"]) == str(txn_id) and t["line_num"] == line_num
    ]
    if not matches:
        same_id = [t for t in all_txns if str(t["qbo_txn_id"]) == str(txn_id)]
        if same_id:
            typer.echo(
                f"Txn {txn_id} has {len(same_id)} line(s). Specify --line-num "
                f"(available: {sorted(t['line_num'] for t in same_id)}).",
                err=True,
            )
        else:
            typer.echo(f"No bank-tab transaction with QBO ID {txn_id}.", err=True)
        raise typer.Exit(code=1)

    txn = matches[0]

    # Run the audit.
    try:
        decision = auditor.audit_transaction(client_id, txn)
    except RuntimeError as e:
        typer.echo(f"Audit failed: {e}", err=True)
        raise typer.Exit(code=1)

    # Persist the transaction row (needed because audit_log FK references it).
    # No-op if it already exists.
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO transactions (
                client_id, qbo_txn_id, txn_date, amount, vendor_raw,
                current_qbo_category
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                str(txn["qbo_txn_id"]),
                txn["txn_date"],
                txn["amount"],
                txn["vendor_raw"],
                txn["current_qbo_category"],
            ),
        )
        row = conn.execute(
            "SELECT id FROM transactions WHERE client_id = ? AND qbo_txn_id = ?",
            (client_id, str(txn["qbo_txn_id"])),
        ).fetchone()
        transaction_db_id = row["id"]

    auditor.log_decision(
        transaction_id=transaction_db_id,
        decision=decision,
        original_category=txn["current_qbo_category"] or "",
        prompt=getattr(decision, "_prompt", ""),
        raw_response=getattr(decision, "_raw_response", ""),
        action_taken="no_change",
    )

    # Pretty-print.
    typer.echo("")
    typer.echo(f"QBO txn:      {txn['qbo_txn_id']} (line {txn['line_num']})")
    typer.echo(f"Vendor:       {txn['vendor_raw']}")
    typer.echo(f"Amount:       {txn['amount']}")
    typer.echo(f"Existing:     {txn['current_qbo_category']}")
    typer.echo("")
    typer.echo(f"is_correct:   {decision.is_correct}")
    if not decision.is_correct:
        typer.echo(f"corrected:    {decision.corrected_category}")
    typer.echo(f"reasoning:    {decision.reasoning}")
    if decision.supporting_email_ids:
        typer.echo(f"emails cited: {', '.join(decision.supporting_email_ids)}")
    typer.echo("")
    typer.echo("(action_taken=no_change — QBO not modified.)")


def _insert_new_transactions(client_id: int, txns: list[dict]) -> None:
    """INSERT OR IGNORE each pulled txn so existing rows are left untouched."""
    with db.get_connection() as conn:
        for t in txns:
            conn.execute(
                """
                INSERT OR IGNORE INTO transactions (
                    client_id, qbo_txn_id, txn_date, amount, vendor_raw,
                    current_qbo_category, audit_status
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    client_id,
                    str(t["qbo_txn_id"]),
                    t["txn_date"],
                    t["amount"],
                    t["vendor_raw"],
                    t["current_qbo_category"],
                ),
            )


def _previously_applied_original(transaction_id: int) -> str | None:
    """Return the original_category from the most recent applied audit, if any.
    Used to detect 'CPA reverted our correction' so we don't re-correct."""
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT original_category FROM audit_log
            WHERE transaction_id = ? AND action_taken = 'applied'
            ORDER BY id DESC LIMIT 1
            """,
            (transaction_id,),
        ).fetchone()
    return row["original_category"] if row else None


def _set_audit_status(transaction_id: int, status: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE transactions SET audit_status = ?, last_audited_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, transaction_id),
        )


@app.command("run")
def run(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Audit + log but do not modify QBO."
    ),
    client_id: int = typer.Option(
        None, "--client-id", help="Limit to one client. Omit to run all clients."
    ),
) -> None:
    # Resolve target clients.
    with db.get_connection() as conn:
        if client_id is not None:
            rows = conn.execute(
                "SELECT id, firm_name FROM clients WHERE id = ?", (client_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT id, firm_name FROM clients").fetchall()
    if not rows:
        typer.echo("No clients to process.", err=True)
        raise typer.Exit(code=1)

    grand_audited = 0
    grand_no_change = 0
    grand_corrected = 0
    grand_dry_run = 0
    grand_skipped = 0
    grand_errors = 0

    for client_row in rows:
        cid = client_row["id"]
        firm = client_row["firm_name"]
        typer.echo(f"\n=== Client {cid}: {firm} ===")

        # Refresh tokens up-front (also surfaces auth failures before doing work).
        try:
            qbo.refresh_token_if_needed(cid)
            outlook.refresh_token_if_needed(cid)
        except RuntimeError as e:
            typer.echo(f"  Token refresh failed: {e}", err=True)
            grand_errors += 1
            continue

        # Pull from QBO and upsert new transactions.
        try:
            pulled = qbo.fetch_recent_transactions(cid)
        except RuntimeError as e:
            typer.echo(f"  QBO pull failed: {e}", err=True)
            grand_errors += 1
            continue
        _insert_new_transactions(cid, pulled)
        typer.echo(f"  Pulled {len(pulled)} txns from QBO.")

        # Build a {qbo_txn_id: txn_dict} index for feeding the auditor without re-fetching.
        pulled_index = {str(t["qbo_txn_id"]): t for t in pulled}

        # Load all pending txns for this client.
        with db.get_connection() as conn:
            pending = conn.execute(
                """
                SELECT id, qbo_txn_id, current_qbo_category
                FROM transactions
                WHERE client_id = ? AND audit_status = 'pending'
                """,
                (cid,),
            ).fetchall()
        typer.echo(f"  {len(pending)} pending txn(s) to audit.")

        for prow in pending:
            txn_db_id = prow["id"]
            qbo_id = prow["qbo_txn_id"]
            grand_audited += 1

            txn = pulled_index.get(qbo_id)
            if txn is None:
                # Pending row exists locally but not in latest pull — skip safely.
                typer.echo(f"  [{qbo_id}] not in current pull, skipping.")
                grand_skipped += 1
                continue

            # Safety: if we previously corrected this txn and it's now back to
            # the original wrong category, the CPA reverted us. Don't fight them.
            prior_orig = _previously_applied_original(txn_db_id)
            if prior_orig is not None and prior_orig == (txn["current_qbo_category"] or ""):
                _set_audit_status(txn_db_id, "do_not_audit")
                typer.echo(
                    f"  [{qbo_id}] previously corrected and reverted by CPA — "
                    f"marking do_not_audit."
                )
                grand_skipped += 1
                continue

            # Run the audit.
            try:
                decision = auditor.audit_transaction(cid, txn)
            except RuntimeError as e:
                typer.echo(f"  [{qbo_id}] audit failed: {e}", err=True)
                grand_errors += 1
                continue

            original_category = txn["current_qbo_category"] or ""
            prompt = getattr(decision, "_prompt", "")
            raw = getattr(decision, "_raw_response", "")

            if decision.is_correct:
                _set_audit_status(txn_db_id, "verified")
                auditor.log_decision(
                    transaction_id=txn_db_id,
                    decision=decision,
                    original_category=original_category,
                    prompt=prompt,
                    raw_response=raw,
                    action_taken="no_change",
                )
                grand_no_change += 1
                continue

            # is_correct == False
            if dry_run:
                # Leave audit_status='pending' so a later non-dry-run picks it up.
                auditor.log_decision(
                    transaction_id=txn_db_id,
                    decision=decision,
                    original_category=original_category,
                    prompt=prompt,
                    raw_response=raw,
                    action_taken="dry_run",
                )
                typer.echo(
                    f"  [{qbo_id}] DRY-RUN: '{original_category}' -> "
                    f"'{decision.corrected_category}' ({decision.reasoning})"
                )
                grand_dry_run += 1
                continue

            # Live mode: actually update QBO.
            try:
                qbo.update_category(cid, qbo_id, decision.corrected_category)
            except RuntimeError as e:
                # Log the failure but keep going through the rest.
                typer.echo(f"  [{qbo_id}] QBO update failed: {e}", err=True)
                auditor.log_decision(
                    transaction_id=txn_db_id,
                    decision=decision,
                    original_category=original_category,
                    prompt=prompt,
                    raw_response=raw,
                    action_taken="dry_run",  # treat failed apply as a dry_run record
                )
                grand_errors += 1
                continue

            _set_audit_status(txn_db_id, "corrected")
            auditor.log_decision(
                transaction_id=txn_db_id,
                decision=decision,
                original_category=original_category,
                prompt=prompt,
                raw_response=raw,
                action_taken="applied",
            )
            typer.echo(
                f"  [{qbo_id}] APPLIED: '{original_category}' -> "
                f"'{decision.corrected_category}'"
            )
            grand_corrected += 1

    # Summary
    typer.echo("\n=== Summary ===")
    typer.echo(f"Audited:   {grand_audited}")
    typer.echo(f"No change: {grand_no_change}")
    if dry_run:
        typer.echo(f"Dry-run:   {grand_dry_run}")
    else:
        typer.echo(f"Corrected: {grand_corrected}")
    typer.echo(f"Skipped:   {grand_skipped}")
    typer.echo(f"Errors:    {grand_errors}")


if __name__ == "__main__":
    app()
