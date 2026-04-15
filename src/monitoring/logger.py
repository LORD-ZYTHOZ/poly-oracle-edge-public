"""Structured signal/trade logger to SQLite."""
import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path

from src.models import Signal, Trade

logger = logging.getLogger(__name__)

CREATE_SIGNALS = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    market_id TEXT,
    time_to_expiry REAL,
    ref_price REAL,
    btc_price REAL,
    delta REAL,
    implied_prob_up REAL,
    market_price_up REAL,
    edge REAL,
    direction TEXT,
    liquidity REAL
);
"""

CREATE_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    market_id TEXT,
    side TEXT,
    size REAL,
    entry_price REAL,
    expected_value REAL,
    mode TEXT,
    status TEXT,
    pnl REAL,
    tx_hash TEXT
);
"""


class SignalLogger:
    def __init__(self, db_path: str = "data/poly_edge.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(CREATE_SIGNALS)
        self._conn.execute(CREATE_TRADES)
        self._conn.commit()

    def log_signal(self, signal: Signal) -> None:
        self._conn.execute(
            """INSERT INTO signals
               (ts, market_id, time_to_expiry, ref_price, btc_price, delta,
                implied_prob_up, market_price_up, edge, direction, liquidity)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (signal.ts, signal.market_id, signal.time_to_expiry, signal.ref_price,
             signal.btc_price, signal.delta, signal.implied_prob_up,
             signal.market_price_up, signal.edge, signal.direction, signal.liquidity),
        )
        self._conn.commit()

    def log_trade(self, trade: Trade) -> None:
        self._conn.execute(
            """INSERT INTO trades
               (ts, market_id, side, size, entry_price, expected_value,
                mode, status, pnl, tx_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (trade.ts, trade.market_id, trade.side, trade.size, trade.entry_price,
             trade.expected_value, trade.mode.value, trade.status.value,
             trade.pnl, trade.tx_hash),
        )
        self._conn.commit()
