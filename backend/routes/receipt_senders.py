"""Per-client receipt sender list.

Stores the email addresses that forward receipts for a given client so we can
filter the firm's mailbox to just that client's receipts during an audit.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from src import db
from backend.deps import require_client_ownership

router = APIRouter(
    prefix="/clients/{client_id}/receipt-senders",
    tags=["receipt-senders"],
    dependencies=[Depends(require_client_ownership)],
)


class SenderIn(BaseModel):
    address: EmailStr


class SenderOut(BaseModel):
    address: str


def _ensure_table():
    """Idempotent: create the table if it doesn't exist yet."""
    with db.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS client_receipt_senders (
                client_id INTEGER NOT NULL REFERENCES clients(id),
                sender_address TEXT NOT NULL,
                PRIMARY KEY (client_id, sender_address)
            )
            """
        )


@router.get("", response_model=list[SenderOut])
def list_senders(client_id: int):
    _ensure_table()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT sender_address FROM client_receipt_senders WHERE client_id = ? ORDER BY sender_address",
            (client_id,),
        ).fetchall()
    return [SenderOut(address=r["sender_address"]) for r in rows]


@router.post("", response_model=SenderOut, status_code=201)
def add_sender(client_id: int, payload: SenderIn):
    _ensure_table()
    addr = payload.address.strip().lower()
    with db.get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO client_receipt_senders (client_id, sender_address) VALUES (?, ?)",
            (client_id, addr),
        )
    return SenderOut(address=addr)


@router.delete("/{address}", status_code=204)
def remove_sender(client_id: int, address: str):
    _ensure_table()
    with db.get_connection() as conn:
        result = conn.execute(
            "DELETE FROM client_receipt_senders WHERE client_id = ? AND sender_address = ?",
            (client_id, address.strip().lower()),
        )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Sender not found")
