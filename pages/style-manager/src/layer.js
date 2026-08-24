// layer.js — 三层表征编辑视图：面板、行渲染、客户端校验、保存（整层替换）。
// 数据模型由后端 DataManager 统一规范化；保存结果通过回调交给 app.js 编排。

import { store, LAYERS, revisionFor, acceptSavedLayer } from './store.js';
import { Api } from './api.js';
import { $, el, esc, clone } from './util.js';
import { icon } from './icons.js';
import { toast, emptyState } from './ui.js';

const HINTS = Object.fromEntries(LAYERS.map((l) => [l.key, l.hint]));
const dedupKey = (value) => value.normalize('NFKC').toLowerCase().trim().replace(/\s+/gu, ' ');

/* ============ 脏数据 UI ============ */
function updateDirtyUI() {
  $('dirtyBanner').classList.toggle('show', Object.values(store.dirty).some(Boolean));
}

function markDirty(key) {
  store.dirty[key] = true;
  store.editSeq[key] = (store.editSeq[key] || 0) + 1;
  const p = $('panel-' + key);
  if (p) p.classList.add('dirty');
  updateDirtyUI();
}

function clearDirty(key) {
  store.dirty[key] = false;
  const p = $('panel-' + key);
  if (p) p.classList.remove('dirty');
  updateDirtyUI();
}

export function clearAllDirty() {
  store.dirty = {};
  document.querySelectorAll('.panel.dirty').forEach((panel) => panel.classList.remove('dirty'));
  updateDirtyUI();
}

/* ============ 层面板渲染 ============ */
export function renderLayer(key, onSaved) {
  const L = LAYERS.find((l) => l.key === key);
  const list = store.model[key];
  const cap = (store.caps && store.caps[key]) ?? ({ universal: 10, contextual: 150, specific: 200 })[key];
  const showCap = key === 'universal';
  const ratio = showCap && cap > 0 ? list.length / cap : 0;
  const capCls = !showCap ? '' : ratio >= 1 ? ' full' : ratio >= 0.8 ? ' warn' : '';
  const capText = showCap ? `${list.length} / ${cap} 条` : `${list.length} 条`;
  const el = $('tabLayer');
  el.innerHTML = `
    <div class="panel ${store.dirty[key] ? 'dirty' : ''} layer-panel-${key}" id="panel-${key}">
      <div class="panel-head">
        <div class="ttl">
          <div class="ttl-icon-box" style="background:${L.soft}; color:${L.color}">
            ${icon(L.icon, 16)}
          </div>
          <div class="ttl-info">
            <div class="ttl-title-row">
              <span class="ttl-name">${L.name}表征</span>
              <span class="dirty-tag"><span class="d"></span>未保存变更</span>
            </div>
            <div class="hint">${HINTS[key]}</div>
          </div>
        </div>
        <div class="panel-head-actions">
          <span class="meta${capCls}" id="cnt-${key}" title="${showCap ? '容量上限 ' + cap + ' 条' : ''}">${capText}</span>
          <button class="btn btn-sm btn-soft" id="add-${key}">${icon('plus', 13)} 添加条目</button>
          <button class="btn btn-sm btn-primary" id="save-${key}">${icon('check', 13)} 保存本层</button>
        </div>
      </div>
      <div class="panel-body">
        <div class="layer-toolbar">
          <div class="search2">
            ${icon('search', 14)}
            <input id="filt-${key}" type="text" placeholder="检索本层条目与关键词..." value="${esc(store.layerFilter)}" aria-label="层内检索">
          </div>
          <span class="toolbar-status" id="status-${key}"></span>
        </div>
        <div class="rows-container" id="rows-${key}"></div>
      </div>
    </div>`;
  $('add-' + key).onclick = () => addRow(key);
  $('save-' + key).onclick = () => saveLayer(key, { onSaved });
  $('filt-' + key).addEventListener('input', (e) => {
    store.layerFilter = e.target.value;
    renderRows(key);
  });
  renderRows(key);
}

/* ============ 行渲染 ============ */
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
    wrap.innerHTML = emptyState({
      title: '暂无表征条目',
      desc: '点击上方「＋ 添加条目」进行手动定义，或由机器人与群友交互后自动分析提取。',
      art: 'empty',
    });
  } else if (!filtered.length) {
    wrap.innerHTML = `<div class="empty-state small">
      <div class="es-title">未找到匹配「${esc(store.layerFilter)}」的条目</div>
      <div class="es-desc">请尝试其他关键词</div>
    </div>`;
  } else {
    filtered.forEach((entry, idx) => wrap.appendChild(buildRow(key, entry, idx)));
  }
  const cnt = $('cnt-' + key);
  if (cnt) {
    const cap = (store.caps && store.caps[key]) ?? ({ universal: 10, contextual: 150, specific: 200 })[key];
    const showCap = key === 'universal';
    const ratio = showCap && cap > 0 ? list.length / cap : 0;
    cnt.textContent = showCap ? `${list.length} / ${cap} 条` : `${list.length} 条`;
    cnt.className = 'meta' + (!showCap ? '' : ratio >= 1 ? ' full' : ratio >= 0.8 ? ' warn' : '');
  }
  const st = $('status-' + key);
  if (st) st.textContent = filtered.length === list.length ? '' : `显示 ${filtered.length}/${list.length}`;
}

function buildRow(key, entry, idx) {
  const row = el('div', 'row card-row');
  const indexBadge = el('span', 'row-idx');
  indexBadge.textContent = String(idx + 1).padStart(2, '0');
  row.appendChild(indexBadge);

  if (key === 'universal') {
    const fieldWrap = el('div', 'row-field-wrap');
    const inp = el('input', 'inp');
    inp.value = entry.content;
    inp.placeholder = '风格描述，如：语气活泼、爱用短句';
    inp.addEventListener('input', () => { entry.content = inp.value; markDirty(key); });
    fieldWrap.appendChild(inp);
    row.appendChild(fieldWrap);

    const metaWrap = el('div', 'row-meta-wrap');
    const meta = el('span', 'meta');
    meta.title = 'proficiency 熟练度 / confirmed_rounds 确认轮次';
    meta.textContent = `熟 ${entry.proficiency ?? 10} · 轮 ${entry.confirmed_rounds ?? 1}`;
    const pbar = el('span', 'pbar');
    pbar.title = '熟练度 ' + Math.min(100, entry.proficiency ?? 0) + '%';
    const fill = el('span');
    fill.style.width = Math.min(100, entry.proficiency ?? 0) + '%';
    pbar.appendChild(fill);
    metaWrap.append(meta, pbar);
    row.appendChild(metaWrap);
  } else if (key === 'contextual') {
    const pairWrap = el('div', 'row-pair-wrap');
    
    const sBox = el('div', 'row-field-group');
    const sLabel = el('span', 'field-tag');
    sLabel.textContent = '场景';
    const sInp = el('input', 'inp');
    sInp.value = entry.scene;
    sInp.placeholder = '场景，如：有人发消息';
    sBox.append(sLabel, sInp);

    const arrow = el('span', 'arrow');
    arrow.textContent = '→';

    const bBox = el('div', 'row-field-group');
    const bLabel = el('span', 'field-tag');
    bLabel.textContent = '行为';
    const bInp = el('input', 'inp');
    bInp.value = entry.behavior;
    bInp.placeholder = '群体反应，如：全员复读';
    bBox.append(bLabel, bInp);

    sInp.addEventListener('input', () => { entry.scene = sInp.value; markDirty(key); });
    bInp.addEventListener('input', () => { entry.behavior = bInp.value; markDirty(key); });
    pairWrap.append(sBox, arrow, bBox);
    row.appendChild(pairWrap);

    if (entry._in_buffer) {
      const buf = el('span', 'buf');
      buf.title = '缓冲位条目：等待维护任务合并或确认';
      buf.innerHTML = icon('clock', 11) + '<span>缓冲</span>';
      row.appendChild(buf);
    }
  } else {
    const specWrap = el('div', 'row-pair-wrap');
    
    const cBox = el('div', 'row-field-group');
    const cLabel = el('span', 'field-tag');
    cLabel.textContent = '词条/释义';
    const cInp = el('input', 'inp');
    cInp.value = entry.content;
    cInp.placeholder = '梗+释义，如：awsl（啊我死了）';
    cBox.append(cLabel, cInp);

    const rBox = el('div', 'row-field-group');
    const rLabel = el('span', 'field-tag mono');
    rLabel.textContent = '触发正则';
    const rInp = el('input', 'inp mono');
    const invalid = typeof entry.trigger_regex !== 'string' || !entry.trigger_regex.trim();
    if (invalid) rInp.classList.add('invalid');
    rInp.value = entry.trigger_regex || '';
    rInp.placeholder = '触发正则，如：awsl|啊我死了';
    rBox.append(rLabel, rInp);

    cInp.addEventListener('input', () => { entry.content = cInp.value; markDirty(key); });
    rInp.addEventListener('input', () => {
      entry.trigger_regex = rInp.value;
      const bad = !rInp.value.trim();
      rInp.classList.toggle('invalid', bad);
      markDirty(key);
    });
    specWrap.append(cBox, rBox);
    row.appendChild(specWrap);

    const meta = el('span', 'meta trig-meta');
    meta.title = 'trigger_count 触发次数';
    meta.innerHTML = icon('zap', 11) + '<span>触发 ' + (entry.trigger_count || 1) + '</span>';
    row.appendChild(meta);
  }

  const del = el('button', 'del');
  del.title = '删除此行（保存前不生效）';
  del.setAttribute('aria-label', '删除此行');
  del.innerHTML = icon('trash', 15);
  del.addEventListener('click', () => {
    const idx = store.model[key].indexOf(entry);
    if (idx >= 0) store.model[key].splice(idx, 1);
    markDirty(key);
    renderRows(key);
  });
  row.appendChild(del);
  return row;
}

/* ============ 添加 / 保存 ============ */
function addRow(key) {
  if (key === 'universal') store.model.universal.push({ content: '', proficiency: 10, confirmed_rounds: 1 });
  else if (key === 'contextual') store.model.contextual.push({ scene: '', behavior: '', _in_buffer: true });
  else store.model.specific.push({ content: '', trigger_regex: '', trigger_count: 1 });
  markDirty(key);
  renderLayer(key);
  const last = $('rows-' + key)?.lastElementChild;
  const inp = last && last.querySelector('input');
  if (inp) inp.focus();
}

export function validateLayer(key) {
  const entries = store.model?.[key];
  if (!Array.isArray(entries)) return { ok: false, message: '当前层数据不可用' };
  const cap = (store.caps && store.caps[key]) ?? ({ universal: 10, contextual: 150, specific: 200 })[key];
  if (entries.length > cap) return { ok: false, message: `条目数超过容量上限 ${cap}` };
  const seen = new Set();
  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];
    const values = key === 'contextual'
      ? [entry.scene, entry.behavior]
      : key === 'specific'
        ? [entry.content, entry.trigger_regex]
        : [entry.content];
    if (values.some((value) => typeof value !== 'string' || !value.trim())) {
      return { ok: false, message: `第 ${i + 1} 条存在空字段` };
    }
    const identity = key === 'contextual'
      ? `${dedupKey(entry.scene)}\u0000${dedupKey(entry.behavior)}`
      : key === 'specific'
        ? `${dedupKey(entry.content)}\u0000${entry.trigger_regex}`
        : dedupKey(entry.content);
    if (seen.has(identity)) return { ok: false, message: `第 ${i + 1} 条与前面的条目重复` };
    seen.add(identity);
  }
  return { ok: true };
}

export async function saveLayer(key, { quiet = false, onSaved } = {}) {
  if (!store.sid) return { ok: false, code: 'no_session' };
  if (!store.dirty[key]) return { ok: true, code: 'clean' };
  const sid = store.sid;
  const btn = $('save-' + key);
  if (btn?.disabled) return { ok: false, code: 'busy' };
  const old = btn?.innerHTML;
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="btn-spin"></span> 保存中`;
  }

  const validation = validateLayer(key);
  if (!validation.ok) {
    if (!quiet) toast(validation.message, 'error');
    if (btn) { btn.disabled = false; btn.innerHTML = old; }
    return { ok: false, code: 'invalid' };
  }
  const baseRevision = revisionFor(key);
  if (!baseRevision) {
    if (!quiet) toast('缺少服务器 revision，请刷新后重试', 'error');
    if (btn) { btn.disabled = false; btn.innerHTML = old; }
    return { ok: false, code: 'missing_revision' };
  }

  const editSeq = store.editSeq[key] || 0;
  const payload = clone(store.model[key]);
  let result;
  try {
    result = await Api.saveLayer(sid, key, payload, baseRevision);
  } catch (e) {
    const conflict = e?.code === 'revision_conflict';
    if (!quiet) toast(conflict ? '服务器数据已更新，请刷新后重新合并' : '保存失败：' + (e?.message || e), 'error');
    if (btn) { btn.disabled = false; btn.innerHTML = old; }
    return { ok: false, code: conflict ? 'revision_conflict' : (e?.code || 'save_failed') };
  }

  const currentSession = acceptSavedLayer(
    key, result.entries, result.revision, sid, editSeq,
  );
  if (currentSession) clearDirty(key);
  if (!quiet) toast(currentSession
    ? `已保存${LAYERS.find((l) => l.key === key).name}层`
    : '服务器版本已保存，后续本地修改仍待保存');
  if (btn) { btn.disabled = false; btn.innerHTML = old; }
  if (currentSession) renderRows(key);
  onSaved?.();
  return { ok: true, code: 'saved' };
}
