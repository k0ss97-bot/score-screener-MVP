from __future__ import annotations

import os
import sys
from pathlib import Path

from score_screener.cli import main


def default_args() -> list[str]:
    state_file = os.environ.get("SCREENER_STATE_FILE")
    if not state_file:
        state_file = "/app/runtime/screener_state.json" if Path("/app").exists() else ".screener_state.json"
    return ["--telegram", "--loop", "--state-file", state_file]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or default_args()))
