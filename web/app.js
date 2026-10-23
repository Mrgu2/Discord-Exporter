/* This page keeps credentials only in the input until the server saves them. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const statusNames = { queued: '排队中', pending: '等待中', running: '进行中', capturing: '保存中', drafting: '整理中', rendering: '生成长图中', ready: '已完成', completed: '已完成', complete: '已完成', success: '已完成', succeeded: '已完成', failed: '失败', error: '失败', partial: '部分完成', cancelled: '已取消' };
  const busyStatuses = new Set(['queued', 'pending', 'running', 'capturing', 'drafting', 'rendering']);
  let snapshot = null;
  let publicConfig = {};
  let configInitialized = false;
  let settingsDirty = false;
  let fetching = false;
  let toastTimer;
  let serviceFailedAt = null;
  let pendingAction = null;
  let lastDraftSignature = '';
  let currentView = 'workspace';
  let draftSearch = '';
  let renderPending = new Set();
  let remoteRenderJobs = [];
  let lastJobSeen = null;
  let draftDatesTouched = false;
  let savingChannels = false;
  let loginRequired = false;
  const isLocal = ['localhost', '127.0.0.1', '::1', '[::1]'].includes(location.hostname);
  function displayTimezone() { return publicConfig.timezone && publicConfig.timezone !== 'auto' ? publicConfig.timezone : Intl.DateTimeFormat().resolvedOptions().timeZone; }

  function node(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined && text !== null) item.textContent = String(text);
    return item;
  }
  function first(...values) { return values.find((value) => value !== undefined && value !== null && value !== ''); }
  function dateValue(value) {
    if (value === undefined || value === null || value === '') return null;
    const parsed = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
    return Number.isFinite(parsed.getTime()) ? parsed : null;
  }
  function dateTime(value, short = false) {
    const parsed = dateValue(value);
    if (!parsed) return '—';
    const options = short ? { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false } : { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false };
    try { return new Intl.DateTimeFormat('zh-CN', { ...options, timeZone: displayTimezone() }).format(parsed); }
    catch { return new Intl.DateTimeFormat('zh-CN', options).format(parsed); }
  }
  function dateOnly(value = new Date()) {
    try { return new Intl.DateTimeFormat('en-CA', { timeZone: publicConfig.market_timezone || 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(value); }
    catch { return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`; }
  }
  function elapsed(value) {
    const parsed = dateValue(value);
    if (!parsed) return '—';
    return duration(Math.max(0, (Date.now() - parsed.getTime()) / 1000));
  }
  function duration(seconds) {
    if (!Number.isFinite(Number(seconds))) return '—';
    seconds = Math.max(0, Number(seconds));
    if (seconds < 60) return '不足 1 分钟';
    if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
    const hours = Math.floor(seconds / 3600);
    return `${hours} 小时${Math.floor(seconds % 3600 / 60) ? ` ${Math.floor(seconds % 3600 / 60)} 分钟` : ''}`;
  }
  function relative(value) {
    const parsed = dateValue(value);
    return parsed ? `${elapsed(value)}前` : '—';
  }
  function number(value) { return value === undefined || value === null ? '—' : Number.isFinite(Number(value)) ? new Intl.NumberFormat('zh-CN').format(Number(value)) : String(value); }
  function text(id, value) { $(id).textContent = value; }
  function showToast(message, isError = false) {
    clearTimeout(toastTimer);
    const toast = $('toast');
    toast.textContent = message;
    toast.classList.toggle('error', isError);
    toast.hidden = false;
    toastTimer = setTimeout(() => { toast.hidden = true; }, isError ? 8500 : 4500);
  }
  async function api(path, options = {}) {
    const mutation = options.method && !['GET', 'HEAD'].includes(options.method.toUpperCase());
    const csrfKey = document.querySelector('meta[name="archive-key"]')?.content;
    const response = await fetch(path, { cache: 'no-store', credentials: 'same-origin', ...options, headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(mutation && csrfKey ? { 'X-Archive-Key': csrfKey } : {}), ...options.headers } });
    let body;
    try { body = await response.json(); } catch { body = null; }
    if (response.status === 401 && path !== '/api/login') { loginRequired = true; $('login-overlay').hidden = false; document.querySelector('.app-shell').inert = true; $('access-code').focus(); }
    if (!response.ok) { const error = new Error(body?.error?.message || (typeof body?.error === 'string' ? body.error : null) || body?.message || `请求失败（${response.status}）`); error.status = response.status; throw error; }
    return body || {};
  }
  async function post(path, body) { return api(path, { method: 'POST', body: JSON.stringify(body) }); }
  function setView(view, changeHash = true) {
    if (!['workspace', 'library', 'settings'].includes(view)) view = 'workspace';
    if (view === 'settings') { $('advanced-settings').open = true; view = currentView === 'library' ? 'library' : 'workspace'; }
    currentView = view;
    for (const candidate of ['workspace', 'library']) $(`${candidate}-view`).hidden = candidate !== view;
    document.querySelectorAll('[data-view]').forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
    text('page-title', { workspace: '工作台', library: '我的稿件' }[view]);
    text('page-eyebrow', { workspace: '工作台', library: '本地资料', settings: '本机配置' }[view]);
    if (changeHash && location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
    if (view === 'library' && snapshot) renderDrafts(true);
  }
  function hydrateConfig(config) {
    publicConfig = config || {};
    if (settingsDirty && configInitialized) return;
    const schedule = publicConfig.schedule || {};
    const model = publicConfig.model || {};
    $('channels').value = (publicConfig.channels || []).map((channel) => typeof channel === 'string' ? channel : `${channel.id || ''}${channel.label ? ` ${channel.label}` : ''}`).join('\n');
    $('target-author').value = publicConfig.target_author_id || '';
    $('target-message-url').value = publicConfig.target_message_url || '';
    $('schedule-enabled').checked = Boolean(schedule.enabled);
    $('interval').value = schedule.interval_minutes || 360;
    $('times').value = Array.isArray(schedule.times) ? schedule.times.join(', ') : schedule.times || '';
    const displayZone = publicConfig.timezone || 'auto';
    if (![...$('timezone').options].some((option) => option.value === displayZone)) {
      const option = node('option', '', '当前自定义时区'); option.value = displayZone; $('timezone').append(option);
    }
    $('timezone').value = displayZone;
    $('market-timezone').value = publicConfig.market_timezone || 'America/New_York';
    $('day-boundary').value = publicConfig.day_boundary_hour ?? 4;
    $('window-enabled').checked = schedule.window?.enabled ?? true;
    $('window-start').value = schedule.window?.start || '15:50';
    $('window-end').value = schedule.window?.end || '16:10';
    const windowStart = $('window-start').value.split(':').map(Number);
    const windowEnd = $('window-end').value.split(':').map(Number);
    $('window-before').value = Math.max(0, 16 * 60 - (windowStart[0] * 60 + windowStart[1]));
    $('window-after').value = Math.max(0, windowEnd[0] * 60 + windowEnd[1] - 16 * 60);
    $('window-every').value = schedule.window?.every_minutes || 5;
    $('model-enabled').checked = Boolean(model.enabled);
    $('model-base-url').value = model.base_url || '';
    $('model-name').value = model.model || '';
    if (!configInitialized) $('draft-mode').value = 'evidence';
    configInitialized = true;
  }
  function renderState(data) {
    remoteRenderJobs = data.state?.render_jobs || [];
    snapshot = data;
    const config = data.config || publicConfig;
    hydrateConfig(config);
    const state = data.state || {};
    if (state.market_day && !draftDatesTouched) {
      for (const id of ['draft-date', 'draft-start', 'draft-end']) $(id).value = state.market_day;
    }
    const connectivity = data.connectivity || state.connectivity || {};
    const archive = data.archive || {};
    const credentials = data.credentials || state.credentials || {};
    const runs = Array.isArray(data.runs) ? data.runs : [];
    const drafts = Array.isArray(data.drafts) ? data.drafts : [];
    const successRun = runs.find((run) => ['success', 'succeeded', 'completed', 'complete', 'partial'].includes(run.status));
    const lastSuccess = first(state.last_success_at, state.last_capture_success_at, state.last_success, state.last_capture_at, connectivity.last_success_at, successRun?.finished_at, successRun?.completed_at);
    const currentJob = first(state.active_job, state.current_job, data.active_job);
    const runningRun = runs.find((run) => busyStatuses.has(run.status));
    const busy = Boolean(currentJob || state.running || state.capture_running || runningRun || pendingAction || state.queue_length);
    const discordCredential = first(credentials.discord, credentials.has_discord, state.has_discord_token, config.discord_token_configured);
    const modelCredential = first(credentials.model, credentials.has_model, state.has_model_key, config.model_key_configured);
    const allChannels = Array.isArray(config.channels) ? config.channels : [];
    const channels = allChannels.filter((channel) => typeof channel === 'string' || channel.enabled !== false);
    const configured = Boolean(channels.length && (config.target_author_id || config.target_message_url) && discordCredential !== false);
    $('setup-alert').hidden = true;
    text('capture-badge', busy ? '正在处理' : `${channels.length} 个已选`);
    $('capture-button').disabled = busy || !channels.length || discordCredential === false;
    $('draft-button').disabled = busy || !channels.length || archive.message_count === 0 || ($('draft-layout').value === 'qa' && !(config.target_author_id || config.target_message_url));
    $('active-job').hidden = !busy;
    let jobText = typeof currentJob === 'string' ? currentJob : first(currentJob?.message, currentJob?.detail, state.progress_message, runningRun?.message, runningRun?.progress, currentJob?.type && statusNames[currentJob.type]);
    if (typeof jobText === 'object') jobText = null;
    text('active-job-text', jobText || (pendingAction === 'draft' ? '正在生成稿件，完成后会出现在下方。' : state.queue_length ? `有 ${state.queue_length} 个任务正在等待处理。` : '正在处理任务，可以继续查看记录。'));
    $('capture-hint').hidden = !busy;
    text('capture-hint', busy ? '任务在后台继续运行' : '');
    renderChannels(allChannels);
    text('last-success', lastSuccess ? dateTime(lastSuccess, true) : '尚未保存');
    text('last-success-detail', lastSuccess ? `${relative(lastSuccess)} · ${displayTimezone()}` : '保存成功后在这里显示');
    const next = first(state.next_capture_at, state.next_run_at, state.next_scheduled_at, data.next_capture_at, config.schedule?.next_run_at);
    text('next-capture', config.schedule?.enabled ? discordCredential === false ? '连接后开始' : next ? dateTime(next, true) : '等待下一轮' : '未启用');
    const fixedTimes = Array.isArray(config.schedule?.times) ? config.schedule.times.join('、') : config.schedule?.times;
    text('schedule-detail', config.schedule?.enabled ? `每 ${config.schedule.interval_minutes || 360} 分钟${fixedTimes ? ` · ${fixedTimes}` : ''}${config.schedule.window?.enabled ? ' · 尾盘密集保存' : ''} · 跟随美股交易时间` : '仍可随时手动保存');
    const connected = first(connectivity.online, connectivity.connected, state.online);
    const isOffline = connected === false || Boolean(connectivity.offline_since || state.offline_since);
    const hasConnectionData = connected !== undefined || connectivity.offline_since || connectivity.last_online_at || state.last_online_at;
    const needsAttention = first(connectivity.requires_attention, state.requires_attention);
    const connectingBrowser = pendingAction === 'connect' || ['connect_browser', 'connect-browser', 'connect', 'browser-connect'].includes(currentJob?.type);
    const browserConnected = first(state.browser_connected, data.browser_connected);
    const connectionLabel = connectingBrowser ? '正在连接 Discord…' : needsAttention ? '需要重新连接' : isOffline ? '暂时离线' : hasConnectionData || browserConnected ? '已连接' : discordCredential === false ? '还未连接 Discord' : '账号已准备好';
    const indicator = node('span', `status-dot${isOffline || needsAttention ? ' error' : !hasConnectionData ? ' pending' : ''}`);
    $('connection-state').replaceChildren(indicator, document.createTextNode(connectionLabel));
    text('connection-detail', connectingBrowser ? '请在打开的窗口中登录 Discord，完成后会自动识别。' : needsAttention ? '请在常开 Mac 上重新连接账号。' : isOffline ? `距上次成功保存 ${lastSuccess ? elapsed(lastSuccess) : '尚无记录'}，网络恢复后会自动重试。` : hasConnectionData || browserConnected ? '可以保存对话，也可以从已有内容生成稿件。' : discordCredential === false ? isLocal ? '首次会打开登录窗口，无需填写密钥。' : '请先在常开 Mac 上连接 Discord。' : '可以开始保存，保存成功后自动追踪更新。');
    $('connection-detail').hidden = !(connectingBrowser || needsAttention || isOffline || discordCredential === false);
    $('connect-browser-button').disabled = busy || !isLocal;
    $('connect-browser-button').querySelector('span').textContent = !isLocal ? '请在 Mac 上连接' : connectingBrowser ? '正在连接…' : discordCredential ? '重新连接 Discord' : '连接 Discord';
    const offlineSince = first(connectivity.offline_since, state.offline_since);
    const offlineSeconds = first(connectivity.offline_seconds, state.offline_seconds);
    text('offline-duration', lastSuccess ? elapsed(lastSuccess) : offlineSeconds !== undefined ? duration(offlineSeconds) : offlineSince ? elapsed(offlineSince) : '尚无成功记录');
    const retryAt = first(connectivity.retry_at, connectivity.next_retry_at, state.retry_at, state.next_retry_at);
    const retrySeconds = first(connectivity.retry_in_seconds, state.retry_in_seconds);
    text('retry-countdown', needsAttention ? '需要本机处理' : retryAt ? countdown(retryAt) : retrySeconds !== undefined ? duration(retrySeconds) : isOffline ? '等待自动重试' : '无需重试');
    const gapHours = first(connectivity.gap_hours, archive.gap_hours, state.gap_hours);
    const gaps = first(archive.gaps, state.gaps, connectivity.gaps);
    const gapSeconds = first(connectivity.gap_seconds, state.gap_seconds);
    const continuityRisk = first(connectivity.possible_retention_loss, archive.possible_retention_loss, state.possible_retention_loss);
    text('capture-gap', !lastSuccess ? '尚未建立基线' : Number(archive.coverage_gap_count) > 0 ? `${archive.coverage_gap_count} 段留存风险待核对` : continuityRisk === true || Number(gapHours) >= 48 ? '可能跨过清理周期' : continuityRisk === false ? '未发现清理周期风险' : gapHours !== undefined ? Number(gapHours) === 0 ? '无' : `${Number(gapHours).toFixed(1)} 小时待核对` : gapSeconds !== undefined ? `${duration(gapSeconds)}待核对` : Array.isArray(gaps) ? `${gaps.length} 段待核对` : gaps !== undefined ? String(gaps) : '尚未检测');
    const attachmentFailures = first(archive.attachment_failures, archive.failed_attachments, state.attachment_failures, connectivity.attachment_failures);
    text('attachment-failures', attachmentFailures === undefined ? '—' : `${number(Array.isArray(attachmentFailures) ? attachmentFailures.length : attachmentFailures)} 个`);
    text('recovery-state', needsAttention ? '自动重试暂停，请处理凭证或频道权限' : busy && first(state.backfilling, connectivity.backfilling) ? '正在补采断线期间的消息' : isOffline ? '保存暂停，服务会持续重试' : lastSuccess ? '保存记录已更新，等待下一轮' : '首次保存后开始追踪连续性');
    const lastError = first(state.last_job_error, connectivity.last_error, state.last_error, data.last_error, state.target_resolution_warning, state.last_warning);
    $('last-error').hidden = !lastError;
    if (lastError) text('last-error', typeof lastError === 'string' ? lastError : lastError.message || '上一轮未成功，请查看保存记录。');
    text('archive-messages', number(first(archive.message_count, archive.messages, archive.total_messages, state.message_count)));
    text('archive-channels', number(first(archive.channel_count, archive.channels_count, Array.isArray(archive.channels) ? archive.channels.length : undefined, channels.length)));
    text('archive-attachments', number(first(archive.attachment_count, archive.attachments, archive.total_attachments, archive.media?.saved)));
    text('archive-drafts', number(drafts.length));
    text('draft-count', String(drafts.length));
    text('day-boundary-help', '按美股交易日期归档，跨午夜的答疑也能放在同一交易日。');
    updateMode();
    const storageName = {keychain:'钥匙串',private_file:'本机受限文件'}[state.browser_account?.credential_backend];
    text('discord-credential-status', discordCredential === undefined ? '未检测' : discordCredential ? `已保存${storageName ? ` · ${storageName}` : ''}` : '未配置');
    text('model-credential-status', modelCredential === undefined ? '未检测' : modelCredential ? '已保存' : '未配置');
    text('service-caption', '本机运行中');
    renderRemote(data.remote || {});
    text('last-updated', `状态更新于 ${dateTime(new Date(), true)}`);
    renderDrafts();
    renderRuns(runs);
    updateDraftOptionsLabel();
    const observedJob = currentJob?.id;
    if (observedJob) lastJobSeen = observedJob;
    else if (lastJobSeen && state.last_job_status) {
      showToast(state.last_job_status === 'failed' ? state.last_job_error || '任务未成功，请查看状态说明。' : '任务已完成，记录已更新。', state.last_job_status === 'failed');
      lastJobSeen = null;
    }
  }
  function renderChannels(channels) {
    if (savingChannels || $('channel-list').contains(document.activeElement)) return;
    $('channel-list').replaceChildren(...(channels.length ? channels.map((channel) => {
      const row = typeof channel === 'string' ? { id: channel, label: '' } : channel;
      const label = node('label', 'channel-option');
      const input = document.createElement('input'); input.type = 'checkbox'; input.checked = row.enabled !== false;
      input.setAttribute('aria-label', row.label || '未命名频道');
      input.addEventListener('change', () => updateChannel(row.id, input.checked));
      label.append(input, node('span', '', row.label || '未命名频道')); return label;
    }) : [node('span', 'muted', '尚未添加频道，可在高级设置中添加。')]));
  }
  async function updateChannel(id, enabled) {
    if (savingChannels) return;
    savingChannels = true;
    $('channel-list').querySelectorAll('input').forEach((input) => { input.disabled = true; });
    try {
      const config = { ...publicConfig, channels: (publicConfig.channels || []).map((channel) => typeof channel === 'object' && String(channel.id) === String(id) ? { ...channel, enabled } : channel) };
      const result = await api('/api/config', { method: 'PUT', body: JSON.stringify(config) });
      publicConfig = result.config || result;
    } catch (error) { showToast(error.message, true); }
    finally { savingChannels = false; document.activeElement?.blur(); await refresh(); }
  }
  async function connectBrowser() {
    if (!isLocal) return;
    pendingAction = 'connect';
    $('connect-browser-button').disabled = true;
    $('connect-browser-button').querySelector('span').textContent = '正在连接…';
    try { await post('/api/connect-browser', {}); showToast('登录窗口正在打开，请完成 Discord 登录。'); }
    catch (error) { showToast(error.message, true); }
    finally { pendingAction = null; await refresh(); }
  }
  function updateDraftOptionsLabel() {
    const scope = document.querySelector('input[name="scope"]:checked').value;
    const layout = $('draft-layout').value;
    text('draft-options-label', `${{ latest: '最近一轮', day: '整个交易日', range: '自选日期' }[scope]} · ${{ stacked: '上下分区拼图', horizontal: '左右分区高清图', collage: '自动拼版', board: '四栏拼版', qa: '独立问答页' }[layout]}`);
  }
  function setupDisclosureMotion() {
    const animations = new WeakMap();
    document.querySelectorAll('details').forEach((details) => {
      const summary = details.querySelector(':scope > summary');
      if (!summary) return;
      summary.addEventListener('click', (event) => {
        if (event.defaultPrevented || event.target.closest('a,button,input,select,textarea')) return;
        event.preventDefault();
        const previous = animations.get(details);
        const shouldOpen = previous ? !previous.shouldOpen : !details.open;
        const startHeight = details.getBoundingClientRect().height;
        previous?.animation.cancel();
        if (matchMedia('(prefers-reduced-motion: reduce)').matches || !details.animate) {
          details.open = shouldOpen;
          details.style.height = '';
          details.style.overflow = '';
          animations.delete(details);
          return;
        }
        details.style.height = '';
        details.open = true;
        const style = getComputedStyle(details);
        const inset = ['paddingTop', 'paddingBottom', 'borderTopWidth', 'borderBottomWidth'].reduce((sum, key) => sum + (parseFloat(style[key]) || 0), 0);
        const endHeight = shouldOpen ? details.getBoundingClientRect().height : summary.getBoundingClientRect().height + inset;
        details.style.overflow = 'hidden';
        const duration = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--duration-disclosure')) || 200;
        const animation = details.animate([{ height: `${startHeight}px` }, { height: `${endHeight}px` }], { duration, easing: 'cubic-bezier(.2,.7,.2,1)' });
        const record = { animation, shouldOpen };
        animations.set(details, record);
        animation.onfinish = () => {
          if (animations.get(details) !== record) return;
          details.open = shouldOpen;
          details.style.height = '';
          details.style.overflow = '';
          animations.delete(details);
        };
      });
    });
  }
  function updateMode() {
    const model = $('draft-mode').value === 'model';
    $('generation-mode').replaceChildren(node('span', `status-dot${model ? '' : ' pending'}`), document.createTextNode(model ? `模型整理${publicConfig.model?.model ? ` · ${publicConfig.model.model}` : ''}` : '本地证据稿'));
  }
  function renderRemote(remote) {
    $('credentials-section').hidden = !isLocal;
    $('remote-phone-note').hidden = isLocal;
    const urls = Array.isArray(remote.urls) ? remote.urls : [];
    const safeURLs = urls.filter((value) => {
      try { const parsed = new URL(typeof value === 'string' ? value : value.url); return ['http:', 'https:'].includes(parsed.protocol); } catch { return false; }
    });
    $('remote-urls').replaceChildren(...(safeURLs.length ? safeURLs.map((value) => {
      const url = typeof value === 'string' ? value : value.url;
      const link = node('a', 'remote-link', url); link.href = url; link.target = '_blank'; link.rel = 'noopener'; return link;
    }) : [node('p', 'form-help', '尚无局域网地址。请确认这台 Mac 已连接网络并启用局域网访问。')]));
    $('remote-code-block').hidden = !isLocal || !remote.access_code;
    text('remote-code', isLocal && remote.access_code ? remote.access_code : '');
  }
  function countdown(value) {
    const parsed = dateValue(value);
    if (!parsed) return '等待重试';
    const seconds = Math.max(0, Math.ceil((parsed.getTime() - Date.now()) / 1000));
    if (seconds <= 0) return '即将重试';
    return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
  }
  function getDraftId(draft) { return String(first(draft.id, draft.draft_id, '')); }
  function draftURL(draft) {
    const id = getDraftId(draft);
    return id ? `/drafts/${encodeURIComponent(id)}/` : null;
  }
  function draftRow(draft) {
    const row = node('article', 'draft-row');
    const mark = node('span', 'document-icon');
    mark.setAttribute('aria-hidden', 'true');
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    icon.setAttribute('viewBox', '0 0 24 24');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M5 3h10l4 4v14H5zM14 3v5h5M9 12h6M9 16h6');
    icon.append(path); mark.append(icon); row.append(mark);
    const info = node('div', 'draft-info');
    const title = node('div', 'draft-title');
    const titleText = first(draft.title, draft.name, '未命名稿件');
    const url = draftURL(draft);
    const isBusy = busyStatuses.has(draft.status);
    const failed = ['failed', 'error'].includes(draft.status);
    const available = url && !isBusy && !failed;
    if (available) { const link = node('a', '', titleText); link.href = url; link.target = '_blank'; link.rel = 'noopener'; title.append(link); } else title.textContent = titleText;
    const meta = node('div', 'draft-meta');
    meta.append(node('span', '', dateTime(first(draft.created_at, draft.generated_at, draft.timestamp), true)));
    const scopeName = { latest: '最近一轮', day: '交易日', range: '日期范围' }[draft.scope];
    if (scopeName) meta.append(node('span', '', `${scopeName}${draft.date ? ` ${draft.date}` : ''}`));
    const messageCount = first(draft.message_count, draft.source_count, draft.messages_count);
    if (messageCount !== undefined) meta.append(node('span', '', `${number(messageCount)} 条消息`));
    if (draft.mode === 'model') meta.append(node('span', '', '模型整理'));
    if (draft.layout) meta.append(node('span', '', { stacked: '上下分区拼图', horizontal: '左右分区高清图', collage: '自动拼版', board: '四栏拼版', qa: '问答页' }[draft.layout] || draft.layout));
    if (draft.render_scale === 2) meta.append(node('span', '', '2× HiDPI'));
    if (draft.audio?.complete) meta.append(node('span', '', `${draft.audio.complete} 条语音转写`));
    if (Array.isArray(draft.warnings) && draft.warnings.length) meta.append(node('span', 'draft-state', `${draft.warnings.length} 项待核对`));
    if (draft.error) meta.append(node('span', 'draft-state failed', typeof draft.error === 'string' ? draft.error : draft.error.message || '生成失败'));
    info.append(title, meta); row.append(info);
    const actions = node('div', 'draft-actions');
    if (available) {
      const preview = node('a', 'text-button', '打开 ↗'); preview.href = url; preview.target = '_blank'; preview.rel = 'noopener'; actions.append(preview);
      if (draft.manuscript_url) {
        const manuscript = node('a', 'text-button', '文字稿'); manuscript.href = draft.manuscript_url; manuscript.download = ''; actions.append(manuscript);
      }
      const images = Array.isArray(draft.images) ? draft.images : [];
      if (images.length) {
        const viewImages = node('button', 'text-button', '查看长图'); viewImages.type = 'button';
        viewImages.addEventListener('click', () => openPreview(images, draft.title || '稿件长图')); actions.append(viewImages);
        const download = node('a','text-button',images.length === 1 ? '下载高清图' : '下载第 1 张');
        download.href = images[0]; download.download = `${draft.title || '稿件'}-高清.png`; actions.append(download);
      }
      const columns = Array.isArray(draft.single_columns) ? draft.single_columns : [];
      if (columns.length) {
        const readyColumns = columns.filter(column => column.images?.length);
        const viewColumns = node('button', 'text-button', readyColumns.length === columns.length ? '分栏图' : renderBusy(draft,'mobile') ? '分栏图生成中…' : '生成分栏图'); viewColumns.type = 'button';
        viewColumns.disabled = renderBusy(draft,'mobile');
        viewColumns.addEventListener('click', () => readyColumns.length === columns.length
          ? window.ArchivePreview?.openGroups(readyColumns,`${draft.title || '稿件'} · 分栏图`) : renderImage(draft,'mobile')); actions.append(viewColumns);
      }
      const imageReady = Boolean(images.length || first(draft.image_path, draft.long_image_path, draft.image_url, draft.png_path, draft.rendered_at));
      const render = node('button', 'text-button', renderBusy(draft,'main') ? '图片生成中…' : imageReady ? '更新图片' : '生成图片');
      render.type = 'button'; render.disabled = renderBusy(draft,'main'); render.addEventListener('click', () => renderImage(draft)); actions.append(render);
    } else actions.append(node('span', `draft-state${failed ? ' failed' : ''}`, statusNames[draft.status] || draft.status || '准备中'));
    row.append(actions);
    return row;
  }
  function openPreview(images, title) {
    if (window.ArchivePreview?.open) window.ArchivePreview.open(images, title);
    else showToast('图片预览暂未载入，请刷新页面后重试。', true);
  }
  function renderDrafts(force = false) {
    const drafts = Array.isArray(snapshot?.drafts) ? snapshot.drafts : [];
    const signature = JSON.stringify(drafts) + draftSearch + [...renderPending].join(',') + JSON.stringify(remoteRenderJobs);
    if (!force && signature === lastDraftSignature) return;
    lastDraftSignature = signature;
    const recent = drafts.slice(0, 3);
    $('recent-drafts').replaceChildren(...(recent.length ? recent.map(draftRow) : [emptyState('还没有稿件', '先保存一轮对话，再选择范围生成。')]));
    const matches = drafts.filter((draft) => String(first(draft.title, draft.name, '')).toLocaleLowerCase().includes(draftSearch.toLocaleLowerCase()));
    $('all-drafts').replaceChildren(...(matches.length ? matches.map(draftRow) : [emptyState(draftSearch ? '没有找到匹配的稿件' : '还没有稿件', draftSearch ? '试试其他关键词。' : '在“工作台”保存对话，再生成第一份稿件。')]));
  }
  function emptyState(title, detail) { const wrapper = node('div', 'empty-state'); wrapper.append(node('span', '', title), node('small', '', detail)); return wrapper; }
  function renderRuns(runs) {
    text('run-count', `${runs.length} 次`);
    if (!runs.length) { const row = node('tr'); const cell = node('td', '', '还没有保存记录。'); cell.colSpan = 4; row.append(cell); $('run-table').replaceChildren(row); return; }
    $('run-table').replaceChildren(...runs.map((run) => {
      const row = node('tr');
      row.append(node('td', '', dateTime(first(run.started_at, run.created_at, run.timestamp), true)));
      const stateCell = node('td'); const failed = ['failed', 'error'].includes(run.status); const busy = busyStatuses.has(run.status);
      const label = node('span', `run-status${failed ? ' failed' : busy ? ' pending' : ''}`); label.append(node('span', `status-dot${failed ? ' error' : busy ? ' pending' : ''}`), document.createTextNode(statusNames[run.status] || run.status || '未知')); stateCell.append(label); row.append(stateCell);
      row.append(node('td', '', number(first(run.message_count, run.messages, run.new_messages, run.total_messages))));
      const detail = first(run.error, run.message, run.summary, run.detail, run.reason);
      row.append(node('td', '', typeof detail === 'string' ? detail : detail?.message || (busy ? '任务正在后台运行' : '—')));
      return row;
    }));
  }
  async function refresh() {
    if (fetching) return;
    fetching = true;
    try {
      const data = await api('/api/status');
      serviceFailedAt = null;
      $('connection-alert').hidden = true;
      renderState(data);
    } catch (error) {
      if (error.status === 401) { $('connection-alert').hidden = true; return; }
      if (!serviceFailedAt) serviceFailedAt = Date.now();
      $('connection-alert').hidden = false;
      $('connection-alert').textContent = `本地服务连接中断，页面会自动重连。中断时长：${duration((Date.now() - serviceFailedAt) / 1000)}。`;
      text('service-caption', '暂时无法连接本机');
      $('capture-button').disabled = true;
      $('draft-button').disabled = true;
      $('connect-browser-button').disabled = true;
    } finally { fetching = false; }
  }
  function parseChannels(value) {
    const channels = [];
    const seen = new Set();
    for (const line of value.split(/\n|,|，/).map((line) => line.trim()).filter(Boolean)) {
      const link = line.match(/(?:https?:\/\/)?(?:canary\.|ptb\.)?discord(?:app)?\.com\/channels\/(?:\d+|@me)\/(\d+)(?:\/\d+)?/i);
      const match = link || line.match(/^<?#?(\d+)>?(?:\s+(.*))?$/);
      if (!match) throw new Error(`无法识别频道：${line.slice(0, 55)}。请填写频道 ID 或 Discord 消息链接。`);
      const id = match[1];
      if (!seen.has(id)) {
        const previous = (publicConfig.channels || []).find((channel) => typeof channel === 'object' && String(channel.id) === id) || {};
        channels.push({ ...previous, id, label: !link && match[2] ? match[2].trim() : previous.label || '' }); seen.add(id);
      }
    }
    if (!channels.length) throw new Error('至少填写一个频道。');
    return channels;
  }
  function parseTimes(value) {
    const times = value.split(/[,，\s]+/).filter(Boolean);
    return [...new Set(times.map((time) => {
      const match = time.match(/^(\d{1,2}):(\d{2})$/);
      if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) throw new Error(`时间“${time}”无效，请使用 24 小时制，例如 22:45。`);
      return `${match[1].padStart(2, '0')}:${match[2]}`;
    }))].sort();
  }
  async function saveConfig(event) {
    event.preventDefault();
    const button = $('config-save-button');
    try {
      const timezone = $('timezone').value.trim();
      if (timezone !== 'auto') { try { new Intl.DateTimeFormat('zh-CN', { timeZone: timezone }); } catch { throw new Error('时间显示设置无效，请重新选择。'); } }
      const marketTimezone = $('market-timezone').value.trim();
      try { new Intl.DateTimeFormat('zh-CN', { timeZone: marketTimezone }); } catch { throw new Error('自动保存的时间设置无效，请刷新页面后重试。'); }
      const authorId = $('target-author').value.trim().replace(/^<@!?(\d+)>$/, '$1');
      const targetMessageURL = $('target-message-url').value.trim();
      if (!authorId && !targetMessageURL) throw new Error('请填写群主用户 ID 或粘贴他的一条发言链接。');
      if (authorId && !/^\d+$/.test(authorId)) throw new Error('群主用户 ID 应为一串数字。');
      if (targetMessageURL && !/^https:\/\/(?:canary\.|ptb\.)?discord(?:app)?\.com\/channels\/\d+\/\d+\/\d+\/?$/.test(targetMessageURL)) throw new Error('请粘贴完整的 Discord 发言链接，包含服务器、频道和消息 ID。');
      const interval = Number($('interval').value);
      const boundary = Number($('day-boundary').value);
      if (!Number.isInteger(interval) || interval < 5 || interval > 1440) throw new Error('保存间隔须为 5 到 1440 分钟的整数。');
      if (!Number.isInteger(boundary) || boundary < 0 || boundary > 23) throw new Error('交易日分界小时须为 0 到 23 的整数。');
      const modelEnabled = $('model-enabled').disabled ? Boolean(publicConfig.model?.enabled) : $('model-enabled').checked;
      if (modelEnabled && (!$('model-base-url').value.trim() || !$('model-name').value.trim())) throw new Error('启用模型整理时，请填写模型服务地址和模型名称。');
      const windowEvery = Number($('window-every').value);
      if (!Number.isInteger(windowEvery) || windowEvery < 1 || windowEvery > 60) throw new Error('尾盘保存间隔须为 1 到 60 分钟。');
      const before = Number($('window-before').value);
      const after = Number($('window-after').value);
      if (![before, after].every((minutes) => Number.isInteger(minutes) && minutes >= 0 && minutes <= 240)) throw new Error('收盘前后时间请填写 0 到 240 分钟。');
      const clock = (minutes) => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
      $('window-start').value = clock(16 * 60 - before);
      $('window-end').value = clock(16 * 60 + after);
      const nextConfig = { ...publicConfig, channels: parseChannels($('channels').value), target_author_id: authorId, target_message_url: targetMessageURL, timezone, market_timezone: marketTimezone, day_boundary_hour: boundary, schedule: { ...publicConfig.schedule, enabled: $('schedule-enabled').checked, interval_minutes: interval, times: parseTimes($('times').value), timezone: marketTimezone, window: { ...publicConfig.schedule?.window, enabled: $('window-enabled').checked, start: $('window-start').value, end: $('window-end').value, every_minutes: windowEvery, weekdays: [0, 1, 2, 3, 4] } }, model: { ...publicConfig.model, enabled: modelEnabled, base_url: $('model-base-url').value.trim(), model: $('model-name').value.trim() } };
      button.disabled = true; button.textContent = '正在保存…';
      const result = await api('/api/config', { method: 'PUT', body: JSON.stringify(nextConfig) });
      settingsDirty = false;
      hydrateConfig(result.config || (result.channels ? result : nextConfig));
      text('config-save-status', '设置已保存。');
      showToast('设置已保存，自动计划将使用新配置。');
      await refresh();
    } catch (error) { showToast(error.message, true); text('config-save-status', '未保存，请检查填写内容。'); }
    finally { button.disabled = false; button.textContent = '保存设置'; }
  }
  async function saveCredential(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.querySelector('input');
    const button = form.querySelector('button');
    const value = input.value.trim();
    if (!value) return;
    button.disabled = true;
    try {
      const result = await post('/api/credentials', { kind: form.dataset.kind, value });
      input.value = '';
      showToast(result.backend === 'private_file' ? '系统钥匙串不可用，凭证已存入本机受限文件。' : form.dataset.kind === 'discord' ? '账号凭证已写入本机钥匙串。' : '模型密钥已写入本机钥匙串。');
      await refresh();
    } catch (error) { showToast(error.message, true); }
    finally { button.disabled = false; }
  }
  async function capture() {
    pendingAction = 'capture';
    $('capture-button').disabled = true;
    $('draft-button').disabled = true;
    $('active-job').hidden = false;
    text('active-job-text', '正在提交保存任务…');
    try { await post('/api/capture', {}); showToast('保存任务已提交，记录会自动更新。'); }
    catch (error) { showToast(error.message, true); }
    finally { pendingAction = null; await refresh(); }
  }
  function changeScope() {
    const scope = document.querySelector('input[name="scope"]:checked').value;
    $('day-fields').hidden = scope !== 'day';
    $('range-fields').hidden = scope !== 'range';
    $('draft-date').required = scope === 'day';
    $('draft-start').required = scope === 'range';
    $('draft-end').required = scope === 'range';
    text('scope-description', { latest: '整理本轮新增或修改的群主发言，按回复关系补齐原问题与旧回答。', day: '合并这个交易日的多次存档，保留群主后续补充与说法变更。', range: '合并选定日期内的存档，适合整理数日答疑或每周汇总。' }[scope]);
    updateDraftOptionsLabel();
  }
  async function createDraft(event) {
    event.preventDefault();
    const scope = document.querySelector('input[name="scope"]:checked').value;
    const body = { scope, mode: $('draft-mode').value, format: 'both', layout: $('draft-layout').value, presentation: $('draft-presentation')?.value || 'reading' };
    if (body.mode === 'model' && !publicConfig.model?.base_url) { showToast('请先在设置中配置模型服务，或选择本地证据稿。', true); return; }
    if ($('draft-title').value.trim()) body.title = $('draft-title').value.trim();
    if (scope === 'day') body.date = $('draft-date').value;
    if (scope === 'range') {
      if ($('draft-start').value > $('draft-end').value) { showToast('结束日期不能早于开始日期。', true); return; }
      body.start = $('draft-start').value; body.end = $('draft-end').value;
    }
    pendingAction = 'draft';
    $('draft-button').disabled = true;
    $('capture-button').disabled = true;
    $('active-job').hidden = false;
    text('active-job-text', '正在提交整理任务…');
    try { await post('/api/drafts', body); showToast('整理任务已提交，完成后可在稿件列表中查看。'); }
    catch (error) { showToast(error.message, true); }
    finally { pendingAction = null; await refresh(); }
  }
  function renderBusy(draft,target) {
    const id = getDraftId(draft);
    return renderPending.has(`${id}:${target}`) || remoteRenderJobs.some(job => job.draft_id === id && [target,'all'].includes(job.target || 'main'));
  }
  async function renderImage(draft,target='main') {
    const id = getDraftId(draft);
    if (!id || renderBusy(draft,target)) return;
    const key = `${id}:${target}`;
    let jobId;
    renderPending.add(key); renderDrafts(true);
    try {
      const result = await post('/api/render', { draft_id: id,target });
      jobId = result.id;
      showToast(result.deduplicated ? '这份图片已经在生成。' : target === 'mobile' ? '正在生成分栏图，完成后可按频道查看。' : '正在生成高清主图，完成后可直接下载。');
    } catch (error) { showToast(error.message, true); }
    finally {
      await refresh(); renderPending.delete(key); renderDrafts(true);
      if (jobId && snapshot?.state?.last_job_id === jobId && snapshot.state.last_job_status === 'success')
        showToast(target === 'mobile' ? '分栏图已就绪。' : '高清图已就绪。');
    }
  }
  function updateClock() {
    text('current-time', dateTime(new Date(), true));
    if (snapshot) {
      const connectivity = snapshot.connectivity || snapshot.state?.connectivity || {};
      const retryAt = first(connectivity.retry_at, connectivity.next_retry_at, snapshot.state?.retry_at, snapshot.state?.next_retry_at);
      if (retryAt) text('retry-countdown', countdown(retryAt));
      const lastSuccess = first(snapshot.state?.last_success_at, snapshot.state?.last_capture_success_at, snapshot.state?.last_success, snapshot.state?.last_capture_at, connectivity.last_success_at);
      if (lastSuccess) text('offline-duration', elapsed(lastSuccess));
    }
  }

  document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
  document.querySelectorAll('[data-go]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.go)));
  $('refresh-button').addEventListener('click', refresh);
  $('capture-button').addEventListener('click', capture);
  $('connect-browser-button').addEventListener('click', connectBrowser);
  $('draft-form').addEventListener('submit', createDraft);
  document.querySelectorAll('input[name="scope"]').forEach((input) => input.addEventListener('change', changeScope));
  $('draft-mode').addEventListener('change', updateMode);
  $('draft-layout').addEventListener('change', () => { if (snapshot) renderState(snapshot); });
  $('config-form').addEventListener('submit', saveConfig);
  $('config-form').addEventListener('input', () => { settingsDirty = true; text('config-save-status', '有未保存的设置。'); });
  document.querySelectorAll('.credential-form').forEach((form) => form.addEventListener('submit', saveCredential));
  $('draft-search').addEventListener('input', (event) => { draftSearch = event.target.value.trim(); renderDrafts(true); });
  $('login-form').addEventListener('submit', async (event) => {
    event.preventDefault(); const button = $('login-button'); button.disabled = true; $('login-error').hidden = true;
    try {
      const result = await post('/api/login', { code: $('access-code').value.trim() });
      $('access-code').value = ''; loginRequired = false; $('login-overlay').hidden = true; document.querySelector('.app-shell').inert = false;
      if (result.archive_key) document.querySelector('meta[name="archive-key"]').content = result.archive_key;
      await refresh();
    } catch (error) { text('login-error', error.message); $('login-error').hidden = false; }
    finally { button.disabled = false; }
  });
  $('copy-remote-code').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('remote-code').textContent); showToast('访问口令已复制。'); }
    catch { showToast('浏览器未开放剪贴板，请选择口令后手动复制。', true); }
  });
  window.addEventListener('hashchange', () => setView(location.hash.slice(1), false));
  window.addEventListener('online', refresh);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  for (const id of ['draft-date', 'draft-start', 'draft-end']) $(id).value = dateOnly();
  for (const id of ['draft-date', 'draft-start', 'draft-end']) $(id).addEventListener('input', () => { draftDatesTouched = true; });
  $('credentials-section').hidden = !isLocal;
  setupDisclosureMotion();
  setView(location.hash.slice(1), false);
  changeScope(); updateClock(); refresh();
  setInterval(() => { if (!loginRequired) refresh(); }, 3000);
  setInterval(updateClock, 1000);
})();
