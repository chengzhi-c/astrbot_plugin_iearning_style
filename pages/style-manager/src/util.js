// util.js — 通用工具：DOM 选取、转义、提示、弹窗、正则、主题、时间
// 无副作用、无外部依赖，可被任意模块复用。

export const $ = (id) => document.getElementById(id);

export const clone = (v) => JSON.parse(JSON.stringify(v));

const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (v) => (v == null ? '' : String(v).replace(/[&<>"']/g, (c) => ESC_MAP[c]));

/** 创建带 class 的元素 */
export function el(tag, cls) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
}

let toastTimer = null;
export function toast(msg, isErr) {
  const t = $('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = 'show' + (isErr ? ' err' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ''; }, 2200);
}

/** 确认弹窗，返回 Promise<boolean> */
export function confirmModal({ title, body, okText = '确定', danger = true }) {
  return new Promise((resolve) => {
    const ov = $('overlay');
    const mTitle = $('mTitle');
    const mBody = $('mBody');
    const mOk = $('mOk');
    const mCancel = $('mCancel');
    mTitle.textContent = title;
    mBody.textContent = body;
    mOk.textContent = okText;
    mOk.className = 'btn ' + (danger ? 'danger' : 'primary');
    ov.classList.add('show');
    const close = (val) => { ov.classList.remove('show'); resolve(val); };
    mOk.onclick = () => close(true);
    mCancel.onclick = () => close(false);
  });
}

export function safeRegex(s) {
  try { new RegExp(s); return true; } catch { return false; }
}

/**
 * 将时间戳转成相对时间。
 * 后端存储的时间戳为纪元秒（time.time()）。
 */
export function relTime(value) {
  if (!value || typeof value !== 'number') return '—';
  const now = Date.now() / 1000;
  const d = now - value;
  if (d < 0) return '—';
  if (d < 60) return '刚刚';
  if (d < 3600) return Math.floor(d / 60) + ' 分钟前';
  if (d < 86400) return Math.floor(d / 3600) + ' 小时前';
  if (d < 86400 * 30) return Math.floor(d / 86400) + ' 天前';
  return new Date(value * 1000).toLocaleDateString();
}

/** 取会话所有条目时间戳的最大值（单调时钟下的相对最近活动，用于排序） */
export function lastActivity(sid, snapshot) {
  let max = 0;
  if (!snapshot) return max;
  const layers = [snapshot.universal, snapshot.contextual, snapshot.specific];
  for (const layer of layers) {
    const arr = (layer && layer[sid]) || [];
    for (const e of arr) {
      for (const k of ['last_updated', 'last_seen', 'created_at', 'first_seen']) {
        if (typeof e[k] === 'number' && e[k] > max) max = e[k];
      }
    }
  }
  return max;
}

export function initTheme() {
  const root = document.documentElement;
  const saved = localStorage.getItem('ils-theme');
  if (saved === 'light' || saved === 'dark') {
    root.dataset.theme = saved;
  } else if (!root.dataset.theme) {
    const prefersDark = window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = prefersDark ? 'dark' : 'light';
  }
}

export function toggleTheme() {
  const root = document.documentElement;
  const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
  root.dataset.theme = next;
  localStorage.setItem('ils-theme', next);
}
