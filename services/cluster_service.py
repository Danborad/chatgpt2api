"""多 ChatGPT2API 实例集群分发与负载均衡服务

功能支持：
- 支持配置多个远程 ChatGPT2API 站点（URL + API Key + 权重 + 优先级 + 启用状态）；
- 支持多种集群调度策略：
  1. local_first: 本地优先，远程备用（本地账号可用时走本地，本地无号/冷却/失败时自动故障转移到集群站点）
  2. round_robin: 顺序轮询（在本地节点与各远程节点之间按权重轮流分发）
  3. random: 随机分发（按本地与远程节点的权重比例随机选择）
  4. priority_order: 优先级主备（按优先级数值由高到低依次尝试，故障时自动切下一个）
  5. remote_only: 仅远程集群（不消耗本地账号，全部转发到远程集群节点）
- 自动故障转移（Failover）：远程节点连接超时或 5xx 异常时自动尝试下一个候选节点；
- 节点连通性测试与延迟检测。
"""
from __future__ import annotations

import json
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from curl_cffi import requests
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, StreamingResponse

from services.config import DATA_DIR
from utils.log import logger

CLUSTER_FILE = DATA_DIR / "cluster.json"

ClusterStrategy = Literal["local_first", "round_robin", "random", "priority_order", "remote_only"]

DEFAULT_CLUSTER_CONFIG: dict[str, Any] = {
    "enabled": False,
    "strategy": "local_first",
    "local_weight": 1,
    "local_priority": 1,
    "retry_on_failure": True,
    "timeout_seconds": 180,
    "nodes": [],
}


class ClusterService:
    def __init__(self, store_file: Path = CLUSTER_FILE) -> None:
        self._store_file = store_file
        self._lock = threading.RLock()
        self._rr_index = 0
        self._config = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            if self._store_file.exists():
                data = json.loads(self._store_file.read_text(encoding="utf-8"))
                return self._normalize(data)
        except Exception as exc:
            logger.warning({"event": "cluster_config_load_failed", "error": str(exc)})
        return dict(DEFAULT_CLUSTER_CONFIG)

    def _normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        cfg = dict(DEFAULT_CLUSTER_CONFIG)
        cfg.update({k: v for k, v in raw.items() if k in DEFAULT_CLUSTER_CONFIG})
        cfg["enabled"] = bool(cfg.get("enabled", False))
        valid_strategies = {"local_first", "round_robin", "random", "priority_order", "remote_only"}
        strat = str(cfg.get("strategy") or "local_first").strip()
        cfg["strategy"] = strat if strat in valid_strategies else "local_first"
        cfg["local_weight"] = max(0, int(cfg.get("local_weight") or 1))
        cfg["local_priority"] = max(1, int(cfg.get("local_priority") or 1))
        cfg["retry_on_failure"] = bool(cfg.get("retry_on_failure", True))
        cfg["timeout_seconds"] = max(10, int(cfg.get("timeout_seconds") or 180))

        raw_nodes = raw.get("nodes")
        normalized_nodes = []
        if isinstance(raw_nodes, list):
            for n in raw_nodes:
                if isinstance(n, dict) and n.get("url"):
                    node_id = str(n.get("id") or "").strip() or f"node_{uuid.uuid4().hex[:8]}"
                    normalized_nodes.append({
                        "id": node_id,
                        "name": str(n.get("name") or "未命名节点").strip(),
                        "url": str(n.get("url") or "").strip().rstrip("/"),
                        "api_key": str(n.get("api_key") or "").strip(),
                        "weight": max(1, int(n.get("weight") or 1)),
                        "priority": max(1, int(n.get("priority") or 1)),
                        "enabled": bool(n.get("enabled", True)),
                        "status": str(n.get("status") or "unknown"),
                        "latency_ms": int(n.get("latency_ms") or 0),
                        "last_checked_at": str(n.get("last_checked_at") or ""),
                        "last_error": str(n.get("last_error") or ""),
                    })
        cfg["nodes"] = normalized_nodes
        return cfg

    def _save(self) -> None:
        try:
            self._store_file.parent.mkdir(parents=True, exist_ok=True)
            self._store_file.write_text(json.dumps(self._config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.error({"event": "cluster_config_save_failed", "error": str(exc)})

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._config, ensure_ascii=False))

    def update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            for k in ("enabled", "strategy", "local_weight", "local_priority", "retry_on_failure", "timeout_seconds"):
                if k in updates and updates[k] is not None:
                    self._config[k] = updates[k]
            if "nodes" in updates and isinstance(updates["nodes"], list):
                self._config["nodes"] = updates["nodes"]
            self._config = self._normalize(self._config)
            self._save()
            return self.get_config()

    def add_node(self, node_data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            url = str(node_data.get("url") or "").strip().rstrip("/")
            if not url:
                raise ValueError("节点 URL 不能为空")
            node = {
                "id": str(node_data.get("id") or "").strip() or f"node_{uuid.uuid4().hex[:8]}",
                "name": str(node_data.get("name") or "集群节点").strip(),
                "url": url,
                "api_key": str(node_data.get("api_key") or "").strip(),
                "weight": max(1, int(node_data.get("weight") or 1)),
                "priority": max(1, int(node_data.get("priority") or 1)),
                "enabled": bool(node_data.get("enabled", True)),
                "status": "unknown",
                "latency_ms": 0,
                "last_checked_at": "",
                "last_error": "",
            }
            self._config["nodes"].append(node)
            self._config = self._normalize(self._config)
            self._save()
            return node

    def update_node(self, node_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            for n in self._config["nodes"]:
                if n["id"] == node_id:
                    for k in ("name", "url", "api_key", "weight", "priority", "enabled", "status", "latency_ms", "last_checked_at", "last_error"):
                        if k in updates and updates[k] is not None:
                            n[k] = updates[k]
                    self._config = self._normalize(self._config)
                    self._save()
                    return dict(n)
            raise KeyError(f"节点不存在: {node_id}")

    def delete_node(self, node_id: str) -> bool:
        with self._lock:
            before_len = len(self._config["nodes"])
            self._config["nodes"] = [n for n in self._config["nodes"] if n["id"] != node_id]
            if len(self._config["nodes"]) < before_len:
                self._save()
                return True
            return False

    def test_node_url(self, url: str, api_key: str, timeout: float = 8.0) -> dict[str, Any]:
        clean_url = str(url or "").strip().rstrip("/")
        if not clean_url:
            return {"ok": False, "error": "URL 不能为空"}
        headers = {
            "User-Agent": "ChatGPT2API-ClusterClient/1.0",
            "Accept": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}" if not api_key.startswith("Bearer ") else api_key

        t0 = time.perf_counter()
        try:
            resp = requests.get(
                f"{clean_url}/v1/models",
                headers=headers,
                timeout=timeout,
                verify=False,
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            if resp.status_code == 200:
                data = resp.json() if resp.text else {}
                models = data.get("data") if isinstance(data, dict) else []
                return {
                    "ok": True,
                    "status_code": 200,
                    "latency_ms": elapsed_ms,
                    "models_count": len(models) if isinstance(models, list) else 0,
                }
            return {
                "ok": False,
                "status_code": resp.status_code,
                "latency_ms": elapsed_ms,
                "error": f"HTTP {resp.status_code}: {resp.text[:150]}",
            }
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            return {"ok": False, "latency_ms": elapsed_ms, "error": str(exc)[:200]}

    def test_node(self, node_id: str) -> dict[str, Any]:
        with self._lock:
            target = next((n for n in self._config["nodes"] if n["id"] == node_id), None)
            if not target:
                raise KeyError(f"节点不存在: {node_id}")
            url = target["url"]
            key = target["api_key"]

        res = self.test_node_url(url, key)
        with self._lock:
            target = next((n for n in self._config["nodes"] if n["id"] == node_id), None)
            if target:
                target["status"] = "online" if res.get("ok") else "offline"
                target["latency_ms"] = res.get("latency_ms", 0)
                target["last_checked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                target["last_error"] = "" if res.get("ok") else str(res.get("error") or "")
                self._save()
        return res

    def is_cluster_active(self) -> bool:
        with self._lock:
            if not self._config.get("enabled"):
                return False
            # 至少有一个启用的远程节点
            return any(n.get("enabled") for n in self._config.get("nodes", []))

    def get_candidate_targets(self, excluded_ids: set[str] | None = None) -> list[dict[str, Any]]:
        """获取所有参与调度的候选节点（包含本地节点与远程节点）。"""
        excluded = excluded_ids or set()
        with self._lock:
            cfg = self._config
            candidates: list[dict[str, Any]] = []

            # 远程节点
            for n in cfg.get("nodes", []):
                if n.get("enabled") and n["id"] not in excluded:
                    candidates.append({
                        "type": "remote",
                        "id": n["id"],
                        "name": n["name"],
                        "node": dict(n),
                        "weight": max(1, int(n.get("weight") or 1)),
                        "priority": max(1, int(n.get("priority") or 1)),
                    })

            # 本地节点
            if "local" not in excluded and cfg.get("strategy") != "remote_only":
                candidates.append({
                    "type": "local",
                    "id": "local",
                    "name": "本地节点 (Master)",
                    "weight": max(0, int(cfg.get("local_weight", 1))),
                    "priority": max(1, int(cfg.get("local_priority", 1))),
                })

            return candidates

    def pick_target(self, excluded_ids: set[str] | None = None) -> dict[str, Any] | None:
        """根据配置的调度策略挑选一个调度目标。"""
        candidates = self.get_candidate_targets(excluded_ids)
        if not candidates:
            return None

        with self._lock:
            strategy = self._config.get("strategy") or "local_first"

            if strategy == "local_first":
                local_cand = next((c for c in candidates if c["type"] == "local"), None)
                if local_cand:
                    return local_cand
                # 本地不可用或已排除，按优先级顺序在远程中选
                remote_cands = [c for c in candidates if c["type"] == "remote"]
                if remote_cands:
                    remote_cands.sort(key=lambda x: x["priority"])
                    return remote_cands[0]
                return None

            if strategy == "priority_order":
                # 按优先级升序排列（1 优先于 2），同优先级内按权重随机
                candidates.sort(key=lambda x: x["priority"])
                best_priority = candidates[0]["priority"]
                top_group = [c for c in candidates if c["priority"] == best_priority]
                weights = [c["weight"] for c in top_group]
                return random.choices(top_group, weights=weights, k=1)[0]

            if strategy == "random":
                weights = [c["weight"] for c in candidates]
                if sum(weights) <= 0:
                    return candidates[0]
                return random.choices(candidates, weights=weights, k=1)[0]

            if strategy == "round_robin":
                expanded: list[dict[str, Any]] = []
                for c in candidates:
                    expanded.extend([c] * max(1, c["weight"]))
                idx = self._rr_index % len(expanded)
                self._rr_index += 1
                return expanded[idx]

            if strategy == "remote_only":
                remote_cands = [c for c in candidates if c["type"] == "remote"]
                if not remote_cands:
                    return None
                weights = [c["weight"] for c in remote_cands]
                return random.choices(remote_cands, weights=weights, k=1)[0]

        return candidates[0]

    def forward_remote_request(
        self,
        node: dict[str, Any],
        path: str,
        payload: dict[str, Any],
        stream: bool = False,
    ) -> Response:
        """将请求透明中继到指定的远程 ChatGPT2API 实例。"""
        target_url = f"{node['url'].rstrip('/')}{path}"
        api_key = node.get("api_key", "").strip()
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "User-Agent": "ChatGPT2API-ClusterForwarder/1.0",
            "X-ChatGPT2API-Cluster-Hop": "1",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}" if not api_key.startswith("Bearer ") else api_key

        timeout_secs = int(self._config.get("timeout_seconds") or 180)
        logger.info({
            "event": "cluster_forward_start",
            "node_name": node.get("name"),
            "node_url": node.get("url"),
            "path": path,
            "stream": stream,
        })

        if stream:
            resp = requests.post(
                target_url,
                json=payload,
                headers=headers,
                stream=True,
                timeout=timeout_secs,
                verify=False,
            )
            if resp.status_code != 200:
                body_preview = ""
                try:
                    body_preview = resp.text[:300]
                except Exception:
                    pass
                resp.close()
                raise RuntimeError(f"集群节点 [{node.get('name')}] 返回 HTTP {resp.status_code}: {body_preview}")

            def _stream_iterator() -> Iterator[bytes]:
                try:
                    for chunk in resp.iter_content(chunk_size=None):
                        if chunk:
                            yield chunk
                finally:
                    resp.close()

            return StreamingResponse(_stream_iterator(), media_type="text/event-stream")

        resp = requests.post(
            target_url,
            json=payload,
            headers=headers,
            timeout=timeout_secs,
            verify=False,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"集群节点 [{node.get('name')}] 返回 HTTP {resp.status_code}: {resp.text[:300]}")

        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type="application/json",
        )

    async def dispatch_request(
        self,
        path: str,
        payload: dict[str, Any],
        stream: bool,
        call: Any,
        local_handler: Callable[[], Any],
    ) -> Any:
        """核心统一分发入口：根据集群调度策略选择本地或远程执行，支持自动重试与故障转移。"""
        if not self.is_cluster_active():
            return None

        # 防止集群节点配置循环嵌套请求 (Loop Protection)
        if hasattr(call, "trace_metadata"):
            req_headers = call.trace_metadata.get("request_headers") or {}
            if isinstance(req_headers, dict) and req_headers.get("x_cluster_hop"):
                logger.info({"event": "cluster_hop_detected_force_local", "call_id": getattr(call, "call_id", "")})
                return None

        excluded: set[str] = set()
        retry_on_failure = bool(self._config.get("retry_on_failure", True))
        strategy = str(self._config.get("strategy") or "local_first")

        # 策略为 local_first 时，先尝试本地
        if strategy == "local_first":
            try:
                return await local_handler()
            except Exception as local_err:
                logger.warning({
                    "event": "cluster_local_first_failed",
                    "error": str(local_err)[:200],
                    "msg": "本地执行失败，自动启动集群故障转移至远程节点...",
                })
                excluded.add("local")

        # 调度循环
        while True:
            target = self.pick_target(excluded)
            if not target:
                if "local" in excluded and strategy == "local_first":
                    # 全部节点均失败，直接让调用方抛错
                    return None
                # 没有候选目标了
                return None

            target_type = target["type"]
            target_id = target["id"]

            if target_type == "local":
                try:
                    call.summary = f"{call.summary} (本地)"
                    return await local_handler()
                except Exception as exc:
                    logger.warning({"event": "cluster_target_local_failed", "error": str(exc)[:200]})
                    excluded.add("local")
                    if not retry_on_failure:
                        raise
                    continue

            # 远程节点转发
            node = target["node"]
            try:
                call.summary = f"{call.summary} [集群:{node.get('name')}]"
                return await run_in_threadpool(self.forward_remote_request, node, path, payload, stream)
            except Exception as exc:
                logger.warning({
                    "event": "cluster_node_forward_failed",
                    "node_id": node.get("id"),
                    "node_name": node.get("name"),
                    "error": str(exc)[:250],
                })
                excluded.add(target_id)
                if not retry_on_failure:
                    raise
                continue


cluster_service = ClusterService()
