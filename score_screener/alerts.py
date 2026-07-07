from __future__ import annotations

from .models import SignalResult


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def format_alert(result: SignalResult) -> str:
    features = result.features
    base = result.base
    close_vs_high = features.get("close_vs_base_high_pct")
    close_position = features.get("close_position_in_range")

    lines = [
        f"{result.signal_type} ALERT: {result.symbol}",
        "",
        f"Impulse score: {result.impulse_score}/100",
        f"Reversal score: {result.reversal_score}/100",
        "",
        f"Base: {base.days} days",
        f"Range: {_fmt_pct(base.range_pct)}",
        f"BB width percentile: {_fmt_num(base.bb_width_percentile, 0)}",
        f"ATR percentile: {_fmt_num(base.atr_pct_percentile, 0)}",
        "",
        "Price:",
        f"Close: {_fmt_num(features.get('close'))}",
        f"Close vs base high: {_fmt_pct(close_vs_high)}",
        f"Close position in range: {_fmt_pct(close_position)}",
        "",
        "Momentum:",
        f"RSI 1H: {_fmt_num(features.get('rsi_1h'), 1)}",
        f"RSI 4H: {_fmt_num(features.get('rsi_4h'), 1)}",
        f"MACD hist 1H: {_fmt_num(features.get('macd_hist_1h'), 5)}",
        f"MACD hist 4H: {_fmt_num(features.get('macd_hist_4h'), 5)}",
        "",
        "Volume:",
        f"RelVolume 1H: {_fmt_num(features.get('rel_volume_1h'), 2)}x",
        f"Volume z-score: {_fmt_num(features.get('volume_zscore_1h'), 2)}",
        "",
        "VWAP:",
        f"Anchored VWAP: {_fmt_num(features.get('anchored_vwap'))}",
        f"Close above anchored VWAP: {'yes' if features.get('above_anchored_vwap') else 'no'}",
    ]

    if result.reasons:
        lines.extend(["", "Reasons:"])
        lines.extend(f"- {reason}" for reason in result.reasons)

    return "\n".join(lines)
