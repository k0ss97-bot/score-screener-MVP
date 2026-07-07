from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from score_screener.data import (
    display_binance_symbol,
    display_quote_symbol,
    generate_demo_candles,
    generate_demo_universe,
    normalize_binance_symbol,
    normalize_exchange_symbol,
    parse_symbol_list,
)
from score_screener.models import ScannerConfig
from score_screener.scanner import detect_consolidation, enrich_candles, scan_symbol, scan_universe


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


if __name__ == "__main__":
    unittest.main()
