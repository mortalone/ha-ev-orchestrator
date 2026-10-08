from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from audit import scan
from ha_client import HomeAssistantClient
from model import build_snapshot
from store import Store

VERSION = "0.3.0"
STATIC_DIR = Path(__file__).parent / "static"

LOG_LEVEL = os.environ.get("EV_ORCH_LOG_LEVEL", "info").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("ev_orchestrator")


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

    async def api_status(self, request: web.Request) -> web.Response:
        return web.json_response({
            "version": VERSION,
            "last_poll": self.last_poll,
            "last_audit": self.last_audit,
            "last_error": self.last_error,
            "snapshot": self.snapshot,
            "audit": self.audit,
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
                "error": "Version 0.3.0 er bevidst låst til Monitor mode. Control mode aktiveres først efter live-validering og legacy-audit er ren."
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
    app.router.add_post("/api/refresh", controller.api_refresh)
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
