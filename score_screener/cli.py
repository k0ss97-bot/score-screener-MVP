from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .alerts import format_alert
from .data import (
    fetch_binance_universe,
    fetch_bybit_universe,
    generate_demo_universe,
    load_csv_grouped,
    load_symbols_file,
    parse_symbol_list,
)
from .env import load_env_file
from .models import ScannerConfig, SignalResult
from .scanner import scan_universe
from .state import SignalState
from .storage import connect, initialize_schema, save_candles, save_signal
from .telegram import send_telegram_message


def _result_to_dict(result: SignalResult) -> dict:
    return {
        "symbol": result.symbol,
        "timestamp": result.timestamp.isoformat(),
        "signal_type": result.signal_type,
        "impulse_score": result.impulse_score,
        "reversal_score": result.reversal_score,
        "reasons": result.reasons,
        "base": {
            "start": result.base.start.isoformat(),
            "end": result.base.end.isoformat(),
            "days": result.base.days,
            "high": result.base.high,
            "low": result.base.low,
            "range_pct": result.base.range_pct,
            "bb_width_percentile": result.base.bb_width_percentile,
            "atr_pct_percentile": result.base.atr_pct_percentile,
        },
        "features": result.features,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automatic score screener MVP")
    parser.add_argument("--demo", action="store_true", help="Run on synthetic breakout/exhaustion candles")
    parser.add_argument("--csv", type=Path, help="Path to 1H OHLCV CSV")
    parser.add_argument("--exchange", choices=["bybit", "binance"], help="Live exchange. Defaults to SCREENER_EXCHANGE or bybit")
    parser.add_argument("--binance-symbols", help="Comma-separated Binance symbols, e.g. BTCUSDT,ETHUSDT")
    parser.add_argument("--bybit-symbols", help="Comma-separated Bybit symbols. Empty means all active quote pairs")
    parser.add_argument("--bybit-category", default=None, help="Bybit category: spot, linear, inverse. Defaults to spot")
    parser.add_argument("--quote-coin", default=None, help="Quote coin for auto universe. Defaults to USDT")
    parser.add_argument("--symbols-file", type=Path, help="Text file with comma/newline-separated symbols")
    parser.add_argument("--kline-limit", type=int, default=None, help="1H candles per symbol, max 1000")
    parser.add_argument("--max-symbols", type=int, default=None, help="Safety cap for live universe. 0 means all")
    parser.add_argument("--request-delay-seconds", type=float, default=None, help="Delay between live kline requests")
    parser.add_argument("--symbol", help="Symbol override when CSV has no symbol column")
    parser.add_argument("--min-score", type=int, default=None, help="Minimum impulse score to print")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text alerts")
    parser.add_argument("--base-range-pct", type=float, default=0.18, help="Max base range, e.g. 0.18 for 18%%")
    parser.add_argument("--telegram", action="store_true", help="Send matching alerts to Telegram")
    parser.add_argument("--telegram-token", help="Telegram bot token. Defaults to TELEGRAM_BOT_TOKEN")
    parser.add_argument("--telegram-chat-id", help="Telegram chat id. Defaults to TELEGRAM_CHAT_ID")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Optional env file to load")
    parser.add_argument("--state-file", type=Path, default=Path(".screener_state.json"), help="Signal dedupe state file")
    parser.add_argument("--sqlite-db", type=Path, default=None, help="Optional SQLite database path for candles and signals")
    parser.add_argument("--send-all", action="store_true", help="Send alerts even if they were already sent")
    parser.add_argument("--loop", action="store_true", help="Run forever with sleep between scans")
    parser.add_argument("--interval-minutes", type=float, default=None, help="Loop sleep interval")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.env_file and args.env_file.exists():
        load_env_file(args.env_file)

    args.min_score = args.min_score if args.min_score is not None else int(os.environ.get("SCREENER_MIN_SCORE", "40"))
    args.interval_minutes = (
        args.interval_minutes if args.interval_minutes is not None else float(os.environ.get("SCREENER_INTERVAL_MINUTES", "60"))
    )
    args.exchange = args.exchange or os.environ.get("SCREENER_EXCHANGE", "bybit").lower()
    args.bybit_category = args.bybit_category or os.environ.get("SCREENER_BYBIT_CATEGORY", "spot")
    args.quote_coin = args.quote_coin or os.environ.get("SCREENER_QUOTE", "USDT")
    args.kline_limit = args.kline_limit if args.kline_limit is not None else int(os.environ.get("SCREENER_KLINE_LIMIT", "1000"))
    sqlite_db = os.environ.get("SCREENER_SQLITE_DB")
    args.sqlite_db = args.sqlite_db or (Path(sqlite_db) if sqlite_db else None)
    args.max_symbols = args.max_symbols if args.max_symbols is not None else int(os.environ.get("SCREENER_MAX_SYMBOLS", "0"))
    args.request_delay_seconds = (
        args.request_delay_seconds
        if args.request_delay_seconds is not None
        else float(os.environ.get("SCREENER_REQUEST_DELAY_SECONDS", "0.05"))
    )
    symbols = _resolve_symbols(args)

    if not args.demo and not args.csv and args.exchange == "binance" and not symbols:
        parser.error("provide --demo, --csv, --binance-symbols, --symbols-file, or SCREENER_SYMBOLS for Binance")
    if args.telegram and not _telegram_credentials(args):
        parser.error("provide TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID or pass Telegram CLI flags")

    config = ScannerConfig(base_range_pct=args.base_range_pct)
    if args.loop:
        while True:
            try:
                _run_once(args, config)
            except Exception as exc:
                _print_error(f"Worker scan failed: {exc}")
            time.sleep(max(1.0, args.interval_minutes * 60))

    return _run_once(args, config)


def _run_once(args: argparse.Namespace, config: ScannerConfig) -> int:
    universe = _load_universe(args)
    results = scan_universe(universe, config=config, min_score=args.min_score)

    if args.sqlite_db:
        _save_scan_to_sqlite(args.sqlite_db, universe, results)

    if args.json:
        print(json.dumps([_result_to_dict(result) for result in results], indent=2, default=str))
    else:
        _print_results(results)

    if args.telegram:
        _send_telegram_alerts(results, args, scanned_symbols=universe.keys())

    return 0


def _print_results(results: list[SignalResult]) -> None:
    if not results:
        print("No alerts matched the current threshold.")
        return
    for index, result in enumerate(results):
        if index:
            print("\n" + "=" * 72 + "\n")
        print(format_alert(result))


def _send_telegram_alerts(results: list[SignalResult], args: argparse.Namespace, scanned_symbols: Iterable[str]) -> None:
    credentials = _telegram_credentials(args)
    if not credentials:
        return

    token, chat_id = credentials
    state = SignalState.load(args.state_file)
    active_symbols = {result.symbol for result in results}
    state.mark_inactive(set(scanned_symbols), active_symbols)

    if not results:
        state.save(args.state_file)
        return

    sent_count = 0
    skipped_count = 0
    failed_count = 0
    for result in results:
        if not args.send_all and not state.is_new(result):
            skipped_count += 1
            continue
        try:
            send_telegram_message(token=token, chat_id=chat_id, text=format_alert(result))
        except Exception as exc:
            failed_count += 1
            _print_error(f"Telegram: failed to send {result.symbol} {result.signal_type}: {exc}")
            continue
        state.mark_sent(result)
        state.save(args.state_file)
        sent_count += 1
    state.save(args.state_file)
    print(f"Telegram: sent {sent_count}/{len(results)} alerts, skipped {skipped_count}, failed {failed_count}.")


def _telegram_credentials(args: argparse.Namespace) -> tuple[str, str] | None:
    token = args.telegram_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = args.telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return None
    return token, chat_id


def _load_universe(args: argparse.Namespace) -> dict:
    if args.demo:
        return generate_demo_universe()
    if args.csv:
        return load_csv_grouped(args.csv, symbol_override=args.symbol)
    symbols = _resolve_symbols(args)
    if args.exchange == "binance":
        return fetch_binance_universe(symbols, limit=args.kline_limit)
    return fetch_bybit_universe(
        symbols=symbols or None,
        category=args.bybit_category,
        quote_coin=args.quote_coin,
        limit=args.kline_limit,
        max_symbols=args.max_symbols,
        request_delay_seconds=args.request_delay_seconds,
    )


def _save_scan_to_sqlite(db_path: Path, universe: dict, results: list[SignalResult]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(db_path)
    try:
        initialize_schema(connection)
        for symbol, candles in universe.items():
            save_candles(connection, symbol, candles)
        for result in results:
            save_signal(connection, result)
    finally:
        connection.close()


def _resolve_symbols(args: argparse.Namespace) -> list[str]:
    symbols: list[str] = []
    if args.symbols_file:
        symbols.extend(load_symbols_file(args.symbols_file))
    elif os.environ.get("SCREENER_SYMBOLS_FILE"):
        symbols.extend(load_symbols_file(Path(os.environ["SCREENER_SYMBOLS_FILE"])))

    raw_symbols = args.bybit_symbols or args.binance_symbols or os.environ.get("SCREENER_SYMBOLS")
    if raw_symbols:
        symbols.extend(parse_symbol_list(raw_symbols))

    return list(dict.fromkeys(symbols))


def _print_error(message: str) -> None:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"{timestamp} {message}", file=sys.stderr, flush=True)
