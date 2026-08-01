"""Audit endpoints: run a batch audit, apply corrections, view history."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src import db, qbo, outlook, auditor
from backend.deps import require_client_ownership

router = APIRouter(
    prefix="/clients/{client_id}/audits",
    tags=["audits"],
    dependencies=[Depends(require_client_ownership)],
)


class FlaggedTxn(BaseModel):
    txn_db_id: int
    qbo_txn_id: str
    txn_type: str
    line_num: int
    txn_date: str
    amount: float
    vendor_raw: str | None
    original_category: str | None
    suggested_category: str | None
    suggested_payee: str | None
    suggested_payor: str | None
    reasoning: str
    supporting_email_ids: list[str]


class AuditRunResult(BaseModel):
    audited: int
    no_change: int
    flagged: int
    errors: int
    skipped: int
    flagged_details: list[FlaggedTxn]


class ApplyRequest(BaseModel):
    txn_db_ids: list[int]  # Which flagged rows to apply to QBO


class ApplyResult(BaseModel):
    applied: int
    failed: int
    details: list[dict]


class AuditLogEntry(BaseModel):
    id: int
    transaction_id: int
    is_correct: bool
    original_category: str
    new_category: str | None
    reasoning: str
    action_taken: str
    created_at: str


def _upsert_pulled(client_id: int, txns: list[dict]) -> None:
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


def _set_status(txn_db_id: int, status: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE transactions SET audit_status = ?, last_audited_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, txn_db_id),
        )


@router.post("/run", response_model=AuditRunResult)
def run_audit(client_id: int):
    """Pull new transactions from QBO, audit all pending ones, return flagged list.
    Always dry-run — this endpoint never writes to QBO. Use /apply for that."""
    try:
        qbo.refresh_token_if_needed(client_id)
        outlook.refresh_token_if_needed(client_id)
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=f"Token refresh failed: {e}")

    try:
        pulled = qbo.fetch_recent_transactions(client_id)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"QBO fetch failed: {e}")

    _upsert_pulled(client_id, pulled)
    pulled_index = {str(t["qbo_txn_id"]): t for t in pulled}

    with db.get_connection() as conn:
        pending = conn.execute(
            """
            SELECT id, qbo_txn_id, current_qbo_category
            FROM transactions
            WHERE client_id = ? AND audit_status = 'pending'
            """,
            (client_id,),
        ).fetchall()

    audited = no_change = flagged = errors = skipped = 0
    flagged_details: list[FlaggedTxn] = []

    for prow in pending:
        txn_db_id = prow["id"]
        qbo_id = prow["qbo_txn_id"]
        txn = pulled_index.get(qbo_id)
        if txn is None:
            skipped += 1
            continue

        audited += 1
        try:
            decision = auditor.audit_transaction(client_id, txn)
        except RuntimeError as e:
            errors += 1
            continue

        original_category = txn["current_qbo_category"] or ""
        prompt = getattr(decision, "_prompt", "")
        raw = getattr(decision, "_raw_response", "")

        if decision.is_correct:
            _set_status(txn_db_id, "verified")
            auditor.log_decision(
                transaction_id=txn_db_id,
                decision=decision,
                original_category=original_category,
                prompt=prompt,
                raw_response=raw,
                action_taken="no_change",
            )
            no_change += 1
        else:
            auditor.log_decision(
                transaction_id=txn_db_id,
                decision=decision,
                original_category=original_category,
                prompt=prompt,
                raw_response=raw,
                action_taken="dry_run",
            )
            flagged += 1
            flagged_details.append(FlaggedTxn(
                txn_db_id=txn_db_id,
                qbo_txn_id=str(txn["qbo_txn_id"]),
                txn_type=txn["txn_type"],
                line_num=txn["line_num"],
                txn_date=str(txn["txn_date"]),
                amount=txn["amount"],
                vendor_raw=txn["vendor_raw"],
                original_category=original_category,
                suggested_category=decision.corrected_category,
                suggested_payee=decision.suggested_payee,
                suggested_payor=decision.suggested_payor,
                reasoning=decision.reasoning,
                supporting_email_ids=decision.supporting_email_ids,
            ))

    return AuditRunResult(
        audited=audited,
        no_change=no_change,
        flagged=flagged,
        errors=errors,
        skipped=skipped,
        flagged_details=flagged_details,
    )


@router.post("/apply", response_model=ApplyResult)
def apply_corrections(client_id: int, payload: ApplyRequest):
    """Apply the specified flagged decisions to QBO."""
    applied = failed = 0
    details = []

    with db.get_connection() as conn:
        for txn_db_id in payload.txn_db_ids:
            row = conn.execute(
                """
                SELECT t.qbo_txn_id, al.new_category, al.original_category
                FROM audit_log al
                JOIN transactions t ON t.id = al.transaction_id
                WHERE al.transaction_id = ?
                ORDER BY al.id DESC LIMIT 1
                """,
                (txn_db_id,),
            ).fetchone()
            if row is None or not row["new_category"]:
                failed += 1
                details.append({"txn_db_id": txn_db_id, "error": "No pending suggestion found"})
                continue

            try:
                qbo.update_category(client_id, row["qbo_txn_id"], row["new_category"])
                _set_status(txn_db_id, "corrected")
                # Log a new "applied" audit_log entry so the history is clean
                conn.execute(
                    """
                    INSERT INTO audit_log (
                        transaction_id, original_category, is_correct, new_category,
                        reasoning, prompt_payload, model_response, supporting_emails,
                        action_taken
                    ) VALUES (?, ?, 0, ?, 'Applied via UI', '{}', '{}', '[]', 'applied')
                    """,
                    (txn_db_id, row["original_category"], row["new_category"]),
                )
                applied += 1
                details.append({"txn_db_id": txn_db_id, "status": "applied"})
            except Exception as e:
                failed += 1
                details.append({"txn_db_id": txn_db_id, "error": str(e)})

    return ApplyResult(applied=applied, failed=failed, details=details)


@router.get("/history", response_model=list[AuditLogEntry])
def audit_history(client_id: int, limit: int = 50):
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT al.id, al.transaction_id, al.is_correct, al.original_category,
                   al.new_category, al.reasoning, al.action_taken, al.created_at
            FROM audit_log al
            JOIN transactions t ON t.id = al.transaction_id
            WHERE t.client_id = ?
            ORDER BY al.id DESC LIMIT ?
            """,
            (client_id, limit),
        ).fetchall()
    return [
        AuditLogEntry(
            id=r["id"],
            transaction_id=r["transaction_id"],
            is_correct=bool(r["is_correct"]),
            original_category=r["original_category"],
            new_category=r["new_category"],
            reasoning=r["reasoning"],
            action_taken=r["action_taken"],
            created_at=str(r["created_at"]),
        )
        for r in rows
    ]
