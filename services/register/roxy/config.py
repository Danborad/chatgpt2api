# -*- coding: utf-8 -*-
"""
RoxyBrowser 指纹浏览器自动化注册配置。

官方文档：
- API 默认 host: http://127.0.0.1:50000
- 所有接口请求头必须带 token
- 可配合 Selenium / Puppeteer / Playwright 自动化

移植自 turb-gpt-free-register/config/roxybrowser.py，
去掉对 turb config.env_loader 的依赖，改为进程环境变量读取。
"""
import os
import random
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def _load_dotenv(path: Path) -> None:
    """极简 .env 解析：把项目根 .env 的 ROXY_* 注入 os.environ，不覆盖已有环境变量。"""
    try:
        if not path.is_file():
            return
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if os.getenv(key) is None:
                os.environ[key] = value
    except Exception:
        pass


def env_str(key: str, default: str = "") -> str:
    return str(os.getenv(key, default)).strip() or default


_load_dotenv(_ENV_PATH)


# 注册驱动：
#   "protocol"     = 原有 curl_cffi 纯协议注册（容易封号，不建议）
#   "roxy"         = 调用 RoxyBrowser 指纹浏览器 + Selenium 自动化注册
#   "cloak"        = 调用 CloakBrowser + Playwright/Selenium 适配层注册
#   "browser_use"  = Browser Use Cloud stealth Chromium + Playwright
#   "skyvern"      = Skyvern Browser Sessions + Playwright
REGISTRATION_DRIVER: str = "roxy"

# RoxyBrowser 本地 API
ROXY_API_BASE: str = env_str("ROXY_API_BASE", "http://127.0.0.1:50000")
ROXY_API_TOKEN: str = env_str("ROXY_API_TOKEN", "")

# Roxy 环境/Profile ID；留空时使用 ROXY_PROFILE_CREATE_* 先创建临时环境（如果接口支持）
ROXY_PROFILE_ID: str = ""

# Roxy 工作区 ID。Roxy 创建 Profile 时接口要求 workspaceId，必须填写。
# 可在 Roxy 工作区/团队页面或 API 返回中查看。
ROXY_WORKSPACE_ID: str = env_str("ROXY_WORKSPACE_ID", "")

# Roxy 项目 ID。/browser/workspace 返回 project_details.projectId；创建 Profile 时一并提交。
ROXY_PROJECT_ID: str = env_str("ROXY_PROJECT_ID", "")

# 获取团队/工作区列表接口路径。不同版本若不同，可在 WebUI 修改；客户端也会自动尝试多个常见路径。
ROXY_WORKSPACE_LIST_PATH: str = "/browser/workspace"
ROXY_WORKSPACE_LIST_METHOD: str = "GET"

# 接口路径模板。不同版本如有差异，只改这里即可。
# {profile_id} 会替换为 ROXY_PROFILE_ID。
ROXY_OPEN_PATH: str = "/browser/open"
ROXY_CLOSE_PATH: str = "/browser/close"
ROXY_CREATE_PATH: str = "/browser/create"

# 接口方法：常见 open/close 为 GET；若你的版本要求 POST，可在 WebUI/配置里改。
ROXY_OPEN_METHOD: str = "POST"
ROXY_CLOSE_METHOD: str = "POST"
ROXY_CREATE_METHOD: str = "POST"

# 打开浏览器时是否无头启动：
#   False = 显示 Roxy 浏览器窗口（便于观察/调试）
#   True  = 无头启动，不显示窗口（如果当前 Roxy 版本支持 headless）
ROXY_OPEN_HEADLESS: bool = False

# 打开浏览器时附加参数；会合并到 /browser/open 请求体，优先级高于默认值。
ROXY_OPEN_EXTRA_PARAMS: dict = {}

# Selenium 行为
ROXY_SELENIUM_TIMEOUT: int = 90
ROXY_KEEP_BROWSER_OPEN: bool = False

# 注册成功后是否发送测试消息激活账号，降低被风控判定为批量账号的概率。
ROXY_ACTIVATE_ACCOUNT: bool = env_str("ROXY_ACTIVATE_ACCOUNT", "true").lower() in ("1", "true", "yes", "on")

# 邮箱验证码单次等待最长秒数（超时即放弃当前账号，不自动重试，避免长时间空等）。
ROXY_OTP_WAIT_SECONDS: int = int(env_str("ROXY_OTP_WAIT_SECONDS", "60") or 60)

# Roxy API transient 错误重试。create 接口默认不重试，避免超时后重复创建孤儿环境；open/close/delete 会重试。
ROXY_API_RETRIES: int = 3
ROXY_API_RETRY_DELAY: int = 2

# 环境生命周期：
#   True  = 一号一环境：每个账号强制创建新 Profile，用完关闭并删除，不允许复用 ROXY_PROFILE_ID
#   False = 可复用 ROXY_PROFILE_ID 或只关闭不删除
ROXY_ONE_PROFILE_PER_ACCOUNT: bool = True

# 一号一环境结束后是否删除 Profile。建议保持 True。
ROXY_DELETE_PROFILE_AFTER_RUN: bool = True

# 删除环境接口路径/方法；如你的 Roxy 版本不同，只改这里。
ROXY_DELETE_PATH: str = "/browser/delete"
ROXY_DELETE_METHOD: str = "POST"

# 创建 Roxy 环境时随机系统指纹；开启后每次 /browser/create 在 Windows / macOS 里随机选一个，
# 避免固定 macOS 指纹。
ROXY_RANDOM_OS_ON_CREATE: bool = True
ROXY_RANDOM_OS_CHOICES: str = "Windows,macOS"

# 创建 Roxy 环境时随机名称；开启后会覆盖 ROXY_PROFILE_CREATE_PAYLOAD 里的固定 name。
ROXY_RANDOM_PROFILE_NAME_ON_CREATE: bool = True
ROXY_PROFILE_NAME_PREFIX: str = "rb"

# 创建 Roxy 环境时默认系统指纹。仅在 ROXY_RANDOM_OS_ON_CREATE=False 时使用。
# Roxy 官方 os 枚举：Windows / macOS / Linux / IOS / Android。
ROXY_DEFAULT_OS: str = "macOS"
# 留空则使用 Roxy 对应系统的默认/最大版本；如需固定可填 15.3.2、14.7 等。
ROXY_DEFAULT_OS_VERSION: str = ""

# 创建 Roxy 环境时是否使用 PROXY_POOL：
#   False = 不主动给 Roxy 环境设置代理
#   True  = 每次创建环境时从 PROXY_POOL 随机取一个代理写入 proxyInfo
ROXY_CREATE_USE_PROXY_POOL: bool = env_str("ROXY_CREATE_USE_PROXY_POOL", "false").lower() in ("1", "true", "yes", "on")

# Roxy 代理检测通道；留空则不传 checkChannel。
ROXY_PROXY_CHECK_CHANNEL: str = "IPRust.io"

# 没有 ROXY_PROFILE_ID 时创建环境的最小 payload；按你的 Roxy 版本字段调整。
# 默认开启 ROXY_RANDOM_PROFILE_NAME_ON_CREATE，因此这里的 name 只是兜底值。
ROXY_PROFILE_CREATE_PAYLOAD: dict = {
    "name": "gpt-free-register",
    "os": "macOS",
}


# 代理池：每次注册随机抽取一个写入 Roxy 环境，避免账号被 OpenAI 判定为同 IP 批量注册。
# 格式：http://user:pass@host:port 或 socks5://host:port；支持 socks5h://（DNS 在代理端解析）。
def _parse_proxy_pool() -> list[str]:
    raw = os.getenv("ROXY_PROXY_POOL", "")
    if raw.strip():
        return [line.strip() for line in raw.replace(";", "\n").splitlines() if line.strip()]
    return []


ROXY_PROXY_POOL: list[str] = _parse_proxy_pool()


def get_roxy_config_dict() -> dict:
    """获取当前 Roxy 配置的序列化字典，用于 WebUI 显示与默认值回填。"""
    return {
        "api_base": ROXY_API_BASE,
        "api_token": ROXY_API_TOKEN,
        "workspace_id": ROXY_WORKSPACE_ID,
        "project_id": ROXY_PROJECT_ID,
        "profile_id": ROXY_PROFILE_ID,
        "open_headless": bool(ROXY_OPEN_HEADLESS),
        "create_use_proxy_pool": bool(ROXY_CREATE_USE_PROXY_POOL),
        "proxy_pool": "\n".join(ROXY_PROXY_POOL) if ROXY_PROXY_POOL else "",
        "activate_account": bool(ROXY_ACTIVATE_ACCOUNT),
        "otp_wait_seconds": int(ROXY_OTP_WAIT_SECONDS or 60),
    }


def pick_proxy() -> str:
    """从代理池中随机抽取一个代理 URL；池为空时返回空串（即不使用代理）。"""
    return random.choice(ROXY_PROXY_POOL) if ROXY_PROXY_POOL else ""


# 兼容入口：默认每次进程启动随机选一个，作为本次注册全程的固定代理
PROXY = pick_proxy()


# Roxy Codex 授权等待 callback 的最长秒数
ROXY_CODEX_CALLBACK_TIMEOUT: int = 180
