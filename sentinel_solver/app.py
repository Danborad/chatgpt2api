"""sentinel 求解服务：常驻一个无头 Chrome 的 chatgpt.com 页面，替主服务计算 Turnstile / SO token。

2026-10-14 起 chatgpt.com 的对话接口要求 Turnstile token 必须在真实的 chatgpt.com 页面里算出，
纯 Python/Node 模拟的结果会被拒（403）。主服务不打包浏览器，改为通过 HTTP 调用本服务。

环境变量：
- SENTINEL_SOLVER_KEY：可选，设置后请求需带 `Authorization: Bearer <key>`
- SENTINEL_SOLVER_PROXY：可选，浏览器出网代理（如 http://host:7890），应与主服务出口一致
- SENTINEL_SOLVER_USER_AGENT：可选，默认按内置 Chromium 版本生成 Linux Chrome UA
- SENTINEL_SOLVER_TIMEZONE：可选，页面时区（如 Asia/Tokyo），应与出口 IP 所在地一致；默认跟随系统
- SENTINEL_SOLVER_REFRESH_SECONDS：页面定期重开的间隔，默认 1800
- SENTINEL_SOLVER_HEADLESS：默认 true；调试时可设为 false
- PORT：监听端口，默认 8080
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import struct
import time
from typing import Any
import urllib.request
from urllib.parse import parse_qs, urlencode, urlparse
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from playwright_stealth import Stealth
from pydantic import BaseModel

CHATGPT_URL = "https://chatgpt.com/"
CHALLENGE_TITLES = ("请稍候", "Just a moment", "Attention Required")
VM_SCRIPT = (Path(__file__).parent / "vm.js").read_text(encoding="utf-8")
BASE_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
"""

SOLVER_KEY = os.getenv("SENTINEL_SOLVER_KEY", "").strip()
PROXY = os.getenv("SENTINEL_SOLVER_PROXY", "").strip()
USER_AGENT = os.getenv("SENTINEL_SOLVER_USER_AGENT", "").strip()
TIMEZONE = os.getenv("SENTINEL_SOLVER_TIMEZONE", "").strip()
REFRESH_SECONDS = max(60, int(os.getenv("SENTINEL_SOLVER_REFRESH_SECONDS", "1800")))
HEADLESS = os.getenv("SENTINEL_SOLVER_HEADLESS", "true").strip().lower() not in {"0", "false", "no"}
READY_TIMEOUT_SECONDS = 60


def _reap_zombies() -> None:
    """清理已退出的子进程，防止僵尸进程积累。"""
    try:
        while True:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid <= 0:
                break
    except Exception:
        pass


class SolverPage:
    """维护一个已通过 Cloudflare 校验的 chatgpt.com 页面，按需重开。"""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._opened_at = 0.0
        self._eval_count = 0
        self._lock = asyncio.Lock()
        self.user_agent = USER_AGENT
        self.last_error = ""

    async def _close_browser_locked(self) -> None:
        """彻底关闭浏览器与上下文，彻底杀死全部子进程。"""
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        self._page = None
        _reap_zombies()

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        try:
            await self.page()
        except Exception as exc:  # 启动时页面暂时打不开不致命，首个请求会重试
            self.last_error = str(exc)
            print(f"[sentinel-solver] initial page open failed: {exc}", flush=True)

    async def stop(self) -> None:
        async with self._lock:
            await self._close_browser_locked()
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    async def page(self) -> Page:
        async with self._lock:
            _reap_zombies()
            stale = (
                self._page is None
                or self._browser is None
                or not self._browser.is_connected()
                or time.monotonic() - self._opened_at > REFRESH_SECONDS
                or self._eval_count >= 100
            )
            if not stale and not await self._is_ready(self._page):
                stale = True
            if stale:
                await self._reopen()
            return self._page

    async def invalidate(self) -> None:
        async with self._lock:
            self._opened_at = 0.0

    async def _reopen(self) -> None:
        await self._close_browser_locked()
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        launch_kwargs: dict[str, Any] = {
            "headless": HEADLESS,
            "channel": "chromium",
            "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
        }
        if PROXY:
            launch_kwargs["proxy"] = {"server": PROXY}
        browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._browser = browser

        if not self.user_agent:
            major = browser.version.split(".")[0]
            self.user_agent = (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
            )

        context_kwargs: dict[str, Any] = {
            "locale": "zh-CN",
            "viewport": {"width": 1280, "height": 800},
            "user_agent": self.user_agent,
        }
        if TIMEZONE:
            context_kwargs["timezone_id"] = TIMEZONE
        context = await browser.new_context(**context_kwargs)
        await context.add_init_script(BASE_INIT_SCRIPT)
        await context.add_init_script(VM_SCRIPT)
        await Stealth().apply_stealth_async(context)
        page = await context.new_page()

        try:
            await page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
            deadline = time.monotonic() + READY_TIMEOUT_SECONDS
            while not await self._is_ready(page):
                if time.monotonic() > deadline:
                    title = await page.title()
                    raise RuntimeError(f"chatgpt.com page not ready (title={title!r}), likely stuck on a Cloudflare challenge")
                await asyncio.sleep(1)
        except Exception:
            await self._close_browser_locked()
            raise

        self._context = context
        self._page = page
        self._opened_at = time.monotonic()
        self._eval_count = 0
        self.last_error = ""
        print(f"[sentinel-solver] chatgpt.com page ready: {await page.title()!r}", flush=True)

    @staticmethod
    async def _is_ready(page: Page | None) -> bool:
        if page is None or page.is_closed():
            return False
        try:
            title = await page.title()
            if any(marker in title for marker in CHALLENGE_TITLES):
                return False
            return await page.evaluate("location.hostname === 'chatgpt.com' && typeof window.__sentinelVM === 'object'")
        except Exception:
            return False

    async def evaluate(self, expression: str, arg: object) -> object:
        """在页面里执行；页面失效时重开一次再试。"""
        for attempt in range(2):
            page = await self.page()
            try:
                return await page.evaluate(expression, arg)
            except Exception as exc:
                self.last_error = str(exc)
                if attempt:
                    raise
                await self.invalidate()
        raise RuntimeError("unreachable")

    def status(self) -> dict[str, object]:
        return {
            "ready": self._page is not None and not self._page.is_closed(),
            "page_age_seconds": int(time.monotonic() - self._opened_at) if self._opened_at else None,
            "browser_version": self._browser.version if self._browser else None,
            "user_agent": self.user_agent,
            "timezone": TIMEZONE or None,
            "last_error": self.last_error or None,
        }


solver = SolverPage()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await solver.start()
    yield
    await solver.stop()


app = FastAPI(title="chatgpt2api sentinel solver", lifespan=lifespan)


class TurnstileRequest(BaseModel):
    dx: str
    p: str


class SORequest(BaseModel):
    collector_dx: str
    snapshot_dx: str
    p: str


def require_key(authorization: str | None) -> None:
    if not SOLVER_KEY:
        return
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, SOLVER_KEY):
        raise HTTPException(status_code=401, detail="invalid solver key")


@app.get("/health")
async def health() -> dict[str, object]:
    return solver.status()


@app.post("/v1/turnstile")
async def solve_turnstile(body: TurnstileRequest, authorization: str | None = Header(default=None)) -> dict[str, str]:
    require_key(authorization)
    try:
        token = await solver.evaluate("([dx, p]) => window.__sentinelVM.turnstile(dx, p)", [body.dx, body.p])
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"turnstile solve failed: {exc}") from exc
    return {"token": str(token or "")}


def compute_totp(secret: str) -> str:
    clean = secret.replace(" ", "").strip().upper()
    missing_padding = len(clean) % 8
    if missing_padding:
        clean += "=" * (8 - missing_padding)
    key = base64.b32decode(clean)
    counter = int(time.time() // 30)
    counter_bytes = struct.pack(">Q", counter)
    mac = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code_int = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code_int % 1000000:06d}"


async def perform_headless_login(
    playwright: Playwright,
    email: str,
    password: str,
    two_factor_secret: str = "",
    proxy: str = "",
) -> dict[str, Any]:
    _reap_zombies()
    proxy_server = proxy.strip() or PROXY
    launch_kwargs: dict[str, Any] = {
        "headless": HEADLESS,
        "channel": "chromium",
        "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
    }
    if proxy_server:
        launch_kwargs["proxy"] = {"server": proxy_server}

    login_browser = await playwright.chromium.launch(**launch_kwargs)
    try:
        context_kwargs: dict[str, Any] = {
            "locale": "zh-CN",
            "viewport": {"width": 1280, "height": 800},
            "user_agent": solver.user_agent
            or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        }
        if proxy_server:
            context_kwargs["proxy"] = {"server": proxy_server}

        context = await login_browser.new_context(**context_kwargs)
        await Stealth().apply_stealth_async(context)
        page = await context.new_page()

        try:
            await page.goto("https://chatgpt.com/auth/login", wait_until="domcontentloaded", timeout=40000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)

        email_input_sel = (
            'input[type="email"], input[name="username"], input[name="email"], '
            'input[autocomplete="email"], input#email-input'
        )
        try:
            await page.wait_for_selector(email_input_sel, state="visible", timeout=25000)
        except Exception:
            title = await page.title()
            if any(m in title for m in CHALLENGE_TITLES):
                raise RuntimeError("登录页被 Cloudflare 质询拦截，请检查代理节点是否干净")
            raise RuntimeError(f"未找到邮箱输入框，当前页面: {page.url} (title={title})")

        await page.fill(email_input_sel, email)
        await page.wait_for_timeout(400)

        # 提交邮箱，过滤 Google/Apple/手机等第三方入口
        await page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button, input[type="submit"]'));
            const submitBtn = btns.find(b => {
                const t = (b.innerText || b.value || '').trim();
                const bad = ['google', 'apple', 'microsoft', 'phone', '手机', 'github'];
                if (bad.some(x => t.toLowerCase().includes(x))) return false;
                return t === '继续' || t.toLowerCase() === 'continue' || b.type === 'submit';
            });
            if (submitBtn) submitBtn.click();
        }""")

        # 等待密码输入框出现或错误提示
        password_input_sel = 'input[type="password"], input[name="password"], input[name="current-password"]'
        start_t = time.time()
        while time.time() - start_t < 25:
            try:
                if await page.locator(password_input_sel).count() > 0 and await page.locator(password_input_sel).first.is_visible():
                    break
                err_text = await page.evaluate("""() => {
                    const el = document.querySelector('[role="alert"], .error, .text-danger, [data-testid="error"]');
                    return el ? el.innerText.trim() : '';
                }""")
                if err_text:
                    raise RuntimeError(f"提交邮箱后提示错误: {err_text}")
            except Exception as e:
                if "提交邮箱后提示错误" in str(e):
                    raise
            await page.wait_for_timeout(800)

        await page.fill(password_input_sel, password)
        await page.wait_for_timeout(400)

        # 提交密码
        await page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button, input[type="submit"]'));
            const submitBtn = btns.find(b => {
                const t = (b.innerText || b.value || '').trim();
                const bad = ['google', 'apple', 'microsoft', 'phone', '手机', 'github'];
                if (bad.some(x => t.toLowerCase().includes(x))) return false;
                return t === '继续' || t.toLowerCase() === 'continue' || b.type === 'submit';
            });
            if (submitBtn) submitBtn.click();
        }""")

        # 等待 2FA 界面或直接进入 ChatGPT
        otp_sel = (
            'input[name="code"], input[placeholder*="验证码"], '
            'input[placeholder*="code" i], input[autocomplete="one-time-code"], input[maxlength="6"]'
        )
        start_t = time.time()
        mfa_needed = False
        while time.time() - start_t < 25:
            try:
                if "chatgpt.com" in page.url and "/auth" not in page.url and "mfa" not in page.url and "login" not in page.url:
                    break
                if "mfa" in page.url or "challenge" in page.url:
                    mfa_needed = True
                    break
                if await page.locator(otp_sel).count() > 0 and await page.locator(otp_sel).first.is_visible():
                    mfa_needed = True
                    break
                err_text = await page.evaluate("""() => {
                    const el = document.querySelector('[role="alert"], .error, #error-element-password, [data-testid="error"]');
                    return el ? el.innerText.trim() : '';
                }""")
                if err_text:
                    raise RuntimeError(f"提交密码后提示错误: {err_text}")
            except Exception as e:
                if "提交密码后提示错误" in str(e):
                    raise
            await page.wait_for_timeout(800)

        # 若需要 2FA 验证
        if mfa_needed:
            if not two_factor_secret:
                raise RuntimeError("该账号已开启 2FA 双重认证，但未提供 2FA 密钥")
            totp = compute_totp(two_factor_secret)
            await page.fill(otp_sel, totp)
            await page.wait_for_timeout(400)
            await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button, input[type="submit"]'));
                const submitBtn = btns.find(b => {
                    const t = (b.innerText || b.value || '').trim();
                    return t === '继续' || t.toLowerCase() === 'continue' || b.type === 'submit';
                });
                if (submitBtn) submitBtn.click();
            }""")

        # 等待重定向至 chatgpt.com
        start_t = time.time()
        logged_in = False
        while time.time() - start_t < 30:
            if "chatgpt.com" in page.url and "/auth" not in page.url and "mfa" not in page.url:
                logged_in = True
                break
            try:
                err_text = await page.evaluate("""() => {
                    const el = document.querySelector('[role="alert"], .error, #error-element-code, [data-testid="error"]');
                    return el ? el.innerText.trim() : '';
                }""")
                if err_text:
                    raise RuntimeError(f"2FA 验证码提交失败: {err_text}")
            except Exception as e:
                if "2FA 验证码提交失败" in str(e):
                    raise
            await page.wait_for_timeout(1000)

        if not logged_in:
            raise RuntimeError(f"未能跳转至 chatgpt.com 主界面，最后停留在: {page.url}")

        await page.wait_for_timeout(1500)
        # 关闭可能出现的弹窗
        try:
            await page.evaluate("""() => {
                const closeBtns = Array.from(document.querySelectorAll('button')).filter(b => {
                    const t = b.innerText.trim();
                    return ['继续', '确定', 'Next', 'Done', 'Got it', '开始使用', 'Stay logged out'].includes(t);
                });
                for (const b of closeBtns) b.click();
            }""")
        except Exception:
            pass

        # 提取 Web Session
        session_info = await page.evaluate("""async () => {
            try {
                const res = await fetch('https://chatgpt.com/api/auth/session', { credentials: 'include' });
                return await res.json();
            } catch (e) {
                return { error: String(e) };
            }
        }""")
        web_access_token = str(session_info.get("accessToken") or "").strip()
        session_token = str(session_info.get("sessionToken") or session_info.get("session_token") or "").strip()

        cookies = await context.cookies()
        cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies if "chatgpt" in c.get("domain", "")])

        # 换取 Platform OAuth Refresh Token
        oauth_tokens = {}
        try:
            verifier = secrets.token_urlsafe(32)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            oauth_params = {
                "issuer": "https://auth.openai.com",
                "client_id": "app_2SKx67EdpoN0G6j64rFvigXD",
                "audience": "https://api.openai.com/v1",
                "redirect_uri": "https://platform.openai.com/auth/callback",
                "device_id": str(secrets.token_hex(16)),
                "screen_hint": "login_or_signup",
                "scope": "openid profile email offline_access",
                "response_type": "code",
                "response_mode": "query",
                "state": "state_" + secrets.token_hex(8),
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "login_hint": email,
            }
            oauth_url = f"https://auth.openai.com/api/accounts/authorize?{urlencode(oauth_params)}"
            await page.goto(oauth_url, timeout=25000)

            callback_url = ""
            start_t = time.time()
            while time.time() - start_t < 15:
                if "platform.openai.com/auth/callback" in page.url and "code=" in page.url:
                    callback_url = page.url
                    break
                try:
                    btn = page.locator('button:has-text("Authorize"), button:has-text("授权"), button:has-text("Continue"), button:has-text("继续")')
                    if await btn.count() > 0 and await btn.first.is_visible():
                        await btn.first.click()
                except Exception:
                    pass
                await page.wait_for_timeout(800)

            if callback_url:
                code = parse_qs(urlparse(callback_url).query).get("code", [""])[0]
                if code:
                    token_req = urllib.request.Request(
                        "https://auth.openai.com/api/accounts/oauth/token",
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": context_kwargs["user_agent"],
                            "Referer": "https://platform.openai.com/",
                            "Origin": "https://platform.openai.com",
                        },
                        data=json.dumps({
                            "client_id": "app_2SKx67EdpoN0G6j64rFvigXD",
                            "code_verifier": verifier,
                            "grant_type": "authorization_code",
                            "code": code,
                            "redirect_uri": "https://platform.openai.com/auth/callback",
                        }).encode(),
                    )
                    handlers = []
                    if proxy_server:
                        handlers.append(urllib.request.ProxyHandler({"https": proxy_server, "http": proxy_server}))
                    opener = urllib.request.build_opener(*handlers)
                    with opener.open(token_req, timeout=30) as resp:
                        oauth_tokens = json.loads(resp.read().decode())
        except Exception:
            pass

        final_access_token = web_access_token or (oauth_tokens.get("access_token") if oauth_tokens else "")
        if not final_access_token:
            raise RuntimeError("未能获取到有效的 Access Token")

        return {
            "email": email,
            "password": password,
            "two_factor_secret": two_factor_secret,
            "access_token": final_access_token,
            "refresh_token": (oauth_tokens.get("refresh_token") if oauth_tokens else "") or "",
            "id_token": (oauth_tokens.get("id_token") if oauth_tokens else "") or "",
            "session_token": session_token,
            "cookie": cookie_header,
            "source_type": "web",
            "registration_engine": "headless_2fa",
            "user_id": str((session_info.get("user") or {}).get("id") or ""),
            "plan_type": str((session_info.get("account") or {}).get("planType") or ""),
            "expires_at": str(session_info.get("expires") or ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        try:
            await context.close()
        except Exception:
            pass
        try:
            await login_browser.close()
        except Exception:
            pass
        _reap_zombies()


class HeadlessLoginRequest(BaseModel):
    email: str
    password: str
    two_factor_secret: str = ""
    proxy: str = ""


@app.post("/v1/so")
async def solve_so(body: SORequest, authorization: str | None = Header(default=None)) -> dict[str, str]:
    require_key(authorization)
    try:
        token = await solver.evaluate(
            "([c, s, p]) => window.__sentinelVM.so(c, s, p)", [body.collector_dx, body.snapshot_dx, body.p]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"so solve failed: {exc}") from exc
    return {"token": str(token or "")}


@app.post("/v1/headless-login")
async def headless_login_endpoint(body: HeadlessLoginRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_key(authorization)
    if solver._playwright is None:
        await solver.start()
    if solver._playwright is None:
        return {"ok": False, "error": "Playwright 运行环境未就绪"}
    try:
        account = await perform_headless_login(
            solver._playwright,
            email=body.email.strip(),
            password=body.password.strip(),
            two_factor_secret=body.two_factor_secret.strip(),
            proxy=body.proxy.strip(),
        )
        return {"ok": True, "account": account}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "35780")), access_log=False)
