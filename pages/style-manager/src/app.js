// app.js — 入口编排：桥接初始化、全局事件、路由切换、会话级操作。
// 模块边界：状态在 store.js，API 在 api.js，组件在 ui.js，
// 视图在 sidebar.js / overview.js / layer.js；本文件只做编排。

import { store, allSids, selectSession, isAnyDirty, counts, LAYERS } from './store.js';
import { Api, setBridge } from './api.js';
import { $, el, esc, initTheme, toggleTheme } from './util.js';
import { icon } from './icons.js';
import { toast, confirmModal, skeleton } from './ui.js';
import { bus } from './bus.js';
import { renderSidebar, selectSessionById, closeDrawer } from './sidebar.js';
import { renderOverview, setLearnHandler } from './overview.js';
import { renderLayer, renderRows, saveLayer, validateLayer, clearAllDirty } from './layer.js';

/* ============ 注入状态指示 ============ */
function applyInjectPill() {
  const dot = $('injectDot');
  const txt = $('injectTxt');
  if (store.injectOn === null) { dot.className = 'dot'; txt.textContent = '注入：—'; }
  else if (store.injectOn) { dot.className = 'dot on'; txt.textContent = '注入：开'; }
  else { dot.className = 'dot off'; txt.textContent = '注入：关'; }
}

/* ============ 会话头 ============ */
function renderSessionHead() {
  const sid = store.sid;
  if (!sid) return;
  const n = counts(sid);
  const inj = store.injectOn;
  $('curSid').textContent = sid;
  $('curChips').innerHTML = `
    <span class="chip"><i style="background:var(--c-universal)"></i>通用 ${n.u}</span>
    <span class="chip"><i style="background:var(--c-contextual)"></i>情境 ${n.c}</span>
    <span class="chip"><i style="background:var(--c-specific)"></i>特定 ${n.p}</span>
    <span class="chip inj"><i class="${inj === null ? 'dot' : inj ? 'dot on' : 'dot off'}"></i>注入 ${inj === null ? '—' : (inj ? '开' : '关')}</span>`;
}

/* ============ 数据加载 ============ */
async function loadAll() {
  store.loading = true;
  $('noSelect').style.display = 'none';
  $('work').style.display = 'none';
  $('tabOverview').innerHTML = skeleton(5);
  $('tabLayer').innerHTML = skeleton(4);

  let snap;
  try {
    snap = await Api.snapshot();
  } catch (e) {
    toast('加载失败：' + (e && e.message ? e.message : e), 'error');
    $('noSelect').style.display = '';
    $('tabOverview').innerHTML = '';
    store.loading = false;
    return;
  }
  store.snapshot = snap;

  // 全局统计（旧后端无此接口时优雅降级）
  try {
    const st = await Api.stats();
    store.injectOn = st.injection_enabled;
    store.caps = st.caps;
  } catch (e) {
    store.injectOn = null;
  }
  applyInjectPill();

  const sids = allSids();
  store.loading = false;
  if (!sids.length) {
    $('noSelect').style.display = '';
    $('work').style.display = 'none';
    renderSidebar();
    return;
  }
  if (!store.sid || !sids.includes(store.sid)) selectSession(sids[0]);
  else selectSession(store.sid);
  showWork();
  renderSidebar();
  renderSessionHead();
  switchTab('overview');
}

function showWork() {
  $('noSelect').style.display = 'none';
  $('work').style.display = '';
}

/* ============ Tab 路由 ============ */
export function switchTab(tab) {
  store.tab = tab;
  document.querySelectorAll('.tab').forEach((t) => {
    const active = t.dataset.tab === tab;
    t.classList.toggle('active', active);
    t.setAttribute('aria-selected', active ? 'true' : 'false');
    t.setAttribute('tabindex', active ? '0' : '-1');
  });
  $('tabOverview').style.display = tab === 'overview' ? '' : 'none';
  $('tabLayer').style.display = tab === 'overview' ? 'none' : '';
  moveTabIndicator();
  if (tab === 'overview') renderOverview();
  else renderLayer(tab);
}

/* ============ 滑动 Tab 指示器 ============ */
function moveTabIndicator() {
  const ind = document.querySelector('.tab-ind');
  if (!ind) return;
  const active = document.querySelector('.tab.active');
  if (!active) { ind.style.width = '0'; return; }
  ind.style.width = active.offsetWidth + 'px';
  ind.style.transform = `translateX(${active.offsetLeft}px)`;
}

/* ============ 全局刷新（保留当前会话） ============ */
async function refreshSnapshotOnly(discardLocal = false) {
  try {
    const snap = await Api.snapshot();
    store.snapshot = snap;
    if (store.sid && (discardLocal || !isAnyDirty())) selectSession(store.sid);
    renderSidebar();
    if (store.sid) {
      renderSessionHead();
      if (discardLocal) switchTab('overview');
      else if (store.tab === 'overview') renderOverview();
      else renderLayer(store.tab);
    }
  } catch (e) {
    toast('刷新失败：' + (e && e.message ? e.message : e), 'error');
  }
}

async function refreshAll() {
  if (isAnyDirty()) {
    const ok = await confirmModal({
      title: '有未保存的修改',
      body: '刷新将丢弃当前修改，确定继续吗？',
    });
    if (!ok) return;
    clearAllDirty();
  }
  await loadAll();
}

/* ============ 会话级操作 ============ */
export async function learnNow() {
  if (!store.sid) return;
  if (isAnyDirty()) {
    toast('请先保存或丢弃当前修改，再立即学习', 'error');
    return;
  }
  const btn = $('btnLearn');
  if (btn.disabled) return;
  const o = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="btn-spin"></span> 学习中`;
  try {
    await Api.learn(store.sid);
    toast('学习完成，已刷新数据');
    await refreshSnapshotOnly();
  } catch (e) {
    toast('学习触发失败：' + (e && e.message ? e.message : e) + '（也可到聊天发送「学习总结」）', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = o;
  }
}

export async function clearSession() {
  if (!store.sid) return;
  const ok = await confirmModal({
    title: '清空本会话',
    body: isAnyDirty()
      ? '将删除服务器数据，本地未保存修改也会丢弃，且不可撤销。确定吗？'
      : '将删除该会话的全部通用/情境/特定表征，且不可撤销。确定吗？',
    okText: '清空',
    icon: 'trash',
  });
  if (!ok) return;
  try {
    await Api.clear(store.sid);
    clearAllDirty();
    await refreshSnapshotOnly(true);
    toast('已清空本会话');
  } catch (e) {
    toast('清空失败：' + (e && e.message ? e.message : e), 'error');
  }
}

export async function exportSession() {
  if (!store.sid) return;
  if (isAnyDirty()) toast('导出的是服务器已保存版本，不包含当前未保存修改');
  try {
    const raw = await Api.exportSession(store.sid);
    const data = raw && raw.data ? raw.data : raw;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = store.sid + '.style.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
    toast('已导出 JSON');
  } catch (e) {
    toast('导出失败：' + (e && e.message ? e.message : e), 'error');
  }
}

export async function saveAll() {
  const sid = store.sid;
  const dirtyKeys = ['universal', 'contextual', 'specific'].filter((key) => store.dirty[key]);
  for (const key of dirtyKeys) {
    const validation = validateLayer(key);
    if (!validation.ok) {
      toast(`${LAYERS.find((layer) => layer.key === key).name}层：${validation.message}`, 'error');
      return { ok: false, saved: 0, code: 'invalid' };
    }
  }
  let saved = 0;
  for (const key of dirtyKeys) {
    if (store.sid !== sid) return { ok: false, saved, code: 'session_changed' };
    const result = await saveLayer(key, { quiet: true });
    if (!result.ok) {
      const layerName = LAYERS.find((layer) => layer.key === key).name;
      const reason = result.code === 'revision_conflict' ? '发生冲突' : '保存失败';
      toast(`已保存 ${saved} 层，${layerName}层${reason}`, 'error');
      return { ok: false, saved, code: result.code };
    }
    saved += 1;
  }
  if (saved > 1) toast(`已保存 ${saved} 层`);
  return { ok: true, saved };
}

async function discardAll() {
  const ok = await confirmModal({
    title: '丢弃修改',
    body: '确定丢弃所有未保存的修改？',
    okText: '丢弃',
  });
  if (!ok) return;
  clearAllDirty();
  const prevTab = store.tab;
  selectSession(store.sid);
  switchTab(prevTab);
}

/* ============ 键盘快捷键 ============ */
function onKey(e) {
  const tag = document.activeElement && document.activeElement.tagName;
  if (e.key === '/' && tag !== 'INPUT' && tag !== 'TEXTAREA') {
    e.preventDefault();
    $('sessSearch').focus();
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault();
    if (store.sid && store.tab !== 'overview') saveLayer(store.tab);
  }
  if (e.key === 'Escape') {
    $('overlay').classList.remove('show');
    $('helpOv').classList.remove('show');
    closeDrawer();
  }
}

/* ============ 事件绑定 ============ */
function wireEvents() {
  $('btnRefresh').onclick = refreshAll;
  $('btnTheme').onclick = () => {
    toggleTheme();
    // 刷新主题图标
    $('btnTheme').innerHTML = icon(document.documentElement.dataset.theme === 'dark' ? 'sun' : 'moon', 17);
  };
  $('btnHelp').onclick = () => $('helpOv').classList.add('show');
  $('helpClose').onclick = () => $('helpOv').classList.remove('show');
  $('helpOv').onclick = (e) => { if (e.target === $('helpOv')) $('helpOv').classList.remove('show'); };

  $('btnLearn').onclick = learnNow;
  $('btnClear').onclick = clearSession;
  $('btnExport').onclick = exportSession;

  $('hamb').onclick = () => { $('sidebar').classList.toggle('open'); $('scrim').classList.toggle('show'); };
  $('scrim').onclick = closeDrawer;

  $('sessSearch').addEventListener('input', (e) => {
    store.sessFilter = e.target.value;
    renderSidebar();
  });

  document.querySelectorAll('.tab').forEach((t) => {
    const go = () => switchTab(t.dataset.tab);
    t.addEventListener('click', go);
    t.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
    });
  });

  $('saveAll2').onclick = saveAll;
  $('discardAll2').onclick = discardAll;

  document.addEventListener('keydown', onKey);
  window.addEventListener('resize', moveTabIndicator);
  window.addEventListener('beforeunload', (event) => {
    if (!isAnyDirty()) return;
    event.preventDefault();
    event.returnValue = '';
  });

  // 事件总线：模块解耦后的全局协调
  bus.on('session-select', (sid) => {
    clearAllDirty();
    selectSession(sid);
    showWork();
    renderSidebar();
    renderSessionHead();
    switchTab('overview');
    closeDrawer();
  });
  bus.on('data-changed', () => {
    renderSidebar();
    renderSessionHead();
    if (store.tab === 'overview') renderOverview();
    else renderRows(store.tab);
  });
}

/* ============ 启动 ============ */
async function boot() {
  initTheme();
  // 主题图标初值
  const isDark = document.documentElement.dataset.theme === 'dark';
  $('btnTheme').innerHTML = icon(isDark ? 'sun' : 'moon', 17);

  const bridge = window.AstrBotPluginPage;
  if (!bridge) {
    toast('请在 AstrBot 面板中打开此页面（扩展 → 插件详情 → 打开插件页面）', 'error');
    $('tabOverview').innerHTML = '';
    $('noSelect').style.display = '';
    return;
  }
  try { await bridge.ready(); } catch (e) { /* 桥接 ready 可选 */ }
  setBridge(bridge);
  setLearnHandler(learnNow);
  await loadAll();
  wireEvents();
}

boot();
