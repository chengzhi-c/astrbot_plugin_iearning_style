// overview.js — 总览视图：统计卡、三层分布环形图、风格画像（注入预览）、Top 梗榜。
// 所有用户内容一律 textContent 渲染（XSS 防护约定，见 AGENTS.md）。

import { store, LAYERS, counts } from './store.js';
import { $, el } from './util.js';
import { icon } from './icons.js';
import { emptyState, toast } from './ui.js';

const LAYER_ORDER = ['universal', 'contextual', 'specific'];

/** 三层分布环形图（纯 SVG，无依赖） */
function donutHTML(n) {
  const total = n.u + n.c + n.p;
  const R = 26, C = 2 * Math.PI * R;
  if (total === 0) {
    return `<svg class="donut" viewBox="0 0 64 64" width="120" height="120" aria-hidden="true">
      <circle cx="32" cy="32" r="${R}" fill="none" stroke="var(--c-surface-2)" stroke-width="10"/>
      <text x="32" y="32" text-anchor="middle" dominant-baseline="central" class="donut-empty">0</text>
    </svg>`;
  }
  const segs = [n.u, n.c, n.p].filter((v) => v > 0);
  const ratios = segs.map((v) => v / total);
  let offset = 0;
  const arcs = ratios.map((r, i) => {
    const len = r * C;
    const dash = `${len - 1.5} ${C - len + 1.5}`;
    const arc = `<circle cx="32" cy="32" r="${R}" fill="none"
      stroke="var(--c-${['universal', 'contextual', 'specific'][i]})" stroke-width="10"
      stroke-dasharray="${dash}" stroke-dashoffset="${-offset * C}"
      transform="rotate(-90 32 32)" stroke-linecap="butt"/>`;
    offset += r;
    return arc;
  }).join('');
  return `<svg class="donut" viewBox="0 0 64 64" width="120" height="120" aria-hidden="true">
    <circle cx="32" cy="32" r="${R}" fill="none" stroke="var(--c-surface-2)" stroke-width="10"/>
    ${arcs}
    <text x="32" y="31" text-anchor="middle" dominant-baseline="central" class="donut-n">${total}</text>
    <text x="32" y="44" text-anchor="middle" dominant-baseline="central" class="donut-l">总条目</text>
  </svg>`;
}

/** 单层容量条（使用中 / 上限） */
function capBar(key, cnt, cap) {
  const pct = cap > 0 ? Math.min(100, Math.round((cnt / cap) * 100)) : 0;
  return `<div class="cap-row">
    <span class="cap-label">${icon(LAYERS.find((l) => l.key === key).icon, 13)}
      <b>${LAYERS.find((l) => l.key === key).name}</b></span>
    <span class="cap-track"><span class="cap-fill cap-${key}" style="width:${pct}%"></span></span>
    <span class="cap-num">${cnt}/${cap}</span>
  </div>`;
}

export function renderOverview() {
  const sid = store.sid;
  if (!sid) return;
  const n = counts(sid);
  const total = n.u + n.c + n.p;
  const caps = store.caps || {};
  const specSorted = [...((store.snapshot.specific && store.snapshot.specific[sid]) || [])]
    .sort((a, b) => (b.trigger_count || 0) - (a.trigger_count || 0)).slice(0, 5);

  const portrait = '在回复时，请尽量采用以下风格特点：通用风格：'
    + (store.model.universal.map((x) => x.content).join('；') || '（暂无）') + '；'
    + '场景反应：' + (store.model.contextual.map((x) => x.scene + '→' + x.behavior).join('；') || '（暂无）') + '；'
    + '群内流行说法：' + (store.model.specific.map((x) => x.content).join('；') || '（暂无）');

  const box = $('tabOverview');
  if (total === 0) {
    box.innerHTML = `<div class="ov-empty-wrap">` + emptyState({
      title: '这个会话还没有学习数据',
      desc: '插件会在聊天记录积累后自动学习，也可以手动触发「立即学习」，或在聊天里发送「学习总结」。',
      art: 'chat',
    }) + `<button class="btn primary" id="ovLearn">${icon('sparkles', 15)} 立即学习</button></div>`;
    const ov = $('ovLearn');
    if (ov) ov.onclick = () => busEmitLearn();
    return;
  }

  box.innerHTML = `
    <div class="stat-grid">
      <div class="stat total">
        <div class="stat-inner">
          <div class="stat-n">${total}</div>
          <div class="stat-l">总表征条目</div>
        </div>
        ${donutHTML(n)}
      </div>
      ${LAYER_ORDER.map((k, i) => {
        const L = LAYERS[i];
        const cnt = counts(sid)[{ universal: 'u', contextual: 'c', specific: 'p' }[k]];
        const cap = caps[k] ?? { universal: 10, contextual: 150, specific: 200 }[k];
        return `<div class="stat ${k[0]}">
          <div class="stat-n">${cnt}</div>
          <div class="stat-l">${icon(L.icon, 13)} ${L.name}表征</div>
          <div class="stat-badge">${capBar(k, cnt, cap)}</div>
        </div>`;
      }).join('')}
    </div>
    <div class="ov-2col">
      <div class="card-box">
        <div class="card-head">${icon('edit', 15)} <h3>风格画像（注入预览）</h3>
          <button class="mini-btn" id="copyPortrait" type="button" title="复制画像文本">${icon('copy', 13)} 复制</button>
        </div>
        <div class="quote" id="ovPortrait"></div>
        <div class="ov-note">这是机器人回复该会话时会被追加的 System Prompt 片段。</div>
      </div>
      <div class="card-box">
        <div class="card-head">${icon('bolt', 15)} <h3>Top 梗榜</h3></div>
        <div id="ovTopList"></div>
        <div class="ov-note">按触发次数排序 · 正则命中才注入</div>
      </div>
    </div>`;

  $('ovPortrait').textContent = portrait;

  // 新增特性：一键复制风格画像（含降级方案）
  const copyBtn = $('copyPortrait');
  if (copyBtn) {
    copyBtn.addEventListener('click', async () => {
      const text = portrait;
      let ok = false;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text);
          ok = true;
        }
      } catch (e) { /* 降级到 execCommand */ }
      if (!ok) {
        try {
          const ta = document.createElement('textarea');
          ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
          document.body.appendChild(ta); ta.select();
          ok = document.execCommand('copy'); ta.remove();
        } catch (e) { ok = false; }
      }
      if (ok) toast('已复制风格画像到剪贴板');
      else toast('复制失败，请手动选择文本复制', 'error');
    });
  }

  const topBox = $('ovTopList');
  if (specSorted.length) {
    const ol = el('ol', 'top-list');
    specSorted.forEach((x, i) => {
      const li = el('li', 'top-item');
      const rank = el('span', 'top-rank');
      rank.textContent = '#' + (i + 1);
      const txt = el('span', 'top-txt');
      txt.textContent = x.content;
      const tc = el('span', 'top-count');
      tc.textContent = `触发 ${x.trigger_count} 次`;
      li.append(rank, txt, tc);
      ol.appendChild(li);
    });
    topBox.appendChild(ol);
  } else {
    topBox.innerHTML = emptyState({ title: '暂无特定表征', art: 'empty' });
  }
}

// 避免循环依赖：由 app.js 通过 bus 注入「立即学习」回调
let _learnFn = null;
export function setLearnHandler(fn) { _learnFn = fn; }
function busEmitLearn() { if (_learnFn) _learnFn(); }
