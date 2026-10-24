from __future__ import annotations

import importlib.util
import json
import plistlib
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = load("desktop_launcher", "desktop_launcher.py")
package = load("package_app", "package_app.py")


class LauncherTests(unittest.TestCase):
    def test_manual_open_does_not_reenable_disabled_autostart(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with mock.patch.object(launcher,'health',return_value='offline'),mock.patch.object(launcher,'archive_locked',return_value=False),mock.patch.object(launcher,'matching_agent',return_value=True),mock.patch.object(launcher,'agent_autostart',return_value=False),mock.patch.object(launcher,'wait_healthy'),mock.patch.object(launcher.sys,'platform','darwin'),mock.patch.object(launcher,'launchctl') as command,mock.patch.object(launcher.subprocess,'Popen') as spawn:
                self.assertEqual(launcher.ensure_service(root),'started')
                command.assert_not_called();spawn.assert_called_once()

    def project(self, root):
        for name in ("app.py", "discord_archive/__init__.py", "web/index.html"):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("")

    def test_running_service_is_reused_without_commands_or_restart(self):
        with mock.patch.object(launcher, "health", return_value="healthy"), \
             mock.patch.object(launcher, "launchctl") as launchctl, \
             mock.patch.object(launcher.subprocess, "Popen") as spawn:
            self.assertEqual(launcher.ensure_service(ROOT), "reused")
            launchctl.assert_not_called()
            spawn.assert_not_called()

    def test_bound_port_with_same_archive_lock_only_waits(self):
        with mock.patch.object(launcher, "health", return_value="occupied"), \
             mock.patch.object(launcher, "archive_locked", return_value=True), \
             mock.patch.object(launcher, "wait_healthy") as wait, \
             mock.patch.object(launcher, "launchctl") as launchctl, \
             mock.patch.object(launcher.subprocess, "Popen") as spawn:
            self.assertEqual(launcher.ensure_service(ROOT), "waited")
            wait.assert_called_once()
            launchctl.assert_not_called()
            spawn.assert_not_called()

    def test_existing_archive_lock_prevents_new_process(self):
        with mock.patch.object(launcher, "health", return_value="offline"), \
             mock.patch.object(launcher, "archive_locked", return_value=True), \
             mock.patch.object(launcher, "wait_healthy"), \
             mock.patch.object(launcher.subprocess, "Popen") as spawn:
            self.assertEqual(launcher.ensure_service(ROOT), "waited")
            spawn.assert_not_called()

    def test_matching_launchagent_starts_without_kill_flag(self):
        with mock.patch.object(launcher, "health", return_value="offline"), \
             mock.patch.object(launcher, "archive_locked", return_value=False), \
             mock.patch.object(launcher, "matching_agent", return_value=True), \
             mock.patch.object(launcher, "wait_healthy"), \
             mock.patch.object(launcher.sys, "platform", "darwin"), \
             mock.patch.object(launcher, "launchctl", return_value=subprocess.CompletedProcess([], 0)) as command, \
             mock.patch.object(launcher.subprocess, "Popen") as spawn:
            self.assertEqual(launcher.ensure_service(ROOT), "agent")
            self.assertEqual([call.args[0] for call in command.call_args_list], ["print", "kickstart"])
            self.assertFalse(any("-k" in call.args for call in command.call_args_list))
            spawn.assert_not_called()

    def test_loaded_agent_with_pid_is_waited_without_kickstart(self):
        with mock.patch.object(launcher, "health", return_value="offline"), \
             mock.patch.object(launcher, "archive_locked", return_value=False), \
             mock.patch.object(launcher, "matching_agent", return_value=True), \
             mock.patch.object(launcher, "wait_healthy"), \
             mock.patch.object(launcher.sys, "platform", "darwin"), \
             mock.patch.object(launcher, "launchctl", return_value=subprocess.CompletedProcess([], 0, "  pid = 321\n")) as command, \
             mock.patch.object(launcher.subprocess, "Popen") as spawn:
            self.assertEqual(launcher.ensure_service(ROOT), "waited")
            self.assertEqual([call.args[0] for call in command.call_args_list], ["print"])
            spawn.assert_not_called()

    def test_agent_start_failure_does_not_spawn_another_instance(self):
        with mock.patch.object(launcher, "health", return_value="offline"), \
             mock.patch.object(launcher, "archive_locked", return_value=False), \
             mock.patch.object(launcher, "matching_agent", return_value=True), \
             mock.patch.object(launcher.sys, "platform", "darwin"), \
             mock.patch.object(launcher, "launchctl", return_value=subprocess.CompletedProcess([], 1)), \
             mock.patch.object(launcher.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "未改写或重装"):
                launcher.ensure_service(ROOT)
            spawn.assert_not_called()

    def test_adjacent_portable_source_precedes_original_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            old, new = base / "old", base / "new"
            self.project(old)
            self.project(new)
            app = new / package.APP_NAME
            resources = app / "Contents" / "Resources"
            resources.mkdir(parents=True)
            (resources / "project.json").write_text(json.dumps({"root": str(old)}))
            self.assertEqual(launcher.project_root(app), new.resolve())

    def test_matching_agent_rejects_different_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            plist = Path(temporary) / "agent.plist"
            plist.write_bytes(plistlib.dumps({"Label": launcher.LABEL,
                                             "ProgramArguments": ["python", "/another/app.py"]}))
            self.assertFalse(launcher.matching_agent(ROOT, plist))

    def test_stopped_agent_is_enabled_before_bootstrap(self):
        with mock.patch.object(launcher, "health", return_value="offline"), \
             mock.patch.object(launcher, "archive_locked", return_value=False), \
             mock.patch.object(launcher, "matching_agent", return_value=True), \
             mock.patch.object(launcher, "wait_healthy"), \
             mock.patch.object(launcher.sys, "platform", "darwin"), \
             mock.patch.object(launcher, "launchctl", side_effect=[subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 0)]) as command:
            self.assertEqual(launcher.ensure_service(ROOT), "agent")
            self.assertEqual([c.args[0] for c in command.call_args_list], ["print", "enable", "bootstrap"])


class PackageTests(unittest.TestCase):
    def fake_source(self, root):
        for name in package.SOURCE_ALLOWLIST:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("source " + name)
        app = root / "dist" / "build" / package.APP_NAME
        resources = app / "Contents" / "Resources"
        resources.mkdir(parents=True)
        (resources / "project.json").write_text('{"root":null}')
        executable = app / "Contents" / "MacOS" / "applet"
        executable.parent.mkdir()
        executable.write_bytes(b"compiled application")
        executable.chmod(0o755)
        return app

    def test_package_excludes_unknown_private_files_and_preserves_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.fake_source(root)
            for name in ("data/credentials.json", "data/browser-profile/Default/Cookies", "output/private.md", ".env", "models/weights.bin", "scripts/private.py", ".runtime/bin/python3", "node_modules/private.js", ".venv/private.txt"):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("sensitive content")
            archive = root / "dist" / "build" / "source.zip"
            result = package.write_zip(root, app, archive)
            self.assertTrue(result["verified"])
            with zipfile.ZipFile(archive) as bundle:
                self.assertFalse(any(b"sensitive content" in bundle.read(name) for name in bundle.namelist()))
                name = f"{package.ZIP_ROOT}/{package.APP_NAME}/Contents/MacOS/applet"
                self.assertTrue((bundle.getinfo(name).external_attr >> 16) & 0o111)
                for script in ('Install.command', 'Start.command', 'Install-Speech.command', 'scripts/install_mac.sh'):
                    self.assertTrue((bundle.getinfo(f'{package.ZIP_ROOT}/{script}').external_attr >> 16) & 0o111)

    def test_source_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fake_source(root)
            (root / "app.py").rename(root / "app-original.py")
            (root / "app.py").symlink_to(root / "app-original.py")
            with self.assertRaisesRegex(ValueError, "符号链接"):
                package.source_files(root)

    def test_existing_version_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "dist" / "existing"
            destination.mkdir(parents=True)
            marker = destination / "keep.txt"
            marker.write_text("keep")
            with self.assertRaises(FileExistsError):
                package.build(root, destination)
            self.assertEqual(marker.read_text(), "keep")

    def test_manifest_cannot_bless_unknown_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "bad.zip"
            name, content = f"{package.ZIP_ROOT}/credentials.json", b"secret"
            manifest = {"files": [{"path": name, "size": len(content), "sha256": package.digest(content)}]}
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(name, content)
                bundle.writestr(f"{package.ZIP_ROOT}/PACKAGE-MANIFEST.json", json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "白名单外"):
                package.verify_zip(archive)


if __name__ == "__main__":
    unittest.main()
