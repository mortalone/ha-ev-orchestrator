from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from audit import scan
from ha_client import HomeAssistantClient
from model import build_snapshot
from store import Store

VERSION = "0.3.8"
STATIC_DIR = Path(__file__).parent / "static"

LOG_LEVEL = os.environ.get("EV_ORCH_LOG_LEVEL", "info").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("ev_orchestrator")

LOG_BUFFER: deque[str] = deque(maxlen=500)


class DiagnosticLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            LOG_BUFFER.append(self.format(record))
        except Exception:
            pass


_diag_handler = DiagnosticLogHandler()
_diag_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger().addHandler(_diag_handler)


SENSITIVE_ATTRIBUTE_KEYS = {
    "latitude", "longitude", "gps_accuracy", "password", "token", "access_token",
    "refresh_token", "api_key", "secret", "client_secret"
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_l = str(key).lower()
            if key_l in SENSITIVE_ATTRIBUTE_KEYS or any(
                marker in key_l for marker in ("password", "token", "secret", "api_key")
            ):
                out[key] = "<redacted>"
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(x) for x in value]
    return value



class App:
    def __init__(self) -> None:
        self.store = Store()
        self.ha = HomeAssistantClient()
        self.states: list[dict[str, Any]] = []
        self.snapshot: dict[str, Any] = {}
        self.audit: dict[str, Any] = {"summary": {}, "stats": {}, "findings": []}
        self.last_error: str | None = None
        self.last_poll: str | None = None
        self.last_audit: str | None = None
        self._last_interesting: dict[str, str] = {}
        self.tasks: list[asyncio.Task[Any]] = []

    async def start(self, app: web.Application) -> None:
        await self.ha.start()
        await self.refresh_all()
        if self.store.read_legacy_baseline() is None:
            await self.capture_legacy_baseline(reason="first_start")
        self.tasks = [
            asyncio.create_task(self.poll_loop(), name="ha_poll"),
            asyncio.create_task(self.audit_loop(), name="audit"),
        ]

    async def stop(self, app: web.Application) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.ha.close()

    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    async def refresh_states(self) -> None:
        try:
            new_states = await self.ha.states()
            self.last_error = None
            self.last_poll = self.now()
            self._record_state_changes(new_states)
            self.states = new_states
            self.snapshot = build_snapshot(self.states, self.store.settings)
        except Exception as exc:
            self.last_error = f"Home Assistant API: {exc}"
            LOG.exception("Failed to refresh HA states")

    def _interesting_entities(self) -> set[str]:
        s = self.store.settings
        entities: set[str] = set()
        for vehicle in ("citroen", "mg"):
            entities.update(s[vehicle]["entities"].values())
        for value in s.get("clever", {}).get("entities", {}).values():
            if isinstance(value, str) and "." in value:
                entities.add(value)
        for item in self.snapshot.get("clever", {}).get("entities", {}).values():
            entity_id = item.get("entity_id") if isinstance(item, dict) else None
            if isinstance(entity_id, str) and "." in entity_id:
                entities.add(entity_id)
        for value in s["shared"].values():
            if isinstance(value, str) and "." in value:
                entities.add(value)
        return entities

    def _record_state_changes(self, states: list[dict[str, Any]]) -> None:
        interesting = self._interesting_entities()
        current = {x.get("entity_id"): x.get("state") for x in states if x.get("entity_id") in interesting}
        for entity_id, state in current.items():
            old = self._last_interesting.get(entity_id)
            if old is not None and old != state:
                self.store.append_event({
                    "ts": self.now(),
                    "type": "state_change",
                    "entity_id": entity_id,
                    "from": old,
                    "to": state,
                })
        self._last_interesting = current

    async def refresh_audit(self) -> None:
        try:
            self.audit = scan(self.states, self.store.settings.get("mode", "monitor"))
            self.last_audit = self.now()
        except Exception as exc:
            LOG.exception("Audit failed")
            self.audit = {"summary": {}, "stats": {"parse_errors": [str(exc)]}, "findings": []}

    async def refresh_all(self) -> None:
        await self.refresh_states()
        await self.refresh_audit()

    async def poll_loop(self) -> None:
        while True:
            await asyncio.sleep(max(2, int(self.store.settings.get("poll_seconds", 5))))
            await self.refresh_states()

    async def audit_loop(self) -> None:
        while True:
            await asyncio.sleep(max(15, int(self.store.settings.get("audit_seconds", 60))))
            await self.refresh_audit()

    async def index(self, request: web.Request) -> web.Response:
        return web.FileResponse(STATIC_DIR / "index.html")

    def _legacy_automation_candidates(self) -> list[dict[str, Any]]:
        """Find EV-related automations that belong to the pre-Orchestrator setup."""
        candidates: dict[str, dict[str, Any]] = {}

        # Anything already recognized by Legacy Audit belongs in the rollback set.
        for finding in self.audit.get("findings", []):
            entity_id = finding.get("entity_id")
            if isinstance(entity_id, str) and entity_id.startswith("automation."):
                candidates[entity_id] = {
                    "entity_id": entity_id,
                    "name": finding.get("name") or entity_id,
                }

        # Also include EV automations that may not currently trigger an audit warning.
        markers = (
            "citro", "ë-c4", "e-c4", "mgs6", "mg s6",
            "ev smart charging", "elbil", "ev - ", "ev •",
        )
        for state in self.states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith("automation."):
                continue
            name = str((state.get("attributes") or {}).get("friendly_name") or entity_id)
            haystack = (entity_id + " " + name).lower()
            if any(marker in haystack for marker in markers):
                candidates.setdefault(entity_id, {"entity_id": entity_id, "name": name})

        out: list[dict[str, Any]] = []
        by_id = {state.get("entity_id"): state for state in self.states}
        for entity_id, item in candidates.items():
            state = by_id.get(entity_id, {})
            attrs = state.get("attributes") or {}
            out.append({
                "entity_id": entity_id,
                "name": item.get("name") or attrs.get("friendly_name") or entity_id,
                "enabled": state.get("state") == "on",
                "state": state.get("state"),
                "automation_id": attrs.get("id"),
            })
        out.sort(key=lambda x: str(x.get("name") or "").lower())
        return out

    async def capture_legacy_baseline(self, reason: str = "manual") -> dict[str, Any]:
        baseline = {
            "captured_at": self.now(),
            "captured_by_version": VERSION,
            "reason": reason,
            "description": "Rollback baseline for the legacy Home Assistant EV automations before EV Orchestrator control.",
            "automations": self._legacy_automation_candidates(),
        }
        self.store.save_legacy_baseline(baseline)
        self.store.append_event({
            "ts": self.now(),
            "type": "legacy_baseline_captured",
            "count": len(baseline["automations"]),
            "reason": reason,
        })
        return baseline

    def legacy_baseline_status(self) -> dict[str, Any]:
        baseline = self.store.read_legacy_baseline()
        if not baseline:
            return {"exists": False, "automations": [], "changed": [], "matching": 0, "total": 0}

        by_id = {state.get("entity_id"): state for state in self.states}
        changed: list[dict[str, Any]] = []
        matching = 0
        automations = baseline.get("automations", [])
        for item in automations:
            entity_id = item.get("entity_id")
            current = by_id.get(entity_id)
            expected = bool(item.get("enabled"))
            if current is None:
                changed.append({
                    "entity_id": entity_id,
                    "name": item.get("name"),
                    "baseline_enabled": expected,
                    "current": "missing",
                })
                continue
            current_enabled = current.get("state") == "on"
            if current_enabled == expected:
                matching += 1
            else:
                changed.append({
                    "entity_id": entity_id,
                    "name": item.get("name"),
                    "baseline_enabled": expected,
                    "current_enabled": current_enabled,
                })

        return {
            "exists": True,
            "captured_at": baseline.get("captured_at"),
            "captured_by_version": baseline.get("captured_by_version"),
            "reason": baseline.get("reason"),
            "total": len(automations),
            "matching": matching,
            "changed": changed,
            "automations": automations,
        }

    async def api_capture_legacy_baseline(self, request: web.Request) -> web.Response:
        baseline = await self.capture_legacy_baseline(reason="manual")
        return web.json_response({
            "ok": True,
            "baseline": baseline,
            "status": self.legacy_baseline_status(),
        })

    async def api_restore_legacy_baseline(self, request: web.Request) -> web.Response:
        baseline = self.store.read_legacy_baseline()
        if not baseline:
            return web.json_response({"error": "Ingen legacy baseline er gemt."}, status=404)

        restored = []
        failed = []
        for item in baseline.get("automations", []):
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, str) or not entity_id.startswith("automation."):
                continue
            try:
                if item.get("enabled"):
                    await self.ha.call_service("automation", "turn_on", {"entity_id": entity_id})
                else:
                    await self.ha.call_service(
                        "automation", "turn_off",
                        {"entity_id": entity_id, "stop_actions": True},
                    )
                restored.append(entity_id)
            except Exception as exc:
                failed.append({"entity_id": entity_id, "error": str(exc)})

        self.store.append_event({
            "ts": self.now(),
            "type": "legacy_baseline_restored",
            "restored_count": len(restored),
            "failed_count": len(failed),
        })
        await asyncio.sleep(0.5)
        await self.refresh_all()
        return web.json_response({
            "ok": not failed,
            "restored": restored,
            "failed": failed,
            "status": self.legacy_baseline_status(),
        })

    def _diagnostic_entity_ids(self) -> set[str]:
        ids = set(self._interesting_entities())
        for item in self.snapshot.get("clever", {}).get("entities", {}).values():
            if isinstance(item, dict) and isinstance(item.get("entity_id"), str):
                ids.add(item["entity_id"])
        for finding in self.audit.get("findings", []):
            entity_id = finding.get("entity_id")
            if isinstance(entity_id, str):
                ids.add(entity_id)
        keywords = (
            "citroen", "vr7bczkxcpe005536", "lsjwx4098tn028453", "ev_smart_charging",
            "ev_aktiv_bil", "clever", "p40_", "house_power_consumption", "watts_live_effekt"
        )
        for state in self.states:
            entity_id = state.get("entity_id", "")
            friendly = str((state.get("attributes") or {}).get("friendly_name", "")).lower()
            haystack = (entity_id + " " + friendly).lower()
            if any(k.lower() in haystack for k in keywords):
                ids.add(entity_id)
        return ids

    def _diagnostic_states(self) -> list[dict[str, Any]]:
        wanted = self._diagnostic_entity_ids()
        output: list[dict[str, Any]] = []
        for state in self.states:
            if state.get("entity_id") not in wanted:
                continue
            output.append({
                "entity_id": state.get("entity_id"),
                "state": state.get("state"),
                "last_changed": state.get("last_changed"),
                "last_updated": state.get("last_updated"),
                "attributes": _redact(state.get("attributes") or {}),
            })
        output.sort(key=lambda x: x.get("entity_id") or "")
        return output

    def diagnostic_dump(self) -> dict[str, Any]:
        return {
            "format": "EV Orchestrator AI diagnostic dump",
            "format_version": 1,
            "generated_at": self.now(),
            "orchestrator_version": VERSION,
            "purpose": "Troubleshooting export. Sensitive HA attributes such as tokens/passwords/GPS coordinates are redacted.",
            "vehicle_polling": {
                "active_vehicle_requests": False,
                "ha_state_poll_seconds": self.store.settings.get("poll_seconds", 5),
                "note": "EV Orchestrator only reads Home Assistant's cached state registry in Monitor mode. It does not call update_entity, wake, refresh, start or stop on either vehicle.",
            },
            "last_poll": self.last_poll,
            "last_audit": self.last_audit,
            "last_error": self.last_error,
            "settings": _redact(copy.deepcopy(self.store.settings)),
            "snapshot": _redact(copy.deepcopy(self.snapshot)),
            "legacy_audit": _redact(copy.deepcopy(self.audit)),
            "legacy_baseline": _redact(copy.deepcopy(self.legacy_baseline_status())),
            "timeline_events": self.store.read_events(500),
            "application_log": list(LOG_BUFFER),
            "relevant_home_assistant_states": self._diagnostic_states(),
        }

    async def api_diagnostics(self, request: web.Request) -> web.Response:
        payload = json.dumps(self.diagnostic_dump(), indent=2, ensure_ascii=False)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return web.Response(
            text=payload,
            content_type="application/json",
            charset="utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="ev-orchestrator-diagnostics-{stamp}.json"'
            },
        )

    async def api_status(self, request: web.Request) -> web.Response:
        return web.json_response({
            "version": VERSION,
            "last_poll": self.last_poll,
            "last_audit": self.last_audit,
            "last_error": self.last_error,
            "snapshot": self.snapshot,
            "vehicle_polling": {
                "active_vehicle_requests": False,
                "ha_state_poll_seconds": self.store.settings.get("poll_seconds", 5),
                "mode": "home_assistant_state_cache_only",
            },
            "audit": self.audit,
            "legacy_baseline": self.legacy_baseline_status(),
            "events": self.store.read_events(100),
        })

    async def api_refresh(self, request: web.Request) -> web.Response:
        await self.refresh_all()
        return await self.api_status(request)

    async def api_settings_get(self, request: web.Request) -> web.Response:
        return web.json_response(self.store.settings)

    async def api_settings_post(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if payload.get("mode") not in (None, "monitor"):
            return web.json_response({
                "error": "Version 0.3.8 er bevidst låst til Monitor mode. Control mode aktiveres først efter live-validering og legacy-audit er ren."
            }, status=400)
        self.store.save_settings(payload)
        self.snapshot = build_snapshot(self.states, self.store.settings)
        await self.refresh_audit()
        self.store.append_event({"ts": self.now(), "type": "settings_saved"})
        return web.json_response(self.store.settings)

    async def api_disable_automation(self, request: web.Request) -> web.Response:
        payload = await request.json()
        entity_id = payload.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id.startswith("automation."):
            return web.json_response({"error": "Ugyldigt automation entity_id"}, status=400)
        await self.ha.call_service("automation", "turn_off", {"entity_id": entity_id, "stop_actions": True})
        self.store.append_event({"ts": self.now(), "type": "automation_disabled", "entity_id": entity_id})
        await asyncio.sleep(0.5)
        await self.refresh_all()
        return web.json_response({"ok": True})

    async def api_stop_script(self, request: web.Request) -> web.Response:
        payload = await request.json()
        entity_id = payload.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id.startswith("script."):
            return web.json_response({"error": "Ugyldigt script entity_id"}, status=400)
        await self.ha.call_service("script", "turn_off", {"entity_id": entity_id})
        self.store.append_event({"ts": self.now(), "type": "script_stopped", "entity_id": entity_id})
        return web.json_response({"ok": True})


async def make_app() -> web.Application:
    controller = App()
    app = web.Application(client_max_size=1024 * 1024)
    app["controller"] = controller
    app.router.add_get("/", controller.index)
    app.router.add_get("/api/status", controller.api_status)
    app.router.add_get("/api/diagnostics", controller.api_diagnostics)
    app.router.add_post("/api/refresh", controller.api_refresh)
    app.router.add_post("/api/legacy-baseline/capture", controller.api_capture_legacy_baseline)
    app.router.add_post("/api/legacy-baseline/restore", controller.api_restore_legacy_baseline)
    app.router.add_get("/api/settings", controller.api_settings_get)
    app.router.add_post("/api/settings", controller.api_settings_post)
    app.router.add_post("/api/automation/disable", controller.api_disable_automation)
    app.router.add_post("/api/script/stop", controller.api_stop_script)
    app.router.add_static("/static/", STATIC_DIR)
    app.on_startup.append(controller.start)
    app.on_cleanup.append(controller.stop)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="0.0.0.0", port=8099, access_log=LOG)
