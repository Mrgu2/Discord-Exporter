"""Validate the same Discord account before committing an SSH-carried login."""
import os
from .collector import DiscordClient, DiscordAPIError, AuthRequired


def bind_connection(credentials, worker, credential, expected_user_id, client_factory=DiscordClient):
    if not isinstance(credential,str) or not 16<=len(credential)<=4096 or any(c.isspace() for c in credential):
        raise ValueError('连接数据无效，未保存')
    if not isinstance(expected_user_id,str) or not expected_user_id.isdigit():
        raise ValueError('缺少已验证的本机账号身份，未保存')
    override=os.environ.get('DISCORD_ARCHIVE_TOKEN')
    if override and override.strip()!=credential:
        raise ValueError('服务使用另一份环境变量连接，请先移除该覆盖配置')
    try:
        identity=client_factory(credential).get('/users/@me')
    except (DiscordAPIError,OSError,ValueError):
        raise ValueError('服务器未能验证本机连接，未保存；请检查服务器网络或账号验证状态') from None
    if not isinstance(identity,dict) or str(identity.get('id',''))!=expected_user_id:
        raise ValueError('服务器与本机验证的账号不一致，未保存')
    previous=credentials.get('discord')
    if previous and previous!=credential:
        try:
            old=client_factory(previous).get('/users/@me')
        except AuthRequired:
            old=worker.state.get('browser_account') or {}
        except (DiscordAPIError,OSError,ValueError):
            raise ValueError('无法确认服务器已有账号，未覆盖原连接') from None
        if not isinstance(old,dict) or str(old.get('id',''))!=expected_user_id:
            raise ValueError('服务器已有另一账号，未覆盖；请先在服务器确认断开原连接')
    with worker.lock:
        if credentials.get('discord')!=previous:
            raise ValueError('服务器连接刚刚发生变化，请刷新后重试；未覆盖原连接')
        if worker.draining or worker.state.get('active_job') or not worker.jobs.empty():
            raise ValueError('请等待当前任务或备用登录窗口结束后再绑定')
        worker.set_automatic_paused(True)
        backend=credentials.set('discord',credential)
        worker.state.update(browser_connected=True,browser_account={
            'id':expected_user_id,'name':str(identity.get('global_name') or identity.get('username') or 'Discord 用户')[:100]},
            requires_attention=False,last_error=None)
        worker.persist()
    return {'ok':True,'user_id':expected_user_id,'backend':backend,'automatic_paused':True}
