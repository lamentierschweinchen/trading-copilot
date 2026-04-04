from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "copilot.db"
LEGACY_TRADES = DATA_DIR / "trades.json"

_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _init_tables(_conn)
        _migrate_legacy(_conn)
    return _conn


def _init_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            recommendation_json TEXT NOT NULL,
            logged_at TEXT NOT NULL,
            resolved INTEGER DEFAULT 0,
            outcome TEXT,
            actual_exit_price REAL,
            pnl_pct REAL,
            resolved_at TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            regime TEXT,
            confidence REAL,
            rec_count INTEGER DEFAULT 0,
            assets_json TEXT,
            summary_json TEXT
        );

        CREATE TABLE IF NOT EXISTS daily_snapshots (
            date TEXT PRIMARY KEY,
            total_trades INTEGER,
            resolved_trades INTEGER,
            win_rate REAL,
            cumulative_pnl REAL,
            data_json TEXT
        );
    """)


def _migrate_legacy(conn: sqlite3.Connection):
    """Migrate trades.json into SQLite on first run."""
    if not LEGACY_TRADES.exists():
        return

    # Check if we already have trades
    count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    if count > 0:
        return

    try:
        trades = json.loads(LEGACY_TRADES.read_text())
        if not trades:
            return

        for t in trades:
            conn.execute(
                """INSERT OR IGNORE INTO trades
                   (id, recommendation_json, logged_at, resolved, outcome,
                    actual_exit_price, pnl_pct, resolved_at, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    t["id"],
                    json.dumps(t["recommendation"]),
                    t["logged_at"],
                    1 if t.get("resolved") else 0,
                    t.get("outcome"),
                    t.get("actual_exit_price"),
                    t.get("pnl_pct"),
                    t.get("resolved_at"),
                    t.get("notes"),
                ),
            )
        conn.commit()
        logger.info("Migrated %d trades from trades.json to SQLite", len(trades))

        # Rename legacy file
        LEGACY_TRADES.rename(LEGACY_TRADES.with_suffix(".json.bak"))
        logger.info("Renamed trades.json -> trades.json.bak")
    except Exception as e:
        logger.error("Failed to migrate legacy trades: %s", e)


def log_session(regime: str | None, confidence: float | None, rec_count: int,
                assets_json: str | None = None, summary_json: str | None = None) -> int:
    """Log a session to the database. Returns the session ID."""
    from datetime import datetime
    conn = get_conn()
    cursor = conn.execute(
        """INSERT INTO sessions (timestamp, regime, confidence, rec_count, assets_json, summary_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), regime, confidence, rec_count, assets_json, summary_json),
    )
    conn.commit()
    return cursor.lastrowid


def get_sessions(limit: int = 20) -> list[dict]:
    """Get recent sessions for the timeline."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, timestamp, regime, confidence, rec_count, assets_json FROM sessions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    results = []
    for r in rows:
        symbols = None
        if r["assets_json"]:
            try:
                assets = json.loads(r["assets_json"])
                symbols = [a.get("symbol") for a in assets if a.get("symbol")]
            except Exception:
                pass
        results.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "regime": r["regime"],
            "confidence": r["confidence"],
            "rec_count": r["rec_count"],
            "symbols": symbols,
        })
    return results
