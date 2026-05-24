import os
import sqlite3

from .config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_name TEXT NOT NULL,
    qbo_realm_id TEXT,
    qbo_access_token TEXT,
    qbo_refresh_token TEXT,
    qbo_token_expires_at TIMESTAMP,
    outlook_access_token TEXT,
    outlook_refresh_token TEXT,
    outlook_token_expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    qbo_account_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    UNIQUE(client_id, qbo_account_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    qbo_txn_id TEXT NOT NULL,
    txn_date DATE NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    vendor_raw TEXT,
    current_qbo_category TEXT,
    audit_status TEXT DEFAULT 'pending',
    last_audited_at TIMESTAMP,
    UNIQUE(client_id, qbo_txn_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    original_category TEXT NOT NULL,
    is_correct INTEGER NOT NULL,
    new_category TEXT,
    reasoning TEXT NOT NULL,
    prompt_payload TEXT,
    model_response TEXT,
    supporting_emails TEXT,
    action_taken TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def add_client(firm_name: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO clients (firm_name) VALUES (?)", (firm_name,)
        )
        return cursor.lastrowid


def list_clients() -> list:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM clients").fetchall()
        return [dict(row) for row in rows]
