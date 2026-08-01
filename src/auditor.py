import json
from datetime import date, datetime
from typing import Any

import anthropic
from pydantic import ValidationError

from . import db, outlook
from .config import ANTHROPIC_API_KEY, RECEIPTS_FROM
from .models import AuditDecision


MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024
EMAIL_WINDOW_DAYS = 14
SENDER_WINDOW_DAYS = 30  # Last N days from now when pulling all emails from RECEIPTS_FROM.
SENDER_MAX_RESULTS = 50  # Cap on emails per audit when in sender-mode.
MAX_SEARCHES = 3         # Cap on search_emails tool calls (fallback mode only).
MAX_TURNS = 6            # Cap on total Claude turns (fallback mode only).

SEARCH_TOOL = {
    "name": "search_emails",
    "description": (
        "Search the user's Outlook inbox for emails relevant to the transaction. "
        "Use this when the starter emails (already provided) are insufficient. "
        "The search is centered on the transaction date. "
        f"You may call this at most {MAX_SEARCHES} times per audit — make each one count. "
        "Good queries: the vendor name, a memorable word from the bank description, "
        "or the dollar amount. Avoid empty or single-letter queries."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Full-text query searched across subject, body, and sender. "
                    "Examples: 'Hotel BLU', 'Tania Nursery receipt', '124.50'."
                ),
            },
            "window_days": {
                "type": "integer",
                "description": (
                    "Date window (±N days around the transaction date). Default 14. "
                    "Max 60."
                ),
            },
        },
        "required": ["query"],
    },
}

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
            "suggested_payee": {
                "type": ["string", "null"],
                "description": (
                    "For OUTGOING transactions (expenses): cleaned-up vendor/payee "
                    "name extracted from the transaction description or email "
                    "evidence. Examples: 'Zoom' (not "
                    "'ATM RCR Payment ZOOM.COM 888-799 ZOOM.US CA #9204'), "
                    "'Kruti Desai' for check payments identified via email, "
                    "'Constant Contact' for CCI*CONSTANT-CON. Null for incoming "
                    "transactions or when no identifiable payee."
                ),
            },
            "suggested_payor": {
                "type": ["string", "null"],
                "description": (
                    "For INCOMING transactions (deposits, credits, receipts): "
                    "cleaned-up name of the person or organization that sent "
                    "the money. Examples: 'Ketan Patel' for an incoming Zelle, "
                    "'United Arts Council' for a grant deposit, 'Zeffy' for a "
                    "platform deposit. Null for outgoing transactions or when "
                    "no identifiable payor."
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

You are given a starter set of emails matched against the dollar amount. These may include \
unrelated messages. Inspect sender, subject, and body to judge relevance.

If the starter emails don't contain useful evidence — especially if the transaction's \
vendor name or bank description suggests a category you can't confirm from the starter set \
— call the search_emails tool to look for receipts by vendor name or other keywords. \
Don't guess "no_change" because you have no evidence; search for evidence first.

You may call search_emails up to 3 times per audit. After each search, decide whether the \
new results change your verdict.

When you cite emails as evidence, include their message IDs in supporting_email_ids so a \
human can audit your reasoning later.

Also fill in either suggested_payee OR suggested_payor (never both) based on transaction \
direction:
- OUTGOING transaction (expense / money leaving): use suggested_payee for the vendor being paid
- INCOMING transaction (deposit / money coming in): use suggested_payor for the source of funds

Clean up the name — strip bank codes, phone numbers, ATM prefixes, extra whitespace. \
Resolve via email evidence when the description is opaque (e.g. "Check 1187" + email \
listing "Ashwani Arora CPA" → payee is "Ashwani Arora CPA"). Set to null only when there's \
no identifiable name.

If you mark is_correct = false, corrected_category MUST be the exact name of an account \
from the chart of accounts provided in the user message. Do not invent account names. \
Do not paraphrase. Copy the name character-for-character.

Always respond by calling the submit_audit_decision tool exactly once."""


def _coerce_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(s[:10], fmt).date()
            except ValueError:
                continue
    raise ValueError(f"Cannot coerce {value!r} to date")


def _load_categories(client_id: int) -> list[dict]:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, description FROM categories WHERE client_id = ? ORDER BY name",
            (client_id,),
        ).fetchall()
    return [dict(r) for r in rows]


SUGGEST_SYSTEM_PROMPT = """You are categorizing fresh bank transactions that have not yet been assigned a QBO account.

Your job is to pick the single most appropriate account from the chart of accounts based on:
- The vendor / bank description
- The transaction date and amount (outflow = expense, inflow = income)
- Any matching email receipt in the user's mailbox

Use submit_audit_decision to return your suggestion:
- If you can confidently pick a category: set is_correct = false and corrected_category = your suggestion. (We reuse the existing tool schema; "is_correct=false + corrected_category" means "this is my suggestion.")
- If you genuinely cannot determine a category (e.g. anonymous deposit with no vendor and no matching email): set is_correct = true and corrected_category = null. The bookkeeper will leave the row uncategorized.

corrected_category MUST be the exact name of an account from the chart of accounts. Copy character-for-character.

When you cite emails as evidence, include their IDs in supporting_email_ids.

Always call submit_audit_decision exactly once."""


def _build_suggest_prompt(
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
        email_block = "(no candidate emails in the date window)"

    direction = "OUTFLOW (expense)" if transaction.get("direction") == "out" else "INFLOW (income)"

    return (
        "Uncategorized bank transaction:\n"
        f"  Date:             {transaction.get('txn_date')}\n"
        f"  Amount:           {transaction.get('amount')}\n"
        f"  Direction:        {direction}\n"
        f"  Bank description: {transaction.get('vendor_raw') or '(none)'}\n"
        f"  From/To:          {transaction.get('counterparty') or '(none)'}\n"
        "\n"
        "Chart of accounts (valid corrected_category values):\n"
        f"{chart_block}\n"
        "\n"
        "Candidate emails from the configured receipt mailbox:\n"
        f"{email_block}\n"
        "\n"
        "Pick the best category. Call submit_audit_decision."
    )


def suggest_category(client_id: int, transaction: dict) -> AuditDecision:
    """Single-call suggestion for an uncategorized bank transaction.
    Returns AuditDecision where:
      - is_correct=False + corrected_category set => Claude's suggested category
      - is_correct=True + corrected_category=None => Claude couldn't determine
    """
    txn_date = _coerce_date(transaction["txn_date"])

    if RECEIPTS_FROM:
        try:
            emails = outlook.fetch_from_sender(
                client_id=client_id,
                sender=RECEIPTS_FROM,
                centered_date=txn_date,
                window_days=SENDER_WINDOW_DAYS,
                max_results=SENDER_MAX_RESULTS,
            )
        except RuntimeError as e:
            emails = []
            print(f"  (warning) sender fetch failed: {e}")
    else:
        emails = []

    categories = _load_categories(client_id)
    valid_category_names = {c["name"] for c in categories}
    user_prompt = _build_suggest_prompt(transaction, emails, categories)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_prompt}]

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SUGGEST_SYSTEM_PROMPT,
        tools=[AUDIT_TOOL],
        tool_choice={"type": "tool", "name": "submit_audit_decision"},
        messages=messages,
    )
    submit = next(
        (b for b in response.content
         if getattr(b, "type", None) == "tool_use" and b.name == "submit_audit_decision"),
        None,
    )
    if submit is None:
        raise RuntimeError("Claude did not call submit_audit_decision.")

    decision, error = _parse_and_validate_decision(submit.input, valid_category_names)
    if decision is None:
        raise RuntimeError(f"Suggestion failed: {error}")

    conversation_log = [{
        "turn": 1,
        "stop_reason": response.stop_reason,
        "content": _serialize_response(response),
    }]
    return _attach_raw(decision, conversation_log, user_prompt)


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


def _serialize_response(response) -> list[dict]:
    blocks = []
    for b in response.content:
        if getattr(b, "type", None) == "text":
            blocks.append({"type": "text", "text": b.text})
        elif getattr(b, "type", None) == "tool_use":
            blocks.append({
                "type": "tool_use",
                "id": b.id,
                "name": b.name,
                "input": b.input,
            })
        else:
            blocks.append({"type": getattr(b, "type", "unknown")})
    return blocks


def _format_email_results(results: list[dict]) -> str:
    if not results:
        return "(no emails matched)"
    parts = []
    for e in results:
        parts.append(
            f"Email ID: {e.get('id')}\n"
            f"  From:    {e.get('sender')}\n"
            f"  Date:    {e.get('received_at')}\n"
            f"  Subject: {e.get('subject')}\n"
            f"  Preview: {e.get('body_preview')}"
        )
    return "\n\n".join(parts)


def _call_claude(client, messages: list[dict]):
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[SEARCH_TOOL, AUDIT_TOOL],
        tool_choice={"type": "any"},  # force at least one tool call per turn
        messages=messages,
    )


def _parse_and_validate_decision(
    tool_input: dict, valid_category_names: set[str]
) -> tuple[AuditDecision | None, str | None]:
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


def audit_transaction(client_id: int, transaction: dict) -> AuditDecision:
    if RECEIPTS_FROM:
        return _audit_with_sender(client_id, transaction)
    return _audit_with_tool_loop(client_id, transaction)


def _audit_with_sender(client_id: int, transaction: dict) -> AuditDecision:
    """Single-call audit. Pulls all emails from RECEIPTS_FROM within ±SENDER_WINDOW_DAYS
    of the txn date and hands the whole batch to Claude in one shot."""
    txn_date = _coerce_date(transaction["txn_date"])

    try:
        emails = outlook.fetch_from_sender(
            client_id=client_id,
            sender=RECEIPTS_FROM,
            centered_date=txn_date,
            window_days=SENDER_WINDOW_DAYS,
            max_results=SENDER_MAX_RESULTS,
        )
    except RuntimeError as e:
        # If the email pull fails, audit blind rather than dying entirely.
        emails = []
        print(f"  (warning) sender fetch failed for txn {transaction.get('qbo_txn_id')}: {e}")

    categories = _load_categories(client_id)
    valid_category_names = {c["name"] for c in categories}
    user_prompt = _build_user_prompt(transaction, emails, categories)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_prompt}]

    # Single call, decision tool only, forced.
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[AUDIT_TOOL],
        tool_choice={"type": "tool", "name": "submit_audit_decision"},
        messages=messages,
    )

    submit = next(
        (b for b in response.content
         if getattr(b, "type", None) == "tool_use" and b.name == "submit_audit_decision"),
        None,
    )
    if submit is None:
        raise RuntimeError("Claude did not call submit_audit_decision.")

    decision, error = _parse_and_validate_decision(submit.input, valid_category_names)
    if decision is not None:
        conversation_log = [{
            "turn": 1,
            "stop_reason": response.stop_reason,
            "content": _serialize_response(response),
        }]
        return _attach_raw(decision, conversation_log, user_prompt)

    # Retry once with the specific failure fed back.
    messages.append({"role": "assistant", "content": response.content})
    messages.append({
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": submit.id,
            "content": (
                f"Decision rejected: {error}\n\n"
                "Retry submit_audit_decision. If is_correct is false, "
                "corrected_category MUST be one of these exact strings:\n"
                + "\n".join(f"- {n}" for n in sorted(valid_category_names))
            ),
            "is_error": True,
        }],
    })
    retry = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[AUDIT_TOOL],
        tool_choice={"type": "tool", "name": "submit_audit_decision"},
        messages=messages,
    )
    retry_submit = next(
        (b for b in retry.content
         if getattr(b, "type", None) == "tool_use" and b.name == "submit_audit_decision"),
        None,
    )
    if retry_submit is None:
        raise RuntimeError("Claude did not call submit_audit_decision on retry.")
    decision, error = _parse_and_validate_decision(retry_submit.input, valid_category_names)
    if decision is None:
        raise RuntimeError(f"Audit failed after retry: {error}")
    conversation_log = [
        {"turn": 1, "stop_reason": response.stop_reason, "content": _serialize_response(response)},
        {"turn": 2, "stop_reason": retry.stop_reason, "content": _serialize_response(retry)},
    ]
    return _attach_raw(decision, conversation_log, user_prompt)


def _audit_with_tool_loop(client_id: int, transaction: dict) -> AuditDecision:
    """Fallback when RECEIPTS_FROM isn't set. Pre-fetches by amount, gives Claude
    a search tool, runs a multi-turn loop."""
    txn_date = _coerce_date(transaction["txn_date"])
    amount = float(transaction["amount"])

    # Pre-fetch a starter set of emails by amount.
    starter_emails = outlook.search_emails(
        client_id=client_id,
        amount=amount,
        txn_date=txn_date,
        window_days=EMAIL_WINDOW_DAYS,
    )

    categories = _load_categories(client_id)
    valid_category_names = {c["name"] for c in categories}

    user_prompt = _build_user_prompt(transaction, starter_emails, categories)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages: list[dict] = [{"role": "user", "content": user_prompt}]

    # Full conversation log we'll persist to audit_log.model_response.
    conversation_log: list[dict] = []

    searches_done = 0

    for turn in range(MAX_TURNS):
        response = _call_claude(client, messages)
        assistant_blocks = _serialize_response(response)
        conversation_log.append({
            "turn": turn + 1,
            "stop_reason": response.stop_reason,
            "content": assistant_blocks,
        })

        tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            raise RuntimeError("Claude ended without calling a tool.")

        # If Claude submitted a decision, validate it.
        submit = next((b for b in tool_uses if b.name == "submit_audit_decision"), None)
        if submit is not None:
            decision, error = _parse_and_validate_decision(submit.input, valid_category_names)
            if decision is not None:
                return _attach_raw(decision, conversation_log, user_prompt)
            # Invalid — feed the error back and let Claude retry.
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tu in tool_uses:
                if tu.id == submit.id:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": (
                            f"Decision rejected: {error}\n\n"
                            "Retry submit_audit_decision. If is_correct is false, "
                            "corrected_category MUST be one of these exact strings:\n"
                            + "\n".join(f"- {n}" for n in sorted(valid_category_names))
                        ),
                        "is_error": True,
                    })
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": "Skipped — fix the rejected decision first.",
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # No submit — Claude is searching. Execute each search_emails call.
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tu in tool_uses:
            if tu.name != "search_emails":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": f"Unknown tool {tu.name!r}.",
                    "is_error": True,
                })
                continue
            if searches_done >= MAX_SEARCHES:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": (
                        f"Search limit reached ({MAX_SEARCHES}). "
                        "Call submit_audit_decision now with your best judgment."
                    ),
                    "is_error": True,
                })
                continue

            searches_done += 1
            query = (tu.input.get("query") or "").strip()
            window_days = int(tu.input.get("window_days") or EMAIL_WINDOW_DAYS)
            window_days = max(1, min(window_days, 60))

            if not query:
                content = "Empty query rejected. Provide a non-empty search string."
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": content,
                    "is_error": True,
                })
                continue

            try:
                results = outlook.search_by_query(
                    client_id=client_id,
                    query=query,
                    centered_date=txn_date,
                    window_days=window_days,
                )
                content = _format_email_results(results)
            except Exception as e:
                content = f"Search failed: {e}"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": content,
            })
            conversation_log.append({
                "tool_result": {"tool_use_id": tu.id, "query": query, "content": content},
            })

        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"Audit failed: max turns ({MAX_TURNS}) exceeded without a decision.")


def _attach_raw(decision: AuditDecision, conversation_log: list[dict], prompt: str) -> AuditDecision:
    # Stash the full multi-turn conversation + initial prompt on the decision so
    # the CLI can persist them to audit_log without re-running the model.
    object.__setattr__(decision, "_raw_response", json.dumps(conversation_log))
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
