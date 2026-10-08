from __future__ import annotations

import os
from typing import Any

import aiohttp


class HomeAssistantClient:
    def __init__(self) -> None:
        self.base = "http://supervisor/core/api"
        self.token = os.environ.get("SUPERVISOR_TOKEN", "")
        self.session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        timeout = aiohttp.ClientTimeout(total=15)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )

    async def close(self) -> None:
        if self.session:
            await self.session.close()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.session:
            raise RuntimeError("HA client not started")
        url = f"{self.base}{path}"
        async with self.session.request(method, url, **kwargs) as response:
            response.raise_for_status()
            if response.status == 204:
                return None
            return await response.json()

    async def states(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/states")

    async def state(self, entity_id: str) -> dict[str, Any] | None:
        try:
            return await self._request("GET", f"/states/{entity_id}")
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                return None
            raise

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> Any:
        return await self._request("POST", f"/services/{domain}/{service}", json=data)
