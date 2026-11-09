from __future__ import annotations

from typing import Any
from .client import ChatGPT2APIClient


class MultiServerDispatcher:
    """多 ChatGPT2API 服务器调度分发器。

    支持策略：
    - round_robin: 平均/轮流导入到各个启用的服务器节点；
    - single: 全部导入到指定的单个服务器。
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.strategy = str(config.get("import_strategy") or "round_robin").strip().lower()
        self.target_server_name = str(config.get("target_server") or "").strip()
        self.clients: list[ChatGPT2APIClient] = []
        self._rr_index = 0

        raw_servers = config.get("servers") or []
        for s in raw_servers:
            if s.get("enabled", True):
                self.clients.append(
                    ChatGPT2APIClient(
                        name=str(s.get("name") or s.get("url")),
                        url=str(s.get("url") or ""),
                        auth_key=str(s.get("auth_key") or ""),
                        target_group_id=s.get("target_group_id"),
                    )
                )

    def has_servers(self) -> bool:
        return len(self.clients) > 0

    def test_all_servers(self) -> list[tuple[ChatGPT2APIClient, bool, str]]:
        """测试所有配置的服务器连通性。"""
        results = []
        for client in self.clients:
            ok, msg = client.test_connection()
            results.append((client, ok, msg))
        return results

    def fetch_all_existing_emails(self) -> dict[str, set[str]]:
        """获取各服务器中已有的账号邮箱列表，返回字典 {server_name: set_of_emails}。"""
        existing_map: dict[str, set[str]] = {}
        for client in self.clients:
            existing_map[client.name] = client.fetch_existing_emails()
        return existing_map

    def get_global_existing_emails(self) -> set[str]:
        """获取所有可用服务器已有账号的并集，用于全局查重。"""
        combined = set()
        for client in self.clients:
            combined.update(client.fetch_existing_emails())
        return combined

    def pick_next_server(self) -> ChatGPT2APIClient:
        """根据策略选择本次要导入的目标服务器。"""
        if not self.clients:
            raise RuntimeError("未配置任何可用的 ChatGPT2API 服务器节点")

        # 策略一：指定单一目标服务器
        if self.strategy == "single":
            if self.target_server_name:
                for c in self.clients:
                    if c.name == self.target_server_name:
                        return c
            return self.clients[0]

        # 策略二：均匀轮询 (Round-Robin)
        chosen = self.clients[self._rr_index % len(self.clients)]
        self._rr_index += 1
        return chosen
