// sidebar.js — 会话侧栏视图：列表渲染、搜索过滤、统计脚注、抽屉关闭。
// 数据只读 store；选中会话等流程由 app.js 编排，本模块通过 bus 响应刷新。

import { store, allSids, counts, isAnyDirty } from './store.js';
import { $, el, esc, lastActivity, relTime } from './util.js';
import { icon } from './icons.js';
import { confirmModal } from './ui.js';
import { bus } from './bus.js';

function totalEntries() {
  let t = 0;
  allSids().forEach((s) => { const n = counts(s); t += n.u + n.c + n.p; });
  return t;
}

export function renderSidebar() {
  const box = $('sessList');
  if (!box) return;
  box.textContent = '';
  const sids = allSids()
    .filter((s) => !store.sessFilter || s.toLowerCase().includes(store.sessFilter.toLowerCase()))
    .sort((a, b) => lastActivity(b, store.snapshot) - lastActivity(a, store.snapshot));
  $('sessCnt').textContent = sids.length + ' 个';
  renderSideFoot();
  if (!sids.length) {
    box.innerHTML = `<div class="empty-state small">
      <div class="es-title">${store.sessFilter ? '无匹配会话' : '暂无会话'}</div>
      <div class="es-desc">${store.sessFilter ? '换个关键词试试' : '插件会在聊天记录积累后自动学习'}</div>
    </div>`;
    return;
  }
  sids.forEach((sid) => {
    const n = counts(sid);
    const active = sid === store.sid;
    const d = el('div', 'sess' + (active ? ' active' : ''));
    d.setAttribute('role', 'listitem');
    d.setAttribute('aria-current', active ? 'true' : 'false');
    d.innerHTML = `
      <span class="sid-dot" style="background:${active ? 'var(--c-primary)' : 'var(--c-text-3)'}"></span>
      <span class="sid-txt">${esc(sid)}</span>
      <span class="sess-meta">
        <span class="mini-stats" title="通用/情境/特定 条目数">
          <i style="background:var(--c-universal)"></i><u>${n.u}</u>
          <i style="background:var(--c-contextual)"></i><u>${n.c}</u>
          <i style="background:var(--c-specific)"></i><u>${n.p}</u>
        </span>
        <span class="sess-time" title="最近活动">${relTime(lastActivity(sid, store.snapshot))}</span>
      </span>`;
    d.addEventListener('click', () => selectSessionById(sid));
    box.appendChild(d);
  });
}

function renderSideFoot() {
  const total = totalEntries();
  $('sideFoot').innerHTML = `
    <span class="sf-item">${icon('users', 13)} ${allSids().length} 会话</span>
    <span class="sf-sep"></span>
    <span class="sf-item">${icon('layers', 13)} ${total} 条目</span>
    ${store.injectOn !== null ? `<span class="sf-sep"></span>
      <span class="sf-item">注入 ${store.injectOn ? '开' : '关'}</span>` : ''}`;
}

/** 切换会话（脏数据确认后）——由 app.js 与侧栏共用 */
export async function selectSessionById(sid) {
  if (sid !== store.sid && isAnyDirty()) {
    const ok = await confirmModal({
      title: '有未保存的修改',
      body: '切换会话将丢弃当前未保存的修改，确定继续吗？',
    });
    if (!ok) return;
  }
  bus.emit('session-select', sid);
}

/** 关闭移动端抽屉 */
export function closeDrawer() {
  $('sidebar').classList.remove('open');
  $('scrim').classList.remove('show');
}
