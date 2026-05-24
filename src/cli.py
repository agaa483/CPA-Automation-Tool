from datetime import date as date_type, datetime

import typer
from tabulate import tabulate

from . import db, outlook, qbo
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


if __name__ == "__main__":
    app()
