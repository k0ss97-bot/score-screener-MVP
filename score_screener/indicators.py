from __future__ import annotations

import math
from statistics import median as _median

from .models import Candle


MaybeFloat = float | None


def median(values: list[float]) -> float:
    if not values:
        raise ValueError("median requires at least one value")
    return float(_median(values))


def percentile_rank(value: float | None, sample: list[float | None]) -> float | None:
    if value is None:
        return None
    clean = [item for item in sample if item is not None and math.isfinite(item)]
    if not clean:
        return None
    count = sum(1 for item in clean if item <= value)
    return count / len(clean) * 100


def ema(values: list[float], period: int) -> list[MaybeFloat]:
    result: list[MaybeFloat] = [None] * len(values)
    if len(values) < period:
        return result
    alpha = 2 / (period + 1)
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    previous = seed
    for index in range(period, len(values)):
        previous = values[index] * alpha + previous * (1 - alpha)
        result[index] = previous
    return result


def ema_from_first(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    previous = values[0]
    for value in values[1:]:
        previous = value * alpha + previous * (1 - alpha)
        result.append(previous)
    return result


def rolling_mean(values: list[float], period: int) -> list[MaybeFloat]:
    result: list[MaybeFloat] = [None] * len(values)
    window_sum = 0.0
    for index, value in enumerate(values):
        window_sum += value
        if index >= period:
            window_sum -= values[index - period]
        if index >= period - 1:
            result[index] = window_sum / period
    return result


def rolling_std(values: list[float], period: int) -> list[MaybeFloat]:
    result: list[MaybeFloat] = [None] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        mean = sum(window) / period
        variance = sum((item - mean) ** 2 for item in window) / period
        result[index] = math.sqrt(variance)
    return result


def rsi(values: list[float], period: int = 14) -> list[MaybeFloat]:
    result: list[MaybeFloat] = [None] * len(values)
    if len(values) <= period:
        return result

    gains = []
    losses = []
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    result[period] = _rsi_from_averages(avg_gain, avg_loss)

    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0)
        loss = max(-change, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        result[index] = _rsi_from_averages(avg_gain, avg_loss)

    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    relative_strength = avg_gain / avg_loss
    return 100 - (100 / (1 + relative_strength))


def macd_histogram(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> list[MaybeFloat]:
    if not values:
        return []
    fast_ema = ema_from_first(values, fast)
    slow_ema = ema_from_first(values, slow)
    macd = [fast_item - slow_item for fast_item, slow_item in zip(fast_ema, slow_ema)]
    signal_ema = ema_from_first(macd, signal)
    warmup = slow + signal
    return [None if index < warmup else macd[index] - signal_ema[index] for index in range(len(values))]


def bollinger_width(values: list[float], period: int = 20, deviations: float = 2.0) -> list[MaybeFloat]:
    means = rolling_mean(values, period)
    stds = rolling_std(values, period)
    result: list[MaybeFloat] = [None] * len(values)
    for index, (mean, std) in enumerate(zip(means, stds)):
        if mean is None or std is None or mean == 0:
            continue
        result[index] = (2 * deviations * std) / mean
    return result


def atr_pct(candles: list[Candle], period: int = 14) -> list[MaybeFloat]:
    result: list[MaybeFloat] = [None] * len(candles)
    if len(candles) <= period:
        return result

    true_ranges = [0.0]
    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )

    atr = sum(true_ranges[1 : period + 1]) / period
    result[period] = atr / candles[period].close * 100 if candles[period].close else None
    for index in range(period + 1, len(candles)):
        atr = (atr * (period - 1) + true_ranges[index]) / period
        result[index] = atr / candles[index].close * 100 if candles[index].close else None
    return result


def mfi(candles: list[Candle], period: int = 14) -> list[MaybeFloat]:
    result: list[MaybeFloat] = [None] * len(candles)
    if len(candles) <= period:
        return result

    typical = [candle.typical_price for candle in candles]
    raw_flow = [typical[index] * candles[index].volume for index in range(len(candles))]
    positive = [0.0] * len(candles)
    negative = [0.0] * len(candles)

    for index in range(1, len(candles)):
        if typical[index] > typical[index - 1]:
            positive[index] = raw_flow[index]
        elif typical[index] < typical[index - 1]:
            negative[index] = raw_flow[index]

    for index in range(period, len(candles)):
        pos_sum = sum(positive[index - period + 1 : index + 1])
        neg_sum = sum(negative[index - period + 1 : index + 1])
        if neg_sum == 0:
            result[index] = 100.0
        else:
            money_ratio = pos_sum / neg_sum
            result[index] = 100 - (100 / (1 + money_ratio))
    return result


def adx(candles: list[Candle], period: int = 14) -> list[MaybeFloat]:
    result: list[MaybeFloat] = [None] * len(candles)
    if len(candles) < period * 2 + 1:
        return result

    true_ranges = [0.0]
    plus_dm = [0.0]
    minus_dm = [0.0]
    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]
        up_move = current.high - previous.high
        down_move = previous.low - current.low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )

    atr = sum(true_ranges[1 : period + 1])
    plus = sum(plus_dm[1 : period + 1])
    minus = sum(minus_dm[1 : period + 1])
    dx_values: list[float] = []

    for index in range(period, len(candles)):
        if index > period:
            atr = atr - (atr / period) + true_ranges[index]
            plus = plus - (plus / period) + plus_dm[index]
            minus = minus - (minus / period) + minus_dm[index]

        plus_di = 100 * plus / atr if atr else 0.0
        minus_di = 100 * minus / atr if atr else 0.0
        total = plus_di + minus_di
        dx = 100 * abs(plus_di - minus_di) / total if total else 0.0
        dx_values.append(dx)

        if len(dx_values) == period:
            result[index] = sum(dx_values) / period
        elif len(dx_values) > period:
            previous_adx = result[index - 1] or dx_values[-2]
            result[index] = ((previous_adx * (period - 1)) + dx) / period

    return result


def relative_volume(volumes: list[float], period: int = 20) -> list[MaybeFloat]:
    result: list[MaybeFloat] = [None] * len(volumes)
    for index in range(period, len(volumes)):
        previous = volumes[index - period : index]
        mean = sum(previous) / period
        result[index] = volumes[index] / mean if mean else None
    return result


def zscore(values: list[float], period: int = 20) -> list[MaybeFloat]:
    result: list[MaybeFloat] = [None] * len(values)
    for index in range(period, len(values)):
        previous = values[index - period : index]
        mean = sum(previous) / period
        variance = sum((item - mean) ** 2 for item in previous) / period
        std = math.sqrt(variance)
        result[index] = (values[index] - mean) / std if std else 0.0
    return result
