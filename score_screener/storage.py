from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Candle, SignalResult


SCHEMA = """
CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT 'unknown',
    base_asset TEXT,
    quote_asset TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    min_volume_filter REAL,
    listed_at TEXT,
    PRIMARY KEY (symbol, exchange)
);

CREATE TABLE IF NOT EXISTS candles_1h (
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    quote_volume REAL,
    PRIMARY KEY (symbol, timestamp)
);

CREATE TABLE IF NOT EXISTS features_1h (
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    rsi REAL,
    macd_hist REAL,
    bb_width REAL,
    atr_pct REAL,
    ema20 REAL,
    ema50 REAL,
    anchored_vwap REAL,
    rel_volume REAL,
    volume_zscore REAL,
    mfi REAL,
    adx REAL,
    base_high REAL,
    base_low REAL,
    base_range_pct REAL,
    close_position_in_range REAL,
    PRIMARY KEY (symbol, timestamp)
);

CREATE TABLE IF NOT EXISTS signals (
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    impulse_score INTEGER NOT NULL,
    reversal_score INTEGER NOT NULL,
    reason TEXT,
    features_json TEXT,
    PRIMARY KEY (symbol, timestamp, signal_type)
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.commit()


def save_candles(connection: sqlite3.Connection, symbol: str, candles: list[Candle]) -> None:
    connection.executemany(
        """
        INSERT OR REPLACE INTO candles_1h
        (symbol, timestamp, open, high, low, close, volume, quote_volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                symbol,
                candle.timestamp.isoformat(),
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                candle.quote_volume,
            )
            for candle in candles
        ],
    )
    connection.commit()


def save_signal(connection: sqlite3.Connection, result: SignalResult) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO signals
        (symbol, timestamp, signal_type, impulse_score, reversal_score, reason, features_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.symbol,
            result.timestamp.isoformat(),
            result.signal_type,
            result.impulse_score,
            result.reversal_score,
            "; ".join(result.reasons),
            json.dumps(result.features, default=str),
        ),
    )
    connection.commit()
