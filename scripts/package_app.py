#!/usr/bin/env python3
"""Build a native macOS shortcut and a source-only, verified migration archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


APP_NAME = "Discord Archive.app"
ZIP_ROOT = "DiscordArchive"
# Deliberately enumerate public source files; never walk data or the project root.
SOURCE_ALLOWLIST = (
    "README.md", ".gitignore", "app.py", "package.json", "package-lock.json",
    "Install.command", "Start.command", "Install-Speech.command",
    "scripts/install_mac.sh", "scripts/install_speech.py", "scripts/doctor.py",
    "scripts/browser_runtime.mjs", "scripts/check_browser.mjs", "scripts/verify_distribution.py",
    "discord_archive/__init__.py", "discord_archive/assets.py", "discord_archive/access.py", "discord_archive/system_controls.py", "discord_archive/connection_binding.py", "discord_archive/remote_access.py",
    "discord_archive/browser_login.py", "discord_archive/collector.py",
    "discord_archive/context.py", "discord_archive/editorial.py",
    "discord_archive/export_names.py", "discord_archive/export_copy.py",
    "discord_archive/export_schedule.py", "discord_archive/auto_export.py",
    "discord_archive/delivery.py", "discord_archive/delivery_config.py", "discord_archive/clawbot.py",
    "scripts/clawbot_crypto.mjs",
    "discord_archive/media.py", "discord_archive/readability.py",
    "discord_archive/render_cache.py", "discord_archive/scheduler.py",
    "discord_archive/settings.py", "discord_archive/speech.py",
    "discord_archive/store.py", "discord_archive/worker.py", "discord_archive/service_control.py", "discord_archive/phone_sessions.py",
    "scripts/benchmark_history.py", "scripts/connect_browser.mjs",
    "scripts/desktop_launcher.py", "scripts/install_service.py",
    "scripts/package_app.py", "scripts/png.mjs", "scripts/render.mjs",
    "scripts/transcribe_local.py", "scripts/verify_workflow.py",
    "scripts/verify_auto_export.py",
    "web/app.js", "web/index.html", "web/manuscript.css", "web/preview.css",
    "web/preview.js", "web/reading.css", "web/style.css", "docs/PACKAGING.md",
    "docs/REFERENCE.md", "docs/INSTALLATION_ACCEPTANCE.md",
)
OPTIONAL_SOURCE_ALLOWLIST = (
    "docs/DELIVERY.md", "tests/test_clawbot.py", "tests/clawbot_check.mjs", "tests/test_delivery.py", "tests/delivery_check.mjs",
    "docs/MAC.md", "docs/LINUX_SETUP.md", "docs/ACCESS.md", "docs/USAGE.md", "docs/OPERATIONS.md", "docs/TROUBLESHOOTING.md", "docs/GITHUB_PRIVACY.md", "helpers/login-assistant-mac.zip", "docs/FINAL_PACKAGE_ACCEPTANCE.md",
    "scripts/package_native_client.py", "login_assistant/native_client.go", "login_assistant/native_client_test.go", "login_assistant/native_extension/manifest.json", "login_assistant/native_extension/launch.mjs", "login_assistant/native_extension/session.mjs", "login_assistant/native_extension/popup.html", "login_assistant/native_extension/popup.mjs", "scripts/configure_tailscale.py", "scripts/install_login_assistants.py", "scripts/package_login_assistant.py", "login_assistant/assistant.mjs", "login_assistant/assistant.html", "login_assistant/bridge.json", "login_assistant/extension/manifest.json", "login_assistant/extension/intent.js", "login_assistant/extension/background.js", "login_assistant/extension/popup.html", "login_assistant/extension/popup.mjs", "tests/initial_loading_check.mjs", "tests/unified_login_check.mjs", "tests/test_mac_connection.py", "tests/test_helper_packages.py", "tests/test_remote_access.py", "tests/first_login_extension_check.mjs", "tests/first_login_network_check.mjs", "tests/login_assistant_check.mjs", "tests/remote_workspace_check.mjs", "docs/REMOTE_ACCESS_ACCEPTANCE.md", "docs/FIRST_LOGIN_ACCEPTANCE.md", "scripts/bind_linux.py", "scripts/receive_connection.py", "tests/test_connection_binding.py", "tests/connection_binding_check.mjs",
    "tests/test_system_controls.py", "tests/system_controls_check.mjs", "docs/SYSTEM_CONTROLS_ACCEPTANCE.md",
    "scripts/verify_speech.py",
    "scripts/install_linux.sh", "scripts/install_linux_service.py", "scripts/linux_desktop.sh",
    "docs/LOGIN_ASSISTANT.md", "docs/LINUX.md", "docs/LINUX_ACCEPTANCE.md", "tests/test_linux.py",
    "scripts/benchmark_workspace.py", "docs/WORKSPACE_PERFORMANCE.md",
    "scripts/benchmark_scaling.py", "tests/test_draft_listing.py", "docs/SCALING.md",
    "scripts/benchmark_draft_listing.py", "tests/test_benchmark_scaling.py", "tests/draft_library_check.mjs",
    "tests/test_export_names.py", "tests/test_export_copy.py", "tests/export_settings_check.mjs",
    "tests/test_export_schedule.py", "tests/test_auto_export.py", "tests/test_auto_export_integration.py", "tests/auto_export_check.mjs",
    "tests/test_phone_sessions.py", "tests/test_service_control.py", "tests/service_controls_check.mjs", "tests/verify_managed_service.py",
    "docs/SERVICE_CONTROL_ACCEPTANCE.md",
    "tests/test_packaging.py", "tests/test_installation.py", "tests/onboarding_check.mjs", "tests/test_settings.py", "tests/test_render_targets.py",
    "tests/test_collector_scheduler.py", "tests/test_benchmark_history.py",
    "tests/test_store_context.py", "tests/test_server.py", "tests/test_worker.py",
    "tests/test_readability.py", "tests/test_speech.py", "tests/test_browser_login.py",
    "tests/test_assets.py", "tests/test_editorial.py", "tests/frontend_design_check.mjs",
    "tests/png_check.mjs", "tests/render_hidpi_check.mjs", "tests/render_collage_check.mjs",
    "tests/render_large_flow_check.mjs", "tests/test_render_diagnostics.py", "docs/LARGE_EXPORTS.md",
    "tests/ui_check.mjs", "tests/workflow_ux_check.mjs", "tests/browser_candidate_check.mjs",
    "docs/ACCEPTANCE.md", "docs/DESIGN.md", "docs/EXPORT_DENSITY.md",
    "docs/HIDPI_ACCEPTANCE.md", "docs/PHONE_ACCEPTANCE.md", "docs/SPEECH_PERFORMANCE.md",
)
APP_FILE_ALLOWLIST = {
    "Contents/Info.plist", "Contents/PkgInfo", "Contents/MacOS/applet",
    "Contents/Resources/applet.icns", "Contents/Resources/Scripts/main.scpt",
    "Contents/Resources/applet.rsrc", "Contents/Resources/Assets.car",
    "Contents/Resources/description.rtfd/TXT.rtf",
    "Contents/Resources/desktop_launcher.py", "Contents/Resources/project.json",
    "Contents/Resources/archive-package.json", "Contents/_CodeSignature/CodeResources",
}

APPLESCRIPT = '''on run
    set appPath to POSIX path of (path to me)
    set launcherPath to appPath & "Contents/Resources/desktop_launcher.py"
    set pythonPath to ""
    set adjacentPython to (do shell script "/usr/bin/dirname " & quoted form of appPath) & "/.runtime/bin/python3"
    repeat with candidate in {adjacentPython, "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"}
        try
            do shell script (quoted form of candidate) & " -c " & quoted form of "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
            set pythonPath to contents of candidate
            exit repeat
        end try
    end repeat
    if pythonPath is "" then
        display dialog "需要 Python 3.10 或更新版本。请先双击同一文件夹中的 Install.command，再打开工作台。" buttons {"好"} default button "好" with title "Discord 归档"
        return
    end if
    try
        do shell script (quoted form of pythonPath) & " " & (quoted form of launcherPath) & " --app-path " & (quoted form of appPath)
    on error errorMessage
        display dialog errorMessage buttons {"好"} default button "好" with title "工作台未能打开"
    end try
end run
'''


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_files(root: Path) -> list[Path]:
    files = []
    for name in (*SOURCE_ALLOWLIST, *OPTIONAL_SOURCE_ALLOWLIST):
        source = root / name
        if not source.exists() and name in OPTIONAL_SOURCE_ALLOWLIST:
            continue
        if not source.is_file():
            raise ValueError(f"缺少源码文件：{name}")
        relative_parts = source.relative_to(root).parts
        if source.is_symlink() or any(root.joinpath(*relative_parts[:index]).is_symlink()
                                      for index in range(1, len(relative_parts))):
            raise ValueError(f"源码白名单不接受符号链接：{name}")
        if not source.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"源码路径超出项目目录：{name}")
        if source.stat().st_size > 2_000_000:
            raise ValueError(f"源码文件异常大，需人工检查：{name}")
        files.append(source)
    return files


def build_app(root: Path, build_dir: Path, portable: bool = False) -> Path:
    app = build_dir / APP_NAME
    if app.exists():
        raise FileExistsError("目标 App 已存在；请使用新的版本目录，保留旧版本")
    compiler = shutil.which("osacompile")
    if not compiler:
        raise RuntimeError("打包需要 macOS 自带的 osacompile")
    script = build_dir / "launcher.applescript"
    script.write_text(APPLESCRIPT)
    result = subprocess.run([compiler, "-o", str(app), str(script)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError("原生 App 编译失败：" + result.stderr[-500:])
    resources = app / "Contents" / "Resources"
    shutil.copy2(root / "scripts" / "desktop_launcher.py", resources / "desktop_launcher.py")
    (resources / "project.json").write_text(json.dumps({"root": None if portable else str(root)}, ensure_ascii=False))
    (resources / "archive-package.json").write_text(json.dumps({"format": 1, "kind": "local-shortcut"}))
    plist = app / "Contents" / "Info.plist"
    info = plistlib.loads(plist.read_bytes())
    info.update(CFBundleDisplayName="Discord 归档", CFBundleName="Discord 归档",
                CFBundleIdentifier="local.discord.archive-launcher",
                CFBundleShortVersionString="1.0", LSUIElement=True)
    plist.write_bytes(plistlib.dumps(info, sort_keys=False))
    # Resources and Info.plist changed after compilation; refresh the local
    # ad-hoc signature so macOS does not see a broken original signature.
    codesign = shutil.which("codesign")
    if not codesign:
        raise RuntimeError("缺少 macOS codesign，无法验证原生 App")
    for arguments in (("--force", "--sign", "-", str(app)), ("--verify", "--strict", str(app))):
        result = subprocess.run([codesign, *arguments], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError("本地 App 签名或校验失败：" + result.stderr[-500:])
    return app


def write_zip(root: Path, app: Path, archive: Path, mac_helper=None) -> dict:
    if archive.exists():
        raise FileExistsError("迁移包已存在，保留原包；请使用新版本目录")
    entries: dict[str, tuple[bytes, int]] = {}
    for source in source_files(root):
        entries[str(PurePosixPath(ZIP_ROOT) / source.relative_to(root).as_posix())] = (
            source.read_bytes(), 0o755 if source.suffix in {".command", ".sh"} else 0o644)
    # osacompile output is newly produced here, not a user-supplied application.
    for source in sorted(app.rglob("*")):
        if not source.is_file():
            continue
        if source.is_symlink():
            raise ValueError("App 构建结果不应包含符号链接")
        relative = source.relative_to(app)
        if relative.as_posix() not in APP_FILE_ALLOWLIST:
            raise ValueError(f"App 构建结果包含未列入白名单的文件：{relative}")
        content = source.read_bytes()
        mode = 0o755 if source.stat().st_mode & stat.S_IXUSR else 0o644
        entries[str(PurePosixPath(ZIP_ROOT) / APP_NAME / relative.as_posix())] = (content, mode)
    if mac_helper is not None:
        import importlib.util
        spec=importlib.util.spec_from_file_location("helper_verifier",Path(__file__).with_name("install_login_assistants.py"));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        verify=module.verify
        verify(Path(mac_helper), {'darwin-arm64','darwin-x64'})
        entries[f"{ZIP_ROOT}/helpers/login-assistant-mac.zip"] = (Path(mac_helper).read_bytes(),0o644)
    manifest = {"format": 1, "kind": "source-and-native-shortcut", "files": [
        {"path": name, "size": len(content), "sha256": digest(content)}
        for name, (content, _mode) in sorted(entries.items())
    ]}
    manifest_name = f"{ZIP_ROOT}/PACKAGE-MANIFEST.json"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for name, (content, mode) in sorted(entries.items()):
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            bundle.writestr(info, content)
        bundle.writestr(manifest_name, json.dumps(manifest, ensure_ascii=False, indent=2))
    return verify_zip(archive)


def verify_zip(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as bundle:
        manifest_name = f"{ZIP_ROOT}/PACKAGE-MANIFEST.json"
        manifest = json.loads(bundle.read(manifest_name))
        expected = {row["path"]: row for row in manifest["files"]}
        names = bundle.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected) | {manifest_name}:
            raise ValueError("迁移包文件清单不一致")
        for name, record in expected.items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or path.parts[0] != ZIP_ROOT:
                raise ValueError("迁移包包含异常路径")
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            if relative.startswith(APP_NAME + "/"):
                if relative.removeprefix(APP_NAME + "/") not in APP_FILE_ALLOWLIST:
                    raise ValueError("迁移包包含 App 白名单外文件")
            elif relative not in (*SOURCE_ALLOWLIST, *OPTIONAL_SOURCE_ALLOWLIST):
                raise ValueError("迁移包包含源码白名单外文件")
            if any(part in {"data", "output", ".venv", ".git", "artifacts", "node_modules", "models"}
                   for part in path.parts):
                raise ValueError("迁移包包含非源码目录")
            content = bundle.read(name)
            if len(content) != record["size"] or digest(content) != record["sha256"]:
                raise ValueError(f"迁移包校验失败：{name}")
        if bundle.testzip() is not None:
            raise ValueError("迁移包 CRC 校验失败")
    return {"files": len(expected), "bytes": archive.stat().st_size,
            "sha256": digest(archive.read_bytes()), "verified": True}


def build(root: Path, destination: Path, mac_helper=None) -> dict:
    root, destination = root.resolve(), destination.resolve()
    if destination.exists():
        raise FileExistsError("构建版本目录已存在；不会覆盖或删除已有文件")
    source_files(root)  # fail before creating a partial build if source is missing
    destination.mkdir(parents=True, mode=0o755)
    app = build_app(root, destination)
    portable = destination / "portable"
    portable.mkdir()
    portable_app = build_app(root, portable, portable=True)
    archive = destination / "DiscordArchive-source.zip"
    verification = write_zip(root, portable_app, archive, mac_helper)
    report = {"app": str(app), "archive": str(archive), **verification,
              "dependencies_bundled": False}
    (destination / "BUILD.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 macOS 快捷 App 和不含私有数据的源码迁移包")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--mac-helper", type=Path)
    args = parser.parse_args()
    destination = args.destination or args.root / "dist" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    # A custom destination still belongs under dist to keep generated files scoped.
    if not destination.resolve().is_relative_to((args.root / "dist").resolve()):
        raise ValueError("构建目录必须位于项目的 dist/ 中")
    helper=args.mac_helper or next((p for p in [args.root/"helpers/login-assistant-mac.zip",args.root/".local/login-assistants/login-assistant-mac.zip"] if p.is_file()),None)
    if helper is None:parser.error("缺少 Mac 首次连接包；先运行 package_native_client.py --with-first-login，再用 --mac-helper 指定 ZIP")
    print(json.dumps(build(args.root, destination, helper), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"打包未完成：{exc}", file=sys.stderr)
        raise SystemExit(1)
