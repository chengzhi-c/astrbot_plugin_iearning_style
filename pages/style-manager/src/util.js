// util.js — 纯工具函数：DOM 选取、转义、时间格式化、正则、主题。
// 无副作用、无外部依赖；与业务视图无关，可被任意模块复用。

export const $ = (id) => document.getElementById(id);
export const qs = (sel, root = document) => root.querySelector(sel);
export const qsa = (sel, root = document) => [...root.querySelectorAll(sel)];

export const clone = (v) => JSON.parse(JSON.stringify(v));

const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (v) => (v == null ? '' : String(v).replace(/[&<>"']/g, (c) => ESC_MAP[c]));

/** 创建带 class 与文本的元素 */
export function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

/** 防抖：返回包装函数，ms 内只执行最后一次 */
export function debounce(fn, ms = 200) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

/** 正则合法性检查（用户输入的 trigger_regex 边界校验） */
export function safeRegex(s) {
  try { new RegExp(s); return true; } catch { return false; }
}

/**
 * 将纪元秒时间戳转成相对时间。
 * 后端存储的时间戳为 epoch 秒（time.time()）。
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

/** 取会话所有条目时间戳的最大值（用于「最近活动」排序） */
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

/* ============ 主题（明/暗，localStorage 持久化 + 系统偏好兜底） ============ */
const THEME_KEY = 'ils-theme';

export function initTheme() {
  const root = document.documentElement;
  const saved = localStorage.getItem(THEME_KEY);
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
  localStorage.setItem(THEME_KEY, next);
  return next;
}

/** 当前主题名 */
export function currentTheme() {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}
