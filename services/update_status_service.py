from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Callable, Mapping
from urllib.parse import quote

from curl_cffi import requests as curl_requests

from contracts.updates import UpdateStatusView
from utils.container_runtime import is_containerized as _in_docker
from utils.log import logger


GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/yukkcat/chatgpt2api/releases/latest"
GITHUB_RELEASES_URL = "https://github.com/yukkcat/chatgpt2api/releases"
GITHUB_CHANGELOG_URL = "https://api.github.com/repos/yukkcat/chatgpt2api/contents/CHANGELOG.md?ref=main"
UPDATE_CHECK_TIMEOUT_SECS = 8
UPDATE_CHECK_MAX_BYTES = 256 * 1024
UPDATE_CHECK_CHUNK_BYTES = 64 * 1024
UPDATE_CHECK_CACHE_TTL_SECS = 300
MANAGED_RUNTIME_MARKER = ".chatgpt2api-image-version"

_VERSION_RE = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)
_CHANGELOG_ITEM_RE = re.compile(r"^[+*-]\s+\[[^\]\n]+\]\s+\S")


class UpdateCheckError(RuntimeError):
    pass


def _read_bounded_response(response, *, source: str) -> bytes:
    try:
        if response.status_code != 200:
            raise UpdateCheckError(f"{source} request failed")

        content_length = str(response.headers.get("content-length") or "").strip()
        if content_length.isdigit() and int(content_length) > UPDATE_CHECK_MAX_BYTES:
            raise UpdateCheckError(f"{source} response is too large")

        chunks: list[bytes] = []
        received_bytes = 0
        for chunk in response.iter_content(chunk_size=UPDATE_CHECK_CHUNK_BYTES):
            if not chunk:
                continue
            received_bytes += len(chunk)
            if received_bytes > UPDATE_CHECK_MAX_BYTES:
                raise UpdateCheckError(f"{source} response is too large")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        response.close()


def _fetch_latest_release() -> Mapping[str, object]:
    response = curl_requests.get(
        GITHUB_LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "chatgpt2api-update-check/3.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=UPDATE_CHECK_TIMEOUT_SECS,
        allow_redirects=False,
        stream=True,
    )
    payload = _read_bounded_response(response, source="GitHub release")

    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateCheckError("GitHub release response is invalid") from exc
    if not isinstance(decoded, dict):
        raise UpdateCheckError("GitHub release response is invalid")
    return decoded


def _fetch_changelog() -> str:
    response = curl_requests.get(
        GITHUB_CHANGELOG_URL,
        headers={
            "Accept": "application/vnd.github.raw+json",
            "User-Agent": "chatgpt2api-update-check/3.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=UPDATE_CHECK_TIMEOUT_SECS,
        allow_redirects=False,
        stream=True,
    )
    payload = _read_bounded_response(response, source="GitHub changelog")
    try:
        return payload.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise UpdateCheckError("GitHub changelog response is invalid") from exc


def _parse_version(value: object) -> tuple[tuple[int, int, int], tuple[str, ...]] | None:
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    if match is None:
        return None
    return (
        (int(match[1]), int(match[2]), int(match[3])),
        tuple((match[4] or "").split(".")) if match[4] else (),
    )


def _compare_prerelease_identifier(left: str, right: str) -> int:
    left_numeric = left.isdigit()
    right_numeric = right.isdigit()
    if left_numeric and right_numeric:
        return (int(left) > int(right)) - (int(left) < int(right))
    if left_numeric != right_numeric:
        return -1 if left_numeric else 1
    return (left > right) - (left < right)


def _compare_versions(left_value: object, right_value: object) -> int | None:
    left = _parse_version(left_value)
    right = _parse_version(right_value)
    if left is None or right is None:
        return None
    if left[0] != right[0]:
        return (left[0] > right[0]) - (left[0] < right[0])
    left_pre, right_pre = left[1], right[1]
    if not left_pre or not right_pre:
        if left_pre == right_pre:
            return 0
        return -1 if left_pre else 1
    for index in range(max(len(left_pre), len(right_pre))):
        if index >= len(left_pre):
            return -1
        if index >= len(right_pre):
            return 1
        comparison = _compare_prerelease_identifier(left_pre[index], right_pre[index])
        if comparison:
            return comparison
    return 0


def _version_parts(value: object) -> tuple[str, str]:
    raw = str(value or "").strip()
    clean = raw[1:] if raw.lower().startswith("v") else raw
    return clean or "unknown", f"v{clean}" if clean else "unknown"


def _release_body_changelog(release: Mapping[str, object], version: str) -> str:
    body = str(release.get("body") or "").strip()
    if not body:
        return ""

    item_lines: list[str] = []
    has_item = False
    fallback_lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(">"):
            continue
        fallback_lines.append(line)
        if _CHANGELOG_ITEM_RE.match(line):
            item_lines.append(line)
            has_item = True
        elif has_item and not re.match(r"^[+*-]\s+", line):
            item_lines.append(line)

    if not has_item:
        summary = " ".join(fallback_lines)
        if not summary:
            return ""
        item_lines = [f"- [更新] {summary}"]

    published_at = str(release.get("published_at") or "").strip()
    published_date = published_at[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", published_at) else ""
    heading = f"## {version}" + (f" - {published_date}" if published_date else "")
    return f"{heading}\n\n" + "\n".join(item_lines)


def _build_type() -> str:
    configured = os.getenv("CHATGPT2API_BUILD_TYPE", "").strip().lower()
    if configured in {"source", "release"}:
        return configured
    root = Path(__file__).resolve().parents[1]
    return "release" if _in_docker() and root.joinpath("web_dist").is_dir() else "source"


def _has_dedicated_mount(path: Path) -> bool:
    if path.is_mount():
        return True
    try:
        mount_lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    expected = path.as_posix()
    for line in mount_lines:
        fields = line.split()
        if len(fields) > 4 and fields[4].replace("\\040", " ") == expected:
            return True
    return False


def _runtime_update_mode(root: Path | None = None) -> str:
    runtime_root = (root or Path(__file__).resolve().parents[1]).resolve()
    if _build_type() != "release" or not _in_docker():
        return "source"
    if _has_dedicated_mount(runtime_root) and runtime_root.joinpath(MANAGED_RUNTIME_MARKER).is_file():
        return "managed_container"
    return "immutable_container"


class UpdateStatusService:
    def __init__(
        self,
        *,
        fetch_release: Callable[[], Mapping[str, object]] = _fetch_latest_release,
        fetch_changelog: Callable[[], str] = _fetch_changelog,
        monotonic: Callable[[], float] = time.monotonic,
        cache_ttl_seconds: float = UPDATE_CHECK_CACHE_TTL_SECS,
    ) -> None:
        self._fetch_release = fetch_release
        self._fetch_changelog = fetch_changelog
        self._monotonic = monotonic
        self._cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._cache_lock = Lock()
        self._cached_version = ""
        self._cached_runtime_mode = ""
        self._cached_at = 0.0
        self._cached_view: UpdateStatusView | None = None

    def view(self, current_version: str, *, force: bool = False) -> UpdateStatusView:
        normalized_current, _ = _version_parts(current_version)
        runtime_mode = _runtime_update_mode()
        now = self._monotonic()
        with self._cache_lock:
            if (
                not force
                and self._cached_view is not None
                and self._cached_version == normalized_current
                and self._cached_runtime_mode == runtime_mode
                and now - self._cached_at < self._cache_ttl_seconds
            ):
                return self._cached_view

        view = self._check(normalized_current, runtime_mode)
        with self._cache_lock:
            self._cached_version = normalized_current
            self._cached_runtime_mode = runtime_mode
            self._cached_at = self._monotonic()
            self._cached_view = view
        return view

    def _check(self, current_version: str, runtime_mode: str) -> UpdateStatusView:
        current_version, current_tag = _version_parts(current_version)
        try:
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="update-check") as executor:
                release_future = executor.submit(self._fetch_release)
                changelog_future = executor.submit(self._fetch_changelog)
                release = release_future.result()
                latest_version, latest_tag = _version_parts(release.get("tag_name"))
                try:
                    changelog = changelog_future.result()
                except Exception as exc:
                    logger.warning({
                        "event": "version_changelog_fetch_failed",
                        "error_type": type(exc).__name__,
                    })
                    changelog = _release_body_changelog(release, latest_version)
            comparison = _compare_versions(latest_version, current_version)
            if comparison is None:
                raise UpdateCheckError("release or current version is invalid")
            release_url = f"{GITHUB_RELEASES_URL}/tag/{quote(latest_tag, safe='')}"
            if comparison > 0:
                can_update = runtime_mode == "managed_container"
                if can_update:
                    status_message = f"发现新版本 {latest_tag}，可以直接更新。"
                elif runtime_mode == "immutable_container":
                    status_message = (
                        f"发现新版本 {latest_tag}，当前容器未启用持久化运行目录，"
                        "请拉取新镜像后重新创建容器。"
                    )
                else:
                    status_message = f"发现新版本 {latest_tag}，当前为源码环境，请使用 Git 更新。"
                return UpdateStatusView(
                    current_tag=current_tag,
                    latest_tag=latest_tag,
                    update_available=True,
                    release_url=release_url,
                    status_label="可更新" if can_update else "发现新版本",
                    status_message=status_message,
                    tone="success" if can_update else "warning",
                    changelog=changelog,
                    can_update=can_update,
                )
            return UpdateStatusView(
                current_tag=current_tag,
                latest_tag=latest_tag,
                update_available=False,
                release_url=release_url,
                status_label="已是最新",
                status_message=f"当前版本 {current_tag} 无需更新。",
                tone="muted",
                changelog=changelog,
                can_update=False,
            )
        except Exception as exc:
            logger.warning({
                "event": "version_update_check_failed",
                "error_type": type(exc).__name__,
            })
            warning = "暂时无法检查最新版本，请稍后重试。"
            return UpdateStatusView(
                current_tag=current_tag,
                update_available=False,
                release_url=GITHUB_RELEASES_URL,
                status_label="检查失败",
                status_message=warning,
                tone="warning",
                can_update=False,
            )


update_status_service = UpdateStatusService()
