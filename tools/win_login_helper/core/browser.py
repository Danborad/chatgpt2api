from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from playwright.async_api import Browser, BrowserContext, Page, Playwright


def compute_totp(secret: str) -> str:
    """标准 HMAC-SHA1 30 秒 6 位动态验证码（TOTP）计算。无需第三方依赖。"""
    clean_secret = re.sub(r"\s+", "", str(secret or "")).upper()
    padding = "=" * ((8 - len(clean_secret) % 8) % 8)
    key = base64.b32decode(clean_secret + padding, casefold=True)
    counter = int(time.time() // 30)
    msg = struct.pack(">Q", counter)
    mac = hmac.new(key, msg, hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code_int = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code_int % 1000000:06d}"


def parse_card_key_accounts(text: str) -> list[dict[str, str]]:
    """超强智能卡密解析器：
    - 支持标准分隔符（----, ---, --, |, \t, 冒号, 空格）；
    - 支持带序号（1. / [1] / 第1张）；
    - 支持带说明文字或 otpauth:// 协议 URL；
    - 支持多行模式（第一行邮箱，下一行密码，再下一行2FA）。
    """
    if not text or not text.strip():
        return []

    results: list[dict[str, str]] = []
    email_re = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,24}")
    otpauth_re = re.compile(r"otpauth://[^\s\"']+?[?&]secret=([a-zA-Z2-7=]+)", re.IGNORECASE)
    base32_token_re = re.compile(r"^[A-Za-z2-7]{16,64}={0,6}$")

    raw_lines = [line.strip() for line in text.strip().splitlines() if line.strip()]

    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]

        if line.startswith("#") or (("发货" in line or "使用说明" in line or "不要" in line) and not email_re.search(line)):
            i += 1
            continue

        emails = email_re.findall(line)
        if not emails:
            i += 1
            continue

        email = emails[0].strip()

        # 检查是否为多行模式
        if i + 1 < len(raw_lines):
            next_l = raw_lines[i + 1]
            if not email_re.search(next_l) and any(k in next_l.lower() for k in ("密码", "password", "pwd", "pass")):
                pwd_match = re.search(r"(?:密码|password|pwd|pass)[:：\s]+([^\s]+)", next_l, re.IGNORECASE)
                pwd = pwd_match.group(1).strip() if pwd_match else next_l.split()[-1].strip()
                two_fa = ""
                i += 2
                if i < len(raw_lines):
                    third_l = raw_lines[i]
                    if not email_re.search(third_l) and any(k in third_l.lower() for k in ("2fa", "密钥", "secret", "key", "totp", "验证码")):
                        m3 = re.search(r"(?:2fa|密钥|secret|key|totp|验证码)[:：\s]+([A-Za-z2-7]{16,64})", third_l, re.IGNORECASE)
                        if m3:
                            two_fa = m3.group(1).strip().upper()
                        else:
                            for token in re.split(r"[\s:：]+", third_l):
                                clean_t = token.replace(" ", "").upper()
                                if base32_token_re.match(clean_t):
                                    two_fa = clean_t
                                    break
                        i += 1
                results.append({"email": email, "password": pwd, "two_factor_secret": two_fa})
                continue

        # 单行模式解析
        two_fa = ""
        access_token = ""

        # 0. 优先提取 Access Token (JWT 格式: eyJ... . eyJ... . ...)
        jwt_m = re.search(r"\b(eyJ[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+){2})\b", line)
        line_clean = line
        if jwt_m:
            access_token = jwt_m.group(1).strip()
            line_clean = f"{line[: jwt_m.start()]} {line[jwt_m.end() :]}".strip()

        # 1. 优先提取 otpauth://
        otp_m = otpauth_re.search(line_clean)
        if otp_m:
            two_fa = otp_m.group(1).strip().upper()
            line_clean = f"{line_clean[: otp_m.start()]} {line_clean[otp_m.end() :]}".strip()

        line_clean = re.sub(r"\(.*?\)|（.*?）", "", line_clean).strip()

        em_idx = line_clean.find(email)
        after_email = line_clean[em_idx + len(email) :].strip() if em_idx != -1 else line_clean

        if not two_fa:
            twofa_label_m = re.search(r"(?:2fa|密钥|secret|key|totp|验证码)[:：\s]+([A-Za-z2-7]{16,64})", after_email, re.IGNORECASE)
            if twofa_label_m:
                two_fa = twofa_label_m.group(1).strip().upper()
                after_email = f"{after_email[:twofa_label_m.start()]} {after_email[twofa_label_m.end():]}".strip()

        password = ""
        pwd_label_m = re.search(r"(?:密码|password|pwd|pass)[:：\s]+([^\s]+)", after_email, re.IGNORECASE)
        if pwd_label_m:
            password = pwd_label_m.group(1).strip()
            after_email = f"{after_email[:pwd_label_m.start()]} {after_email[pwd_label_m.end():]}".strip()

        after_email = re.sub(r"^[\s\-_|:,]+", "", after_email).strip()

        if password:
            if not two_fa and after_email:
                b32_match = re.search(r"\b([A-Za-z2-7]{16,64})\b", after_email)
                if b32_match:
                    two_fa = b32_match.group(1).upper()
            res_item = {"email": email, "password": password, "two_factor_secret": two_fa}
            if access_token:
                res_item["access_token"] = access_token
            results.append(res_item)
            i += 1
            continue

        sep_pattern = re.compile(r"\s*(?:----+|---+|--+|[|:,]|\t+)\s*")
        parts = [p.strip() for p in sep_pattern.split(after_email) if p.strip()]
        if len(parts) <= 1:
            parts = [p.strip() for p in after_email.split() if p.strip()]

        clean_parts = []
        for p in parts:
            p_clean = re.sub(r"^(?:账号|账户|邮箱|user|username|email|密码|password|pwd|pass|2fa|密钥|secret|key|totp)[:：\s-]*", "", p, flags=re.IGNORECASE).strip()
            if p_clean:
                clean_parts.append(p_clean)

        if clean_parts:
            if not two_fa and len(clean_parts) >= 2:
                last_token = clean_parts[-1].replace(" ", "").upper()
                if base32_token_re.match(last_token):
                    two_fa = last_token
                    password = clean_parts[0]
                else:
                    password = clean_parts[0]
                    two_fa = clean_parts[1].replace(" ", "").upper()
            else:
                password = clean_parts[0]
                if not two_fa and len(clean_parts) > 1:
                    two_fa = clean_parts[1].replace(" ", "").upper()

        if email and password:
            res_item = {
                "email": email,
                "password": password,
                "two_factor_secret": two_fa,
            }
            if access_token:
                res_item["access_token"] = access_token
            results.append(res_item)
        i += 1

    return results


BASE_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""


async def perform_windows_login(
    playwright: Playwright,
    email: str,
    password: str,
    two_factor_secret: str = "",
    proxy: str = "",
    browser_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """在 Windows 桌面启动真实浏览器（有头/无痕）执行 ChatGPT 登录，提取完整 Token 凭据。"""
    b_cfg = browser_config or {}
    channel = str(b_cfg.get("channel") or "msedge").strip().lower()
    headless = bool(b_cfg.get("headless", False))
    timeout_sec = int(b_cfg.get("timeout_seconds") or 90)
    slow_mo = int(b_cfg.get("slow_mo_ms") or 50)

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    launch_kwargs: dict[str, Any] = {
        "headless": headless,
        "args": launch_args,
        "slow_mo": slow_mo,
    }

    if channel in ("msedge", "chrome"):
        launch_kwargs["channel"] = channel

    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}

    browser: Browser | None = None
    try:
        browser = await playwright.chromium.launch(**launch_kwargs)
    except Exception as exc:
        # 若指定 msedge/chrome 失败，尝试默认 chromium
        if "channel" in launch_kwargs:
            del launch_kwargs["channel"]
            browser = await playwright.chromium.launch(**launch_kwargs)
        else:
            raise RuntimeError(f"启动 Windows 本地浏览器失败: {exc}") from exc

    context: BrowserContext | None = None
    try:
        context_kwargs: dict[str, Any] = {
            "locale": "zh-CN",
            "viewport": {"width": 1280, "height": 800},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
        if proxy:
            context_kwargs["proxy"] = {"server": proxy}

        context = await browser.new_context(**context_kwargs)
        await context.add_init_script(BASE_STEALTH_JS)
        page: Page = await context.new_page()
        page.set_default_timeout(timeout_sec * 1000)

        # 1. 访问首页，建立自然会话上下文
        try:
            await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=35000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        email_input_sel = (
            'input[type="email"], input#mobile-auth-email, input[name="login_hint"], '
            'input[name="username"], input[name="email"], input[autocomplete="email"], input#email-input'
        )

        start_wait = time.time()
        while time.time() - start_wait < 25:
            if await page.locator(email_input_sel).count() > 0 and await page.locator(email_input_sel).first.is_visible():
                break

            login_btn = page.locator('button:has-text("Log in"), button:has-text("登录"), [data-testid="login-button"], a:has-text("Log in"), a:has-text("登录")')
            if await login_btn.count() > 0 and await login_btn.first.is_visible():
                try:
                    await login_btn.first.click()
                    await page.wait_for_timeout(1500)
                    if await page.locator(email_input_sel).count() > 0 and await page.locator(email_input_sel).first.is_visible():
                        break
                except Exception:
                    pass

            # 检查是否有 Cloudflare Turnstile 质询
            if "cf_chl" in page.url or "Just a moment" in (await page.title()):
                try:
                    cf_frame = page.frame_locator('iframe[src*="cloudflare.com"]')
                    cf_btn = cf_frame.locator('input[type="checkbox"], #challenge-stage')
                    if await cf_btn.count() > 0:
                        await cf_btn.first.click()
                except Exception:
                    pass

            if time.time() - start_wait > 8 and "/auth" not in page.url:
                try:
                    await page.goto("https://chatgpt.com/auth/login", wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    pass

            await page.wait_for_timeout(800)

        if not (await page.locator(email_input_sel).count() > 0 and await page.locator(email_input_sel).first.is_visible()):
            raise RuntimeError(f"未找到邮箱输入框，当前页面: {page.url} (title={await page.title()})")

        # 2. 填写邮箱并提交
        await page.locator(email_input_sel).first.fill(email)
        await page.wait_for_timeout(300)
        try:
            await page.locator(email_input_sel).first.press("Enter")
        except Exception:
            pass

        # 辅助点击提交按钮
        try:
            submit_loc = page.locator('button:has-text("继续"), button:has-text("Continue"), button[type="submit"]')
            cnt = await submit_loc.count()
            for idx in range(cnt):
                btn = submit_loc.nth(idx)
                if await btn.is_visible():
                    aria = (await btn.get_attribute("aria-label") or "").strip()
                    if "发送消息" in aria:
                        continue
                    await btn.click(timeout=1500)
                    break
        except Exception:
            pass

        # 3. 等待密码输入框
        password_input_sel = 'input[type="password"], input[name="password"], input[name="current-password"]'
        start_t = time.time()
        while time.time() - start_t < 25:
            try:
                if await page.locator(password_input_sel).count() > 0 and await page.locator(password_input_sel).first.is_visible():
                    break
                err_loc = page.locator('[role="alert"], .error, .text-danger, [data-testid="error"], #error-element-password, .ulp-alert-error')
                if await err_loc.count() > 0 and await err_loc.first.is_visible():
                    err_msg = (await err_loc.first.text_content() or "").strip()
                    if err_msg:
                        raise RuntimeError(f"提交邮箱后提示错误: {err_msg}")
            except Exception as e:
                if "提交邮箱后提示错误" in str(e):
                    raise
            await page.wait_for_timeout(600)

        if not (await page.locator(password_input_sel).count() > 0 and await page.locator(password_input_sel).first.is_visible()):
            raise RuntimeError(f"未找到密码输入框，当前页面: {page.url} (title={await page.title()})")

        # 4. 填写密码并提交
        await page.locator(password_input_sel).first.fill(password)
        await page.wait_for_timeout(300)
        try:
            await page.locator(password_input_sel).first.press("Enter")
        except Exception:
            pass

        try:
            submit_loc = page.locator('button[type="submit"], button:has-text("继续"), button:has-text("Continue"), button[name="action"][value="default"]')
            cnt = await submit_loc.count()
            for idx in range(cnt):
                btn = submit_loc.nth(idx)
                if await btn.is_visible():
                    aria = (await btn.get_attribute("aria-label") or "").strip()
                    if "发送消息" in aria:
                        continue
                    await btn.click(timeout=1500)
                    break
        except Exception:
            pass

        # 5. 等待 2FA 界面或直接跳转成功
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
                err_loc = page.locator('[role="alert"], .error, #error-element-password, .ulp-alert-error, [data-testid="error"]')
                if await err_loc.count() > 0 and await err_loc.first.is_visible():
                    err_msg = (await err_loc.first.text_content() or "").strip()
                    if err_msg:
                        raise RuntimeError(f"密码错误: {err_msg}")
            except Exception as e:
                if "密码错误" in str(e):
                    raise
            await page.wait_for_timeout(600)

        # 6. 处理 2FA 验证码
        if mfa_needed:
            if not two_factor_secret:
                raise RuntimeError("该账号已开启 2FA 双重认证，但卡密中未提供 2FA 密钥")
            totp = compute_totp(two_factor_secret)
            await page.locator(otp_sel).first.fill(totp)
            await page.wait_for_timeout(300)
            try:
                await page.locator(otp_sel).first.press("Enter")
            except Exception:
                pass
            try:
                submit_loc = page.locator('button[type="submit"], button:has-text("继续"), button:has-text("Continue")')
                if await submit_loc.count() > 0 and await submit_loc.first.is_visible():
                    await submit_loc.first.click(timeout=2000)
            except Exception:
                pass

        # 7. 等待完全进入 ChatGPT 主界面
        start_t = time.time()
        logged_in = False
        while time.time() - start_t < 25:
            if "chatgpt.com" in page.url and "/auth" not in page.url and "mfa" not in page.url:
                logged_in = True
                break
            try:
                err_loc = page.locator('[role="alert"], .error, #error-element-code, [data-testid="error"]')
                if await err_loc.count() > 0 and await err_loc.first.is_visible():
                    err_msg = (await err_loc.first.text_content() or "").strip()
                    if err_msg:
                        raise RuntimeError(f"2FA 验证码提交失败: {err_msg}")
            except Exception as e:
                if "2FA 验证码" in str(e):
                    raise
            await page.wait_for_timeout(800)

        if not logged_in:
            raise RuntimeError(f"未能跳转至 chatgpt.com 主界面，最后停留在: {page.url}")

        await page.wait_for_timeout(1000)

        # 8. 提取 Web Session 与 Token
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

        # 9. 尝试静默换取 Platform OAuth Refresh Token（拥有长期续期权限）
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
            await page.goto(oauth_url, timeout=20000)

            callback_url = ""
            start_t = time.time()
            while time.time() - start_t < 12:
                if "platform.openai.com/auth/callback" in page.url and "code=" in page.url:
                    callback_url = page.url
                    break
                try:
                    btn = page.locator('button:has-text("Authorize"), button:has-text("授权"), button:has-text("Continue"), button:has-text("继续")')
                    if await btn.count() > 0 and await btn.first.is_visible():
                        await btn.first.click()
                except Exception:
                    pass
                await page.wait_for_timeout(600)

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
                    if proxy:
                        handlers.append(urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
                    opener = urllib.request.build_opener(*handlers)
                    with opener.open(token_req, timeout=25) as resp:
                        oauth_tokens = json.loads(resp.read().decode())
        except Exception:
            pass

        final_access_token = web_access_token or (oauth_tokens.get("access_token") if oauth_tokens else "")
        if not final_access_token:
            raise RuntimeError("登录成功但未能提取到有效的 Access Token")

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
            "registration_engine": "win_desktop_helper",
            "user_id": str((session_info.get("user") or {}).get("id") or ""),
            "plan_type": str((session_info.get("account") or {}).get("planType") or "free"),
            "expires_at": str(session_info.get("expires") or ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
