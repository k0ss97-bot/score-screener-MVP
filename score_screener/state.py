from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import SignalResult


def signal_key(result: SignalResult) -> str:
    return f"{result.symbol}|{result.signal_type}|{result.timestamp.isoformat()}"


@dataclass
class SignalState:
    sent_keys: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: str | Path) -> "SignalState":
        state_path = Path(path)
        if not state_path.exists():
            return cls()
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        return cls(sent_keys=set(payload.get("sent_keys", [])))

    def is_new(self, result: SignalResult) -> bool:
        return signal_key(result) not in self.sent_keys

    def mark_sent(self, result: SignalResult) -> None:
        self.sent_keys.add(signal_key(result))

    def save(self, path: str | Path) -> None:
        state_path = Path(path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"sent_keys": sorted(self.sent_keys)}, indent=2),
            encoding="utf-8",
        )
