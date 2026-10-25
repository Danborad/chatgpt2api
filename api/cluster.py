from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.support import require_admin
from services.cluster_service import cluster_service


class ClusterConfigRequest(BaseModel):
    enabled: bool | None = None
    strategy: str | None = None
    local_weight: int | None = None
    local_priority: int | None = None
    retry_on_failure: bool | None = None
    timeout_seconds: int | None = None


class ClusterNodeCreateRequest(BaseModel):
    name: str = "集群节点"
    url: str = Field(..., min_length=1)
    api_key: str = ""
    weight: int = 1
    priority: int = 1
    enabled: bool = True


class ClusterNodeUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    api_key: str | None = None
    weight: int | None = None
    priority: int | None = None
    enabled: bool | None = None


class ClusterTestUrlRequest(BaseModel):
    url: str = Field(..., min_length=1)
    api_key: str = ""


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/cluster")
    async def get_cluster_config(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"cluster": cluster_service.get_config()}

    @router.post("/api/cluster")
    async def update_cluster_config(
        body: ClusterConfigRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        updates = body.model_dump(exclude_none=True)
        updated = cluster_service.update_config(updates)
        return {"cluster": updated}

    @router.post("/api/cluster/nodes")
    async def add_cluster_node(
        body: ClusterNodeCreateRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            node = cluster_service.add_node(body.model_dump())
            return {"node": node, "cluster": cluster_service.get_config()}
        except Exception as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.put("/api/cluster/nodes/{node_id}")
    async def update_cluster_node(
        node_id: str,
        body: ClusterNodeUpdateRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            node = cluster_service.update_node(node_id, body.model_dump(exclude_none=True))
            return {"node": node, "cluster": cluster_service.get_config()}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.delete("/api/cluster/nodes/{node_id}")
    async def delete_cluster_node(
        node_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        deleted = cluster_service.delete_node(node_id)
        if not deleted:
            raise HTTPException(status_code=404, detail={"error": f"节点不存在: {node_id}"})
        return {"success": True, "cluster": cluster_service.get_config()}

    @router.post("/api/cluster/nodes/{node_id}/test")
    async def test_cluster_node(
        node_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            result = await run_in_threadpool(cluster_service.test_node, node_id)
            return {"result": result, "cluster": cluster_service.get_config()}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc

    @router.post("/api/cluster/test-url")
    async def test_raw_node_url(
        body: ClusterTestUrlRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        result = await run_in_threadpool(cluster_service.test_node_url, body.url, body.api_key)
        return {"result": result}

    return router
