// views.js — 视图渲染与局部交互。
// 所有 DOM 变更集中在此；路由切换(switchTab)与全局事件在 app.js。

import {
  store, LAYERS, allSids, counts, isAnyDirty, selectSession,
} from './store.js';
import { Api } from './api.js';
import {
  $, el, esc, clone, toast, confirmModal, safeRegex, lastActivity,
} from './util.js';

const HINTS = {
  universal: LAYERS[0].hint,
  contextual: LAYERS[1].hint,
  specific: LAYERS[2].hint,
};

/* ============ 脏数据 UI ============ */
function updateDirtyUI() {
  const b = $('dirtyBanner');
  if (isAnyDirty()) b.classList.add('show'); else b.classList.remove('show');
}
function markDirty(key) {
  store.dirty[key] = true;
  const p = $('panel-' + key);
  if (p) p.classList.add('dirty');
  updateDirtyUI();
}

/* ============ 侧栏 ============ */
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
  $('sideFoot').textContent = '共 ' + allSids().length + ' 个会话 · 总条目 ' + totalEntries() + ' 条';
  if (!sids.length) {
    box.innerHTML = '<div class="empty" style="padding:24px">无匹配会话</div>';
    return;
  }
  sids.forEach((sid) => {
    const n = counts(sid);
    const d = el('div', 'sess' + (sid === store.sid ? ' active' : ''));
    d.setAttribute('role', 'listitem');
    d.innerHTML = `
      <span class="sid">${esc(sid)}</span>
      <span class="mini">
        <i style="background:var(--c-universal)"></i><u>${n.u}</u>
        <i style="background:var(--c-contextual)"></i><u>${n.c}</u>
        <i style="background:var(--c-specific)"></i><u>${n.p}</u>
      </span>`;
    d.addEventListener('click', () => selectSessionById(sid));
    box.appendChild(d);
  });
}

/* ============ 会话切换（含脏数据确认） ============ */
export async function selectSessionById(sid) {
  if (sid !== store.sid && isAnyDirty()) {
    const ok = await confirmModal({
      title: '有未保存的修改',
      body: '切换会话将丢弃当前未保存的修改，确定继续吗？',
    });
    if (!ok) return;
  }
  selectSession(sid);
  $('noSelect').style.display = 'none';
  $('work').style.display = '';
  renderSessionHead();
  switchTab('overview');
  updateDirtyUI();
  renderSidebar();
  $('sidebar').classList.remove('open');
  $('scrim').classList.remove('show');
}

/* ============ 会话头 ============ */
export function renderSessionHead() {
  const sid = store.sid;
  if (!sid) return;
  const n = counts(sid);
  const inj = store.injectOn;
  $('curSid').textContent = sid;
  $('curChips').innerHTML = `
    <span class="chip"><u style="background:var(--c-universal)"></u>通用 ${n.u}</span>
    <span class="chip"><u style="background:var(--c-contextual)"></u>情境 ${n.c}</span>
    <span class="chip"><u style="background:var(--c-specific)"></u>特定 ${n.p}</span>
    <span class="chip">🕒 注入 ${inj === null ? '—' : (inj ? '开' : '关')}</span>`;
}

/* ============ Tab 路由 ============ */
export function switchTab(tab) {
  store.tab = tab;
  document.querySelectorAll('.tab').forEach((t) => {
    const active = t.dataset.tab === tab;
    t.classList.toggle('active', active);
    t.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  $('tabOverview').style.display = tab === 'overview' ? '' : 'none';
  $('tabLayer').style.display = tab === 'overview' ? 'none' : '';
  if (tab === 'overview') renderOverview();
  else renderLayer(tab);
}

/* ============ 总览 ============ */
export function renderOverview() {
  const sid = store.sid;
  if (!sid) return;
  const n = counts(sid);
  const total = n.u + n.c + n.p;
  const specSorted = [...((store.snapshot.specific && store.snapshot.specific[sid]) || [])]
    .sort((a, b) => (b.trigger_count || 0) - (a.trigger_count || 0)).slice(0, 5);
  const portrait = '在回复时，请尽量采用以下风格特点：通用风格：'
    + (store.model.universal.map((x) => x.content).join('；') || '（暂无）') + '；'
    + '场景反应：' + (store.model.contextual.map((x) => x.scene + '→' + x.behavior).join('；') || '（暂无）') + '；'
    + '群内流行说法：' + (store.model.specific.map((x) => x.content).join('；') || '（暂无）');
  const el = $('tabOverview');

  if (total === 0) {
    el.innerHTML = `<div class="empty">
      <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.6-.8L3 21l1.9-5.5A8.38 8.38 0 0 1 4 11.5 8.5 8.5 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5z"/></svg>
      <div class="t">这个会话还没有学习数据</div>
      <div class="d">插件会在聊天记录积累后自动学习。也可以点右上角「立即学习」手动触发，或在聊天里发送「学习总结」。</div>
      <button class="btn primary" id="ovLearn">⚡ 立即学习</button></div>`;
    const ov = $('ovLearn');
    if (ov) ov.onclick = learnNow;
    return;
  }
  const caps = store.caps || {};
  el.innerHTML = `
    <div class="stat-grid">
      <div class="stat"><div class="n">${total}</div><div class="l">总表征条目</div></div>
      <div class="stat u"><div class="n">${n.u}</div><div class="l">通用表征</div><div class="badge">≤${caps.universal || 10} 条</div></div>
      <div class="stat c"><div class="n">${n.c}</div><div class="l">情境表征</div><div class="badge">FIFO ≤${caps.contextual || 150}</div></div>
      <div class="stat s"><div class="n">${n.p}</div><div class="l">特定表征</div><div class="badge">≤${caps.specific || 200}</div></div>
    </div>
    <div class="ov-2col">
      <div class="card-box">
        <h3>🎭 风格画像（注入预览）</h3>
        <div class="quote" id="ovPortrait"></div>
        <div class="ov-note">这是机器人回复该会话时会被追加的 System Prompt 片段。</div>
      </div>
      <div class="card-box top">
        <h3>🔥 Top 梗榜</h3>
        <div id="ovTopList"></div>
        <div class="ov-note">按 trigger_count 排序</div>
      </div>
    </div>`;
  $('ovPortrait').textContent = portrait;
  const topBox = $('ovTopList');
  if (specSorted.length) {
    const ol = el('ol');
    specSorted.forEach((x) => {
      const li = el('li');
      li.textContent = x.content;
      const tc = el('span', 'tc');
      tc.textContent = `触发 ${x.trigger_count} 次`;
      li.appendChild(tc);
      ol.appendChild(li);
    });
    topBox.appendChild(ol);
  } else {
    topBox.innerHTML = '<div class="empty" style="padding:20px">暂无特定表征</div>';
  }
}

/* ============ 层编辑 ============ */
export function renderLayer(key) {
  const L = LAYERS.find((l) => l.key === key);
  const list = store.model[key];
  const el = $('tabLayer');
  el.innerHTML = `
    <div class="panel ${store.dirty[key] ? 'dirty' : ''}" id="panel-${key}">
      <div class="panel-head">
        <div class="ttl"><span class="bar" style="background:${L.color}"></span>${L.name}表征</div>
        <span class="dirty-tag"><span class="d"></span>未保存</span>
        <span class="sp"></span>
        <span class="meta" id="cnt-${key}">${list.length} 条</span>
        <button class="btn sm" id="add-${key}">＋ 添加</button>
        <button class="btn sm primary" id="save-${key}">保存本层</button>
        <div class="hint">${HINTS[key]}</div>
      </div>
      <div class="panel-body">
        <div class="layer-toolbar">
          <div class="search2">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>
            <input id="filt-${key}" type="text" placeholder="在本层内检索…" value="${esc(store.layerFilter)}" aria-label="层内检索">
          </div>
        </div>
        <div id="rows-${key}"></div>
      </div>
    </div>`;
  $('add-' + key).onclick = () => addRow(key);
  $('save-' + key).onclick = () => saveLayer(key);
  const filt = $('filt-' + key);
  filt.addEventListener('input', (e) => { store.layerFilter = e.target.value; renderRows(key); });
  renderRows(key);
}

export function renderRows(key) {
  const wrap = $('rows-' + key);
  if (!wrap) return;
  wrap.textContent = '';
  const list = store.model[key];
  const q = store.layerFilter.trim().toLowerCase();
  const filtered = list.filter((e) => {
    if (!q) return true;
    if (key === 'contextual') return (e.scene + ' ' + e.behavior).toLowerCase().includes(q);
    if (key === 'specific') return (e.content + ' ' + (e.trigger_regex || '')).toLowerCase().includes(q);
    return (e.content || '').toLowerCase().includes(q);
  });

  if (!list.length) {
    wrap.innerHTML = '<div class="empty" style="padding:28px"><div class="t">暂无条目</div><div class="d">点「＋ 添加」手动新增，或等插件自动学习。</div></div>';
  } else if (!filtered.length) {
    wrap.innerHTML = `<div class="empty" style="padding:20px">无匹配「${esc(store.layerFilter)}」的条目</div>`;
  } else {
    filtered.forEach((entry) => wrap.appendChild(buildRow(key, entry)));
  }
  const cnt = $('cnt-' + key);
  if (cnt) cnt.textContent = list.length + ' 条';
}

function buildRow(key, entry) {
  const row = el('div', 'row');
  if (key === 'universal') {
    const inp = el('input', 'inp');
    inp.value = entry.content;
    inp.placeholder = '风格描述，如：语气活泼、爱用短句';
    inp.addEventListener('input', () => { entry.content = inp.value; markDirty(key); });
    const meta = el('span', 'meta');
    meta.title = 'proficiency 熟练度 / confirmed_rounds 确认轮次';
    meta.textContent = `熟 ${entry.proficiency ?? 10}·轮 ${entry.confirmed_rounds ?? 1}`;
    const pbar = el('span', 'pbar');
    const fill = el('span');
    fill.style.width = Math.min(100, entry.proficiency ?? 0) + '%';
    pbar.appendChild(fill);
    row.append(inp, meta, pbar);
  } else if (key === 'contextual') {
    const sInp = el('input', 'inp');
    sInp.value = entry.scene;
    sInp.placeholder = '场景，如：有人发消息';
    const arrow = el('span', 'arrow');
    arrow.textContent = '→';
    const bInp = el('input', 'inp');
    bInp.value = entry.behavior;
    bInp.placeholder = '群体反应，如：全员复读';
    sInp.addEventListener('input', () => { entry.scene = sInp.value; markDirty(key); });
    bInp.addEventListener('input', () => { entry.behavior = bInp.value; markDirty(key); });
    row.append(sInp, arrow, bInp);
    if (entry._in_buffer) {
      const buf = el('span', 'buf');
      buf.textContent = '缓冲';
      row.append(buf);
    }
  } else {
    const cInp = el('input', 'inp');
    cInp.value = entry.content;
    cInp.placeholder = '梗+释义，如：awsl（啊我死了）';
    const rInp = el('input', 'inp mono');
    const invalid = entry.trigger_regex && !safeRegex(entry.trigger_regex);
    if (invalid) rInp.classList.add('invalid');
    rInp.value = entry.trigger_regex || '';
    rInp.placeholder = '触发正则，如：awsl|啊我死了';
    cInp.addEventListener('input', () => { entry.content = cInp.value; markDirty(key); });
    rInp.addEventListener('input', () => {
      entry.trigger_regex = rInp.value;
      const bad = !rInp.value || !safeRegex(rInp.value);
      rInp.classList.toggle('invalid', bad);
      markDirty(key);
    });
    const meta = el('span', 'meta');
    meta.title = 'trigger_count 触发次数';
    meta.textContent = '触发 ' + (entry.trigger_count || 1);
    row.append(cInp, rInp, meta);
  }

  const del = el('button', 'del');
  del.textContent = '✕';
  del.title = '删除此行（保存前不生效）';
  del.addEventListener('click', () => {
    const idx = store.model[key].indexOf(entry);
    if (idx >= 0) store.model[key].splice(idx, 1);
    markDirty(key);
    renderRows(key);
  });
  row.append(del);
  return row;
}

export function addRow(key) {
  if (key === 'universal') store.model.universal.push({ content: '', proficiency: 10, confirmed_rounds: 1 });
  else if (key === 'contextual') store.model.contextual.push({ scene: '', behavior: '', _in_buffer: true });
  else store.model.specific.push({ content: '', trigger_regex: '', trigger_count: 1 });
  markDirty(key);
  renderLayer(key);
  const last = $('rows-' + key) && $('rows-' + key).lastElementChild;
  if (last) { const inp = last.querySelector('input'); if (inp) inp.focus(); }
}

export async function saveLayer(key) {
  if (!store.sid) return;
  const btn = $('save-' + key);
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span>';

  // 客户端正则校验（特定层）
  if (key === 'specific') {
    for (let i = 0; i < store.model.specific.length; i++) {
      const e = store.model.specific[i];
      if (!e.trigger_regex || !safeRegex(e.trigger_regex)) {
        toast(`第 ${i + 1} 条正则无效，保存被拦截`, true);
        btn.disabled = false; btn.innerHTML = old;
        return;
      }
    }
  }

  try {
    await Api.saveLayer(store.sid, key, store.model[key]);
  } catch (e) {
    toast('保存失败：' + (e && e.message ? e.message : e), true);
    btn.disabled = false; btn.innerHTML = old;
    return;
  }

  store.dirty[key] = false;
  const p = $('panel-' + key);
  if (p) p.classList.remove('dirty');
  updateDirtyUI();
  toast('已保存 ' + LAYERS.find((l) => l.key === key).name + ' 层');
  btn.disabled = false; btn.innerHTML = old;

  // 回读最新快照，保留服务器维护的元数据；仅刷新本层避免覆盖其他层编辑
  try {
    const snap = await Api.snapshot();
    store.snapshot = snap;
    store.model[key] = clone((snap[key] && snap[key][store.sid]) || []);
  } catch (e) { /* 回读失败则保留当前编辑视图 */ }
  renderSidebar();
  renderSessionHead();
  renderRows(key);
  const cnt = $('cnt-' + key);
  if (cnt) cnt.textContent = store.model[key].length + ' 条';
}

/* ============ 会话级操作 ============ */
async function refreshSnapshotOnly() {
  try {
    const snap = await Api.snapshot();
    store.snapshot = snap;
    if (store.sid && !isAnyDirty()) selectSession(store.sid);
    renderSidebar();
    if (store.sid) {
      renderSessionHead();
      if (store.tab === 'overview') renderOverview();
      else renderLayer(store.tab);
    }
  } catch (e) {
    toast('刷新失败：' + (e && e.message ? e.message : e), true);
  }
}

export async function learnNow() {
  if (!store.sid) return;
  const btn = $('btnLearn');
  const o = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> 学习中';
  try {
    await Api.learn(store.sid);
    toast('学习完成，已刷新数据');
    await refreshSnapshotOnly();
  } catch (e) {
    toast('学习触发失败：' + (e && e.message ? e.message : e) + '（也可到聊天发送「学习总结」）', true);
  } finally {
    btn.disabled = false; btn.innerHTML = o;
  }
}

export async function clearSession() {
  if (!store.sid) return;
  const ok = await confirmModal({
    title: '清空本会话',
    body: '将删除该会话的全部通用/情境/特定表征，且不可撤销。确定吗？',
  });
  if (!ok) return;
  try {
    await Api.clear(store.sid);
    await refreshSnapshotOnly();
    toast('已清空本会话');
  } catch (e) {
    toast('清空失败：' + (e && e.message ? e.message : e), true);
  }
}

export async function exportSession() {
  if (!store.sid) return;
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
    toast('导出失败：' + (e && e.message ? e.message : e), true);
  }
}
