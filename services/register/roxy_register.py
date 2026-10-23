from __future__ import annotations

import logging
import threading
import time

from services.account_service import account_service
from services.register import mail_provider, openai_register
from services.register.roxy import config as roxy_config
from services.register.roxy import registration as roxy_registration


class _WebLogBridge(logging.Handler):
    """把 roxy_registration 的 logger 输出同时转发到 WebUI 日志面板。

    使用 roxy_register 模块自己的 register_log_sink（由 RegisterService 设置为
    roxy 服务的 _append_log），而不是 openai_register 的全局 sink（那个是 None）。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
            color = ""
            if record.levelno >= logging.ERROR:
                color = "red"
            elif record.levelno >= logging.WARNING:
                color = "yellow"
            _emit_log(text, color)
            # 保留容器 stdout 输出，便于本地排查。
            openai_register.log(text, color)
        except Exception:
            pass


config = {
    "mail": {
        "request_timeout": 30,
        "wait_timeout": 30,
        "wait_interval": 2,
        "api_use_register_proxy": False,
        "providers": [],
    },
    "proxy": "",
    "total": 10,
    "threads": 1,
}
# 合并 RoxyBrowser 专用配置；RegisterService 会覆写 mail/proxy/total/threads 以及 roxy 专有配置。
config["roxy"] = roxy_config.get_roxy_config_dict()
stats_lock = threading.Lock()
stats = {"done": 0, "success": 0, "fail": 0, "start_time": 0.0}
register_log_sink = None


def _emit_log(text: str, color: str = "") -> None:
    if register_log_sink:
        register_log_sink(text, color)


def _apply_roxy_config() -> None:
    """把 roxy 引擎的 roxy 配置同步到 roxy/config.py 模块属性，供 client 读取。"""
    overrides = config.get("roxy") if isinstance(config.get("roxy"), dict) else {}
    mapping = {
        "api_base": "ROXY_API_BASE",
        "api_token": "ROXY_API_TOKEN",
        "workspace_id": "ROXY_WORKSPACE_ID",
        "project_id": "ROXY_PROJECT_ID",
        "profile_id": "ROXY_PROFILE_ID",
        "open_headless": "ROXY_OPEN_HEADLESS",
        "one_profile_per_account": "ROXY_ONE_PROFILE_PER_ACCOUNT",
        "delete_profile_after_run": "ROXY_DELETE_PROFILE_AFTER_RUN",
        "keep_browser_open": "ROXY_KEEP_BROWSER_OPEN",
        "create_use_proxy_pool": "ROXY_CREATE_USE_PROXY_POOL",
        "activate_account": "ROXY_ACTIVATE_ACCOUNT",
        "otp_wait_seconds": "ROXY_OTP_WAIT_SECONDS",
        "ignore_proxy_check": "ROXY_IGNORE_PROXY_CHECK",
    }
    for key, attr in mapping.items():
        if key in overrides and overrides[key] is not None:
            val = overrides[key]
            if key in (
                "open_headless",
                "one_profile_per_account",
                "delete_profile_after_run",
                "keep_browser_open",
                "create_use_proxy_pool",
                "activate_account",
                "ignore_proxy_check",
            ):
                val = bool(val)
            elif key == "otp_wait_seconds":
                try:
                    val = max(10, int(val or 60))
                except (TypeError, ValueError):
                    val = 60
            setattr(roxy_config, attr, val)

    if "proxy_pool" in overrides and overrides["proxy_pool"] is not None:
        pool_raw = overrides["proxy_pool"]
        if isinstance(pool_raw, str):
            roxy_config.ROXY_PROXY_POOL = [
                line.strip() for line in pool_raw.replace(";", "\n").splitlines() if line.strip()
            ]
        elif isinstance(pool_raw, list):
            roxy_config.ROXY_PROXY_POOL = [str(x).strip() for x in pool_raw if str(x).strip()]


def _random_name() -> str:
    first, last = openai_register._random_name()
    return f"{first} {last}"


def worker(index: int, stop_event: threading.Event | None = None, generation: int = 0) -> dict:
    started = time.time()
    _apply_roxy_config()
    proxy = str(config.get("proxy") or "").strip() or roxy_config.pick_proxy()
    mail_config = config.get("mail") if isinstance(config.get("mail"), dict) else {}

    bridge = _WebLogBridge()
    bridge.setLevel(logging.DEBUG)
    bridge.setFormatter(logging.Formatter("[Roxy注册] %(message)s"))
    previous_level = roxy_registration.logger.level
    roxy_registration.logger.setLevel(logging.DEBUG)
    roxy_registration.logger.addHandler(bridge)
    try:
        return _worker_impl(index, stop_event, generation, started, proxy, mail_config)
    finally:
        try:
            roxy_registration.logger.removeHandler(bridge)
            roxy_registration.logger.setLevel(previous_level)
            bridge.close()
        except Exception:
            pass


def _step(index: int, text: str, color: str = "") -> None:
    msg = f"[任务{index}] {text}"
    _emit_log(msg, color)
    openai_register.step(index, text, color)


def _log(text: str, color: str = "") -> None:
    _emit_log(text, color)
    openai_register.log(text, color)


def _worker_impl(index: int, stop_event, generation: int, started: float, proxy: str, mail_config: dict) -> dict:
    _step(index, f"Roxy 注册任务启动 generation={generation}")
    mailbox = None
    try:
        mailbox = openai_register.create_mailbox(register_proxy=proxy, mail_config=mail_config)
        email = str(mailbox.get("address") or "").strip()
        if not email:
            mail_provider.release_mailbox(mailbox)
            raise RuntimeError("邮箱服务未返回 address")
        _step(index, f"Roxy 注册：邮箱创建完成: {email}")
        mail_provider.mark_mailbox_stage(mailbox, "authorize")

        result = roxy_registration.run_roxy_registration(
            email=email,
            name=_random_name(),
            birthday=openai_register._random_birthdate(),
            proxy=proxy,
            otp_code=None,
            mail_config=mail_config,
            mailbox=mailbox,
            stop_event=stop_event,
        )
        if not result.get("success"):
            raise RuntimeError(str(result.get("error") or "Roxy 注册失败"))
        if stop_event is not None and stop_event.is_set():
            raise openai_register.RegistrationStopped("roxy_registration_stopped")

        result.pop("success", None)
        result["registration_engine"] = "roxy"
        mail_provider.mark_mailbox_result(mailbox, success=True)

        account_service.add_account_items([result])
        access_token = str(result.get("access_token") or "")
        try:
            refresh_result = account_service.refresh_accounts([access_token])
            if refresh_result.get("errors"):
                account_service.update_account(
                    access_token,
                    {"image_quota_unknown": True, "status": "正常"},
                    quiet=True,
                )
                _step(index, "Roxy 账号已保存，状态刷新稍后重试", "yellow")
        except Exception as ref_exc:
            _step(index, f"Roxy 账号已入库，远端配额同步稍后进行: {ref_exc}", "yellow")

        elapsed = time.time() - started
        with stats_lock:
            stats["done"] += 1
            stats["success"] += 1
            avg = (time.time() - stats["start_time"]) / max(1, stats["success"])
        _log(
            f"Roxy 注册成功：{email}，本次耗时{elapsed:.1f}s，平均耗时{avg:.1f}s",
            "green",
        )
        return {"ok": True, "index": index, "generation": generation, "result": result}
    except openai_register.RegistrationStopped:
        elapsed = time.time() - started
        _step(index, f"Roxy 注册任务已停止，本次耗时{elapsed:.1f}s", "yellow")
        try:
            if mailbox is not None:
                mail_provider.release_mailbox(mailbox)
        except Exception:
            pass
        return {"ok": False, "cancelled": True, "index": index, "generation": generation}
    except Exception as error:
        elapsed = time.time() - started
        if stop_event is not None and stop_event.is_set():
            try:
                if mailbox is not None:
                    mail_provider.release_mailbox(mailbox)
            except Exception:
                pass
            return {"ok": False, "cancelled": True, "index": index, "generation": generation}
        with stats_lock:
            stats["done"] += 1
            stats["fail"] += 1
        _log(f"Roxy 注册任务{index}失败，本次耗时{elapsed:.1f}s，原因: {error}", "red")
        return {
            "ok": False,
            "index": index,
            "generation": generation,
            "error": str(error),
        }
