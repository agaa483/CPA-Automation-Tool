# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # then fill in credentials
python -m src.cli init-db
```

The app is invoked as `python -m src.cli <command>`.

## CLI Commands

```bash
# One-time setup per client
python -m src.cli add-client --firm-name "Acme LLC"      # returns client_id
python -m src.cli qbo-connect --client-id 1               # opens browser for OAuth
python -m src.cli outlook-connect --client-id 1           # opens browser for OAuth
python -m src.cli qbo-sync-categories --client-id 1       # pull chart of accounts into DB

# Inspection
python -m src.cli qbo-pull --client-id 1 [--days-back 30] [--account "Checking"]
python -m src.cli outlook-search --client-id 1 --amount 124.50 --date 2024-01-15

# Auditing
python -m src.cli audit --client-id 1 --txn-id 123        # audit one txn (read-only)
python -m src.cli run --client-id 1 --dry-run             # bulk audit, no QBO writes
python -m src.cli run --client-id 1                       # bulk audit + write corrections to QBO
python -m src.cli run                                      # all clients
```

## Required Environment Variables

```
QBO_CLIENT_ID, QBO_CLIENT_SECRET, QBO_REDIRECT_URI, QBO_ENVIRONMENT
MS_CLIENT_ID, MS_CLIENT_SECRET, MS_TENANT_ID, MS_REDIRECT_URI
ANTHROPIC_API_KEY
DB_PATH          # optional, defaults to data/app.db
RECEIPTS_FROM    # optional; see Audit Modes below
```

Both OAuth redirect URIs must point to `http://localhost:8000/callback`.

## Architecture

The tool audits existing QuickBooks Online transaction categorizations using Claude AI and Outlook email receipts as evidence.

**Data flow for `run`:**
1. Pull transactions from QBO API → upsert into local SQLite `transactions` table (status=`pending`)
2. For each pending txn, call `auditor.audit_transaction()` → Claude returns `AuditDecision`
3. If `is_correct=False` and not `--dry-run`: call `qbo.update_category()` to write back to QBO
4. Log everything to `audit_log`; set `audit_status` to `verified`, `corrected`, or `do_not_audit`

**SQLite schema (`src/db.py`):** `clients` → `categories` (chart of accounts) → `transactions` → `audit_log`. Each client row holds both QBO and Outlook OAuth tokens.

**Audit modes (`src/auditor.py`):**
- **Sender mode** (when `RECEIPTS_FROM` is set): Pre-fetches all emails from a single known sender (e.g., a receipt-forwarding address) within ±30 days of the txn date. Passes the full batch to Claude in one call. Faster and more reliable.
- **Tool loop mode** (fallback): Pre-fetches emails by dollar amount, then runs a multi-turn agentic loop where Claude can call `search_emails` up to 3 times to look for receipts by vendor name or keywords (max 6 turns total).

**Claude integration:** Uses `claude-opus-4-7` with two tools — `search_emails` (agentic search, tool loop only) and `submit_audit_decision` (forced final call). `AuditDecision` (Pydantic model in `src/models.py`) validates that `corrected_category` must exactly match a name from the local chart of accounts. On validation failure, Claude gets one retry with the error message and the valid category list.

**QBO write-back:** `qbo.update_category()` only handles `Purchase` objects. It swaps the first expense line's `AccountRef`. Item-based lines are converted to account-based lines on update.

**Safety guard:** If a correction was previously applied (`action_taken='applied'`) but the CPA reverted it (current QBO category matches `original_category` in audit_log), the txn is permanently marked `do_not_audit` to avoid re-fighting the CPA.

**`action_taken` values:** `no_change` (Claude confirmed correct), `applied` (wrote to QBO), `dry_run` (flagged but not written).
