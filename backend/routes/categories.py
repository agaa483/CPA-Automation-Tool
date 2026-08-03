"""Chart of accounts (categories) endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src import db, qbo
from backend.deps import require_client_ownership

router = APIRouter(
    prefix="/clients/{client_id}/categories",
    tags=["categories"],
    dependencies=[Depends(require_client_ownership)],
)


class Category(BaseModel):
    id: int
    name: str
    description: str | None = None


class SyncResult(BaseModel):
    synced: int


@router.get("", response_model=list[Category])
def list_categories(client_id: int):
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, description FROM categories WHERE client_id = ? ORDER BY name",
            (client_id,),
        ).fetchall()
    return [Category(id=r["id"], name=r["name"], description=r["description"]) for r in rows]


@router.post("/sync", response_model=SyncResult)
def sync_categories(client_id: int):
    """Pull chart of accounts from QBO into local DB. Requires QBO connected."""
    try:
        count = qbo.sync_categories(client_id)
    except Exception as e:
        # Catch broadly (QuickbooksException, RuntimeError, network, etc.) so
        # the frontend sees a real error message instead of a generic fetch failure.
        raise HTTPException(status_code=400, detail=f"Sync failed: {e}")
    return SyncResult(synced=count)
