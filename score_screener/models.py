from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float | None = None
    symbol: str = ""

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3

    @property
    def dollar_volume(self) -> float:
        return self.quote_volume if self.quote_volume is not None else self.close * self.volume


@dataclass(frozen=True)
class EnrichedCandle:
    candle: Candle
    ema9: float | None = None
    ema20: float | None = None
    ema50: float | None = None
    rsi: float | None = None
    macd_hist: float | None = None
    bb_width: float | None = None
    atr_pct: float | None = None
    mfi: float | None = None
    adx: float | None = None
    rel_volume: float | None = None
    volume_zscore: float | None = None


@dataclass(frozen=True)
class BaseWindow:
    start: datetime
    end: datetime
    days: int
    high: float
    low: float
    range_pct: float
    bb_width_percentile: float | None
    atr_pct_percentile: float | None
    slope_pct: float


@dataclass(frozen=True)
class ScannerConfig:
    min_base_days: int = 5
    max_base_days: int = 10
    base_range_pct: float = 0.18
    max_base_slope_pct: float = 0.08
    max_base_end_offset_hours: int = 72
    max_hourly_move_in_base_pct: float = 0.12
    bb_width_percentile: float = 30.0
    atr_pct_percentile: float = 35.0
    breakout_buffer_pct: float = 0.005
    early_rel_volume: float = 1.3
    strong_rel_volume: float = 1.5
    breakout_rel_volume: float = 2.0
    reversal_alert_score: int = 70


@dataclass(frozen=True)
class SignalResult:
    symbol: str
    timestamp: datetime
    signal_type: str
    impulse_score: int
    reversal_score: int
    base: BaseWindow
    features: dict[str, float | bool | str | None]
    reasons: list[str] = field(default_factory=list)
