"""Client CRUD, scoped to the caller's firm."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src import db
from backend.deps import get_firm_id, require_client_ownership

router = APIRouter(prefix="/clients", tags=["clients"])


class Client(BaseModel):
    id: int
    firm_name: str
    qbo_connected: bool
    outlook_connected: bool


class ClientCreate(BaseModel):
    firm_name: str


@router.get("", response_model=list[Client])
def list_clients(firm_id: int = Depends(get_firm_id)):
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, firm_name,
                   qbo_refresh_token IS NOT NULL AS qbo_connected,
                   outlook_refresh_token IS NOT NULL AS outlook_connected
            FROM clients
            WHERE firm_id = ?
            ORDER BY id
            """,
            (firm_id,),
        ).fetchall()
    return [
        Client(
            id=r["id"],
            firm_name=r["firm_name"],
            qbo_connected=bool(r["qbo_connected"]),
            outlook_connected=bool(r["outlook_connected"]),
        )
        for r in rows
    ]


@router.post("", response_model=Client, status_code=201)
def create_client(payload: ClientCreate, firm_id: int = Depends(get_firm_id)):
    if not payload.firm_name.strip():
        raise HTTPException(status_code=400, detail="firm_name is required")
    name = payload.firm_name.strip()
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO clients (firm_name, firm_id) VALUES (?, ?)",
            (name, firm_id),
        )
        new_id = cur.lastrowid
    return Client(id=new_id, firm_name=name, qbo_connected=False, outlook_connected=False)


@router.get("/{client_id}", response_model=Client)
def get_client(client_id: int = Depends(require_client_ownership)):
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, firm_name,
                   qbo_refresh_token IS NOT NULL AS qbo_connected,
                   outlook_refresh_token IS NOT NULL AS outlook_connected
            FROM clients WHERE id = ?
            """,
            (client_id,),
        ).fetchone()
    return Client(
        id=row["id"],
        firm_name=row["firm_name"],
        qbo_connected=bool(row["qbo_connected"]),
        outlook_connected=bool(row["outlook_connected"]),
    )
