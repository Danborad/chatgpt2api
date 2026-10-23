from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.support import require_admin
from services.register_service import (
    new_register_service,
    register_service,
    roxy_register_service,
)


class RegisterConfigRequest(BaseModel):
    mail: dict | None = None
    proxy: str | None = None
    total: int | None = None
    threads: int | None = None
    mode: str | None = None
    target_quota: int | None = None
    target_available: int | None = None
    check_interval: int | None = None
    periodic_interval_hours: float | None = None
    periodic_count: int | None = None
    schedule_enabled: bool | None = None
    schedule_start: str | None = None
    schedule_end: str | None = None
    roxy: dict | None = None


class OutlookPoolResetRequest(BaseModel):
    scope: str | None = None


def create_router() -> APIRouter:
    router = APIRouter()

    def new_register_snapshot() -> dict:
        snapshot = new_register_service.get()
        shared = register_service.get()
        for key in (
            "mail",
            "proxy",
            "total",
            "threads",
            "mode",
            "target_quota",
            "target_available",
            "check_interval",
            "periodic_interval_hours",
            "periodic_count",
            "schedule_enabled",
            "schedule_start",
            "schedule_end",
        ):
            snapshot[key] = shared[key]
        return snapshot

    def roxy_register_snapshot() -> dict:
        snapshot = roxy_register_service.get()
        shared = register_service.get()
        for key in (
            "mail",
            "proxy",
            "total",
            "threads",
            "mode",
            "target_quota",
            "target_available",
            "check_interval",
            "periodic_interval_hours",
            "periodic_count",
            "schedule_enabled",
            "schedule_start",
            "schedule_end",
        ):
            snapshot[key] = shared[key]
        if "roxy" not in snapshot or not isinstance(snapshot.get("roxy"), dict):
            from services.register.roxy import config as rc
            snapshot["roxy"] = rc.get_roxy_config_dict()
        # 日志只推最近 80 条，降低 SSE 传输与前端渲染开销。
        if isinstance(snapshot.get("logs"), list):
            snapshot["logs"] = snapshot["logs"][-80:]
        return snapshot

    @router.get("/api/register")
    async def get_register_config(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.get()}

    @router.post("/api/register")
    async def update_register_config(body: RegisterConfigRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        updates = body.model_dump(exclude_none=True)
        if "roxy" in updates and updates["roxy"] is not None:
            roxy_register_service.update({"roxy": updates["roxy"]})
        result = register_service.update({k: v for k, v in updates.items() if k != "roxy"})
        schedule_updates = {
            key: result[key]
            for key in ("schedule_enabled", "schedule_start", "schedule_end")
            if key in updates
        }
        if schedule_updates:
            new_register_service.update(schedule_updates)
        return {"register": result}

    @router.post("/api/register/start")
    async def start_register(body: RegisterConfigRequest | None = None, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        updates = body.model_dump(exclude_none=True) if body is not None else None
        return {"register": register_service.start(updates)}

    @router.post("/api/register/stop")
    async def stop_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.stop()}

    @router.post("/api/register/reset")
    async def reset_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset()}

    @router.post("/api/register/outlook-pool/reset")
    async def reset_outlook_pool(body: OutlookPoolResetRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset_outlook_pool(body.scope or "all")}

    @router.get("/api/register/events")
    async def register_events(token: str = ""):
        require_admin(f"Bearer {token}")

        async def stream():
            last = ""
            while True:
                payload = json.dumps(register_service.get(), ensure_ascii=False)
                if payload != last:
                    last = payload
                    yield f"data: {payload}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @router.get("/api/register/new")
    async def get_new_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": new_register_snapshot()}

    @router.post("/api/register/new/start")
    async def start_new_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        new_register_service.start(register_service.shared_config_snapshot())
        return {"register": new_register_snapshot()}

    @router.post("/api/register/new/stop")
    async def stop_new_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        new_register_service.stop()
        return {"register": new_register_snapshot()}

    @router.post("/api/register/new/reset")
    async def reset_new_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        new_register_service.reset()
        return {"register": new_register_snapshot()}

    @router.get("/api/register/new/events")
    async def new_register_events(token: str = ""):
        require_admin(f"Bearer {token}")

        async def stream():
            last = ""
            while True:
                payload = json.dumps(new_register_snapshot(), ensure_ascii=False)
                if payload != last:
                    last = payload
                    yield f"data: {payload}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @router.get("/api/register/roxy")
    async def get_roxy_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": roxy_register_snapshot()}

    @router.post("/api/register/roxy")
    async def update_roxy_register_config(
        body: RegisterConfigRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        updates = body.model_dump(exclude_none=True)
        if "roxy" in updates and updates["roxy"] is not None:
            roxy_register_service.update({"roxy": updates["roxy"]})
        shared_updates = {k: v for k, v in updates.items() if k != "roxy"}
        if shared_updates:
            register_service.update(shared_updates)
        return {"register": roxy_register_snapshot()}

    @router.post("/api/register/roxy/start")
    async def start_roxy_register(
            body: RegisterConfigRequest | None = None,
            authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        updates = body.model_dump(exclude_none=True) if body is not None else None
        if updates:
            if "roxy" in updates and updates["roxy"] is not None:
                roxy_register_service.update({"roxy": updates["roxy"]})
            shared_updates = {k: v for k, v in updates.items() if k != "roxy"}
            if shared_updates:
                register_service.update(shared_updates)
        roxy_register_service.start(register_service.shared_config_snapshot())
        return {"register": roxy_register_snapshot()}

    @router.post("/api/register/roxy/stop")
    async def stop_roxy_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        roxy_register_service.stop()
        return {"register": roxy_register_snapshot()}

    @router.post("/api/register/roxy/reset")
    async def reset_roxy_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        roxy_register_service.reset()
        return {"register": roxy_register_snapshot()}

    @router.get("/api/register/roxy/workspaces")
    async def get_roxy_workspaces(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.register.roxy.client import RoxyBrowserClient
        client = RoxyBrowserClient()
        return await run_in_threadpool(client.list_workspaces)

    @router.get("/api/register/roxy/events")
    async def roxy_register_events(token: str = ""):
        require_admin(f"Bearer {token}")

        async def stream():
            last = ""
            while True:
                payload = json.dumps(roxy_register_snapshot(), ensure_ascii=False)
                if payload != last:
                    last = payload
                    yield f"data: {payload}\n\n"
                await asyncio.sleep(1.0)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
