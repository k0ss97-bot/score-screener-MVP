from __future__ import annotations

import csv
import json
import math
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib import error, parse, request

from .models import Candle


def parse_timestamp(value: str) -> datetime:
    raw = value.strip()
    if raw.isdigit():
        number = int(raw)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(number, tz=UTC).replace(tzinfo=None)

    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def load_csv_grouped(path: Path, symbol_override: str | None = None) -> dict[str, list[Candle]]:
    grouped: dict[str, list[Candle]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = symbol_override or row.get("symbol") or row.get("pair") or "UNKNOWN"
            candle = Candle(
                timestamp=parse_timestamp(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                quote_volume=float(row["quote_volume"]) if row.get("quote_volume") else None,
                symbol=symbol,
            )
            grouped[symbol].append(candle)

    return {symbol: sorted(candles, key=lambda item: item.timestamp) for symbol, candles in grouped.items()}


def load_symbols_file(path: Path) -> list[str]:
    symbols = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        symbols.extend(parse_symbol_list(line))
    return symbols


def parse_symbol_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]


def normalize_exchange_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").upper()


def display_quote_symbol(symbol: str, quote_coin: str = "USDT") -> str:
    normalized = normalize_exchange_symbol(symbol)
    quote = quote_coin.upper()
    if normalized.endswith(quote):
        return f"{normalized[: -len(quote)]}/{quote}"
    return normalized


def normalize_binance_symbol(symbol: str) -> str:
    return normalize_exchange_symbol(symbol)


def display_binance_symbol(symbol: str) -> str:
    normalized = normalize_binance_symbol(symbol)
    if normalized.endswith("USDT"):
        return f"{normalized[:-4]}/USDT"
    if normalized.endswith("BUSD"):
        return f"{normalized[:-4]}/BUSD"
    if normalized.endswith("USDC"):
        return f"{normalized[:-4]}/USDC"
    return normalized


def fetch_bybit_instruments(category: str = "spot", quote_coin: str = "USDT") -> list[str]:
    symbols: list[str] = []
    cursor = ""
    while True:
        params = {
            "category": category,
            "status": "Trading",
        }
        if quote_coin:
            params["quoteCoin"] = quote_coin.upper()
        if cursor:
            params["cursor"] = cursor
        if category != "spot":
            params["limit"] = "1000"

        payload = _fetch_bybit("/v5/market/instruments-info", params)
        result = payload.get("result", {})
        for item in result.get("list", []):
            if item.get("status") != "Trading":
                continue
            if quote_coin and item.get("quoteCoin") != quote_coin.upper():
                continue
            if item.get("symbolType") == "xstocks":
                continue
            symbol = item.get("symbol")
            if symbol:
                symbols.append(symbol)

        cursor = result.get("nextPageCursor") or ""
        if not cursor:
            break

    return sorted(dict.fromkeys(symbols))


def fetch_bybit_klines(
    symbol: str,
    category: str = "spot",
    quote_coin: str = "USDT",
    interval: str = "60",
    limit: int = 1000,
) -> list[Candle]:
    normalized = normalize_exchange_symbol(symbol)
    payload = _fetch_bybit(
        "/v5/market/kline",
        {
            "category": category,
            "symbol": normalized,
            "interval": interval,
            "limit": str(limit),
        },
    )
    rows = payload.get("result", {}).get("list", [])
    display_symbol = display_quote_symbol(normalized, quote_coin=quote_coin)
    candles = []
    for row in rows:
        timestamp_ms, open_, high, low, close, volume, turnover = row[:7]
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=UTC).replace(tzinfo=None),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
                quote_volume=float(turnover),
                symbol=display_symbol,
            )
        )
    return sorted(candles, key=lambda item: item.timestamp)


def fetch_bybit_universe(
    symbols: list[str] | None = None,
    category: str = "spot",
    quote_coin: str = "USDT",
    interval: str = "60",
    limit: int = 1000,
    max_symbols: int = 0,
    request_delay_seconds: float = 0.05,
) -> dict[str, list[Candle]]:
    selected_symbols = symbols or fetch_bybit_instruments(category=category, quote_coin=quote_coin)
    if max_symbols > 0:
        selected_symbols = selected_symbols[:max_symbols]

    universe: dict[str, list[Candle]] = {}
    for index, symbol in enumerate(selected_symbols, start=1):
        try:
            candles = fetch_bybit_klines(symbol, category=category, quote_coin=quote_coin, interval=interval, limit=limit)
        except RuntimeError as exc:
            print(f"Bybit: skipped {symbol}: {exc}", file=sys.stderr)
            continue
        if candles:
            universe[candles[0].symbol] = candles
        if request_delay_seconds > 0 and index < len(selected_symbols):
            time.sleep(request_delay_seconds)
    return universe


def fetch_binance_klines(symbol: str, interval: str = "1h", limit: int = 1000) -> list[Candle]:
    normalized = normalize_binance_symbol(symbol)
    query = parse.urlencode({"symbol": normalized, "interval": interval, "limit": limit})
    url = f"https://api.binance.com/api/v3/klines?{query}"
    rows = _fetch_json(url)
    display_symbol = display_binance_symbol(normalized)
    candles = []
    for row in rows:
        timestamp_ms, open_, high, low, close, volume, _close_time, quote_volume = row[:8]
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).replace(tzinfo=None),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
                quote_volume=float(quote_volume),
                symbol=display_symbol,
            )
        )
    return candles


def fetch_binance_universe(symbols: list[str], interval: str = "1h", limit: int = 1000) -> dict[str, list[Candle]]:
    universe: dict[str, list[Candle]] = {}
    for symbol in symbols:
        candles = fetch_binance_klines(symbol, interval=interval, limit=limit)
        if candles:
            universe[candles[0].symbol] = candles
    return universe


def resample_candles(candles: list[Candle], timeframe: str) -> list[Candle]:
    if timeframe not in {"4h", "1d"}:
        raise ValueError("timeframe must be '4h' or '1d'")
    if not candles:
        return []

    buckets: dict[datetime, list[Candle]] = defaultdict(list)
    for candle in sorted(candles, key=lambda item: item.timestamp):
        ts = candle.timestamp
        if timeframe == "4h":
            bucket = ts.replace(hour=(ts.hour // 4) * 4, minute=0, second=0, microsecond=0)
        else:
            bucket = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        buckets[bucket].append(candle)

    result: list[Candle] = []
    for bucket in sorted(buckets):
        items = buckets[bucket]
        first = items[0]
        last = items[-1]
        quote_volume = None
        if any(item.quote_volume is not None for item in items):
            quote_volume = sum(item.quote_volume or item.close * item.volume for item in items)
        result.append(
            Candle(
                timestamp=bucket,
                open=first.open,
                high=max(item.high for item in items),
                low=min(item.low for item in items),
                close=last.close,
                volume=sum(item.volume for item in items),
                quote_volume=quote_volume,
                symbol=first.symbol,
            )
        )
    return result


def generate_demo_universe() -> dict[str, list[Candle]]:
    return {
        "ALGO/USDT": generate_demo_candles("ALGO/USDT", breakout=True),
        "LATE/USDT": generate_demo_candles("LATE/USDT", breakout=True, exhausted=True),
        "QUIET/USDT": generate_demo_candles("QUIET/USDT", breakout=False),
    }


def generate_demo_candles(symbol: str, breakout: bool = True, exhausted: bool = False) -> list[Candle]:
    start = datetime(2026, 1, 1)
    candles: list[Candle] = []
    price = 100.0

    for index in range(60 * 24):
        ts = start + timedelta(hours=index)
        if index < 50 * 24:
            wave = math.sin(index / 11) * 4.2 + math.sin(index / 37) * 5.1
            drift = index * 0.0015
            close = 96.0 + wave + drift
            volume = 950 + 360 * (1 + math.sin(index / 9))
        else:
            phase = index - 50 * 24
            wave = math.sin(phase / 6) * 0.22 + math.sin(phase / 13) * 0.16
            close = 100.0 + wave
            volume = 620 + 60 * (1 + math.sin(phase / 8))

        open_price = price
        high = max(open_price, close) * 1.003
        low = min(open_price, close) * 0.997
        candles.append(
            Candle(
                timestamp=ts,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=max(volume, 1),
                quote_volume=max(volume, 1) * close,
                symbol=symbol,
            )
        )
        price = close

    ts = start + timedelta(hours=len(candles))
    if breakout:
        close = 108.0 if not exhausted else 148.0
        high = close * (1.01 if not exhausted else 1.08)
        low = max(price * 0.995, close * 0.94)
        volume = 2800 if not exhausted else 5800
    else:
        close = 101.0
        high = 101.3
        low = 99.7
        volume = 700

    candles.append(
        Candle(
            timestamp=ts,
            open=price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            quote_volume=volume * close,
            symbol=symbol,
        )
    )

    if exhausted:
        for offset, close in enumerate([142.0, 138.0], start=1):
            ts = start + timedelta(hours=len(candles))
            open_price = candles[-1].close
            candles.append(
                Candle(
                    timestamp=ts,
                    open=open_price,
                    high=max(open_price, close) * 1.01,
                    low=min(open_price, close) * 0.97,
                    close=close,
                    volume=5200 - offset * 250,
                    quote_volume=(5200 - offset * 250) * close,
                    symbol=symbol,
                )
            )

    return candles


def fetch_ohlcv_ccxt(exchange_id: str, symbol: str, timeframe: str = "1h", limit: int = 1000) -> list[Candle]:
    try:
        import ccxt  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install ccxt to use live exchange fetching: python3 -m pip install ccxt") from exc

    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True})
    if not exchange.has.get("fetchOHLCV"):
        raise RuntimeError(f"{exchange_id} does not support fetchOHLCV")

    rows = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    candles = []
    for timestamp_ms, open_, high, low, close, volume in rows:
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).replace(tzinfo=None),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
                quote_volume=float(volume) * float(close),
                symbol=symbol,
            )
        )
    return candles


def _fetch_json(url: str, timeout: int = 20) -> object:
    try:
        with request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc.reason) and shutil.which("curl"):
            return _fetch_json_with_curl(url, timeout)
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def _fetch_json_with_curl(url: str, timeout: int) -> object:
    completed = subprocess.run(
        ["curl", "-sS", "--max-time", str(timeout), url],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"curl fallback failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def _fetch_bybit(path: str, params: dict[str, str]) -> dict:
    query = parse.urlencode(params)
    payload = _fetch_json(f"https://api.bybit.com{path}?{query}")
    if not isinstance(payload, dict):
        raise RuntimeError("Bybit returned a non-object response")

    ret_code = payload.get("retCode")
    if ret_code != 0:
        message = payload.get("retMsg", "unknown Bybit API error")
        raise RuntimeError(f"Bybit retCode {ret_code}: {message}")
    return payload
