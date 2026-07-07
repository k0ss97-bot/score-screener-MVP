from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
