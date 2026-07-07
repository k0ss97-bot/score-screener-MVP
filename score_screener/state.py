from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path

from .models import SignalResult


def signal_key(result: SignalResult) -> str:
    return f"{result.symbol}|{result.signal_type}"


@dataclass
class SignalState:
    sent_keys: set[str] = field(default_factory=set)
    last_signals: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "SignalState":
        state_path = Path(path)
        if not state_path.exists():
            return cls()
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except JSONDecodeError:
            return cls()

        sent_keys = set(payload.get("sent_keys", []))
        last_signals = _coerce_last_signals(payload.get("last_signals"))
        if not last_signals:
            last_signals = _last_signals_from_legacy_keys(sent_keys)
        return cls(sent_keys=sent_keys, last_signals=last_signals)

    def is_new(self, result: SignalResult) -> bool:
        return self.last_signals.get(result.symbol) != result.signal_type

    def mark_sent(self, result: SignalResult) -> None:
        self.sent_keys.add(signal_key(result))
        self.last_signals[result.symbol] = result.signal_type

    def mark_inactive(self, scanned_symbols: set[str], active_symbols: set[str]) -> None:
        for symbol in scanned_symbols - active_symbols:
            self.last_signals.pop(symbol, None)

    def save(self, path: str | Path) -> None:
        state_path = Path(path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "sent_keys": sorted(self.sent_keys),
                    "last_signals": dict(sorted(self.last_signals.items())),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def _coerce_last_signals(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for symbol, signal_type in value.items():
        if isinstance(symbol, str) and isinstance(signal_type, str):
            result[symbol] = signal_type
    return result


def _last_signals_from_legacy_keys(sent_keys: set[str]) -> dict[str, str]:
    last_signals: dict[str, str] = {}
    for raw_key in sorted(sent_keys):
        parts = raw_key.split("|", 2)
        if len(parts) >= 2:
            last_signals[parts[0]] = parts[1]
    return last_signals
