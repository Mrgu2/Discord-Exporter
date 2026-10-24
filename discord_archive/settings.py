"""Private local settings; credentials never enter version control or responses."""
import copy
import json
import os
import re
import secrets
import subprocess
import threading
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo
from .export_schedule import AUTO_EXPORT_DEFAULTS, normalize_auto_export

DEFAULT_CONFIG = {
    'channels': [],
    'target_author_id': '',
    'target_message_url': '',
    'market_timezone': 'America/New_York', 'timezone': 'auto', 'day_boundary_hour': 4,
    'schedule': {'enabled': True, 'interval_minutes': 360, 'times': [], 'timezone': 'America/New_York',
        'window': {'enabled': True, 'start': '15:50', 'end': '16:10', 'every_minutes': 5, 'weekdays': [0, 1, 2, 3, 4]}},
    'model': {'enabled': False, 'base_url': '', 'model': ''},
    'download_media': True,
    'speech': {'enabled': True, 'language': 'zh', 'model_path': '', 'python': ''},
    'export': {'name_prefix': '答疑存档', 'date_format': 'YYYY-MM-DD',
        'sequence_digits': 2, 'separator': '-', 'copy_directory': ''},
    'auto_export': copy.deepcopy(AUTO_EXPORT_DEFAULTS),
}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def message_location(value):
    found = re.search(r'(?:https://)?(?:www\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)', value or '')
    return found.groups() if found else None


def normalize_export_preferences(value=None, *, validate_directory=True):
    """Validate export options without creating directories or moving files."""
    if value is None:
        value = {}
    if not isinstance(value,dict):
        raise ValueError('导出设置须为对象')
    result = {key:value.get(key,default) for key,default in DEFAULT_CONFIG['export'].items()}
    prefix = result['name_prefix']
    if (not isinstance(prefix,str) or any(unicodedata.category(character).startswith('C') for character in prefix)
            or re.search(r'[/\\:<>"|?*]',prefix)):
        raise ValueError('文件名前缀不能包含路径或控制字符')
    prefix = unicodedata.normalize('NFC',prefix).strip()
    if not prefix or len(prefix) > 40:
        raise ValueError('文件名前缀须为 1 到 40 个字符')
    result['name_prefix'] = prefix
    if result['date_format'] not in ('YYYY-MM-DD','YYYYMMDD'):
        raise ValueError('日期格式须为 YYYY-MM-DD 或 YYYYMMDD')
    if type(result['sequence_digits']) is not int or result['sequence_digits'] not in (2,3,4):
        raise ValueError('序号位数须为 2、3 或 4')
    if result['separator'] not in ('-','_'):
        raise ValueError('文件名分隔符须为 - 或 _')
    directory = result['copy_directory']
    if not isinstance(directory,str) or any(unicodedata.category(character).startswith('C') for character in directory):
        raise ValueError('导出目录须为不含控制字符的路径')
    directory = directory.strip()
    if directory:
        try:
            path = Path(directory).expanduser()
        except (RuntimeError,ValueError) as exc:
            raise ValueError('无法展开导出目录，请填写本机绝对路径') from exc
        if not path.is_absolute():
            raise ValueError('导出目录须为本机绝对路径或以 ~ 开头的路径')
        if validate_directory:
            try:
                if (path.exists() or path.is_symlink()) and not path.is_dir():
                    raise ValueError('导出目录不能指向现有文件')
            except OSError as exc:
                raise ValueError('无法检查导出目录，请检查本机路径权限') from exc
        directory = str(path)
    result['copy_directory'] = directory
    return result


class Settings:
    def __init__(self, root):
        self.root, self.lock = Path(root), threading.RLock()
        self.path = self.root / 'data' / 'config.json'
        if not self.path.exists():
            atomic_json(self.path, DEFAULT_CONFIG)

    def read(self):
        with self.lock:
            value = json.loads(self.path.read_text())
            if not isinstance(value,dict):
                raise ValueError('配置文件须为对象')
            saved_export = value.get('export',{})
            if not isinstance(saved_export,dict):
                raise ValueError('导出设置须为对象')
            value['export'] = normalize_export_preferences(saved_export,validate_directory=False)
            value['auto_export'] = normalize_auto_export(value.get('auto_export',{}))
            return value

    def update(self, incoming):
        with self.lock:
            if not isinstance(incoming,dict):
                raise ValueError('设置须为对象')
            value = self.read()
            old_link = value.get('target_message_url', '')
            old_author = str(value.get('target_author_id') or '')
            allowed = set(DEFAULT_CONFIG)
            for key, content in incoming.items():
                if key in allowed:
                    if key == 'export':
                        if not isinstance(content,dict):
                            raise ValueError('导出设置须为对象')
                        value[key] = {**value['export'],**content}
                    elif key == 'auto_export':
                        if not isinstance(content,dict):
                            raise ValueError('自动导出设置须为对象')
                        value[key] = {**value['auto_export'],**content}
                    else:
                        value[key] = content
            value['export'] = normalize_export_preferences(value['export'])
            value['auto_export'] = normalize_auto_export(value['auto_export'])
            if value['auto_export']['enabled'] and not value['export']['copy_directory']:
                raise ValueError('开启定时出稿前，请先在 Mac 上设置自动另存目录')
            if (incoming.get('target_message_url')
                    and incoming['target_message_url'] != old_link
                    and str(incoming.get('target_author_id') or old_author) == old_author):
                # The author inferred from the old example must not silently
                # survive selection of a different speaker's example link.
                value['target_author_id'] = ''
            if value['timezone'] != 'auto':
                ZoneInfo(value['timezone'])
            ZoneInfo(value['market_timezone'])
            schedule = value['schedule']
            ZoneInfo(schedule.get('timezone', value['market_timezone']))
            schedule['interval_minutes'] = max(1, min(1440, int(schedule.get('interval_minutes', 360))))
            from .scheduler import _minute
            for clock in schedule.get('times', []):
                _minute(clock)
            window = schedule.get('window', {})
            for key, fallback in [('start', '15:50'), ('end', '16:10')]:
                _minute(window.get(key, fallback))
            window['every_minutes'] = max(1, min(60, int(window.get('every_minutes', 5))))
            if not 0 <= int(value['day_boundary_hour']) <= 23:
                raise ValueError('交易日分界须为0到23点')
            normalized = []
            for row in value['channels']:
                identity = str(row.get('id', '') if isinstance(row, dict) else row).strip()
                location = message_location(identity)
                identity = location[1] if location else identity
                if not identity.isdigit():
                    raise ValueError('频道 ID 须为数字或有效消息链接')
                label = row.get('label', '') if isinstance(row, dict) else ''
                kind = row.get('kind', 'qa' if '示例问答' in label else 'feed') if isinstance(row, dict) else 'feed'
                enabled = row.get('enabled', True) is not False if isinstance(row, dict) else True
                normalized.append({'id': identity, 'label': label, 'kind': kind if kind in ('qa', 'feed') else 'feed', 'enabled': enabled})
            value['channels'] = list({row['id']: row for row in normalized}.values())
            author = str(value.get('target_author_id', '')).strip()
            if author and not author.isdigit():
                raise ValueError('群主 ID 须为数字')
            value['target_author_id'] = author
            model = value['model']
            if model.get('base_url') and not re.match(r'^https?://[^\s]+$', model['base_url']):
                raise ValueError('模型地址须为 http 或 https URL')
            atomic_json(self.path, value)
            return copy.deepcopy(value)


class Credentials:
    SERVICE = 'local.discord-answer-archive'

    def __init__(self, root):
        self.path = Path(root) / 'data' / 'credentials.json'

    def get(self, kind):
        environment = os.environ.get('DISCORD_ARCHIVE_TOKEN' if kind == 'discord' else 'ARCHIVE_MODEL_KEY')
        if environment:
            return environment.strip()
        if self.path.exists():
            fallback = json.loads(self.path.read_text()).get(kind)
            if fallback:
                return fallback
        if Path('/usr/bin/security').exists():
            try:
                result = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', self.SERVICE, '-a', kind, '-w'], capture_output=True, text=True, timeout=2)
            except (OSError, subprocess.SubprocessError):
                return None
            if result.returncode == 0:
                return result.stdout.strip()
        return None

    def set(self, kind, value):
        if kind not in ('discord', 'model') or not isinstance(value, str) or not value.strip():
            raise ValueError('凭证类型或内容无效')
        value = value.strip()
        if '\n' in value or '\r' in value:
            raise ValueError('凭证包含意外换行')
        if Path('/usr/bin/security').exists():
            try:
                result = subprocess.run(['/usr/bin/security', 'add-generic-password', '-U', '-s', self.SERVICE, '-a', kind, '-w', value], capture_output=True, timeout=12)
                saved = result.returncode == 0
            except (OSError, subprocess.SubprocessError):
                saved = False
            if saved:
                # A previous portable fallback takes precedence in get(). Once
                # this value reaches Keychain, remove only its stale fallback
                # entry; preserve the file and any other credential kind.
                if self.path.exists():
                    existing = json.loads(self.path.read_text())
                    if kind in existing:
                        existing.pop(kind)
                        atomic_json(self.path, existing)
                return 'keychain'
        # Portable fallback stays private and ignored by Git. It is only used
        # when the OS keychain is unavailable, never silently returned to UI.
        existing = json.loads(self.path.read_text()) if self.path.exists() else {}
        existing[kind] = value
        atomic_json(self.path, existing)
        return 'private_file'


def access_code(root):
    path = Path(root) / 'data' / 'access-code.txt'
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_urlsafe(18))
    return path.read_text().strip()
