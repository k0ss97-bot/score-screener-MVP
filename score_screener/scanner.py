from __future__ import annotations

import math

from .data import resample_candles
from .indicators import (
    adx,
    atr_pct,
    bollinger_width,
    ema,
    macd_histogram,
    median,
    mfi,
    percentile_rank,
    relative_volume,
    rsi,
    zscore,
)
from .models import BaseWindow, Candle, EnrichedCandle, ScannerConfig, SignalResult


def enrich_candles(candles: list[Candle]) -> list[EnrichedCandle]:
    ordered = sorted(candles, key=lambda item: item.timestamp)
    closes = [item.close for item in ordered]
    volumes = [item.volume for item in ordered]

    ema9_values = ema(closes, 9)
    ema20_values = ema(closes, 20)
    ema50_values = ema(closes, 50)
    rsi_values = rsi(closes)
    macd_values = macd_histogram(closes)
    bb_values = bollinger_width(closes)
    atr_values = atr_pct(ordered)
    mfi_values = mfi(ordered)
    adx_values = adx(ordered)
    rel_volume_values = relative_volume(volumes)
    volume_zscore_values = zscore(volumes)

    return [
        EnrichedCandle(
            candle=candle,
            ema9=ema9_values[index],
            ema20=ema20_values[index],
            ema50=ema50_values[index],
            rsi=rsi_values[index],
            macd_hist=macd_values[index],
            bb_width=bb_values[index],
            atr_pct=atr_values[index],
            mfi=mfi_values[index],
            adx=adx_values[index],
            rel_volume=rel_volume_values[index],
            volume_zscore=volume_zscore_values[index],
        )
        for index, candle in enumerate(ordered)
    ]


def detect_consolidation(enriched: list[EnrichedCandle], config: ScannerConfig) -> BaseWindow | None:
    if len(enriched) < config.min_base_days * 24 + 1:
        return None

    lookback = enriched[:-1]
    bb_sample = [item.bb_width for item in lookback]
    atr_sample = [item.atr_pct for item in lookback]

    max_offset = min(config.max_base_end_offset_hours, max(0, len(lookback) - config.min_base_days * 24))
    for end_offset in range(0, max_offset + 1):
        source = lookback[: len(lookback) - end_offset] if end_offset else lookback
        for days in range(config.max_base_days, config.min_base_days - 1, -1):
            count = days * 24
            if len(source) < count:
                continue
            window = source[-count:]
            base = _try_base_window(window, bb_sample, atr_sample, days, config)
            if base is not None:
                return base

    return None


def _try_base_window(
    window: list[EnrichedCandle],
    bb_sample: list[float | None],
    atr_sample: list[float | None],
    days: int,
    config: ScannerConfig,
) -> BaseWindow | None:
    highs = [item.candle.high for item in window]
    lows = [item.candle.low for item in window]
    closes = [item.candle.close for item in window]

    base_high = max(highs)
    base_low = min(lows)
    median_close = median(closes)
    if median_close <= 0:
        return None

    range_pct = (base_high - base_low) / median_close
    if range_pct > config.base_range_pct:
        return None

    slope_pct = (closes[-1] - closes[0]) / median_close
    if abs(slope_pct) > config.max_base_slope_pct:
        return None

    hourly_moves = [
        abs(closes[index] / closes[index - 1] - 1)
        for index in range(1, len(closes))
        if closes[index - 1]
    ]
    if hourly_moves and max(hourly_moves) > config.max_hourly_move_in_base_pct:
        return None

    window_bb = [item.bb_width for item in window if item.bb_width is not None]
    window_atr = [item.atr_pct for item in window if item.atr_pct is not None]
    if not window_bb or not window_atr:
        return None

    bb_percentile = percentile_rank(median(window_bb), bb_sample)
    atr_percentile = percentile_rank(median(window_atr), atr_sample)
    if bb_percentile is None or atr_percentile is None:
        return None
    if bb_percentile > config.bb_width_percentile or atr_percentile > config.atr_pct_percentile:
        return None

    return BaseWindow(
        start=window[0].candle.timestamp,
        end=window[-1].candle.timestamp,
        days=days,
        high=base_high,
        low=base_low,
        range_pct=range_pct,
        bb_width_percentile=bb_percentile,
        atr_pct_percentile=atr_percentile,
        slope_pct=slope_pct,
    )


def build_latest_features(
    symbol: str,
    enriched_1h: list[EnrichedCandle],
    enriched_4h: list[EnrichedCandle],
    base: BaseWindow,
) -> dict[str, float | bool | str | None]:
    latest = enriched_1h[-1]
    previous = enriched_1h[-2] if len(enriched_1h) >= 2 else latest
    latest_4h = enriched_4h[-1] if enriched_4h else None
    previous_4h = enriched_4h[-2] if len(enriched_4h) >= 2 else latest_4h

    close = latest.candle.close
    range_width = base.high - base.low
    close_position = (close - base.low) / range_width if range_width else None
    close_vs_base_high_pct = close / base.high - 1 if base.high else None

    base_start_index = next(
        (index for index, item in enumerate(enriched_1h) if item.candle.timestamp >= base.start),
        max(0, len(enriched_1h) - base.days * 24),
    )
    anchored_window = enriched_1h[base_start_index:]
    anchored_vwap = _anchored_vwap([item.candle for item in anchored_window])

    upper_wick_ratio = _upper_wick_ratio(latest.candle)
    macd_hist_1h_falling = _is_falling(latest.macd_hist, previous.macd_hist)
    macd_hist_1h_rising = _is_rising(latest.macd_hist, previous.macd_hist)

    return {
        "symbol": symbol,
        "timestamp": latest.candle.timestamp.isoformat(),
        "close": close,
        "base_high": base.high,
        "base_low": base.low,
        "base_range_pct": base.range_pct,
        "close_position_in_range": close_position,
        "close_vs_base_high_pct": close_vs_base_high_pct,
        "price_extension_pct": max(0.0, close_vs_base_high_pct or 0.0),
        "anchored_vwap": anchored_vwap,
        "above_anchored_vwap": close > anchored_vwap if anchored_vwap is not None else False,
        "rsi_1h": latest.rsi,
        "rsi_4h": latest_4h.rsi if latest_4h else None,
        "macd_hist_1h": latest.macd_hist,
        "macd_hist_4h": latest_4h.macd_hist if latest_4h else None,
        "macd_hist_1h_rising": macd_hist_1h_rising,
        "macd_hist_1h_falling": macd_hist_1h_falling,
        "macd_hist_4h_falling": _is_falling(
            latest_4h.macd_hist if latest_4h else None,
            previous_4h.macd_hist if previous_4h else None,
        ),
        "rel_volume_1h": latest.rel_volume,
        "volume_zscore_1h": latest.volume_zscore,
        "mfi_1h": latest.mfi,
        "adx_1h": latest.adx,
        "adx_1h_rising": _is_rising(latest.adx, previous.adx),
        "bb_width_1h": latest.bb_width,
        "bb_width_1h_expanding": _is_rising(latest.bb_width, previous.bb_width),
        "atr_pct_1h": latest.atr_pct,
        "ema9_1h": latest.ema9,
        "ema20_1h": latest.ema20,
        "ema50_1h": latest.ema50,
        "lost_ema9": latest.ema9 is not None and close < latest.ema9,
        "lost_ema20": latest.ema20 is not None and close < latest.ema20,
        "lost_vwap": anchored_vwap is not None and close < anchored_vwap,
        "upper_wick_ratio": upper_wick_ratio,
        "lower_high_lower_low": latest.candle.high < previous.candle.high and latest.candle.low < previous.candle.low,
    }


def calculate_impulse_score(features: dict[str, float | bool | str | None], base: BaseWindow, config: ScannerConfig) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if base.range_pct <= config.base_range_pct:
        score += 20
        reasons.append("base range is narrow")

    bb_ok = (base.bb_width_percentile or 100) <= config.bb_width_percentile
    atr_ok = (base.atr_pct_percentile or 100) <= config.atr_pct_percentile
    if bb_ok and atr_ok:
        score += 15
        reasons.append("BB width and ATR are compressed")
    elif bb_ok or atr_ok:
        score += 8
        reasons.append("partial volatility compression")

    close_position = _num(features.get("close_position_in_range"))
    if close_position is not None and close_position >= 0.70:
        score += 10
        reasons.append("close is in the upper 30% of the base")

    if features.get("above_anchored_vwap"):
        if close_position is not None and close_position >= 0.50:
            score += 15
            reasons.append("close reclaimed anchored VWAP")
        else:
            score += 8
            reasons.append("close is above anchored VWAP but still low in the base")

    rsi_1h = _num(features.get("rsi_1h"))
    rsi_4h = _num(features.get("rsi_4h"))
    macd_1h = _num(features.get("macd_hist_1h"))
    macd_4h = _num(features.get("macd_hist_4h"))
    rel_volume = _num(features.get("rel_volume_1h"))
    momentum_points = 0
    if rsi_1h is not None and rsi_1h > 55:
        momentum_points += 4
    if macd_1h is not None and macd_1h > 0:
        momentum_points += 4
    if rsi_4h is not None and rsi_4h > 55:
        momentum_points += 4
    if macd_4h is not None and macd_4h > 0:
        momentum_points += 3
    if close_position is not None and close_position < 0.70 and (rel_volume is None or rel_volume < config.early_rel_volume):
        momentum_points = min(momentum_points, 5)
    if momentum_points:
        score += momentum_points
        reasons.append("RSI/MACD momentum is improving")

    volume_z = _num(features.get("volume_zscore_1h"))
    if rel_volume is not None and rel_volume >= config.strong_rel_volume:
        score += 12
        reasons.append("relative volume is elevated")
    elif rel_volume is not None and rel_volume >= config.early_rel_volume:
        score += 8
        reasons.append("relative volume is waking up")
    if volume_z is not None and volume_z >= 2:
        score += 3
        reasons.append("volume z-score confirms the move")

    close_vs_high = _num(features.get("close_vs_base_high_pct"))
    if close_vs_high is not None and close_vs_high >= config.breakout_buffer_pct:
        score += 10
        reasons.append("close broke above base high")
    elif close_position is not None and close_position >= 0.90:
        score += 5
        reasons.append("close is pressing the base high")

    return min(score, 100), reasons


def calculate_reversal_score(features: dict[str, float | bool | str | None]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    rsi_1h = _num(features.get("rsi_1h"))
    rsi_4h = _num(features.get("rsi_4h"))
    mfi_1h = _num(features.get("mfi_1h"))
    extension = _num(features.get("price_extension_pct"))
    rel_volume = _num(features.get("rel_volume_1h"))
    volume_z = _num(features.get("volume_zscore_1h"))
    upper_wick_ratio = _num(features.get("upper_wick_ratio"))

    if rsi_1h is not None and rsi_1h > 78:
        score += 15
        reasons.append("RSI 1H is overheated")
    if rsi_4h is not None and rsi_4h > 78:
        score += 15
        reasons.append("RSI 4H is overheated")
    if mfi_1h is not None and mfi_1h > 85:
        score += 15
        reasons.append("MFI is overheated")
    if extension is not None and extension >= 0.30:
        score += 20
        reasons.append("price is extended 30%+ from base high")
    elif extension is not None and extension >= 0.20:
        score += 10
        reasons.append("price is extended 20%+ from base high")
    if features.get("macd_hist_1h_falling"):
        score += 8
        reasons.append("MACD histogram is falling")
    if rel_volume is not None and rel_volume >= 3:
        score += 8
        reasons.append("relative volume looks climactic")
    if volume_z is not None and volume_z >= 3:
        score += 7
        reasons.append("volume z-score is climactic")
    elif volume_z is not None and volume_z >= 2.5 and extension is not None and extension >= 0.20:
        score += 4
        reasons.append("volume z-score is elevated after extension")
    if extension is not None and extension >= 0.20 and features.get("bb_width_1h_expanding"):
        score += 5
        reasons.append("Bollinger width is expanding after extension")
    if upper_wick_ratio is not None and upper_wick_ratio >= 0.40:
        score += 10
        reasons.append("upper wick is large")
    if features.get("lost_ema20"):
        score += 10
        reasons.append("price lost EMA20")
    if features.get("lost_vwap"):
        score += 10
        reasons.append("price lost anchored VWAP")
    if features.get("lower_high_lower_low"):
        score += 10
        reasons.append("latest candle made lower high and lower low")

    return min(score, 100), reasons


def classify_signal(
    impulse_score: int,
    reversal_score: int,
    features: dict[str, float | bool | str | None],
    config: ScannerConfig,
) -> str:
    extension = _num(features.get("price_extension_pct")) or 0.0
    close_vs_high = _num(features.get("close_vs_base_high_pct")) or 0.0

    if reversal_score >= config.reversal_alert_score:
        return "EXIT RISK"
    if impulse_score >= 85 and extension >= 0.10:
        return "MOMENTUM"
    if impulse_score >= 85 and close_vs_high >= config.breakout_buffer_pct:
        return "BREAKOUT"
    if impulse_score >= 75:
        return "STRONG PRE-BREAKOUT"
    if impulse_score >= 60:
        return "EARLY"
    if impulse_score >= 40:
        return "WATCHLIST"
    return "NO SIGNAL"


def scan_symbol(symbol: str, candles: list[Candle], config: ScannerConfig | None = None) -> SignalResult | None:
    config = config or ScannerConfig()
    if len(candles) < config.min_base_days * 24 + 60:
        return None

    enriched_1h = enrich_candles(candles)
    base = detect_consolidation(enriched_1h, config)
    if base is None:
        return None

    candles_4h = resample_candles(candles, "4h")
    enriched_4h = enrich_candles(candles_4h)
    features = build_latest_features(symbol, enriched_1h, enriched_4h, base)
    impulse_score, impulse_reasons = calculate_impulse_score(features, base, config)
    reversal_score, reversal_reasons = calculate_reversal_score(features)
    signal_type = classify_signal(impulse_score, reversal_score, features, config)

    return SignalResult(
        symbol=symbol,
        timestamp=enriched_1h[-1].candle.timestamp,
        signal_type=signal_type,
        impulse_score=impulse_score,
        reversal_score=reversal_score,
        base=base,
        features=features,
        reasons=impulse_reasons + reversal_reasons,
    )


def scan_universe(
    universe: dict[str, list[Candle]],
    config: ScannerConfig | None = None,
    min_score: int = 40,
) -> list[SignalResult]:
    config = config or ScannerConfig()
    results = []
    for symbol, candles in universe.items():
        result = scan_symbol(symbol, candles, config=config)
        if result and (result.impulse_score >= min_score or result.reversal_score >= config.reversal_alert_score):
            results.append(result)
    return sorted(results, key=lambda item: (item.signal_type == "EXIT RISK", item.impulse_score, item.reversal_score), reverse=True)


def _anchored_vwap(candles: list[Candle]) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for candle in candles:
        volume = candle.volume
        numerator += candle.typical_price * volume
        denominator += volume
    if denominator == 0:
        return None
    return numerator / denominator


def _upper_wick_ratio(candle: Candle) -> float | None:
    full_range = candle.high - candle.low
    if full_range <= 0:
        return None
    return (candle.high - max(candle.open, candle.close)) / full_range


def _is_rising(current: float | None, previous: float | None) -> bool:
    return current is not None and previous is not None and current > previous


def _is_falling(current: float | None, previous: float | None) -> bool:
    return current is not None and previous is not None and current < previous


def _num(value: float | bool | str | None) -> float | None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return None
    if not math.isfinite(value):
        return None
    return float(value)
