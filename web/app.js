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
  let deliveryDirty = false;
  let deliverySaving = false;
  let deliveryHistorySignature = "";
  let fetching = false;
  let toastTimer;
  let serviceFailedAt = null;
  let serviceInstance = null;
  let serviceAction = null;
  let serviceRequest = false;
  let startupRequest = false;
  let pendingAction = null;
  let lastDraftSignature = '';
  let currentView = 'workspace';
  let draftSearch = '';
  const draftPageSize = 20;
  let draftLibrary = { items: [], total: 0, offset: 0, has_more: false, revision: null };
  let draftListLoading = false;
  let draftListError = '';
  let draftListSequence = 0;
  let draftListRequest = '';
  let draftSearchTimer;
  let renderPending = new Set();
  const renderScales = new Map();
  let remoteRenderJobs = [];
  let lastJobSeen = null;
  let draftDatesTouched = false;
  let savingChannels = false;
  let loginRequired = false;
  let onboardingEditing = false;
  // UI capability only; the server independently authorizes every operation.
  let isLocal = ['localhost', '127.0.0.1', '::1', '[::1]'].includes(location.hostname);
  const autoExportDefaults = { enabled: false, times: ['16:15'], weekdays: [0, 1, 2, 3, 4], render_scales: [1], layout: 'horizontal', presentation: 'reading', target: 'main' };
  const exportDefaults = { name_prefix: '答疑存档', date_format: 'YYYY-MM-DD', sequence_digits: 2, separator: '-', copy_directory: '' };
  function displayTimezone() { return publicConfig.timezone && publicConfig.timezone !== 'auto' ? publicConfig.timezone : Intl.DateTimeFormat().resolvedOptions().timeZone; }

  function node(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined && text !== null) item.textContent = String(text);
    return item;
  }
  function first(...values) { return values.find((value) => value !== undefined && value !== null && value !== ''); }
  function imageDownloadName(value) {
    try {
      const name = decodeURIComponent(new URL(value, location.href).pathname.split('/').pop() || '');
      return name && name !== '.' && name !== '..' && !/[\\/\u0000-\u001f\u007f]/.test(name) ? name : '长图.png';
    } catch { return '长图.png'; }
  }
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
  async function refreshRequestKey() {
    const response = await fetch('/', { cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) throw new Error('暂时无法连接本机，请稍后重试。');
    const page = new DOMParser().parseFromString(await response.text(), 'text/html');
    const key = page.querySelector('meta[name="archive-key"]')?.content;
    if (!key || key === '__ARCHIVE_KEY__') throw new Error('连接信息未就绪，请稍后重试。');
    document.querySelector('meta[name="archive-key"]').content = key;
  }
  async function api(path, options = {}, retryKey = true) {
    const mutation = options.method && !['GET', 'HEAD'].includes(options.method.toUpperCase());
    const csrfKey = document.querySelector('meta[name="archive-key"]')?.content;
    const response = await fetch(path, { cache: 'no-store', credentials: 'same-origin', ...options, headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(mutation && csrfKey ? { 'X-Archive-Key': csrfKey } : {}), ...options.headers } });
    let body;
    try { body = await response.json(); } catch { body = null; }
    // Only retry a request explicitly rejected before any mutation ran.
    if (response.status === 403 && body?.code === 'csrf_expired' && mutation && retryKey) {
      await refreshRequestKey();
      return api(path, options, false);
    }
    if (response.ok && body?.archive_key) document.querySelector('meta[name="archive-key"]').content = body.archive_key;
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
    if (view === 'library' && snapshot) { renderDrafts(true); syncDraftLibrary(); }
  }
  const deliveryChannels = ['email', 'telegram', 'discord', 'clawbot'];
  function deliveryPreferences() {
    return {
      email: {enabled: $('delivery-email-enabled').checked, host: $('delivery-email-host').value.trim(),
        port: Number($('delivery-email-port').value), security: $('delivery-email-security').value,
        username: $('delivery-email-username').value.trim(), sender: $('delivery-email-sender').value.trim(),
        recipients: $('delivery-email-recipients').value.split(/[,，;；\s]+/).filter(Boolean)},
      telegram: {enabled: $('delivery-telegram-enabled').checked, chat_id: $('delivery-telegram-chat_id').value.trim()},
      discord: {enabled: $('delivery-discord-enabled').checked},
      clawbot: {enabled: $('delivery-clawbot-enabled').checked}
    };
  }
  function renderDelivery(data) {
    const preferences = data.config?.delivery || {};
    for (const channel of deliveryChannels) {
      text(`delivery-${channel}-configured`, channel === 'clawbot' ? (data.state?.clawbot?.connected ? '已绑定' : '未绑定') : data.credentials?.[`delivery_${channel}`] ? '凭据已保存' : '未配置凭据');
      if (!deliveryDirty && !deliverySaving) {
        const row = preferences[channel] || {};
        $(`delivery-${channel}-enabled`).checked = Boolean(row.enabled);
        for (const [key, value] of Object.entries(row)) {
          const input = $(`delivery-${channel}-${key}`);
          if (input && key !== 'enabled') input.value = Array.isArray(value) ? value.join(', ') : value;
        }
      }
    }
    renderClawBot(data.state?.clawbot || {});
    const items = data.state?.delivery || [];
    const signature = JSON.stringify(items);
    if (deliveryHistorySignature === signature) return;
    deliveryHistorySignature = signature;
    const history = $('delivery-history'); history.replaceChildren();
    if (!items.length) { history.append(node('p', 'form-help', '尚无发送记录')); return; }
    for (const item of items) {
      const row = node('div', 'delivery-record');
      row.append(node('strong', '', `${{email:'邮箱',telegram:'Telegram',discord:'Discord',clawbot:'微信 ClawBot'}[item.channel]} · ${item.title}`));
      row.append(node('p', 'form-help', `${{pending:'等待发送',retrying:'等待重试',failed:'发送失败',sent:'已发送',attention:'需微信操作'}[item.status] || item.status}${item.error ? ' · ' + item.error : ''}${item.status === 'retrying' && item.retry_at ? ' · 下次重试 ' + dateTime(item.retry_at) : ''}`));
      if (['failed','retrying','attention'].includes(item.status)) {
        const retry = node('button', 'text-button', '重试发送'); retry.type = 'button';
        retry.addEventListener('click', async () => {
          retry.disabled = true;
          try { await post('/api/delivery/retry', {id: item.id}); showToast('已加入补发队列。'); await refresh(); }
          catch (error) { showToast(error.message, true); retry.disabled = false; }
        }); row.append(retry);
      }
      history.append(row);
    }
  }
  function renderClawBot(state) {
    const labels = {unbound:'尚未绑定微信',ready:'微信会话可发送',needs_message:'已绑定，请向微信 ClawBot 发一条消息',needs_rebind:'微信登录已失效，请重新扫码'};
    const loginLabels = {wait:'等待扫码',scaned:'已扫码，请在手机确认',need_verifycode:'请填写微信手机端显示的验证码',expired:'二维码已过期，请重新生成',verify_code_blocked:'验证码尝试过多，请重新生成二维码',scaned_but_redirect:'正在连接微信服务'};
    text('clawbot-status', loginLabels[state.login_status] || labels[state.status] || labels.unbound);
    $('clawbot-connect').textContent = ['expired','verify_code_blocked'].includes(state.login_status) ? '重新生成二维码' : state.connected ? '重新绑定微信' : '扫码绑定微信';
    $('clawbot-connect').disabled = !isLocal;
    $('delivery-clawbot-enabled').disabled = !state.connected;
    const showQR = Boolean(state.qr_url && !['confirmed','expired','verify_code_blocked'].includes(state.login_status));
    $('clawbot-qr-panel').hidden = !showQR;
    if (showQR && $('clawbot-qr').getAttribute('src') !== state.qr_url) $('clawbot-qr').src = state.qr_url;
    if (!showQR) $('clawbot-qr').removeAttribute('src');
    $('clawbot-verify-panel').hidden = state.login_status !== 'need_verifycode';
    $('clawbot-error').hidden = !state.error && isLocal;
    text('clawbot-error', state.error || (!isLocal ? '扫码绑定请通过管理员连接操作。' : ''));
  }
  async function connectClawBot() {
    const button = $('clawbot-connect'); button.disabled = true;
    try {
      const result = await post('/api/clawbot/connect', {});
      renderClawBot(result);
      showToast('二维码已生成，请用微信扫码并确认。');
    } catch (error) {showToast(error.message, true);}
    finally {button.disabled = !isLocal;}
  }
  async function verifyClawBot() {
    const button = $('clawbot-verify'); button.disabled = true;
    try {
      await post('/api/clawbot/verify', {id:snapshot?.state?.clawbot?.login_id, code:$('clawbot-verify-code').value.trim()});
      $('clawbot-verify-code').value = ''; showToast('验证码已提交，正在等待微信确认。');
    } catch (error) {showToast(error.message, true);}
    finally {button.disabled = false;}
  }
  async function saveDelivery(channel = null) {
    if (deliverySaving) return;
    deliverySaving = true;
    const buttons = [...$('delivery-form').querySelectorAll('button')]; buttons.forEach(button => button.disabled = true);
    try {
      const preferences = deliveryPreferences();
      for (const name of deliveryChannels) {
        const input = $(`delivery-${name}-secret`);
        if (input?.value.trim()) {
          await post('/api/delivery/credential', {channel:name, value:input.value.trim()});
          input.value = '';
        }
      }
      await api('/api/config', {method:'PUT', body:JSON.stringify({delivery:preferences})});
      deliveryDirty = false;
      text('delivery-save-status', '推送设置已保存。');
      if (channel) {
        await post('/api/delivery/test', {channel});
        text('delivery-save-status', '设置已保存，测试已排队；发送结果见下方记录。');
      }
      showToast(channel ? '测试发送已排队。' : '推送设置已保存。');
    } catch (error) {
      text('delivery-save-status', error.message); showToast(error.message, true);
    } finally {
      deliverySaving = false; buttons.forEach(button => button.disabled = false); await refresh();
    }
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
    const exports = { ...exportDefaults, ...publicConfig.export };
    $('export-prefix').value = exports.name_prefix;
    $('export-date-format').value = exports.date_format;
    $('export-sequence-digits').value = String(exports.sequence_digits);
    $('export-separator').value = exports.separator;
    $('export-copy-directory').value = exports.copy_directory || '';
    updateExportPreview();
    const autoExport = { ...autoExportDefaults, ...publicConfig.auto_export };
    $('auto-export-enabled').checked = Boolean(autoExport.enabled);
    $('auto-export-times').value = autoExport.times.join(', ');
    const weekdays = [...autoExport.weekdays].sort().join(',');
    const daysOption = weekdays === '0,1,2,3,4' ? 'weekdays' : weekdays === '0,1,2,3,4,5,6' ? 'daily' : 'custom';
    if (daysOption === 'custom' && !$('auto-export-weekdays').querySelector('[value="custom"]')) {
      const option = node('option', '', '自定义执行日'); option.value = 'custom'; $('auto-export-weekdays').append(option);
    }
    $('auto-export-weekdays').value = daysOption;
    $('auto-export-scales').value = autoExport.render_scales.length === 2 ? 'both' : String(autoExport.render_scales[0]);
    $('auto-export-layout').value = autoExport.layout;
    $('auto-export-presentation').value = autoExport.presentation;
    $('auto-export-columns').checked = autoExport.target === 'all';
    if (!configInitialized) $('draft-mode').value = 'evidence';
    configInitialized = true;
  }
  function updateExportPreview() {
    const date = snapshot?.drafts?.find(draft => /^\d{4}-\d{2}-\d{2}$/.test(draft.date || ''))?.date || snapshot?.state?.market_day || dateOnly();
    const formattedDate = $('export-date-format').value === 'YYYYMMDD' ? date.replaceAll('-', '') : date;
    const digits = Number($('export-sequence-digits').value) || 2;
    const separator = $('export-separator').value || '-';
    text('export-name-preview', `${$('export-prefix').value.trim() || exportDefaults.name_prefix}${separator}${formattedDate}${separator}${'1'.padStart(digits, '0')}.png`);
  }
  function setExportDirectoryAccess() {
    $('export-copy-directory').readOnly = !isLocal;
    $('export-directory-choose').disabled = !isLocal;
    $('export-directory-phone-note').hidden = isLocal;
  }
  async function chooseExportDirectory() {
    if (!isLocal) return;
    if (snapshot?.platform?.system === 'linux') {
      const path = window.prompt('输入 Linux 服务器上的目录绝对路径', $('export-copy-directory').value);
      if (path !== null) {
        $('export-copy-directory').value = path.trim();
        settingsDirty = true; text('config-save-status', '有未保存的设置。');
      }
      return;
    }
    const button = $('export-directory-choose');
    button.disabled = true; button.textContent = '正在选择…';
    try {
      const result = await post('/api/export-directory', { action: 'choose' });
      if (typeof result.path === 'string' && result.path) {
        $('export-copy-directory').value = result.path;
        settingsDirty = true; text('config-save-status', '有未保存的设置。');
      }
    } catch (error) { showToast(error.message, true); }
    finally { button.disabled = false; button.textContent = '选择文件夹'; }
  }
  function renderAutoExportState(state) {
    const autoExport = state.auto_export || {};
    const paused = state.automatic_paused;
    const enabled = autoExport.enabled ?? publicConfig.auto_export?.enabled ?? false;
    text('auto-export-next', paused ? '已暂停' : enabled ? autoExport.next_at ? dateTime(autoExport.next_at, true) : '等待计划' : '未启用');
    const stages = { capture: '正在保存频道', capture_partial: '频道保存未完整', draft: '正在整理稿件', render: '正在生成图片', copy: '正在另存文件' };
    const failedStages = { capture: '频道保存未完成', capture_partial: '频道保存未完整', draft: '稿件整理未完成', render: '图片生成未完成', copy: '文件另存未完成' };
    const statuses = { ...statusNames, idle: '尚未执行', skipped: '该交易日无可导出发言', paused: '已暂停', disabled: '未启用' };
    const stageLabel = autoExport.last_status === 'running' ? stages[autoExport.stage] : ['failed', 'error'].includes(autoExport.last_status) ? failedStages[autoExport.stage] : null;
    let label = stageLabel || statuses[autoExport.last_status] || (autoExport.last_status ? '等待处理' : '尚未执行');
    if (autoExport.retry_at) label += ` · ${dateTime(autoExport.retry_at, true)} 重试`;
    else if (autoExport.last_completed_at && autoExport.last_status === 'success') label += ` · ${dateTime(autoExport.last_completed_at, true)}`;
    text('auto-export-status', label);
    $('auto-export-error').hidden = !autoExport.last_error;
    text('auto-export-error', autoExport.last_error || '');
    const lastDraft = autoExport.last_draft_id;
    const link = $('auto-export-last-draft');
    link.hidden = !lastDraft;
    if (lastDraft) link.href = `/drafts/${encodeURIComponent(String(lastDraft))}/`;
    else link.removeAttribute('href');
  }
  function renderState(data) {
    isLocal = ['localhost','127.0.0.1','::1','[::1]'].includes(location.hostname) || data.remote?.administrator === true;
    remoteRenderJobs = data.state?.render_jobs || [];
    renderDelivery(data);
    snapshot = data;
    if (data.platform?.system === 'linux') {
      document.querySelector('label[for="export-copy-directory"]').textContent = '自动另存目录（Linux 服务器）';
      $('export-directory-choose').textContent = '填写服务器目录';
      $('export-copy-directory').placeholder = '/home/用户名/图片目录';
      document.querySelector('#credentials-section .form-help').textContent = '通过 SSH 隧道连接服务器后配置，页面不显示已保存的值。';
      document.querySelector('#service-more .form-help').textContent = '停止后访问会断开。在服务器执行 systemctl --user start discordarchive 可重新启动，数据保留。';
    }
    const config = data.config || publicConfig;
    hydrateConfig(config);
    const state = data.state || {};
    renderAutoExportState(state);
    renderServiceControls(data);
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
    const linuxBinding=data.platform?.system==='linux';
    const localHelper=Boolean(data.connection_helper?.available);
    const helperBinding=Boolean(data.remote?.https_url)||localHelper;
    $('linux-binding').hidden=!(linuxBinding||localHelper) || !isLocal;
    $('helper-downloads').hidden=!helperBinding;
    $('legacy-binding').hidden=helperBinding;
    $('windows-helper-download').hidden=localHelper&&!linuxBinding;
    $('connect-browser-fallback').hidden=!linuxBinding || !isLocal || !data.platform?.login_desktop;
    $('connect-browser-fallback').disabled=busy;
    if (linuxBinding) {
      const root=String(data.system?.binding_root || '/服务器项目目录').replaceAll("'", "'\\''");
      text('linux-binding-command',`python3 scripts/bind_linux.py --ssh-file .env.ssh.local --remote-root '${root}'`);
    }
    const modelCredential = first(credentials.model, credentials.has_model, state.has_model_key, config.model_key_configured);
    const allChannels = Array.isArray(config.channels) ? config.channels : [];
    const channels = allChannels.filter((channel) => typeof channel === 'string' || channel.enabled !== false);
    const configured = Boolean(channels.length && (config.target_author_id || config.target_message_url) && discordCredential !== false);
    const needsChannels = !allChannels.length;
    const needsAuthor = !(config.target_author_id || config.target_message_url);
    $('setup-alert').hidden = !isLocal || (!needsChannels && !needsAuthor);
    text('setup-step', discordCredential === false ? '首次使用：先连接 Discord，再添加频道与答疑人。' : needsChannels ? '下一步：添加要保存的频道和答疑人。' : '下一步：指定要整理的答疑人。');
    text('setup-action', discordCredential === false ? localHelper ? '首次连接 Discord' : linuxBinding ? helperBinding ? '首次连接 Discord' : '本机登录后绑定' : '连接 Discord' : needsChannels ? '添加频道与答疑人' : '指定答疑人');
    $('setup-action').disabled = busy;
    $('setup-save').hidden = !isLocal || (!needsChannels && !needsAuthor);
    $('setup-save').disabled = busy;
    $('setup-action').onclick = () => {
      if (discordCredential === false) { $('connect-browser-button').click(); return; }
      onboardingEditing = true;
      $('advanced-settings').open = true;
      const field = $(needsChannels ? 'channels' : 'target-message-url');
      field.scrollIntoView({block:'center'});
      field.focus();
    };
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
    text('next-capture', state.automatic_paused ? '已暂停' : config.schedule?.enabled ? discordCredential === false ? '连接后开始' : next ? dateTime(next, true) : '等待下一轮' : '未启用');
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
    if ((linuxBinding||localHelper) && isLocal && !connectingBrowser) {
      $('connect-browser-button').querySelector('span').textContent=discordCredential ? (helperBinding ? '账号说明' : '重新绑定账号') : helperBinding ? '首次连接 Discord' : '本机登录后绑定';
      if(helperBinding)text('connection-detail',discordCredential?(localHelper?'此 Mac 已保存连接，可独立采集。':'Ubuntu 已保存连接，可独立采集；换电脑直接访问，无需重新绑定。'):'先下载客户端并运行首次连接工具，再在日常 Discord 页面识别并确认账号。');
      if (discordCredential===false && !helperBinding) text('connection-detail','在 Mac 本机登录后，经 SSH 绑定此服务器。绑定后可独立运行，VNC 仅作备用。');
    }
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
    text('recovery-state', state.automatic_paused ? '自动任务已暂停，仍可手动保存和出稿' : needsAttention ? '自动重试暂停，请处理凭证或频道权限' : busy && first(state.backfilling, connectivity.backfilling) ? '正在补采断线期间的消息' : isOffline ? '保存暂停，服务会持续重试' : lastSuccess ? '保存记录已更新，等待下一轮' : '首次保存后开始追踪连续性');
    const lastError = first(state.last_job_error, connectivity.last_error, state.last_error, data.last_error, state.target_resolution_warning, state.last_warning);
    $('last-error').hidden = !lastError;
    if (lastError) text('last-error', typeof lastError === 'string' ? lastError : lastError.message || '上一轮未成功，请查看保存记录。');
    text('archive-messages', number(first(archive.message_count, archive.messages, archive.total_messages, state.message_count)));
    text('archive-channels', number(first(archive.channel_count, archive.channels_count, Array.isArray(archive.channels) ? archive.channels.length : undefined, channels.length)));
    text('archive-attachments', number(first(archive.attachment_count, archive.attachments, archive.total_attachments, archive.media?.saved)));
    text('archive-drafts', number(first(data.draft_count, drafts.length)));
    text('draft-count', String(first(data.draft_count, drafts.length)));
    text('day-boundary-help', '按美股交易日期归档，跨午夜的答疑也能放在同一交易日。');
    updateMode();
    const storageName = {keychain:'钥匙串',private_file:'本机受限文件'}[state.browser_account?.credential_backend];
    text('discord-credential-status', discordCredential === undefined ? '未检测' : discordCredential ? `已保存${storageName ? ` · ${storageName}` : ''}` : '未配置');
    text('model-credential-status', modelCredential === undefined ? '未检测' : modelCredential ? '已保存' : '未配置');
    text('service-caption', serviceAction ? serviceAction.startsWith('host-') ? '正在处理服务器电源操作' : serviceAction === 'restart' ? '正在重启服务' : '正在停止服务' : state.automatic_paused ? '自动任务已暂停' : data.platform?.system==='linux' ? '服务器运行中' : '本机运行中');
    renderRemote(data.remote || {});
    text('last-updated', `状态更新于 ${dateTime(new Date(), true)}`);
    renderDrafts();
    if (currentView === 'library') syncDraftLibrary();
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
  async function connectBrowser({fallback=false}={}) {
    if (!isLocal) return;
    if ((snapshot?.platform?.system==='linux'||snapshot?.connection_helper?.available) && !fallback) {
      $('advanced-settings').open=true;
      $('linux-binding').scrollIntoView({block:'center'});
      if(snapshot?.remote?.https_url||snapshot?.connection_helper?.available)$('helper-downloads').querySelector('a').focus();
      else $('linux-binding-command').focus();
      return;
    }
    if (snapshot?.platform?.system === 'linux' && snapshot.platform.login_desktop) {
      window.open('http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale', '_blank', 'noopener');
    }
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
    if (snapshot?.platform?.system === 'linux' && remote.access && !remote.https_url) {
      const access = remote.access;
      $('remote-urls').closest('.settings-section').querySelector('h2').textContent = '以后如何访问';
      const addresses = Array.isArray(access.server_addresses) ? access.server_addresses.join('、') : '';
      $('remote-urls').replaceChildren(
        node('p', '', addresses ? `服务器私有 IP：${addresses}` : '未检测到服务器私有 IP，请在服务器执行 ip -4 address 核对。'),
        node('p', 'form-help', access.loopback_only
          ? '当前仅监听服务器本机。上述 IP 用于 SSH 连接，不能直接加 :8765 打开工作台。'
          : `当前监听 ${access.listen_host}:${access.listen_port}，请核对私有网络与访问口令设置。`),
        node('p', 'form-help', '以后使用：跨网络时先连 Tailscale 或同类私有网络，再建立 SSH 隧道，打开 http://127.0.0.1:18765。关闭隧道后需重新连接；服务和数据仍保留。'),
        node('p', 'form-help', access.tailscale_installed
          ? '检测到 Tailscale 程序；请自行确认服务器和访问设备均已连接且策略允许。'
          : '未检测到 Tailscale。相同局域网可直接建立 SSH 隧道；跨网络先配置私有网络，不开放公网端口。')
      );
    }
    if(remote.https_url){
      $('remote-urls').closest('.settings-section').querySelector('h2').textContent='以后如何访问';
      $('remote-urls').append(node('p','form-help','保持 Tailscale 在线，收藏上方 HTTPS 地址即可。不需要 SSH 隧道；由获准的 Tailscale 账号管理。'));
    }
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
  function selectedRenderScale(draft) { return renderScales.get(getDraftId(draft)) || 1; }
  function selectedImageVariant(draft, scale = selectedRenderScale(draft)) {
    const variants = draft.image_variants || {};
    const columns = Array.isArray(draft.single_columns) ? draft.single_columns : [];
    const legacy = !Object.keys(variants).length;
    const variant = variants[String(scale)] || (legacy ? {...draft,
      images:Number(draft.render_scale || 1) === scale ? draft.images : [],
      single_columns:columns.map(column => Number(column.render_scale || draft.render_scale || 1) === scale ? column
        : {title:column.title,channel_id:column.channel_id,file:column.file,images:[]})} : {});
    return {
      ...variant,
      images: Array.isArray(variant.images) ? variant.images : [],
      single_columns: Array.isArray(variant.single_columns) ? variant.single_columns
        : columns.map(column => ({ title: column.title, channel_id: column.channel_id, file: column.file, images: [] })),
    };
  }
  function draftURL(draft) {
    const id = getDraftId(draft);
    return id ? `/drafts/${encodeURIComponent(id)}/` : null;
  }
  function draftRow(draft) {
    const row = node('article', 'draft-row');
    row.dataset.draftId = getDraftId(draft);
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
    if (draft.audio?.complete) meta.append(node('span', '', `${draft.audio.complete} 条语音转写`));
    const warningCount = first(draft.warning_count, Array.isArray(draft.warnings) ? draft.warnings.length : 0);
    if (warningCount) meta.append(node('span', 'draft-state', `${warningCount} 项待核对`));
    if (draft.export_copy?.error) {
      const copyState = node('button', 'draft-state failed export-copy-error', '自动另存未完成');
      copyState.type = 'button'; copyState.title = draft.export_copy.error;
      copyState.setAttribute('aria-label', '自动另存未完成，查看原因');
      copyState.addEventListener('click', () => showToast(`${draft.export_copy.error}。检查 Mac 目录后重新生成图片；现有图片仍可下载。`, true));
      meta.append(copyState);
    }
    if (draft.error) meta.append(node('span', 'draft-state failed', typeof draft.error === 'string' ? draft.error : draft.error.message || '生成失败'));
    info.append(title, meta); row.append(info);
    const actions = node('div', 'draft-actions');
    if (available) {
      const preview = node('a', 'text-button', '打开 ↗'); preview.href = url; preview.target = '_blank'; preview.rel = 'noopener'; actions.append(preview);
      if (draft.manuscript_url) {
        const manuscript = node('a', 'text-button', '文字稿'); manuscript.href = draft.manuscript_url; manuscript.download = ''; actions.append(manuscript);
      }
      const scale = selectedRenderScale(draft);
      const variant = selectedImageVariant(draft, scale);
      const density = node('select', 'export-density'); density.setAttribute('aria-label', '图片清晰度');
      for (const [value, label] of [[1, '标准 · 1×'], [2, 'HiDPI · 2×']]) {
        const option = node('option', '', label); option.value = String(value); density.append(option);
      }
      density.value = String(scale);
      density.addEventListener('change', () => {
        const list = density.closest('#recent-drafts, #all-drafts');
        renderScales.set(getDraftId(draft), Number(density.value)); renderDrafts(true);
        list?.querySelector(`[data-draft-id="${CSS.escape(getDraftId(draft))}"] .export-density`)?.focus();
      });
      actions.append(density);
      const images = variant.images;
      if (images.length) {
        const viewImages = node('button', 'text-button', '查看长图'); viewImages.type = 'button';
        viewImages.addEventListener('click', () => openPreview(images, `${draft.title || '稿件长图'} · ${scale}×`)); actions.append(viewImages);
        const download = node('a','text-button',images.length === 1 ? '下载图片' : '下载第 1 张');
        download.href = images[0]; download.download = imageDownloadName(images[0]); actions.append(download);
      }
      const columns = variant.single_columns;
      if (columns.length) {
        const readyColumns = columns.filter(column => column.images?.length);
        const viewColumns = node('button', 'text-button', readyColumns.length === columns.length ? '分栏图' : renderBusy(draft,'mobile') ? '分栏图生成中…' : '生成分栏图'); viewColumns.type = 'button';
        viewColumns.disabled = renderBusy(draft,'mobile');
        viewColumns.addEventListener('click', () => readyColumns.length === columns.length
          ? window.ArchivePreview?.openGroups(readyColumns,`${draft.title || '稿件'} · 分栏图 · ${scale}×`) : renderImage(draft,'mobile')); actions.append(viewColumns);
      }
      const imageReady = Boolean(images.length);
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
  function draftPage() {
    if (snapshot?.draft_revision !== undefined) return draftLibrary;
    // Older servers and offline fixtures still return their complete list.
    const rows = (Array.isArray(snapshot?.drafts) ? snapshot.drafts : []).filter(draft =>
      String(first(draft.title, draft.name, '')).toLocaleLowerCase().includes(draftSearch.toLocaleLowerCase()));
    const offset = Math.min(draftLibrary.offset, Math.max(0, Math.floor((rows.length - 1) / draftPageSize) * draftPageSize));
    return { items: rows.slice(offset, offset + draftPageSize), total: rows.length, offset, has_more: offset + draftPageSize < rows.length };
  }
  function syncDraftLibrary() {
    if (snapshot?.draft_revision !== undefined && draftLibrary.revision !== snapshot.draft_revision)
      loadDraftPage(draftLibrary.offset);
  }
  async function loadDraftPage(offset = 0) {
    if (snapshot?.draft_revision === undefined) {
      draftLibrary.offset = offset; renderDrafts(true); return;
    }
    const revision = snapshot.draft_revision;
    const request = JSON.stringify([offset, draftSearch, revision]);
    if (draftListLoading && request === draftListRequest) return;
    const sequence = ++draftListSequence;
    draftListRequest = request; draftListLoading = true; draftListError = ''; renderDrafts(true);
    try {
      const query = new URLSearchParams({ limit: String(draftPageSize), offset: String(offset), search: draftSearch });
      const result = await api(`/api/drafts?${query}`);
      if (sequence !== draftListSequence) return;
      if (!Array.isArray(result.items)) throw new Error('稿件列表暂时无法读取，请重试。');
      if (offset && offset >= result.total) { draftListLoading = false; return loadDraftPage(Math.max(0, Math.floor((result.total - 1) / draftPageSize) * draftPageSize)); }
      draftLibrary = { ...result, revision: result.revision ?? revision };
    } catch (error) {
      if (sequence === draftListSequence) draftListError = error.message;
    } finally {
      if (sequence === draftListSequence) { draftListLoading = false; renderDrafts(true); }
    }
  }
  function renderDrafts(force = false) {
    const recent = (Array.isArray(snapshot?.drafts) ? snapshot.drafts : []).slice(0, 3);
    const page = draftPage();
    const signature = JSON.stringify([recent, page, draftSearch, draftListLoading, draftListError, [...renderPending], remoteRenderJobs, [...renderScales]]);
    if (!force && signature === lastDraftSignature) return;
    lastDraftSignature = signature;
    $('recent-drafts').replaceChildren(...(recent.length ? recent.map(draftRow) : [emptyState('还没有稿件', '先保存一轮对话，再选择范围生成。')]));
    $('all-drafts').replaceChildren(...(page.items.length ? page.items.map(draftRow) : [emptyState(draftListLoading ? '正在读取…' : draftSearch ? '没有找到匹配的稿件' : '还没有稿件', draftListLoading ? '' : draftSearch ? '试试其他关键词。' : '在“工作台”保存对话，再生成第一份稿件。')]));
    $('draft-pagination').hidden = !page.total && !draftListError;
    text('draft-page-count', page.total ? `${page.offset + 1}–${page.offset + page.items.length} / ${number(page.total)}` : '');
    $('draft-page-previous').disabled = draftListLoading || page.offset === 0;
    $('draft-page-next').disabled = draftListLoading || !page.has_more;
    $('draft-list-error').hidden = !draftListError;
    text('draft-list-error-text', draftListError);
    $('all-drafts').setAttribute('aria-busy', String(draftListLoading));
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
  function renderServiceControls(data) {
    const service = data.service || {};
    $('service-more').querySelector('p').textContent=data.platform?.system==='linux'?'停止后 HTTPS 工作台断开。通过 SSH 执行 systemctl --user start discordarchive.service 可恢复；归档、稿件和模型保留。':'停止后网页和手机访问断开。再次打开 Mac App 或 Start.command 可启动，归档、稿件和凭证均保留。';
    serviceAction = service.action || (service.error ? null : serviceAction);
    const paused = Boolean(data.state?.automatic_paused);
    text('service-pause', paused ? '恢复自动任务' : '暂停自动任务');
    text('service-control-status', service.error || (serviceAction
      ? `${({'restart':'重启服务','stop':'停止服务','host-reboot':'重启服务器','host-poweroff':'关闭服务器'})[serviceAction] || '服务操作'}：等待已接受的任务结束，然后执行。`
      : paused ? '自动任务已暂停，仍可手动保存和出稿。' : '服务运行中'));
    $('service-pause').disabled = serviceRequest || Boolean(serviceAction);
    for (const id of ['service-restart', 'service-stop']) {
      $(id).hidden = !isLocal;
      $(id).disabled = serviceRequest || startupRequest || Boolean(serviceAction) || service.available === false;
    }
    $('service-more').hidden = !isLocal;
    $('service-local-note').hidden = isLocal;
    const startup=data.system?.startup;
    $('startup-controls').hidden=!isLocal || !startup;
    if (startup) {
      text('startup-label', data.platform?.system === 'linux' && startup.scope === 'boot' ? '开机后自动运行' : '登录后自动运行');
      if (!startupRequest) $('startup-enabled').checked=Boolean(startup.enabled);
      $('startup-enabled').disabled=startupRequest || !startup.available || Boolean(serviceAction);
      text('startup-note',startupRequest ? '正在保存系统启动设置…' : startup.note || '关闭开关不会停止当前服务。');
    }
    const power=data.system?.power;
    $('host-power-controls').hidden=!isLocal || !power?.supported;
    for (const action of ['reboot','poweroff']) {
      $('host-'+action).disabled=!power?.[action] || serviceRequest || startupRequest || Boolean(serviceAction);
    }
    text('host-power-note',power?.note || '需要输入对应操作的确认文字，不会强制中断本应用任务。');
  }
  async function changeStartup() {
    if (!isLocal || startupRequest) return;
    const enabled=$('startup-enabled').checked;
    startupRequest=true;renderServiceControls(snapshot || {});
    try {
      const result=await post('/api/autostart',{enabled});
      if (snapshot) { snapshot.system ||= {};snapshot.system.startup=result; }
      showToast(enabled ? '自动启动已开启，当前服务继续运行。' : '自动启动已关闭，当前服务继续运行。');
    } catch(error) { showToast(error.message,true); }
    finally {startupRequest=false;renderServiceControls(snapshot || {});await refresh();}
  }
  async function controlHostPower(action) {
    if (!isLocal || serviceRequest || startupRequest || serviceAction) return;
    if (settingsDirty) {showToast('请先保存设置，再操作服务器电源。',true);return;}
    const label=action==='reboot'?'重启服务器':'关闭服务器';
    const hostname=snapshot?.system?.hostname || '';
    const address=snapshot?.remote?.access?.server_addresses?.[0] || '';
    const target=hostname && address ? `${hostname} (${address})` : hostname || address || '当前服务器';
    const manualStart=action==='reboot' && snapshot?.system?.startup?.enabled===false ? '当前未开启自动启动，重启后需登录服务器手动启动本应用。' : '';
    const confirmation=window.prompt(`目标：${target}\n${label}将影响整台服务器及其他程序。等待本应用任务结束后执行。${action==='poweroff'?'关机后需从主机或虚拟机管理工具开机。':'重启后需等待服务器上线并重新建立 SSH 隧道。'}${manualStart}\n输入“${label}”确认：`);
    if (confirmation!==label) {
      if (confirmation!==null) showToast('确认文字不匹配，未执行服务器电源操作。',true);
      return;
    }
    serviceRequest=true;renderServiceControls(snapshot || {});
    try {await post('/api/host-power',{action,confirmation});serviceAction='host-'+action;}
    catch(error){showToast(error.message,true);}
    finally {serviceRequest=false;await refresh();}
  }
  async function controlService(action) {
    if (serviceRequest || startupRequest || serviceAction) return;
    if (['restart', 'stop'].includes(action)) {
      if (settingsDirty) { showToast('请先保存设置，再操作服务。', true); return; }
      if (!window.confirm(action === 'stop'
        ? (snapshot?.platform?.system === 'linux' ? '停止本应用后网页将断开。可在服务器执行 systemctl --user start discordarchive.service 恢复；自动启动偏好保留。等待已有任务结束后停止？' : '停止服务后，网页和手机访问将断开，登录服务的自动拉起也会暂停。再次打开 Mac App 或 Start.command 可恢复。等待已有任务结束后停止？')
        : '等待已有任务结束后重启服务？页面会自动重新连接。')) return;
    }
    serviceRequest = true;
    renderServiceControls(snapshot || {});
    try {
      const result = await post('/api/service', { action });
      if (action === 'pause' || action === 'resume') {
        if (snapshot) snapshot.state.automatic_paused = result.automatic_paused;
        showToast(action === 'pause' ? '自动任务已暂停，正在执行的任务会正常完成。' : '自动任务已恢复。');
      } else serviceAction = action;
      await refresh();
    } catch (error) { showToast(error.message, true); }
    finally { serviceRequest = false; renderServiceControls(snapshot || {}); }
  }
  let authorizationShown=false;
  async function refresh() {
    if (fetching) return;
    fetching = true;
    try {
      const data = await api('/api/status');
      if (serviceInstance && data.service?.instance && serviceInstance !== data.service.instance) {
        serviceAction = null;
        lastJobSeen = null;
      }
      serviceInstance = data.service?.instance || serviceInstance;
      serviceFailedAt = null;
      $('connection-alert').hidden = true;
      renderState(data);
      const requestId=new URLSearchParams(location.search).get('authorize');
      if(requestId && data.remote?.administrator && !authorizationShown){
        authorizationShown=true;
        try{
          const info=await api('/api/helper/authorization?id='+encodeURIComponent(requestId));
          text('helper-device','设备：'+info.device);text('helper-server','服务器：'+location.origin);
          $('helper-authorization').showModal();
          $('helper-approve').onclick=async()=>{
            $('helper-approve').disabled=true;
            try{await post('/api/helper/approve',{request_id:requestId});text('helper-authorization-status','已允许连接。请回到助手完成 Discord 登录和账号确认。');}
            catch(e){text('helper-authorization-status',e.message);$('helper-approve').disabled=false;}
          };
          $('helper-cancel').onclick=()=>$('helper-authorization').close();
        }catch(e){showToast(e.message,true);}
      }

    } catch (error) {
      if (error.status === 401) { $('connection-alert').hidden = true; return; }
      if (!serviceFailedAt) serviceFailedAt = Date.now();
      $('connection-alert').hidden = false;
      $('connection-alert').textContent = serviceAction?.startsWith('host-') ? (serviceAction==='host-reboot' ? '服务器正在重启。等待上线并恢复 Tailscale 后，当前页面会自动重新连接。' : '服务器已关闭。需要从主机或虚拟机管理工具开机。') : serviceAction === 'stop' ? (snapshot?.platform?.system==='linux'?'服务已断开。在服务器执行 systemctl --user start discordarchive.service 可启动。':'服务已断开。再次打开 Mac App 或 Start.command 可启动。') : serviceAction === 'restart' ? '服务正在重启，页面会自动重新连接。若长时间未恢复，请检查服务状态。' : `本地服务连接中断，页面会自动重连。中断时长：${duration((Date.now() - serviceFailedAt) / 1000)}。`;
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
    if (button.disabled) return;
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
      const namePrefix = $('export-prefix').value.trim();
      if (!namePrefix || /[\\/:*?"<>|\u0000-\u001f\u007f]/.test(namePrefix)) throw new Error('文件名前缀不能为空，也不能包含路径或特殊符号。');
      const exportOptions = { ...publicConfig.export, name_prefix: namePrefix, date_format: $('export-date-format').value, sequence_digits: Number($('export-sequence-digits').value), separator: $('export-separator').value };
      if (isLocal) {
        exportOptions.copy_directory = $('export-copy-directory').value.trim();
        if (exportOptions.copy_directory && !/^(\/|~\/|~$)/.test(exportOptions.copy_directory)) throw new Error('另存目录请填写 Mac 上的绝对路径，或选择文件夹。');
      } else delete exportOptions.copy_directory;
      const autoExportEnabled = $('auto-export-enabled').checked;
      const autoExportTimes = parseTimes($('auto-export-times').value);
      if (autoExportEnabled && !autoExportTimes.length) throw new Error('请填写至少一个纽约时间出稿时刻。');
      if (autoExportTimes.length > 24) throw new Error('出稿时刻最多设置 24 个。');
      const copyDirectory = isLocal ? exportOptions.copy_directory : publicConfig.export?.copy_directory;
      if (autoExportEnabled && !String(copyDirectory || '').trim() && !Object.values(publicConfig.delivery || {}).some(row => row.enabled)) throw new Error(isLocal ? '请先在上方选择自动另存目录，再启用定时出稿。' : '请先在 Mac 上设置自动另存目录，再启用定时出稿。');
      const autoExportDays = $('auto-export-weekdays').value;
      const autoExportScales = $('auto-export-scales').value;
      const autoExport = { ...autoExportDefaults, ...publicConfig.auto_export, enabled: autoExportEnabled,
        times: autoExportTimes.length ? autoExportTimes : autoExportDefaults.times,
        weekdays: autoExportDays === 'daily' ? [0, 1, 2, 3, 4, 5, 6] : autoExportDays === 'custom' ? publicConfig.auto_export.weekdays : [0, 1, 2, 3, 4],
        render_scales: autoExportScales === 'both' ? [1, 2] : [Number(autoExportScales)],
        layout: $('auto-export-layout').value, presentation: $('auto-export-presentation').value,
        target: $('auto-export-columns').checked ? 'all' : 'main' };
      const nextConfig = { ...publicConfig, export: exportOptions, auto_export: autoExport, channels: parseChannels($('channels').value), target_author_id: authorId, target_message_url: targetMessageURL, timezone, market_timezone: marketTimezone, day_boundary_hour: boundary, schedule: { ...publicConfig.schedule, enabled: $('schedule-enabled').checked, interval_minutes: interval, times: parseTimes($('times').value), timezone: marketTimezone, window: { ...publicConfig.schedule?.window, enabled: $('window-enabled').checked, start: $('window-start').value, end: $('window-end').value, every_minutes: windowEvery, weekdays: [0, 1, 2, 3, 4] } }, model: { ...publicConfig.model, enabled: modelEnabled, base_url: $('model-base-url').value.trim(), model: $('model-name').value.trim() } };
      button.disabled = true; button.textContent = '正在保存…';
      const result = await api('/api/config', { method: 'PUT', body: JSON.stringify(nextConfig) });
      settingsDirty = false;
      hydrateConfig(result.config || (result.channels ? result : nextConfig));
      text('config-save-status', '设置已保存。');
      showToast('设置已保存，自动计划将使用新配置。');
      await refresh();
      if (onboardingEditing) {
        onboardingEditing = false;
        $('advanced-settings').open = false;
        $('capture-button').scrollIntoView({block:'center'});
        $('capture-button').focus();
      }
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
  function renderBusy(draft,target,scale=selectedRenderScale(draft)) {
    const id = getDraftId(draft);
    return renderPending.has(`${id}:${target}:${scale}`) || remoteRenderJobs.some(job => job.draft_id === id && Number(job.render_scale || 1) === scale && [target,'all'].includes(job.target || 'main'));
  }
  async function renderImage(draft,target='main',scale=selectedRenderScale(draft)) {
    const id = getDraftId(draft);
    if (!id || renderBusy(draft,target,scale)) return;
    const key = `${id}:${target}:${scale}`;
    let jobId;
    renderPending.add(key); renderDrafts(true);
    try {
      const result = await post('/api/render', { draft_id: id,target,render_scale:scale });
      jobId = result.id;
      showToast(result.deduplicated ? '这份图片已经在生成。' : target === 'mobile' ? '正在生成分栏图，完成后可按频道查看。' : '正在生成主图，完成后可直接下载。');
    } catch (error) { showToast(error.message, true); }
    finally {
      await refresh(); renderPending.delete(key); renderDrafts(true);
      if (jobId && snapshot?.state?.last_job_id === jobId && snapshot.state.last_job_status === 'success')
        showToast(target === 'mobile' ? '分栏图已就绪。' : '图片已就绪。');
    }
  }
  function updateClock() {
    text('current-time', dateTime(new Date(), true));
    if (snapshot) {
      const connectivity = snapshot.connectivity || snapshot.state?.connectivity || {};
      const retryAt = first(connectivity.retry_at, connectivity.next_retry_at, snapshot.state?.retry_at, snapshot.state?.next_retry_at);
      if (snapshot.state?.automatic_paused) text('retry-countdown', '已暂停');
      else if (retryAt) text('retry-countdown', countdown(retryAt));
      const lastSuccess = first(snapshot.state?.last_success_at, snapshot.state?.last_capture_success_at, snapshot.state?.last_success, snapshot.state?.last_capture_at, connectivity.last_success_at);
      if (lastSuccess) text('offline-duration', elapsed(lastSuccess));
    }
  }

  document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
  document.querySelectorAll('[data-go]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.go)));
  $('service-pause').addEventListener('click', () => controlService(snapshot?.state?.automatic_paused ? 'resume' : 'pause'));
  $('service-restart').addEventListener('click', () => controlService('restart'));
  $('service-stop').addEventListener('click', () => controlService('stop'));
  $('startup-enabled').addEventListener('change',changeStartup);
  $('host-reboot').addEventListener('click',()=>controlHostPower('reboot'));
  $('host-poweroff').addEventListener('click',()=>controlHostPower('poweroff'));
  $('refresh-button').addEventListener('click', refresh);
  $('capture-button').addEventListener('click', capture);
  $('connect-browser-button').addEventListener('click', connectBrowser);
  $('connect-browser-fallback').addEventListener('click',()=>connectBrowser({fallback:true}));
  $('draft-form').addEventListener('submit', createDraft);
  document.querySelectorAll('input[name="scope"]').forEach((input) => input.addEventListener('change', changeScope));
  $('draft-mode').addEventListener('change', updateMode);
  $('draft-layout').addEventListener('change', () => { if (snapshot) renderState(snapshot); });
  $('clawbot-connect').addEventListener('click', connectClawBot);
  $('clawbot-verify').addEventListener('click', verifyClawBot);
  $('delivery-form').addEventListener('submit', event => {event.preventDefault(); saveDelivery();});
  $('delivery-form').addEventListener('input', () => {deliveryDirty = true; text('delivery-save-status', '有未保存的推送设置。');});
  document.querySelectorAll('[data-delivery-test]').forEach(button => button.addEventListener('click', () => saveDelivery(button.dataset.deliveryTest)));
  $('config-form').addEventListener('submit', saveConfig);
  $('config-form').addEventListener('input', () => { settingsDirty = true; text('config-save-status', '有未保存的设置。'); });
  for (const id of ['export-prefix', 'export-date-format', 'export-sequence-digits', 'export-separator']) {
    $(id).addEventListener('input', updateExportPreview);
    $(id).addEventListener('change', updateExportPreview);
  }
  $('export-directory-choose').addEventListener('click', chooseExportDirectory);
  document.querySelectorAll('.credential-form').forEach((form) => form.addEventListener('submit', saveCredential));
  $('draft-search').addEventListener('input', (event) => {
    draftSearch = event.target.value.trim(); clearTimeout(draftSearchTimer);
    // Invalidate an older search immediately, even during the debounce window.
    draftListSequence += 1; draftListLoading = false; draftLibrary = { items: [], total: 0, offset: 0, has_more: false, revision: null };
    renderDrafts(true); draftSearchTimer = setTimeout(() => loadDraftPage(0), 250);
  });
  $('draft-page-previous').addEventListener('click', () => loadDraftPage(Math.max(0, draftPage().offset - draftPageSize)));
  $('draft-page-next').addEventListener('click', () => loadDraftPage(draftPage().offset + draftPageSize));
  $('draft-list-retry').addEventListener('click', () => loadDraftPage(draftPage().offset));
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
  setExportDirectoryAccess();
  setupDisclosureMotion();
  setView(location.hash.slice(1), false);
  changeScope(); updateClock(); refresh();
  setInterval(() => { if (!loginRequired) refresh(); }, 3000);
  setInterval(updateClock, 1000);
})();
