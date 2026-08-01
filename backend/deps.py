"""Reusable FastAPI dependencies for auth + multi-tenant scoping."""
from fastapi import Depends, HTTPException

from src import db
from backend.auth import current_user_id


def _ensure_firms_schema() -> None:
    """Idempotent schema migration: adds firms table + firm_id column on clients.
    Runs on-demand rather than requiring a separate migration step for v1.
    Backfills existing clients into the first firm that logs in (dad's setup).
    """
    with db.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS firms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clerk_user_id TEXT NOT NULL UNIQUE,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Add firm_id to clients if not present.
        cols = conn.execute("PRAGMA table_info(clients)").fetchall()
        has_firm_id = any(c["name"] == "firm_id" for c in cols)
        if not has_firm_id:
            conn.execute("ALTER TABLE clients ADD COLUMN firm_id INTEGER REFERENCES firms(id)")


def get_firm_id(user_id: str = Depends(current_user_id)) -> int:
    """Return the firm_id for the calling user, creating the firm row on first login."""
    _ensure_firms_schema()

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM firms WHERE clerk_user_id = ?", (user_id,)
        ).fetchone()
        if row is not None:
            return row["id"]

        # First-time login: create the firm.
        cur = conn.execute(
            "INSERT INTO firms (clerk_user_id) VALUES (?)", (user_id,)
        )
        new_firm_id = cur.lastrowid

        # Backfill: claim any orphan clients (no firm_id) for this firm.
        # This is a one-time convenience for dad's setup where existing clients
        # were created before multi-tenancy. Only fires once (subsequent firms
        # start empty).
        orphan_count = conn.execute(
            "SELECT COUNT(*) AS n FROM clients WHERE firm_id IS NULL"
        ).fetchone()["n"]
        if orphan_count > 0:
            first_firm = conn.execute(
                "SELECT COUNT(*) AS n FROM firms"
            ).fetchone()["n"] == 1
            if first_firm:
                conn.execute(
                    "UPDATE clients SET firm_id = ? WHERE firm_id IS NULL",
                    (new_firm_id,),
                )

    return new_firm_id


def require_client_ownership(client_id: int, firm_id: int = Depends(get_firm_id)) -> int:
    """Ensures client_id belongs to the caller's firm. Returns client_id."""
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM clients WHERE id = ? AND firm_id = ?", (client_id, firm_id)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Client {client_id} not found")
    return client_id
