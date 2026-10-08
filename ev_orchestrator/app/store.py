from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from defaults import DEFAULT_SETTINGS

DATA_DIR = Path("/data")
SETTINGS_PATH = DATA_DIR / "settings.json"
EVENTS_PATH = DATA_DIR / "events.jsonl"


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Store:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.settings = self._load_settings()

    def _load_settings(self) -> dict[str, Any]:
        if not SETTINGS_PATH.exists():
            settings = copy.deepcopy(DEFAULT_SETTINGS)
            self.save_settings(settings)
            return settings
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return deep_merge(DEFAULT_SETTINGS, raw)
        except Exception:
            return copy.deepcopy(DEFAULT_SETTINGS)

    def save_settings(self, settings: dict[str, Any]) -> None:
        merged = deep_merge(DEFAULT_SETTINGS, settings)
        SETTINGS_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
        self.settings = merged

    def append_event(self, event: dict[str, Any]) -> None:
        with EVENTS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._trim_events(3000)

    def _trim_events(self, max_lines: int) -> None:
        try:
            lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
            if len(lines) > max_lines:
                EVENTS_PATH.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")
        except FileNotFoundError:
            pass

    def read_events(self, limit: int = 200) -> list[dict[str, Any]]:
        try:
            lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
        except FileNotFoundError:
            return []
        out: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
