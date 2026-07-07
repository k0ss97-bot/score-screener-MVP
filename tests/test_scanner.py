from __future__ import annotations

import io
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from score_screener.data import (
    display_binance_symbol,
    display_quote_symbol,
    drop_incomplete_candles,
    generate_demo_candles,
    generate_demo_universe,
    normalize_binance_symbol,
    normalize_exchange_symbol,
    parse_symbol_list,
)
from score_screener.cli import main
from score_screener.models import Candle, ScannerConfig
from score_screener.scanner import detect_consolidation, enrich_candles, scan_symbol, scan_universe
from score_screener.state import SignalState


class ScreenerTests(unittest.TestCase):
    def test_detects_consolidation_before_breakout(self) -> None:
        candles = generate_demo_candles("ALGO/USDT", breakout=True)
        enriched = enrich_candles(candles)
        base = detect_consolidation(enriched, ScannerConfig())

        self.assertIsNotNone(base)
        self.assertLessEqual(base.range_pct, 0.18)
        self.assertGreaterEqual(base.days, 5)

    def test_breakout_scores_high(self) -> None:
        candles = generate_demo_candles("ALGO/USDT", breakout=True)
        result = scan_symbol("ALGO/USDT", candles, ScannerConfig())

        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.impulse_score, 75)
        self.assertIn(result.signal_type, {"BREAKOUT", "MOMENTUM", "STRONG PRE-BREAKOUT"})
        self.assertTrue(result.features["above_anchored_vwap"])

    def test_exhaustion_adds_exit_risk(self) -> None:
        candles = generate_demo_candles("LATE/USDT", breakout=True, exhausted=True)
        result = scan_symbol("LATE/USDT", candles, ScannerConfig())

        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.reversal_score, 70)
        self.assertEqual(result.signal_type, "EXIT RISK")

    def test_universe_filters_quiet_symbol(self) -> None:
        results = scan_universe(generate_demo_universe(), ScannerConfig(), min_score=60)
        symbols = {result.symbol for result in results}

        self.assertIn("ALGO/USDT", symbols)
        self.assertIn("LATE/USDT", symbols)
        self.assertNotIn("QUIET/USDT", symbols)

    def test_exchange_symbol_helpers(self) -> None:
        self.assertEqual(parse_symbol_list("BTCUSDT, ETH/USDT\nSOLUSDT"), ["BTCUSDT", "ETH/USDT", "SOLUSDT"])
        self.assertEqual(normalize_exchange_symbol("btc/usdt"), "BTCUSDT")
        self.assertEqual(display_quote_symbol("ETHUSDT"), "ETH/USDT")
        self.assertEqual(normalize_binance_symbol("eth/usdt"), "ETHUSDT")
        self.assertEqual(display_binance_symbol("SOLUSDT"), "SOL/USDT")

    def test_drops_incomplete_hourly_candle(self) -> None:
        candles = [
            Candle(datetime(2026, 1, 1, 0), 1, 1, 1, 1, 1, symbol="BTC/USDT"),
            Candle(datetime(2026, 1, 1, 1), 1, 1, 1, 1, 1, symbol="BTC/USDT"),
        ]

        complete = drop_incomplete_candles(candles, "60", now=datetime(2026, 1, 1, 1, 30))

        self.assertEqual([item.timestamp.hour for item in complete], [0])

    def test_signal_state_dedupes_same_type_until_inactive(self) -> None:
        result = scan_symbol("ALGO/USDT", generate_demo_candles("ALGO/USDT", breakout=True), ScannerConfig())
        self.assertIsNotNone(result)

        state = SignalState()
        self.assertTrue(state.is_new(result))
        state.mark_sent(result)
        self.assertFalse(state.is_new(result))

        state.mark_inactive({"ALGO/USDT"}, set())
        self.assertTrue(state.is_new(result))

    def test_cli_persists_demo_scan_to_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "scan.sqlite"
            with redirect_stdout(io.StringIO()):
                exit_code = main(["--demo", "--min-score", "60", "--sqlite-db", str(db_path)])

            self.assertEqual(exit_code, 0)
            with closing(sqlite3.connect(db_path)) as connection:
                candle_count = connection.execute("SELECT COUNT(*) FROM candles_1h").fetchone()[0]
                signal_count = connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0]

            self.assertGreater(candle_count, 0)
            self.assertGreaterEqual(signal_count, 2)


if __name__ == "__main__":
    unittest.main()
