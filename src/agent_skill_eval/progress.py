"""Live per-run progress events for long eval runs.

The runner appends one JSON object per line to ``progress.jsonl`` in the
iteration directory while the suite runs, so a separate shell can
``tail -f`` it to see which case is active, how long it has been running,
and what it consumed — without digging through workspace directories.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ProgressLog:
    """Thread-safe JSONL event log (the runner grades runs concurrently)."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._start = time.time()
        # Start each run with a fresh file: progress is per-invocation
        # state, unlike the cumulative result artifacts.
        self.path.write_text("")

    def emit(self, event: str, **fields) -> None:
        record = {
            "event": event,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "elapsed_s": round(time.time() - self._start, 1),
            **{k: v for k, v in fields.items() if v is not None},
        }
        line = json.dumps(record)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


def run_label(eval_id, agent: str, with_skill: bool, run_index: int, runs: int) -> str:
    """Human-readable identity of one run for console progress lines."""
    config = "with_skill" if with_skill else "without_skill"
    label = f"eval={eval_id} agent={agent} config={config}"
    if runs > 1:
        label += f" run={run_index}"
    return label


def format_tokens(count: Optional[int]) -> str:
    if count is None:
        return "?"
    if count >= 1000:
        return f"{count / 1000:.0f}k"
    return str(count)
