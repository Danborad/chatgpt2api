from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping
from urllib.parse import urljoin, urlparse

from curl_cffi import requests as curl_requests

from contracts.updates import UpdateTaskEventView, UpdateTaskView
from services.json_file import read_json_object, write_json_file
from services.update_status_service import (
    _compare_versions,
    _fetch_latest_release,
    _runtime_update_mode,
    _version_parts,
)
from utils.log import logger


UPDATE_ARCHIVE_NAME = "chatgpt2api-app.tar.gz"
UPDATE_CHECKSUM_NAME = "checksums.txt"
UPDATE_DOWNLOAD_TIMEOUT_SECS = 15 * 60
UPDATE_DOWNLOAD_MAX_BYTES = 256 * 1024 * 1024
UPDATE_EXTRACT_MAX_BYTES = 512 * 1024 * 1024
UPDATE_EXTRACT_MAX_FILES = 10_000
UPDATE_RESTART_DELAY_SECS = 2.5
UPDATE_BUNDLE_FORMAT = 1
UPDATE_TASK_TOTAL = 6
UPDATE_TARGETS = (
    "main.py",
    "VERSION",
    "api",
    "contracts",
    "services",
    "utils",
    "scripts/image_upscale/upscale.mjs",
    "pyproject.toml",
    "uv.lock",
    "web_dist",
)
_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}

InstallerProgress = Callable[[str, int, str, str], None]


class UpdateInstallError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_download_url(value: object) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    host = str(parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in _ALLOWED_DOWNLOAD_HOSTS:
        raise UpdateInstallError("更新包下载地址无效。")
    return raw


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


class ReleaseBundleInstaller:
    """Install a verified release bundle into a managed persistent runtime."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        runtime_mode: Callable[[Path], str] = _runtime_update_mode,
    ) -> None:
        self.root = (root or Path(__file__).resolve().parents[1]).resolve()
        self._runtime_mode = runtime_mode

    def install(
        self,
        release: Mapping[str, object],
        latest_tag: str,
        *,
        progress: InstallerProgress | None = None,
    ) -> None:
        if self._runtime_mode(self.root) != "managed_container":
            raise UpdateInstallError("当前运行目录不支持持久化在线更新，请使用部署工具升级。")

        archive_url, checksum_url = self._asset_urls(release)
        with tempfile.TemporaryDirectory(prefix=".chatgpt2api-update-", dir=self.root) as temp_value:
            temp_dir = Path(temp_value)
            archive_path = temp_dir / UPDATE_ARCHIVE_NAME
            checksum_path = temp_dir / UPDATE_CHECKSUM_NAME

            if progress:
                progress("downloading", 2, "下载更新包", "正在下载官方发布包与校验文件。")
            self._download(archive_url, archive_path, max_bytes=UPDATE_DOWNLOAD_MAX_BYTES)
            self._download(checksum_url, checksum_path, max_bytes=1024 * 1024)

            if progress:
                progress("verifying", 3, "校验更新包", "正在校验完整性并检查更新清单。")
            self._verify_checksum(archive_path, checksum_path)
            extract_dir = temp_dir / "extracted"
            self._extract_archive(archive_path, extract_dir)
            bundle_dir = extract_dir / "chatgpt2api-app"
            self._validate_bundle(bundle_dir, latest_tag)

            if progress:
                progress("installing", 4, "安装运行文件", "正在替换受管运行目录中的应用文件。")
            replaced = self._apply_bundle(bundle_dir, temp_dir / "backup")
            try:
                if progress:
                    progress("syncing", 5, "同步运行依赖", "正在按新版本锁文件同步依赖。")
                self._sync_dependencies()
            except Exception as exc:
                self._rollback(replaced)
                try:
                    self._sync_dependencies()
                except Exception as rollback_exc:
                    raise UpdateInstallError("依赖同步失败，旧文件已恢复，但运行依赖恢复失败。") from rollback_exc
                raise UpdateInstallError("依赖同步失败，已恢复原版本。") from exc

    @staticmethod
    def _asset_urls(release: Mapping[str, object]) -> tuple[str, str]:
        assets = release.get("assets")
        if not isinstance(assets, list):
            assets = []
        by_name = {
            str(item.get("name") or "").strip(): str(item.get("browser_download_url") or "").strip()
            for item in assets
            if isinstance(item, dict)
        }
        archive_url = by_name.get(UPDATE_ARCHIVE_NAME, "")
        checksum_url = by_name.get(UPDATE_CHECKSUM_NAME, "")
        if not archive_url or not checksum_url:
            raise UpdateInstallError("该版本没有可用的在线更新包，请打开发布页手动更新。")
        return _safe_download_url(archive_url), _safe_download_url(checksum_url)

    @staticmethod
    def _download(url: str, destination: Path, *, max_bytes: int) -> None:
        current_url = _safe_download_url(url)
        for _ in range(4):
            response = curl_requests.get(
                current_url,
                headers={"User-Agent": "chatgpt2api-updater/3.0"},
                timeout=UPDATE_DOWNLOAD_TIMEOUT_SECS,
                allow_redirects=False,
                stream=True,
            )
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = str(response.headers.get("location") or "").strip()
                    if not location:
                        raise UpdateInstallError("更新包下载重定向无效。")
                    current_url = _safe_download_url(urljoin(current_url, location))
                    continue
                if response.status_code != 200:
                    raise UpdateInstallError("更新包下载失败。")
                _safe_download_url(str(response.url or current_url))
                content_length = str(response.headers.get("content-length") or "").strip()
                expected = int(content_length) if content_length.isdigit() else 0
                if expected > max_bytes:
                    raise UpdateInstallError("更新包超过允许大小。")

                received = 0
                with destination.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if not chunk:
                            continue
                        received += len(chunk)
                        if received > max_bytes:
                            raise UpdateInstallError("更新包超过允许大小。")
                        output.write(chunk)
                return
            finally:
                response.close()
        raise UpdateInstallError("更新包下载重定向次数过多。")

    @staticmethod
    def _verify_checksum(archive_path: Path, checksum_path: Path) -> None:
        expected = ""
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) == 2 and parts[1].lstrip("*") == UPDATE_ARCHIVE_NAME:
                expected = parts[0].lower()
                break
        if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
            raise UpdateInstallError("更新包校验文件无效。")

        digest = hashlib.sha256()
        with archive_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise UpdateInstallError("更新包完整性校验失败。")

    @staticmethod
    def _extract_archive(archive_path: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=False)
        total_size = 0
        file_count = 0
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive:
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise UpdateInstallError("更新包包含不安全路径。")
                if member.issym() or member.islnk() or member.isdev():
                    raise UpdateInstallError("更新包包含不支持的文件类型。")
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                file_count += 1
                total_size += max(0, int(member.size or 0))
                if file_count > UPDATE_EXTRACT_MAX_FILES or total_size > UPDATE_EXTRACT_MAX_BYTES:
                    raise UpdateInstallError("更新包解压内容超过允许大小。")
                source = archive.extractfile(member)
                if source is None:
                    raise UpdateInstallError("更新包内容不完整。")
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)

    @staticmethod
    def _validate_bundle(bundle_dir: Path, latest_tag: str) -> None:
        manifest_path = bundle_dir / "update-manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateInstallError("更新包清单无效。") from exc
        expected_version = latest_tag.removeprefix("v")
        if (
            not isinstance(manifest, dict)
            or manifest.get("format") != UPDATE_BUNDLE_FORMAT
            or str(manifest.get("version") or "").removeprefix("v") != expected_version
            or tuple(manifest.get("paths") or ()) != UPDATE_TARGETS
        ):
            raise UpdateInstallError("更新包清单与目标版本不匹配。")
        if any(not bundle_dir.joinpath(*PurePosixPath(path).parts).exists() for path in UPDATE_TARGETS):
            raise UpdateInstallError("更新包缺少运行文件。")

    def _apply_bundle(
        self,
        bundle_dir: Path,
        backup_dir: Path,
    ) -> list[tuple[Path, Path, bool]]:
        replaced: list[tuple[Path, Path, bool]] = []
        backup_dir.mkdir(parents=True, exist_ok=False)
        try:
            for relative_value in UPDATE_TARGETS:
                relative = PurePosixPath(relative_value)
                source = bundle_dir.joinpath(*relative.parts)
                target = self.root.joinpath(*relative.parts)
                backup = backup_dir.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                backup.parent.mkdir(parents=True, exist_ok=True)
                existed = target.exists() or target.is_symlink()
                if existed:
                    os.replace(target, backup)
                try:
                    os.replace(source, target)
                except Exception:
                    if existed and backup.exists():
                        os.replace(backup, target)
                    raise
                replaced.append((target, backup, existed))
        except Exception as exc:
            self._rollback(replaced)
            raise UpdateInstallError("应用更新文件失败，已恢复原版本。") from exc
        return replaced

    @staticmethod
    def _rollback(replaced: list[tuple[Path, Path, bool]]) -> None:
        for target, backup, existed in reversed(replaced):
            _remove_path(target)
            if existed and backup.exists():
                os.replace(backup, target)

    def _sync_dependencies(self) -> None:
        try:
            result = subprocess.run(
                ["uv", "sync", "--frozen", "--no-dev", "--no-install-project"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateInstallError("运行依赖同步失败。") from exc
        if result.returncode != 0:
            raise UpdateInstallError("运行依赖同步失败。")


class UpdateService:
    """Own the complete update task, including installation and restart."""

    def __init__(
        self,
        *,
        fetch_release: Callable[[], Mapping[str, object]] = _fetch_latest_release,
        installer: ReleaseBundleInstaller | None = None,
        runtime_mode: Callable[[Path], str] = _runtime_update_mode,
        state_path: Path | None = None,
        run_worker: Callable[[Callable[[], None]], None] | None = None,
        schedule_exit: Callable[[Callable[[], None]], None] | None = None,
        exit_process: Callable[[int], None] = os._exit,
    ) -> None:
        self._fetch_release = fetch_release
        self._installer = installer or ReleaseBundleInstaller(runtime_mode=runtime_mode)
        self._runtime_mode = runtime_mode
        self._state_path = state_path or self._installer.root.joinpath("data", "update_task.json")
        self._run_worker = run_worker or self._start_worker_thread
        self._schedule_exit_callback = schedule_exit or self._schedule_exit_timer
        self._exit_process = exit_process
        self._lock = threading.RLock()
        self._task: UpdateTaskView | None = None
        self._loaded = False
        self._worker_active = False
        self._restart_scheduled = False

    @staticmethod
    def _start_worker_thread(callback: Callable[[], None]) -> None:
        thread = threading.Thread(target=callback, name="chatgpt2api-update", daemon=True)
        thread.start()

    @staticmethod
    def _schedule_exit_timer(callback: Callable[[], None]) -> None:
        timer = threading.Timer(UPDATE_RESTART_DELAY_SECS, callback)
        timer.daemon = True
        timer.start()

    @staticmethod
    def _idle_view(current_version: str) -> UpdateTaskView:
        _, current_tag = _version_parts(current_version)
        return UpdateTaskView(
            status_label="未开始",
            message="当前没有系统更新任务。",
            current_tag=current_tag,
            updated_at=_utc_now(),
        )

    def _load_locked(self, current_version: str) -> None:
        if self._loaded:
            return
        self._loaded = True
        payload = read_json_object(self._state_path, name="system update task")
        try:
            self._task = UpdateTaskView.model_validate(payload) if payload else None
        except Exception:
            self._task = None
        if self._task is None:
            self._task = self._idle_view(current_version)

    def _persist_locked(self) -> None:
        if self._task is None:
            return
        write_json_file(self._state_path, self._task.model_dump(mode="json"), backup=False)

    def _replace_locked(self, **changes: object) -> UpdateTaskView:
        if self._task is None:
            raise RuntimeError("update task is not initialized")
        payload = self._task.model_dump(mode="python")
        payload.update({"updated_at": _utc_now(), **changes})
        self._task = UpdateTaskView.model_validate(payload)
        self._persist_locked()
        return self._task

    def _record_locked(
        self,
        *,
        state: str,
        stage: str,
        current: int,
        status_label: str,
        message: str,
        tone: str = "info",
        error: str = "",
        latest_tag: str | None = None,
        current_tag: str | None = None,
    ) -> UpdateTaskView:
        if self._task is None:
            raise RuntimeError("update task is not initialized")
        timestamp = _utc_now()
        event = UpdateTaskEventView(
            id=f"{self._task.task_id}:{len(self._task.events) + 1}",
            timestamp=timestamp,
            label=status_label,
            message=message,
            tone=tone,
        )
        changes: dict[str, object] = {
            "state": state,
            "stage": stage,
            "current": current,
            "status_label": status_label,
            "message": message,
            "tone": tone,
            "busy": state in {"queued", "running"},
            "error": error,
            "events": (*self._task.events, event),
        }
        if latest_tag is not None:
            changes["latest_tag"] = latest_tag
        if current_tag is not None:
            changes["current_tag"] = current_tag
        return self._replace_locked(**changes)

    def _reconcile_locked(self, current_version: str) -> None:
        if self._task is None or not self._task.busy or self._worker_active or self._restart_scheduled:
            return
        _, current_tag = _version_parts(current_version)
        if self._task.stage == "restarting" and current_tag == self._task.latest_tag:
            self._record_locked(
                state="succeeded",
                stage="completed",
                current=UPDATE_TASK_TOTAL,
                status_label="更新完成",
                message=f"服务已更新到 {current_tag}。",
                tone="success",
                current_tag=current_tag,
            )
            return
        message = (
            "服务重启后版本未生效，请查看容器日志并重新升级。"
            if self._task.stage == "restarting"
            else "系统更新被服务重启中断，请重新开始。"
        )
        self._record_locked(
            state="failed",
            stage="failed",
            current=self._task.current,
            status_label="更新失败",
            message=message,
            tone="danger",
            error=message,
            current_tag=current_tag,
        )

    def view(self, current_version: str) -> UpdateTaskView:
        with self._lock:
            self._load_locked(current_version)
            self._reconcile_locked(current_version)
            if self._task is None:
                raise RuntimeError("update task is not initialized")
            return self._task

    def start(self, current_version: str) -> UpdateTaskView:
        if self._runtime_mode(self._installer.root) != "managed_container":
            raise UpdateInstallError("当前部署不支持持久化在线更新，请使用部署工具升级。")
        with self._lock:
            self._load_locked(current_version)
            self._reconcile_locked(current_version)
            if self._task is not None and self._task.busy:
                return self._task
            _, current_tag = _version_parts(current_version)
            task_id = uuid.uuid4().hex
            queued = UpdateTaskEventView(
                id=f"{task_id}:1",
                timestamp=_utc_now(),
                label="等待更新",
                message="系统更新任务已进入队列。",
                tone="info",
            )
            self._task = UpdateTaskView(
                task_id=task_id,
                state="queued",
                stage="queued",
                current=0,
                total=UPDATE_TASK_TOTAL,
                status_label="等待更新",
                message="系统更新任务已进入队列。",
                tone="info",
                busy=True,
                current_tag=current_tag,
                updated_at=_utc_now(),
                events=(queued,),
            )
            self._worker_active = True
            self._restart_scheduled = False
            self._persist_locked()
            task = self._task

        try:
            self._run_worker(lambda: self._perform_task(current_version, task_id))
        except Exception as exc:
            with self._lock:
                self._worker_active = False
                self._fail_locked(exc)
            raise UpdateInstallError("无法启动系统更新任务。") from exc
        return task

    def _installer_progress(self, stage: str, current: int, label: str, message: str) -> None:
        with self._lock:
            self._record_locked(
                state="running",
                stage=stage,
                current=current,
                status_label=label,
                message=message,
            )

    def _perform_task(self, current_version: str, task_id: str) -> None:
        try:
            with self._lock:
                if self._task is None or self._task.task_id != task_id:
                    return
                self._record_locked(
                    state="running",
                    stage="checking",
                    current=1,
                    status_label="确认目标版本",
                    message="正在读取最新发布版本与更新资产。",
                )

            release = self._fetch_release()
            latest_version, latest_tag = _version_parts(release.get("tag_name"))
            normalized_current, current_tag = _version_parts(current_version)
            comparison = _compare_versions(latest_version, normalized_current)
            if comparison is None:
                raise UpdateInstallError("远程版本号无效。")
            if comparison <= 0:
                with self._lock:
                    self._record_locked(
                        state="succeeded",
                        stage="completed",
                        current=UPDATE_TASK_TOTAL,
                        status_label="无需更新",
                        message="当前已经是最新版本。",
                        tone="success",
                        latest_tag=latest_tag,
                        current_tag=current_tag,
                    )
                return

            with self._lock:
                self._replace_locked(latest_tag=latest_tag)
            self._installer.install(release, latest_tag, progress=self._installer_progress)

            with self._lock:
                self._record_locked(
                    state="running",
                    stage="restarting",
                    current=UPDATE_TASK_TOTAL - 1,
                    status_label="重启服务",
                    message=f"{latest_tag} 已安装，正在重启服务使更新生效。",
                    latest_tag=latest_tag,
                )
                self._restart_scheduled = True
            self._schedule_exit_callback(lambda: self._exit_process(0))
        except Exception as exc:
            with self._lock:
                self._fail_locked(exc)
        finally:
            with self._lock:
                self._worker_active = False

    def _fail_locked(self, exc: Exception) -> None:
        message = str(exc).strip() if isinstance(exc, UpdateInstallError) else "在线更新失败，请查看服务日志后重试。"
        logger.error({
            "event": "system_update_failed",
            "error_type": type(exc).__name__,
        })
        if self._task is not None:
            self._record_locked(
                state="failed",
                stage="failed",
                current=self._task.current,
                status_label="更新失败",
                message=message,
                tone="danger",
                error=message,
            )


update_service = UpdateService()
