from __future__ import annotations

import requests
from typing import Any


class ChatGPT2APIClient:
    """与 ChatGPT2API 服务端交互的客户端。

    提供：
    1. 连通性测试与鉴权检查
    2. 全量读取已有账号邮箱（用于自动查重排重）
    3. 导入新登录账号数据（含 AT、RT、Session、Plan 等）
    """

    def __init__(self, name: str, url: str, auth_key: str = "", target_group_id: str | None = None) -> None:
        self.name = name
        self.base_url = url.rstrip("/")
        self.auth_key = auth_key.strip()
        self.target_group_id = target_group_id

    @property
    def headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ChatGPT2API-WinLoginHelper/1.0",
        }
        if self.auth_key:
            headers["Authorization"] = f"Bearer {self.auth_key}"
        return headers

    def test_connection(self) -> tuple[bool, str]:
        """测试服务器是否在线且密钥有效。"""
        try:
            resp = requests.get(f"{self.base_url}/version", headers=self.headers, timeout=10)
            if resp.status_code == 200:
                ver_info = resp.json()
                ver = ver_info.get("version", "unknown")
                return True, f"在线 (v{ver})"
            return False, f"HTTP {resp.status_code}"
        except Exception as exc:
            return False, f"连接失败: {exc}"

    def fetch_existing_emails(self) -> set[str]:
        """分页获取服务器中已有的全部账号邮箱（小写），用于本地查重。"""
        existing = set()
        page = 1
        page_size = 500

        while True:
            try:
                resp = requests.get(
                    f"{self.base_url}/api/accounts",
                    headers=self.headers,
                    params={"page": page, "page_size": page_size, "status": "all"},
                    timeout=15,
                )
                if resp.status_code != 200:
                    break

                data = resp.json() or {}
                accounts = data.get("accounts") or []
                for acc in accounts:
                    email = str(acc.get("email") or "").strip().lower()
                    if email:
                        existing.add(email)

                total = int(data.get("total") or 0)
                if len(existing) >= total or not accounts:
                    break

                page += 1
            except Exception:
                break

        return existing

    def push_account(
        self,
        account_payload: dict[str, Any],
        group_id: str | None = None,
    ) -> tuple[bool, str]:
        """将成功登录的账号凭据上传至服务端数据库。"""
        target_group = group_id if group_id is not None else self.target_group_id
        payload = {
            "accounts": [account_payload],
            "tokens": [],
            "target_group_id": target_group,
            "sync_after_import": True,
        }

        try:
            resp = requests.post(
                f"{self.base_url}/api/accounts",
                headers=self.headers,
                json=payload,
                timeout=30,
            )
            if resp.status_code in (200, 201):
                data = resp.json() or {}
                added = data.get("added", 0)
                if added > 0:
                    return True, "成功导入入库"
                return True, "已入库或已存在"
            err_msg = ""
            try:
                err_msg = resp.json().get("detail", {}).get("error", "")
            except Exception:
                err_msg = resp.text[:200]
            return False, f"服务端返回 HTTP {resp.status_code}: {err_msg}"
        except Exception as exc:
            return False, f"上传至服务端失败: {exc}"
