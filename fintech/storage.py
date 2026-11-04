"""Слой хранения данных на SQLite.

Все денежные операции выполняются внутри одной транзакции БД
(BEGIN IMMEDIATE), что гарантирует атомарность перевода: либо списание
и зачисление проходят оба, либо не проходит ничего.
"""
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    login         TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    failed_logins INTEGER NOT NULL DEFAULT 0,
    blocked       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS accounts (
    number     TEXT PRIMARY KEY,
    client_id  INTEGER NOT NULL REFERENCES clients(id),
    balance    INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
    currency   TEXT NOT NULL DEFAULT 'RUB',
    status     TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED','FROZEN')),
    opened_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT UNIQUE,
    kind            TEXT NOT NULL CHECK (kind IN ('DEPOSIT','WITHDRAW','TRANSFER')),
    from_account    TEXT REFERENCES accounts(number),
    to_account      TEXT REFERENCES accounts(number),
    amount          INTEGER NOT NULL CHECK (amount > 0),
    status          TEXT NOT NULL CHECK (status IN ('DONE','REJECTED','ON_REVIEW')),
    reason          TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  INTEGER,
    action     TEXT NOT NULL,
    details    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_tx_from_date ON transactions(from_account, created_at);
"""


class Database:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def query(self, sql: str, params=()):
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params=()):
        return self.conn.execute(sql, params).fetchone()
