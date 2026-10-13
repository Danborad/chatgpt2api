# -*- coding: utf-8 -*-
"""随机化操作节奏，让协议流程更接近人工浏览器操作。"""
import logging
import random
import time

logger = logging.getLogger(__name__)

# 人工操作节奏配置（移植自 turb config/humanize.py）
ENABLE_HUMANIZE_DELAY = True
HUMANIZE_DELAY_FACTOR = 1.0
HUMANIZE_DELAYS = {
    "api": (0.45, 1.35),
    "navigate": (1.2, 3.2),
    "challenge": (0.8, 2.4),
    "otp_input": (2.5, 8.0),
    "form": (1.8, 5.0),
    "post_auth": (1.5, 4.0),
    "job_stagger": (0.4, 1.8),
    "click": (0.15, 0.85),
    "keystroke": (0.035, 0.18),
    "typing_pause": (0.18, 0.75),
    "page_warmup": (0.7, 2.2),
}


def delay(kind: str = "api", *, minimum: float | None = None, maximum: float | None = None) -> float:
    """
    按配置随机 sleep，返回实际 sleep 秒数。

    Args:
        kind: HUMANIZE_DELAYS 的 key。
        minimum/maximum: 临时覆盖区间。
    """
    if not ENABLE_HUMANIZE_DELAY:
        return 0.0
    if minimum is None or maximum is None:
        lo, hi = HUMANIZE_DELAYS.get(kind, (0.4, 1.2))
        minimum = lo if minimum is None else minimum
        maximum = hi if maximum is None else maximum
    factor = float(HUMANIZE_DELAY_FACTOR or 1.0)

    lo = max(0.0, float(minimum) * factor)
    hi = max(lo, float(maximum) * factor)
    seconds = random.uniform(lo, hi)
    logger.debug(f"[Humanize] delay kind={kind}, seconds={seconds:.2f}")
    time.sleep(seconds)
    return seconds
