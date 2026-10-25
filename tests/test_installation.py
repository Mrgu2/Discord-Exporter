import importlib.util
import subprocess
import re
import shutil
import sys
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discord_archive.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('doctor', ROOT / 'scripts/doctor.py')
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)


class InstallationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for actual version-check regression')
    def test_real_node_accepts_supported_version_without_boolean_exit_code(self):
        script = (ROOT / 'scripts/install_mac.sh').read_text()
        expression = re.search(r"if ! node -e '([^']+)'", script).group(1)
        major = int(subprocess.check_output(['node', '-p', 'process.versions.node.split(".")[0]'], text=True))
        completed = subprocess.run(['node', '-e', expression], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0 if major >= 20 else 1, completed.stderr)

    def test_missing_or_invalid_optional_assistant_keeps_local_install_available(self):
        script = (ROOT / 'scripts/install_mac.sh').read_text()
        block = script[script.index('if [[ -f helpers/login-assistant-mac.zip ]]'):script.index("echo '安装检查通过")]
        for invalid in (False, True):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root/'scripts').mkdir()
                shutil.copy2(ROOT/'scripts/install_login_assistants.py', root/'scripts/install_login_assistants.py')
                sentinel = root/'data/config.json'; sentinel.parent.mkdir(); sentinel.write_text('original-config')
                if invalid:
                    (root/'helpers').mkdir(); (root/'helpers/login-assistant-mac.zip').write_text('not-a-zip')
                result = subprocess.run(['bash', '-eu', '-c', 'selected_python='+shlex.quote(sys.executable)+'\n'+block+'\necho LOCAL_INSTALL_CONTINUES'], cwd=root, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('LOCAL_INSTALL_CONTINUES', result.stdout)
                self.assertEqual(sentinel.read_text(), 'original-config')
                self.assertFalse((root/'.local/login-assistants/login-assistant-mac.zip').exists())

    def test_first_install_has_no_private_configuration_and_speech_is_opt_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Settings(temporary).read()
            self.assertEqual(config['channels'], [])
            self.assertEqual(config['target_author_id'], '')
            self.assertFalse(config['speech']['enabled'])
            self.assertEqual(config['export']['name_prefix'], '答疑存档')
            self.assertFalse((Path(temporary) / 'data/credentials.json').exists())

    def test_doctor_missing_node_does_not_run_browser(self):
        with patch.object(doctor.shutil, 'which', return_value=None), \
             patch.object(doctor.subprocess, 'run') as run:
            self.assertIn('缺少 Node.js', doctor.check(ROOT)[0])
            run.assert_not_called()

    def test_doctor_rejects_old_node_before_launch(self):
        with patch.object(doctor.shutil, 'which', return_value='/node'), \
             patch.object(doctor.subprocess, 'check_output', return_value='18.0.0'), \
             patch.object(doctor.subprocess, 'run') as run:
            self.assertIn('Node.js 20', doctor.check(ROOT)[0])
            run.assert_not_called()

    def test_browser_failure_is_reported_not_success(self):
        with patch.object(doctor.shutil, 'which', return_value='/node'), \
             patch.object(doctor.subprocess, 'check_output', return_value='22.0.0'), \
             patch.object(doctor.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '缺少项目浏览器工具')):
            self.assertEqual(doctor.check(ROOT), ['缺少项目浏览器工具'])

    def test_installed_environment_passes_only_after_browser_check(self):
        with patch.object(doctor.shutil, 'which', return_value='/node'), \
             patch.object(doctor.subprocess, 'check_output', return_value='22.0.0'), \
             patch.object(doctor.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            self.assertEqual(doctor.check(ROOT), [])
            self.assertIn('check_browser.mjs', run.call_args.args[0][1])


if __name__ == '__main__':
    unittest.main()
