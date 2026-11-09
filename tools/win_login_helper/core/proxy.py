from __future__ import annotations

import re
import uuid
from urllib.parse import urlparse, urlunparse


def derive_isolated_proxy(base_proxy: str, identity: str = "", salt: str = "") -> str:
    """针对粘性代理池（如 Resin、动态住宅代理、Luminati），为每个账号派生独立隔离的会话出口代理。

    原理：
    - 输入基础代理：http://user@proxy-pool.local:2260
    - 账号1派生：  http://user.acc_user1@proxy-pool.local:2260  -> Resin 分配独立干净 IP A
    - 账号2派生：  http://user.acc_user2@proxy-pool.local:2260  -> Resin 分配独立干净 IP B
    - 重试时加入 salt： http://user.acc_user1_r1@...         -> 强制更换全新出口 IP
    """
    if not base_proxy or not base_proxy.strip():
        return ""

    url = base_proxy.strip()
    try:
        parsed = urlparse(url)
        if not parsed.hostname or not parsed.username:
            return url

        # 提取邮箱前缀作为基础标识，清理非安全字符
        raw_prefix = identity.split("@")[0] if identity else ""
        clean_prefix = re.sub(r"[^a-zA-Z0-9_]", "", raw_prefix)
        if not clean_prefix:
            clean_prefix = uuid.uuid4().hex[:8]
        else:
            clean_prefix = clean_prefix[:14]

        # 如果指定了重试 salt，拼接区分
        if salt:
            clean_salt = re.sub(r"[^a-zA-Z0-9_]", "", salt)[:6]
            session_id = f"{clean_prefix}_{clean_salt}"
        else:
            session_id = clean_prefix

        username = parsed.username
        password = parsed.password

        # 若用户名中已包含点号（如 nohks.session），替换后缀；否则直接追加 .session_id
        if "." in username:
            base_user = username.split(".")[0]
            new_username = f"{base_user}.{session_id}"
        else:
            new_username = f"{username}.{session_id}"

        netloc_auth = f"{new_username}:{password}" if password else new_username
        port_part = f":{parsed.port}" if parsed.port else ""
        new_netloc = f"{netloc_auth}@{parsed.hostname}{port_part}"
        return urlunparse((parsed.scheme, new_netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    except Exception:
        return url
