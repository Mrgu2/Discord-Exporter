"""Public delivery preferences; transport credentials live in Credentials."""
import copy
import re

CHANNELS = ('email', 'telegram', 'discord', 'clawbot')
DEFAULT_DELIVERY = {
    'email': {'enabled': False, 'host': '', 'port': 465, 'security': 'ssl',
              'username': '', 'sender': '', 'recipients': []},
    'telegram': {'enabled': False, 'chat_id': ''},
    'discord': {'enabled': False},
    'clawbot': {'enabled': False},
}
SECRET_KINDS = {'email': 'delivery_email', 'telegram': 'delivery_telegram', 'discord': 'delivery_discord', 'clawbot': 'delivery_clawbot'}


def normalize_delivery(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(CHANNELS):
        raise ValueError('推送渠道无效')
    result = copy.deepcopy(DEFAULT_DELIVERY)
    for channel in CHANNELS:
        incoming = value.get(channel, {})
        if not isinstance(incoming, dict) or set(incoming) - set(result[channel]):
            raise ValueError('推送设置包含无效字段；密钥请单独保存')
        result[channel].update(incoming)
        row = result[channel]
        if type(row['enabled']) is not bool:
            raise ValueError('推送开关须为布尔值')
        for key in set(row) - {'enabled', 'port', 'recipients'}:
            if not isinstance(row[key], str):
                raise ValueError('推送字段须为文本')
        for key, item in row.items():
            if isinstance(item, str):
                if len(item) > 320 or any(ord(c) < 32 for c in item):
                    raise ValueError('推送字段不能包含控制字符或过长内容')
                row[key] = item.strip()
        if channel == 'email':
            if type(row['port']) is not int or not 1 <= row['port'] <= 65535:
                raise ValueError('SMTP 端口须为 1 到 65535')
            if row['security'] not in ('ssl', 'starttls'):
                raise ValueError('SMTP 须使用 SSL 或 STARTTLS')
            if not isinstance(row['recipients'], list) or len(row['recipients']) > 20:
                raise ValueError('收件人须为最多 20 个邮箱地址')
            row['recipients'] = list(dict.fromkeys(row['recipients'])) if all(isinstance(x, str) for x in row['recipients']) else row['recipients']
            for address in [row['sender'], *row['recipients']]:
                if not isinstance(address, str) or (address and not re.fullmatch(r'[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+', address)) or len(address) > 254:
                    raise ValueError('请填写有效邮箱地址')
            if any(not x for x in row['recipients']):
                raise ValueError('收件邮箱不能为空')
        if row['enabled']:
            validate_destination(channel, row)
    return result


def validate_destination(channel, row):
    if channel == 'email' and (not row['host'] or not row['sender'] or not row['recipients']):
        raise ValueError('请填写 SMTP 服务器、发件人和收件人')
    if channel == 'telegram' and not re.fullmatch(r'-?\d+|@[A-Za-z0-9_]+', row['chat_id']):
        raise ValueError('请填写 Telegram Chat ID 或频道用户名')
