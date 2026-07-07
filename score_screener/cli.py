from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .alerts import format_alert
from .data import generate_demo_universe, load_csv_grouped
from .env import load_env_file
from .models import ScannerConfig, SignalResult
from .scanner import scan_universe
from .state import SignalState
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
    parser.add_argument("--symbol", help="Symbol override when CSV has no symbol column")
    parser.add_argument("--min-score", type=int, default=40, help="Minimum impulse score to print")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text alerts")
    parser.add_argument("--base-range-pct", type=float, default=0.18, help="Max base range, e.g. 0.18 for 18%%")
    parser.add_argument("--telegram", action="store_true", help="Send matching alerts to Telegram")
    parser.add_argument("--telegram-token", help="Telegram bot token. Defaults to TELEGRAM_BOT_TOKEN")
    parser.add_argument("--telegram-chat-id", help="Telegram chat id. Defaults to TELEGRAM_CHAT_ID")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Optional env file to load")
    parser.add_argument("--state-file", type=Path, default=Path(".screener_state.json"), help="Signal dedupe state file")
    parser.add_argument("--send-all", action="store_true", help="Send alerts even if they were already sent")
    parser.add_argument("--loop", action="store_true", help="Run forever with sleep between scans")
    parser.add_argument("--interval-minutes", type=float, default=60.0, help="Loop sleep interval")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.env_file and args.env_file.exists():
        load_env_file(args.env_file)

    if not args.demo and not args.csv:
        parser.error("provide --demo or --csv")
    if args.telegram and not _telegram_credentials(args):
        parser.error("provide TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID or pass Telegram CLI flags")

    config = ScannerConfig(base_range_pct=args.base_range_pct)
    if args.loop:
        while True:
            _run_once(args, config)
            time.sleep(max(1.0, args.interval_minutes * 60))

    return _run_once(args, config)


def _run_once(args: argparse.Namespace, config: ScannerConfig) -> int:
    universe = generate_demo_universe() if args.demo else load_csv_grouped(args.csv, symbol_override=args.symbol)
    results = scan_universe(universe, config=config, min_score=args.min_score)

    if args.json:
        print(json.dumps([_result_to_dict(result) for result in results], indent=2, default=str))
    else:
        _print_results(results)

    if args.telegram:
        _send_telegram_alerts(results, args)

    return 0


def _print_results(results: list[SignalResult]) -> None:
    if not results:
        print("No alerts matched the current threshold.")
        return
    for index, result in enumerate(results):
        if index:
            print("\n" + "=" * 72 + "\n")
        print(format_alert(result))


def _send_telegram_alerts(results: list[SignalResult], args: argparse.Namespace) -> None:
    credentials = _telegram_credentials(args)
    if not credentials or not results:
        return

    token, chat_id = credentials
    state = SignalState.load(args.state_file)
    sent_count = 0
    for result in results:
        if not args.send_all and not state.is_new(result):
            continue
        send_telegram_message(token=token, chat_id=chat_id, text=format_alert(result))
        state.mark_sent(result)
        sent_count += 1
    state.save(args.state_file)
    print(f"Telegram: sent {sent_count}/{len(results)} alerts.")


def _telegram_credentials(args: argparse.Namespace) -> tuple[str, str] | None:
    token = args.telegram_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = args.telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return None
    return token, chat_id
