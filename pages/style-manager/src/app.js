// app.js — 入口：桥接初始化、全局事件、路由编排。
// 视图渲染与局部交互在 views.js；状态在 store.js；桥接封装在 api.js。

import {
  store, allSids, isAnyDirty, selectSession,
} from './store.js';
import { Api, setBridge } from './api.js';
import * as Views from './views.js';
import {
  $, toast, confirmModal, initTheme, toggleTheme, clone,
} from './util.js';

let bridge = null;

function applyInjectPill() {
  const dot = $('injectDot');
  const txt = $('injectTxt');
  if (store.injectOn === null) { dot.className = 'dot'; txt.textContent = '注入：—'; }
  else if (store.injectOn) { dot.className = 'dot on'; txt.textContent = '注入：开'; }
  else { dot.className = 'dot off'; txt.textContent = '注入：关'; }
}

async function loadAll() {
  let snap;
  try {
    snap = await Api.snapshot();
  } catch (e) {
    toast('加载失败：' + (e && e.message ? e.message : e), true);
    $('sessList').innerHTML = '<div class="empty" style="padding:24px">加载失败，点右上角「刷新」重试</div>';
    return;
  }
  store.snapshot = snap;

  // 全局统计（可选：旧后端无此接口时优雅降级）
  try {
    const st = await Api.stats();
    store.injectOn = st.injection_enabled;
    store.caps = st.caps;
    applyInjectPill();
  } catch (e) {
    store.injectOn = null;
    applyInjectPill();
  }

  const sids = allSids();
  if (!sids.length) {
    $('noSelect').style.display = '';
    $('work').style.display = 'none';
    Views.renderSidebar();
    return;
  }
  if (!store.sid || !sids.includes(store.sid)) selectSession(sids[0]);
  else selectSession(store.sid);
  $('noSelect').style.display = 'none';
  $('work').style.display = '';
  Views.renderSidebar();
  Views.renderSessionHead();
  Views.switchTab('overview');
}

async function refreshAll() {
  if (isAnyDirty()) {
    const ok = await confirmModal({
      title: '有未保存的修改',
      body: '刷新将丢弃当前修改，确定继续吗？',
    });
    if (!ok) return;
  }
  await loadAll();
}

async function saveAll() {
  for (const l of ['universal', 'contextual', 'specific']) {
    if (store.dirty[l]) await Views.saveLayer(l);
  }
}

async function discardAll() {
  const ok = await confirmModal({ title: '丢弃修改', body: '确定丢弃所有未保存的修改？' });
  if (!ok) return;
  const sid = store.sid;
  store.dirty = {};
  const s = store.snapshot;
  store.model = {
    universal: clone((s.universal && s.universal[sid]) || []),
    contextual: clone((s.contextual && s.contextual[sid]) || []),
    specific: clone((s.specific && s.specific[sid]) || []),
  };
  Views.switchTab(store.tab);
}

function onKey(e) {
  const tag = document.activeElement && document.activeElement.tagName;
  if (e.key === '/' && tag !== 'INPUT' && tag !== 'TEXTAREA') {
    e.preventDefault();
    $('sessSearch').focus();
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault();
    if (store.sid && store.tab !== 'overview') Views.saveLayer(store.tab);
  }
  if (e.key === 'Escape') {
    $('overlay').classList.remove('show');
    $('helpOv').classList.remove('show');
  }
}

function wireEvents() {
  $('btnRefresh').onclick = refreshAll;
  $('btnTheme').onclick = toggleTheme;
  $('btnHelp').onclick = () => $('helpOv').classList.add('show');
  $('helpClose').onclick = () => $('helpOv').classList.remove('show');
  $('helpOv').onclick = (e) => { if (e.target === $('helpOv')) $('helpOv').classList.remove('show'); };

  $('btnLearn').onclick = Views.learnNow;
  $('btnClear').onclick = Views.clearSession;
  $('btnExport').onclick = Views.exportSession;

  $('hamb').onclick = () => { $('sidebar').classList.toggle('open'); $('scrim').classList.toggle('show'); };
  $('scrim').onclick = () => { $('sidebar').classList.remove('open'); $('scrim').classList.remove('show'); };

  $('sessSearch').addEventListener('input', (e) => { store.sessFilter = e.target.value; Views.renderSidebar(); });

  document.querySelectorAll('.tab').forEach((t) => {
    const go = () => Views.switchTab(t.dataset.tab);
    t.addEventListener('click', go);
    t.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
    });
  });

  $('mCancel').onclick = () => $('overlay').classList.remove('show');
  $('overlay').onclick = (e) => { if (e.target === $('overlay')) $('overlay').classList.remove('show'); };

  $('saveAll2').onclick = saveAll;
  $('discardAll2').onclick = discardAll;

  document.addEventListener('keydown', onKey);
}

async function boot() {
  initTheme();
  bridge = window.AstrBotPluginPage;
  if (!bridge) {
    toast('请在 AstrBot 面板中打开此页面（扩展 → 插件详情 → 打开插件页面）', true);
    return;
  }
  try { await bridge.ready(); } catch (e) { /* 桥接 ready 可选 */ }
  setBridge(bridge);
  await loadAll();
  wireEvents();
}

boot();
