const $ = id => document.getElementById(id);
const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
let config = null, historyPage = 1, statsPage = 1;
let historyVersion = 0, statsVersion = 0, previewVersion = 0;
const kernelName = id => config?.kernels.find(k => k.id === id)?.name || id;
const notify = (text, kind = '') => { $('notice').textContent = text; $('notice').className = `notice ${kind}`; };
const sourceName = value => ({command:'指令', agent:'Agent 工具', page_test:'后台测试'}[value] || value);
const displayTime = value => new Date(value).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false});
const textNode = (tag, value, className = '') => { const n = document.createElement(tag); n.textContent = value; n.className = className; return n; };
const tokenNumber = value => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('zh-CN') : '未知';
const tokenScope = scope => ({root_selection:'指令取根气',page_interpretation:'后台 AI 解读',agent_context:'外部 Agent',historical:'旧记录'}[scope] || scope);
function tokenSummary(record) {
  const usage = record.token_usage;
  if (!usage) return '未记录';
  if (usage.status === 'not_used') return '0 · 未请求模型';
  if (usage.status === 'external') return '未知 · 外部 Agent';
  return tokenNumber(usage.total_tokens) + (usage.status === 'partial' ? ' · 部分已知' : '');
}
function tokenDetail(record) {
  const usage = record.token_usage;
  if (!usage) return '旧卦例未记录 Token，无法补算。';
  const counts = data => `输入 ${tokenNumber(data.input_tokens)} · 输出 ${tokenNumber(data.output_tokens)} · 缓存命中 ${tokenNumber(data.cached_tokens)} · 总计 ${tokenNumber(data.total_tokens)}`;
  const lines = [`Token：${tokenSummary(record)}`, counts(usage)];
  for (const [index, call] of (usage.calls || []).entries()) {
    lines.push(`${index + 1}. ${tokenScope(call.scope)}${call.provider_id ? ` · ${call.provider_id}` : ''}\n${counts(call)}`);
  }
  if (usage.status === 'external') lines.push('根气来自外部 Agent 对话，无法准确拆分本卦消耗，未将整段对话算入。');
  if (usage.status === 'unknown' || usage.status === 'partial') lines.push('未返回的用量保留未知，不按文字长度估算。');
  lines.push('缓存命中已包含在输入中，不重复加到总计。');
  return lines.join('\n');
}

async function busy(button, action, label = '处理中…') {
  const before = button.textContent; button.disabled = true; button.textContent = label;
  try { return await action(); } catch (e) { notify(e.message || '操作失败，请重试。', 'error'); }
  finally { button.textContent = before; button.disabled = false; }
}
function showTab(name) {
  for (const section of document.querySelectorAll('.tab')) section.hidden = section.id !== `tab-${name}`;
  for (const button of document.querySelectorAll('.nav')) {
    const active = button.dataset.tab === name;
    button.classList.toggle('active', active);
    active ? button.setAttribute('aria-current','page') : button.removeAttribute('aria-current');
  }
  if (config && name === 'history') refreshHistory().catch(e => notify(e.message,'error'));
  if (config && name === 'stats') refreshStats().catch(e => notify(e.message,'error'));
}
for (const button of document.querySelectorAll('.nav')) button.addEventListener('click', () => showTab(button.dataset.tab));
function updateKernelDescription() {
  $('kernel-description').textContent = config?.kernels.find(k => k.id === $('kernel-id').value)?.description || '';
}
function applySettings(data) {
  const previousTest = $('test-kernel').value;
  config = data;
  for (const id of ['kernel-id','test-kernel']) {
    $(id).replaceChildren(...data.kernels.map(k => { const option = textNode('option',k.name); option.value = k.id; return option; }));
  }
  $('kernel-id').value = data.values.kernel_id;
  $('test-kernel').value = previousTest || data.values.kernel_id;
  $('active-kernel').textContent = `当前：${kernelName(data.values.kernel_id)}`;
  $('page-provider').value = data.values.page_provider_id;
  $('command-provider').value = data.values.command_provider_id;
  $('daily-limit').value = data.values.ai_daily_limit;
  $('timeout').value = data.values.command_analysis_timeout_seconds;
  $('command-ai').checked = data.values.command_ai_analysis_enabled;
  $('tool-enabled').checked = data.values.llm_tool_enabled;
  $('providers').replaceChildren(...data.providers.map(id => {const option = document.createElement('option'); option.value = id; return option;}));
  $('conventions').replaceChildren(...(data.kernels.find(k => k.id === 'document_v2')?.conventions || []).map(text => textNode('li',text)));
  updateKernelDescription(); $('cast').disabled = false; $('save-settings').disabled = false;
}
$('kernel-id').addEventListener('change', updateKernelDescription);
$('reload-settings').addEventListener('click', event => busy(event.currentTarget, async () => {applySettings(await bridge.apiGet('settings')); notify('已重新载入配置。','success');}));
$('settings-form').addEventListener('submit', event => {
  event.preventDefault();
  busy($('save-settings'), async () => {
    const values = {kernel_id:$('kernel-id').value, page_provider_id:$('page-provider').value.trim(), command_provider_id:$('command-provider').value.trim(), ai_daily_limit:Number($('daily-limit').value), command_analysis_timeout_seconds:Number($('timeout').value), command_ai_analysis_enabled:$('command-ai').checked, llm_tool_enabled:$('tool-enabled').checked};
    const result = await bridge.apiPost('settings', {revision:config.revision, values}); applySettings(result);
    notify(`已保存，正式起卦使用${kernelName(values.kernel_id)}。`,'success');
  }, '正在保存…');
});
$('sample').addEventListener('click', () => { $('question').value = '这次销售交易能否达到预期，何时能达成？'; $('numbers').value = '15997'; $('root').value = '水'; $('test-kernel').value = 'document_v2'; });
function showResult(data) {
  const record = data.record;
  $('result-heading').textContent = `本次判定 · ${record.result.verdict}`;
  $('result-kernel').textContent = kernelName(record.kernel);
  $('preview-empty').hidden = true;
  $('chart').hidden = !data.image;
  if (data.image) $('chart').src = data.image; else $('chart').removeAttribute('src');
  $('image-warning').textContent = data.image_error || ''; $('image-warning').hidden = !data.image_error;
  $('reading-details').hidden = false; $('reading-details').open = !data.image;
  $('reading').textContent = record.reading;
  $('ai-reading').textContent = record.ai_interpretation || record.ai_error || '本次未请求 AI 解读。';
  $('result-tokens').hidden = false; $('result-tokens').textContent = `Token：${tokenSummary(record)}`;
  $('result-token-detail').textContent = tokenDetail(record);
}
$('test-form').addEventListener('submit', event => {
  event.preventDefault();
  busy($('cast'), async () => {
    notify($('with-ai').checked ? '正在计算并请求模型解读，请稍候…' : '正在本地计算并生成卦图…');
    const request_id = (crypto.randomUUID?.() || `${Date.now()}_${Math.random().toString(36).slice(2)}`).replaceAll('-','_');
    const data = await bridge.apiPost('test', {question:$('question').value.trim(), numbers:$('numbers').value, root:$('root').value, kernel:$('test-kernel').value, with_ai:$('with-ai').checked, request_id});
    showResult(data); notify(data.record.ai_error || '测试卦例已保存，正式群聊排行与额度不受影响。', data.record.ai_error ? 'error' : 'success');
  }, '正在起卦…');
});
function rankRows(target, rows, label) {
  if (!rows.length) { const tr = document.createElement('tr'), td = textNode('td',`暂无${label}记录`,'muted'); td.colSpan = 4; tr.append(td); $(target).replaceChildren(tr); return; }
  $(target).replaceChildren(...rows.map(row => {
    const tr = document.createElement('tr'), who = document.createElement('td');
    who.append(textNode('span',row.name || row.id),textNode('small',`${row.id} · ${row.platform}`));
    tr.append(textNode('td',row.rank),who,textNode('td',row.count),textNode('td',row.ai_count)); return tr;
  }));
}
async function refreshStats() {
  const version = ++statsVersion, data = await bridge.apiGet('stats',{page:statsPage,limit:30});
  if (version !== statsVersion) return;
  $('stat-total').textContent = data.total; $('stat-ai').textContent = data.ai_total;
  $('stat-scope').textContent = `${data.group_total} / ${data.user_total}`; $('stat-tests').textContent = data.test_total;
  $('stats-since').textContent = `记录起点：${data.started_at ? displayTime(data.started_at) : '尚无记录'}。只统计已保存的正式卦例；个人按平台与账号合并各群次数，后台测试不参与排行。`;
  rankRows('group-ranks',data.groups,'群调用'); rankRows('user-ranks',data.users,'个人调用');
  const pages = Math.max(1,Math.ceil(Math.max(data.group_total,data.user_total)/data.limit));
  $('stats-page').textContent = `第 ${data.page} / ${pages} 页`;
  $('stats-prev').disabled = data.page <= 1; $('stats-next').disabled = data.page >= pages;
}
async function openHistory(record) {
  const version = ++previewVersion;
  $('history-dialog').showModal(); $('history-detail-meta').textContent = `${displayTime(record.created_at)} · ${record.user_name || record.user_id} · ${record.numbers} · ${kernelName(record.kernel)}`;
  $('history-detail-reading').textContent = `${record.question}\n\n${record.reading}`;
  $('history-detail-ai').textContent = record.ai_interpretation || record.ai_error || '未请求 AI 解读。';
  $('history-detail-tokens').textContent = tokenDetail(record);
  $('history-chart').hidden = true; $('history-chart').removeAttribute('src'); $('history-image-warning').textContent = '正在生成历史卦图预览…';
  try {
    const data = await bridge.apiGet(`history/${record.id}/preview`);
    if (version !== previewVersion) return;
    $('history-detail-tokens').textContent = tokenDetail(data.record);
    $('history-image-warning').textContent = data.image_error || '';
    if (data.image) { $('history-chart').src = data.image; $('history-chart').hidden = false; }
  } catch (e) { if (version === previewVersion) $('history-image-warning').textContent = e.message; }
}
$('close-dialog').addEventListener('click', () => {previewVersion++; $('history-dialog').close();});
$('history-dialog').addEventListener('cancel', () => {previewVersion++;});
async function refreshHistory() {
  const version = ++historyVersion;
  const data = await bridge.apiGet('history',{page:historyPage,limit:20,source:$('history-source').value});
  if (version !== historyVersion) return;
  $('history-rows').replaceChildren(...data.records.map(record => {
    const tr = document.createElement('tr');
    const time = textNode('td',displayTime(record.created_at)); time.append(textNode('small',sourceName(record.source)));
    const who = textNode('td',record.user_name || record.user_id); who.append(textNode('small',record.user_id), textNode('small',record.group_name || record.group_id || (record.source === 'page_test' ? '管理后台' : '私聊')));
    const numbers = textNode('td',record.numbers); numbers.append(textNode('small',kernelName(record.kernel)));
    const verdict = document.createElement('td'); verdict.append(textNode('span',record.result.verdict,'badge'));
    const action = document.createElement('td'), button = textNode('button','查看 / 预览','secondary'); button.addEventListener('click',() => openHistory(record)); action.append(button);
    tr.append(time,who,textNode('td',record.question),numbers,verdict,textNode('td',record.ai_interpretation ? '有 AI 解读' : record.ai_status === 'failed' ? 'AI 失败' : '程序解卦'),textNode('td',tokenSummary(record)),action); return tr;
  }));
  if (!data.records.length) { const tr = document.createElement('tr'), td = textNode('td','暂无卦例。可先到起卦实验室生成一条测试记录。','muted'); td.colSpan = 8; tr.append(td); $('history-rows').append(tr); }
  const pages = Math.max(1,Math.ceil(data.total/data.limit)); $('history-page').textContent = `共 ${data.total} 条 · 第 ${data.page} / ${pages} 页`;
  $('history-prev').disabled = data.page <= 1; $('history-next').disabled = data.page >= pages;
}
for (const [id,action] of [['refresh-stats',refreshStats],['refresh-history',refreshHistory]]) $(id).addEventListener('click', e => busy(e.currentTarget,action));
for (const [id,delta] of [['stats-prev',-1],['stats-next',1]]) $(id).addEventListener('click',() => {statsPage += delta; refreshStats().catch(e => notify(e.message,'error'));});
for (const [id,delta] of [['history-prev',-1],['history-next',1]]) $(id).addEventListener('click',() => {historyPage += delta; refreshHistory().catch(e => notify(e.message,'error'));});
$('history-source').addEventListener('change',() => {historyPage=1; refreshHistory().catch(e => notify(e.message,'error'));});
$('export-all').addEventListener('click', e => busy(e.currentTarget,async () => {await bridge.download('export',{},'数字卦卦例库.zip'); notify('全部卦例已导出：JSON 存储文件与 Markdown 字段说明。','success');},'正在导出…'));
try {
  if (!bridge) throw new Error('请从 AstrBot 插件详情中的管理页面打开；本页需要已登录的 Dashboard 连接。');
  await bridge.ready(); applySettings(await bridge.apiGet('settings')); notify('已连接。可以测试起卦或调整正式内核。');
} catch (e) { notify(e.message,'error'); }
