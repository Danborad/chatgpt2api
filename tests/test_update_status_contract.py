from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import Callable
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import system as system_api
from contracts.updates import UpdateStatusView, UpdateTaskView
from services import update_status_service as update_status_module
from services import update_service as update_module
from services.update_service import (
    UPDATE_ARCHIVE_NAME,
    UPDATE_CHECKSUM_NAME,
    UPDATE_TARGETS,
    ReleaseBundleInstaller,
    UpdateInstallError,
    UpdateService,
)
from services.update_status_service import (
    GITHUB_RELEASES_URL,
    MANAGED_RUNTIME_MARKER,
    UPDATE_CHECK_MAX_BYTES,
    UpdateCheckError,
    UpdateStatusService,
)


def _release(tag: str = "v3.1.0") -> dict[str, object]:
    return {
        "tag_name": tag,
        "assets": [
            {
                "name": UPDATE_ARCHIVE_NAME,
                "browser_download_url": f"https://github.com/yukkcat/chatgpt2api/releases/download/{tag}/{UPDATE_ARCHIVE_NAME}",
            },
            {
                "name": UPDATE_CHECKSUM_NAME,
                "browser_download_url": f"https://github.com/yukkcat/chatgpt2api/releases/download/{tag}/{UPDATE_CHECKSUM_NAME}",
            },
        ],
    }


def _write_runtime_targets(root: Path, version: str, marker: str) -> None:
    directory_targets = {"api", "contracts", "services", "utils", "web_dist"}
    for relative in UPDATE_TARGETS:
        target = root.joinpath(*relative.split("/"))
        if relative in directory_targets:
            target.mkdir(parents=True, exist_ok=True)
            (target / "marker.txt").write_text(marker, encoding="utf-8")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(version if relative == "VERSION" else marker, encoding="utf-8")


def _build_release_assets(base: Path, version: str = "3.1.0") -> tuple[Path, Path]:
    bundle = base / "bundle" / "chatgpt2api-app"
    _write_runtime_targets(bundle, version, "new")
    (bundle / "update-manifest.json").write_text(
        json.dumps({"format": 1, "version": version, "paths": list(UPDATE_TARGETS)}),
        encoding="utf-8",
    )
    archive = base / UPDATE_ARCHIVE_NAME
    with tarfile.open(archive, "w:gz") as output:
        output.add(bundle, arcname="chatgpt2api-app")
    checksum = base / UPDATE_CHECKSUM_NAME
    checksum.write_text(
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {UPDATE_ARCHIVE_NAME}\n",
        encoding="utf-8",
    )
    return archive, checksum


class UpdateStatusServiceTests(unittest.TestCase):
    def test_new_release_projects_managed_update_capability(self) -> None:
        service = UpdateStatusService(
            fetch_release=lambda: {
                "tag_name": "v3.1.0",
                "body": "+ [新增] 在线更新。",
                "published_at": "2026-08-07T00:00:00Z",
            },
        )

        with patch.object(update_status_module, "_runtime_update_mode", return_value="managed_container"):
            view = service.view("3.0.0")

        self.assertTrue(view.update_available)
        self.assertTrue(view.can_update)
        self.assertEqual(view.current_tag, "v3.0.0")
        self.assertEqual(view.latest_tag, "v3.1.0")
        self.assertEqual(view.release_url, f"{GITHUB_RELEASES_URL}/tag/v3.1.0")
        self.assertEqual(view.release_notes, "+ [新增] 在线更新。")
        self.assertEqual(view.release_published_at, "2026-08-07T00:00:00Z")

    def test_immutable_container_requires_image_upgrade(self) -> None:
        service = UpdateStatusService(fetch_release=lambda: {"tag_name": "v3.1.0"})
        with patch.object(update_status_module, "_runtime_update_mode", return_value="immutable_container"):
            view = service.view("3.0.0")
        self.assertFalse(view.can_update)
        self.assertIn("拉取新镜像", view.status_message)

    def test_source_runtime_requires_git_update(self) -> None:
        service = UpdateStatusService(fetch_release=lambda: {"tag_name": "v3.1.0"})
        with patch.object(update_status_module, "_runtime_update_mode", return_value="source"):
            view = service.view("3.0.0")
        self.assertFalse(view.can_update)
        self.assertIn("Git", view.status_message)

    def test_runtime_mode_requires_docker_mount_and_marker(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            (root / MANAGED_RUNTIME_MARKER).write_text("3.0.0", encoding="utf-8")
            with (
                patch.object(update_status_module, "_build_type", return_value="release"),
                patch.object(update_status_module, "_in_docker", return_value=True),
                patch.object(update_status_module, "_has_dedicated_mount", return_value=True),
            ):
                self.assertEqual(update_status_module._runtime_update_mode(root), "managed_container")

            (root / MANAGED_RUNTIME_MARKER).unlink()
            with (
                patch.object(update_status_module, "_build_type", return_value="release"),
                patch.object(update_status_module, "_in_docker", return_value=True),
                patch.object(update_status_module, "_has_dedicated_mount", return_value=True),
            ):
                self.assertEqual(update_status_module._runtime_update_mode(root), "immutable_container")

    def test_stable_release_is_newer_than_prerelease(self) -> None:
        service = UpdateStatusService(fetch_release=lambda: {"tag_name": "v3.1.0"})
        view = service.view("3.1.0-rc.2")
        self.assertTrue(view.update_available)

    def test_check_result_is_cached_and_force_bypasses_it(self) -> None:
        fetch_release = Mock(side_effect=[{"tag_name": "v3.0.0"}, {"tag_name": "v3.1.0"}])
        service = UpdateStatusService(fetch_release=fetch_release, cache_ttl_seconds=300)
        first = service.view("3.0.0")
        self.assertIs(first, service.view("3.0.0"))
        self.assertEqual(service.view("3.0.0", force=True).latest_tag, "v3.1.0")
        self.assertEqual(fetch_release.call_count, 2)

    def test_remote_failure_returns_safe_projection(self) -> None:
        service = UpdateStatusService(fetch_release=lambda: (_ for _ in ()).throw(RuntimeError("secret")))
        view = service.view("3.0.0")
        self.assertFalse(view.update_available)
        self.assertFalse(view.can_update)
        self.assertEqual(view.release_url, GITHUB_RELEASES_URL)
        self.assertNotIn("secret", view.status_message)

    def test_default_fetcher_rejects_oversized_response(self) -> None:
        response = Mock(status_code=200, headers={"content-length": str(UPDATE_CHECK_MAX_BYTES + 1)})
        with patch.object(update_status_module.curl_requests, "get", return_value=response):
            with self.assertRaisesRegex(UpdateCheckError, "too large"):
                update_status_module._fetch_latest_release()
        response.close.assert_called_once_with()


class ReleaseBundleInstallerTests(unittest.TestCase):
    def test_download_streams_to_disk_and_enforces_limit(self) -> None:
        response = Mock(
            status_code=200,
            headers={"content-length": "6"},
            url="https://release-assets.githubusercontent.com/file",
        )
        response.iter_content.return_value = [b"abc", b"def"]
        with tempfile.TemporaryDirectory() as value:
            destination = Path(value) / "asset"
            with patch.object(update_module.curl_requests, "get", return_value=response) as request:
                ReleaseBundleInstaller._download(
                    "https://github.com/yukkcat/chatgpt2api/releases/download/v3.1.0/asset",
                    destination,
                    max_bytes=6,
                )
            self.assertEqual(destination.read_bytes(), b"abcdef")
        response.close.assert_called_once_with()
        self.assertFalse(request.call_args.kwargs["allow_redirects"])

    def test_download_rejects_untrusted_redirect_before_following_it(self) -> None:
        response = Mock(
            status_code=302,
            headers={"location": "https://evil.example/file"},
            url="https://github.com/yukkcat/chatgpt2api/releases/download/v3.1.0/asset",
        )
        with tempfile.TemporaryDirectory() as value:
            with patch.object(update_module.curl_requests, "get", return_value=response) as request:
                with self.assertRaisesRegex(UpdateInstallError, "下载地址无效"):
                    ReleaseBundleInstaller._download(
                        "https://github.com/yukkcat/chatgpt2api/releases/download/v3.1.0/asset",
                        Path(value) / "asset",
                        max_bytes=6,
                    )
            request.assert_called_once()
        response.close.assert_called_once_with()

    def test_extractor_rejects_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                info = tarfile.TarInfo("../escape")
                info.size = 1
                output.addfile(info, io.BytesIO(b"x"))
            with self.assertRaisesRegex(UpdateInstallError, "不安全路径"):
                ReleaseBundleInstaller._extract_archive(archive, root / "extract")

    def test_verified_bundle_replaces_runtime_targets(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            base = Path(value)
            runtime = base / "runtime"
            runtime.mkdir()
            _write_runtime_targets(runtime, "3.0.0", "old")
            archive, checksum = _build_release_assets(base)
            installer = ReleaseBundleInstaller(runtime, runtime_mode=lambda _root: "managed_container")

            def download(_url: str, destination: Path, *, max_bytes: int) -> None:
                del max_bytes
                shutil.copyfile(archive if destination.name == UPDATE_ARCHIVE_NAME else checksum, destination)

            progress: list[str] = []
            with (
                patch.object(installer, "_download", side_effect=download),
                patch.object(installer, "_sync_dependencies"),
            ):
                installer.install(
                    _release(),
                    "v3.1.0",
                    progress=lambda stage, *_args: progress.append(stage),
                )

            self.assertEqual((runtime / "VERSION").read_text(encoding="utf-8"), "3.1.0")
            self.assertEqual((runtime / "services" / "marker.txt").read_text(encoding="utf-8"), "new")
            self.assertEqual(progress, ["downloading", "verifying", "installing", "syncing"])

    def test_dependency_failure_restores_files_and_old_environment(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            base = Path(value)
            runtime = base / "runtime"
            runtime.mkdir()
            _write_runtime_targets(runtime, "3.0.0", "old")
            archive, checksum = _build_release_assets(base)
            installer = ReleaseBundleInstaller(runtime, runtime_mode=lambda _root: "managed_container")

            def download(_url: str, destination: Path, *, max_bytes: int) -> None:
                del max_bytes
                shutil.copyfile(archive if destination.name == UPDATE_ARCHIVE_NAME else checksum, destination)

            with (
                patch.object(installer, "_download", side_effect=download),
                patch.object(
                    installer,
                    "_sync_dependencies",
                    side_effect=[UpdateInstallError("new dependency failure"), None],
                ) as sync_dependencies,
            ):
                with self.assertRaisesRegex(UpdateInstallError, "已恢复原版本"):
                    installer.install(_release(), "v3.1.0")

            self.assertEqual((runtime / "VERSION").read_text(encoding="utf-8"), "3.0.0")
            self.assertEqual((runtime / "services" / "marker.txt").read_text(encoding="utf-8"), "old")
            self.assertEqual(sync_dependencies.call_count, 2)


class UpdateTaskServiceTests(unittest.TestCase):
    def _service(
        self,
        root: Path,
        *,
        installer: Mock | None = None,
        run_worker=None,
        schedule_exit=None,
    ) -> UpdateService:
        bundle_installer = installer or Mock(root=root)
        bundle_installer.root = root
        return UpdateService(
            fetch_release=lambda: _release(),
            installer=bundle_installer,
            runtime_mode=lambda _root: "managed_container",
            state_path=root / "data" / "update_task.json",
            run_worker=run_worker,
            schedule_exit=schedule_exit,
            exit_process=Mock(),
        )

    def test_task_owns_installation_and_restart_then_recovers_after_boot(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            installer = Mock(root=root)

            def install(_release_data, _latest_tag, *, progress) -> None:
                progress("downloading", 2, "下载更新包", "下载中")
                progress("verifying", 3, "校验更新包", "校验中")
                progress("installing", 4, "安装运行文件", "安装中")
                progress("syncing", 5, "同步运行依赖", "同步中")

            installer.install.side_effect = install
            exits: list[Callable[[], None]] = []
            service = self._service(
                root,
                installer=installer,
                run_worker=lambda callback: callback(),
                schedule_exit=lambda callback: exits.append(callback),
            )

            service.start("3.0.0")
            restarting = service.view("3.0.0")
            self.assertEqual(restarting.stage, "restarting")
            self.assertTrue(restarting.busy)
            self.assertEqual(len(exits), 1)
            self.assertEqual([event.label for event in restarting.events][-1], "重启服务")

            recovered = self._service(root).view("3.1.0")
            self.assertEqual(recovered.state, "succeeded")
            self.assertEqual(recovered.stage, "completed")
            self.assertFalse(recovered.busy)
            self.assertEqual(recovered.current_tag, "v3.1.0")

    def test_concurrent_start_returns_the_active_task(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workers: list[Callable[[], None]] = []
            service = self._service(root, run_worker=lambda callback: workers.append(callback))
            first = service.start("3.0.0")
            second = service.start("3.0.0")
            self.assertEqual(first.task_id, second.task_id)
            self.assertEqual(len(workers), 1)

    def test_interrupted_task_becomes_failed_after_process_restart(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            service = self._service(root, run_worker=lambda _callback: None)
            started = service.start("3.0.0")
            self.assertTrue(started.busy)

            recovered = self._service(root).view("3.0.0")
            self.assertEqual(recovered.state, "failed")
            self.assertIn("中断", recovered.error)

    def test_installer_failure_is_projected_by_the_task(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            installer = Mock(root=root)
            installer.install.side_effect = UpdateInstallError("更新包不可用。")
            service = self._service(root, installer=installer, run_worker=lambda callback: callback())
            service.start("3.0.0")
            failed = service.view("3.0.0")
            self.assertEqual(failed.state, "failed")
            self.assertEqual(failed.error, "更新包不可用。")


class UpdateRouteContractTests(unittest.TestCase):
    def test_routes_publish_backend_owned_task_and_no_restart_command(self) -> None:
        task = UpdateTaskView(
            task_id="task-1",
            state="queued",
            stage="queued",
            status_label="等待更新",
            message="系统更新任务已进入队列。",
            busy=True,
            current_tag="v3.0.0",
            latest_tag="v3.1.0",
            updated_at="2026-08-07T00:00:00Z",
        )
        service = Mock()
        service.view.return_value = task
        service.start.return_value = task
        status_service = Mock()
        status_service.view.return_value = UpdateStatusService(
            fetch_release=lambda: {"tag_name": "v3.1.0"},
        ).view("3.0.0")
        app = FastAPI()

        with (
            patch.object(system_api, "require_admin", return_value={"id": "admin"}),
            patch.object(system_api, "update_service", service),
            patch.object(system_api, "update_status_service", status_service),
        ):
            app.include_router(system_api.create_router("3.0.0"))
            client = TestClient(app)
            status = client.get("/api/system/update-status?force=true")
            current = client.get("/api/system/update-task")
            started = client.post("/api/system/update")
            restart = client.post("/api/system/restart")

        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(started.status_code, 202, started.text)
        self.assertEqual(started.json()["task_id"], "task-1")
        self.assertEqual(restart.status_code, 404)
        status_service.view.assert_called_once_with("3.0.0", force=True)
        service.view.assert_called_once_with("3.0.0")
        service.start.assert_called_once_with("3.0.0")


class ManagedComposeContractTests(unittest.TestCase):
    def test_compose_and_image_use_a_persistent_managed_runtime(self) -> None:
        root = Path(__file__).resolve().parents[1]
        compose = root.joinpath("docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = root.joinpath("Dockerfile").read_text(encoding="utf-8")
        entrypoint = root.joinpath("deploy", "docker-entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn("chatgpt2api-runtime:/app", compose)
        self.assertIn("WORKDIR /opt/chatgpt2api", dockerfile)
        self.assertIn('ENTRYPOINT ["chatgpt2api-entrypoint"]', dockerfile)
        self.assertIn("seed_root=/opt/chatgpt2api", entrypoint)
        self.assertIn("marker_name=.chatgpt2api-image-version", entrypoint)
        self.assertIn("uv sync --frozen --no-dev --no-install-project", entrypoint)


if __name__ == "__main__":
    unittest.main()
