// sidebar.js — 会话侧栏视图：列表渲染、搜索过滤、统计脚注、抽屉关闭。
// 数据只读 store；选中会话等流程由 app.js 编排并通过回调传入。

import { store, allSids, counts, sessionDisplayName } from './store.js';
import { $, el, esc, lastActivity, relTime } from './util.js';
import { icon } from './icons.js';

function totalEntries() {
  let t = 0;
  allSids().forEach((s) => { const n = counts(s); t += n.u + n.c + n.p; });
  return t;
}

/** 生成会话头像文本/简写 */
function sessionAvatarText(name) {
  if (!name) return '会';
  const clean = name.replace(/[^\u4e00-\u9fa5a-zA-Z0-9]/g, '');
  return clean.slice(0, 1) || name.slice(0, 1) || '会';
}

export function renderSidebar(onSelect) {
  const box = $('sessList');
  if (!box) return;
  box.textContent = '';
  const sids = allSids()
    .filter((s) => {
      const filter = store.sessFilter.toLowerCase();
      return !filter || s.toLowerCase().includes(filter)
        || sessionDisplayName(s).toLowerCase().includes(filter);
    })
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
    const displayName = sessionDisplayName(sid);
    const avatar = sessionAvatarText(displayName);
    const d = el('button', 'session-item' + (active ? ' active' : ''));
    d.type = 'button';
    d.title = sid;
    d.setAttribute(
      'aria-label',
      displayName === sid ? sid : `${displayName}（${sid}）`,
    );
    d.setAttribute('aria-current', active ? 'true' : 'false');
    d.innerHTML = `
      <div class="session-avatar ${active ? 'active' : ''}">${esc(avatar)}</div>
      <div class="session-content-wrap">
        <div class="session-title-row">
          <span class="session-dot" style="background:${active ? 'var(--accent)' : 'var(--text-3)'}"></span>
          <span class="session-id">${esc(displayName)}</span>
        </div>
        <div class="session-sub-row">
          <span class="session-count" title="通用/情境/特定 条目数">
            <span class="sc-badge sc-u"><i style="background:var(--c-universal)"></i><u>${n.u}</u></span>
            <span class="sc-badge sc-c"><i style="background:var(--c-contextual)"></i><u>${n.c}</u></span>
            <span class="sc-badge sc-p"><i style="background:var(--c-specific)"></i><u>${n.p}</u></span>
          </span>
          <span class="session-time" title="最近活动">${relTime(lastActivity(sid, store.snapshot))}</span>
        </div>
      </div>`;
    d.addEventListener('click', () => onSelect?.(sid));
    box.appendChild(d);
  });
}

function renderSideFoot() {
  const total = totalEntries();
  $('sideFoot').innerHTML = `
    <span class="sf-item" title="全部会话总数">${icon('users', 13)} ${allSids().length} 会话</span>
    <span class="sf-sep"></span>
    <span class="sf-item" title="全部表征条目总数">${icon('layers', 13)} ${total} 条目</span>
    ${store.injectOn !== null ? `<span class="sf-sep"></span>
      <span class="sf-item ${store.injectOn ? 'sf-on' : 'sf-off'}">
        <span class="sf-dot ${store.injectOn ? 'on' : 'off'}"></span>
        注入 ${store.injectOn ? '开' : '关'}
      </span>` : ''}`;
}

/** 关闭移动端抽屉 */
export function closeDrawer() {
  $('sidebar').classList.remove('open');
  $('scrim').classList.remove('show');
  $('hamb').setAttribute('aria-expanded', 'false');
}
