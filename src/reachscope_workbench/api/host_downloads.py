"""Host preparation downloads; this transport adapter never executes captures."""

from __future__ import annotations

import asyncio
import hashlib
import json

from fastapi import FastAPI
from fastapi.responses import Response

from ..core.registry import ModuleRegistry


def register_host_downloads(app: FastAPI, modules: ModuleRegistry) -> None:
    @app.get("/api/host/template", response_class=Response)
    async def host_input_template() -> Response:
        from ..modules.host.demo import input_template

        modules.get("host")
        body = (json.dumps(input_template(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="reachscope-host-template.json"'})

    async def artifact(*, source: bool) -> Response:
        from ..collectors.host.builder import build_zipapp

        modules.get("host")
        body = await asyncio.to_thread(build_zipapp)
        # A pyz is itself a readable source ZIP. Both downloads contain the
        # identical reviewed code; no generated remote commands or user paths.
        filename = "reachscope-host-collector-source.zip" if source else "reachscope-host-collector.pyz"
        return Response(body, media_type="application/zip" if source else "application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                 "X-Content-SHA256": hashlib.sha256(body).hexdigest(), "Cache-Control": "no-store"})

    @app.get("/api/host/collector", response_class=Response)
    async def host_collector() -> Response:
        return await artifact(source=False)

    @app.get("/api/host/collector/source", response_class=Response)
    async def host_collector_source() -> Response:
        return await artifact(source=True)
