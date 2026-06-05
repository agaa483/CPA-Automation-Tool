import json
from datetime import date, datetime
from typing import Any

import anthropic
from pydantic import ValidationError

from . import db, outlook
from .config import ANTHROPIC_API_KEY
from .models import AuditDecision


MODEL = "claude-opus-4-7"
MAX_TOKENS = 1024
EMAIL_WINDOW_DAYS = 14

AUDIT_TOOL = {
    "name": "submit_audit_decision",
    "description": (
        "Submit your final decision about whether the transaction's existing QBO "
        "category is correct. Always call this tool exactly once."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_correct": {
                "type": "boolean",
                "description": (
                    "True if the existing QBO category is appropriate for this "
                    "transaction. False only if you have clear evidence it is wrong."
                ),
            },
            "corrected_category": {
                "type": ["string", "null"],
                "description": (
                    "Required when is_correct is false. Must be the exact name of "
                    "an account from the provided chart of accounts. Null when "
                    "is_correct is true."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "1-3 sentences explaining your decision.",
            },
            "supporting_email_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Graph message IDs of emails you used as evidence. Empty list "
                    "if you used no emails."
                ),
            },
        },
        "required": ["is_correct", "reasoning", "supporting_email_ids"],
    },
}


SYSTEM_PROMPT = """You are auditing existing transaction categorizations in QuickBooks Online for a bookkeeping client.

Your job is NOT to pick a category from scratch. The bookkeeper has already chosen one. \
Your job is to decide whether that existing choice is reasonable, and only flag it as \
incorrect if the available evidence clearly contradicts it.

Strong bias toward leaving the existing category alone. Mark is_correct = false only when:
- The evidence (vendor name, email receipts, transaction description) clearly identifies \
a different appropriate category, AND
- The existing category is implausible for that vendor or purchase

When in doubt, mark is_correct = true. False positives (flagging correct categorizations as \
wrong) are worse than false negatives (missing a miscategorization) in this workflow.

Candidate emails may include unrelated messages that happened to match the dollar amount. \
Inspect sender, subject, and body to judge relevance. If an email is unrelated, ignore it \
and do not cite it. If no emails are relevant, audit using only the transaction's vendor \
name and bank description.

When you cite emails as evidence, include their message IDs in supporting_email_ids so a \
human can audit your reasoning later.

If you mark is_correct = false, corrected_category MUST be the exact name of an account \
from the chart of accounts provided in the user message. Do not invent account names. \
Do not paraphrase. Copy the name character-for-character.

Always respond by calling the submit_audit_decision tool exactly once."""


def _coerce_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    raise ValueError(f"Cannot coerce {value!r} to date")


def _load_categories(client_id: int) -> list[dict]:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, description FROM categories WHERE client_id = ? ORDER BY name",
            (client_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _build_user_prompt(
    transaction: dict, emails: list[dict], categories: list[dict]
) -> str:
    if categories:
        chart_lines = [
            f"- {c['name']}" + (f": {c['description']}" if c.get("description") else "")
            for c in categories
        ]
        chart_block = "\n".join(chart_lines)
    else:
        chart_block = "(no categories loaded for this client)"

    if emails:
        email_blocks = []
        for e in emails:
            email_blocks.append(
                f"Email ID: {e.get('id')}\n"
                f"  From:    {e.get('sender')}\n"
                f"  Date:    {e.get('received_at')}\n"
                f"  Subject: {e.get('subject')}\n"
                f"  Preview: {e.get('body_preview')}"
            )
        email_block = "\n\n".join(email_blocks)
    else:
        email_block = "(no candidate emails found for this amount and date window)"

    return (
        "Transaction to audit:\n"
        f"  QBO ID:           {transaction.get('qbo_txn_id')}\n"
        f"  Type:             {transaction.get('txn_type')}\n"
        f"  Date:             {transaction.get('txn_date')}\n"
        f"  Amount:           {transaction.get('amount')}\n"
        f"  Vendor / payee:   {transaction.get('vendor_raw')}\n"
        f"  Existing QBO category: {transaction.get('current_qbo_category')}\n"
        "\n"
        "Chart of accounts (valid corrected_category values):\n"
        f"{chart_block}\n"
        "\n"
        "Candidate emails (may include unrelated messages — judge relevance):\n"
        f"{email_block}\n"
        "\n"
        "Decide whether the existing QBO category is correct. Call submit_audit_decision."
    )


def _extract_tool_use(response) -> dict:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_audit_decision":
            return block.input
    raise RuntimeError("Claude did not call submit_audit_decision.")


def _serialize_response(response) -> str:
    blocks = []
    for b in response.content:
        if getattr(b, "type", None) == "text":
            blocks.append({"type": "text", "text": b.text})
        elif getattr(b, "type", None) == "tool_use":
            blocks.append({"type": "tool_use", "name": b.name, "input": b.input})
        else:
            blocks.append({"type": getattr(b, "type", "unknown")})
    return json.dumps({
        "id": response.id,
        "model": response.model,
        "stop_reason": response.stop_reason,
        "content": blocks,
    })


def _call_claude(client, messages: list[dict]):
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[AUDIT_TOOL],
        tool_choice={"type": "tool", "name": "submit_audit_decision"},
        messages=messages,
    )


def audit_transaction(client_id: int, transaction: dict) -> AuditDecision:
    txn_date = _coerce_date(transaction["txn_date"])
    amount = float(transaction["amount"])

    emails = outlook.search_emails(
        client_id=client_id,
        amount=amount,
        txn_date=txn_date,
        window_days=EMAIL_WINDOW_DAYS,
    )

    categories = _load_categories(client_id)
    valid_category_names = {c["name"] for c in categories}

    user_prompt = _build_user_prompt(transaction, emails, categories)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages: list[dict] = [{"role": "user", "content": user_prompt}]

    # Attempt 1
    response = _call_claude(client, messages)
    decision, error = _parse_and_validate(response, valid_category_names)
    if decision is not None:
        return _attach_raw(decision, response, user_prompt)

    # Attempt 2 — retry once with the specific failure
    messages.append({"role": "assistant", "content": response.content})
    messages.append({
        "role": "user",
        "content": (
            f"Your previous tool call was rejected: {error}\n\n"
            "Please call submit_audit_decision again. If is_correct is false, "
            "corrected_category MUST be one of these exact strings:\n"
            + "\n".join(f"- {n}" for n in sorted(valid_category_names))
        ),
    })
    response2 = _call_claude(client, messages)
    decision, error = _parse_and_validate(response2, valid_category_names)
    if decision is None:
        raise RuntimeError(f"Audit failed after retry: {error}")
    return _attach_raw(decision, response2, user_prompt)


def _parse_and_validate(
    response, valid_category_names: set[str]
) -> tuple[AuditDecision | None, str | None]:
    try:
        tool_input = _extract_tool_use(response)
    except RuntimeError as e:
        return None, str(e)

    try:
        decision = AuditDecision(**tool_input)
    except ValidationError as e:
        return None, f"Pydantic validation failed: {e}"

    if not decision.is_correct:
        if decision.corrected_category not in valid_category_names:
            return None, (
                f"corrected_category {decision.corrected_category!r} is not in the "
                f"chart of accounts."
            )

    return decision, None


def _attach_raw(decision: AuditDecision, response, prompt: str) -> AuditDecision:
    # We stash the raw response + prompt on the decision via private attrs so the
    # caller can log them without re-running the model. Pydantic v2 allows this via
    # __dict__ but not via normal field access — use object.__setattr__.
    object.__setattr__(decision, "_raw_response", _serialize_response(response))
    object.__setattr__(decision, "_prompt", prompt)
    return decision


def log_decision(
    transaction_id: int,
    decision: AuditDecision,
    original_category: str,
    prompt: str,
    raw_response: str,
    action_taken: str,
) -> None:
    if action_taken not in {"no_change", "applied", "dry_run"}:
        raise ValueError(f"Invalid action_taken: {action_taken!r}")

    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (
                transaction_id, original_category, is_correct, new_category,
                reasoning, prompt_payload, model_response, supporting_emails,
                action_taken
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction_id,
                original_category,
                1 if decision.is_correct else 0,
                decision.corrected_category,
                decision.reasoning,
                json.dumps({"prompt": prompt, "system": SYSTEM_PROMPT}),
                raw_response,
                json.dumps(decision.supporting_email_ids),
                action_taken,
            ),
        )
