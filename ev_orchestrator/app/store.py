from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from defaults import DEFAULT_SETTINGS

DATA_DIR = Path("/data")
SETTINGS_PATH = DATA_DIR / "settings.json"
EVENTS_PATH = DATA_DIR / "events.jsonl"
LEGACY_BASELINE_PATH = DATA_DIR / "legacy_baseline.json"
SHADOW_STATE_PATH = DATA_DIR / "shadow_state.json"
SHADOW_EVENTS_PATH = DATA_DIR / "shadow_events.jsonl"


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


    def read_legacy_baseline(self) -> dict[str, Any] | None:
        if not LEGACY_BASELINE_PATH.exists():
            return None
        try:
            data = json.loads(LEGACY_BASELINE_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def save_legacy_baseline(self, baseline: dict[str, Any]) -> None:
        LEGACY_BASELINE_PATH.write_text(
            json.dumps(baseline, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def read_shadow_state(self) -> dict[str, Any]:
        if not SHADOW_STATE_PATH.exists():
            return {"observations": {}, "last_signature": None, "last_sample_at": None}
        try:
            data = json.loads(SHADOW_STATE_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {"observations": {}, "last_signature": None, "last_sample_at": None}

    def save_shadow_state(self, state: dict[str, Any]) -> None:
        SHADOW_STATE_PATH.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def append_shadow_event(self, event: dict[str, Any], max_lines: int = 2000) -> None:
        with SHADOW_EVENTS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._trim_path(SHADOW_EVENTS_PATH, max_lines)

    def read_shadow_events(self, limit: int = 200) -> list[dict[str, Any]]:
        try:
            lines = SHADOW_EVENTS_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
        except FileNotFoundError:
            return []
        out: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def _trim_path(self, path: Path, max_lines: int) -> None:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > max_lines:
                path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")
        except FileNotFoundError:
            pass

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
