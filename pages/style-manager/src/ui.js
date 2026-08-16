// ui.js — 设计系统 UI 组件层：Toast / 确认弹窗 / 骨架屏 / 空状态。
// 所有组件只依赖 DOM 工具和图标，不读取业务状态。

import { $, el } from './util.js';
import { icon, emptyArt } from './icons.js';

/* ============ Toast（可堆叠、类型化、自动消失） ============ */
const TOAST_TYPES = {
  success: { icon: 'checkCircle', cls: 'success' },
  error: { icon: 'alertCircle', cls: 'error' },
  info: { icon: 'info', cls: 'info' },
};

/**
 * 弹出 Toast。
 * @param {string} msg 文案
 * @param {('success'|'error'|'info')} [type='success']
 * @param {number} [duration=2400] 停留毫秒
 */
export function toast(msg, type = 'success', duration = 2400) {
  const wrap = $('toastWrap');
  if (!wrap) return;
  const t = TOAST_TYPES[type] || TOAST_TYPES.info;
  const node = el('div', 'toast ' + t.cls);
  node.innerHTML = icon(t.icon, 16) + '<span class="t-msg"></span>';
  node.querySelector('.t-msg').textContent = msg;
  wrap.appendChild(node);
  // 入场
  requestAnimationFrame(() => node.classList.add('show'));
  setTimeout(() => {
    node.classList.remove('show');
    setTimeout(() => node.remove(), 260);
  }, duration);
}

/* ============ 确认弹窗 ============ */
let _lastFocused = null;

/**
 * 确认弹窗，返回 Promise<boolean>。
 * @param {{title:string, body:string, okText?:string, cancelText?:string,
 *          danger?:boolean, icon?:string}} opts
 */
export function confirmModal(opts = {}) {
  const {
    title = '确认', body = '', okText = '确定', cancelText = '取消',
    danger = true, icon: iconName = danger ? 'alert' : 'help',
  } = opts;
  return new Promise((resolve) => {
    const ov = $('overlay');
    const mTitle = $('mTitle');
    const mBody = $('mBody');
    const mOk = $('mOk');
    const mCancel = $('mCancel');
    const mIcon = $('mIcon');

    _lastFocused = document.activeElement;
    mTitle.textContent = title;
    mBody.textContent = body;
    mOk.textContent = okText;
    mCancel.textContent = cancelText;
    mOk.className = 'btn ' + (danger ? 'danger' : 'primary');
    mIcon.innerHTML = icon(iconName, 22);

    let settled = false;
    const close = (val) => {
      if (settled) return;
      settled = true;
      mOk.onclick = null;
      mCancel.onclick = null;
      ov.removeEventListener('cancel', onCancel);
      ov.removeEventListener('click', onBackdrop);
      ov.close();
      resolve(val);
      if (_lastFocused && _lastFocused.focus) _lastFocused.focus();
    };
    const onCancel = (event) => {
      event.preventDefault();
      close(false);
    };
    const onBackdrop = (event) => { if (event.target === ov) close(false); };

    mOk.onclick = () => close(true);
    mCancel.onclick = () => close(false);
    ov.addEventListener('cancel', onCancel);
    ov.addEventListener('click', onBackdrop);
    ov.showModal();
    setTimeout(() => mCancel.focus(), 30); // 默认聚焦安全项
  });
}

/* ============ 骨架屏 ============ */
/** 初始加载骨架屏（替换 empty/loading 区块）。@param {number} rows */
export function skeleton(rows = 4) {
  const cards = Array.from({ length: 3 }, (_, i) => `
    <div class="sk-card" style="animation-delay:${i * 90}ms">
      <div class="sk-line w30"></div>
      <div class="sk-line w70"></div>
      <div class="sk-line w50"></div>
    </div>`).join('');
  const lines = Array.from({ length: rows }, (_, i) =>
    `<div class="sk-line w${[60, 90, 75, 45][i % 4]}" style="animation-delay:${i * 60}ms"></div>`
  ).join('');
  return `<div class="skeleton"><div class="sk-grid">${cards}</div><div class="sk-block">${lines}</div></div>`;
}

/* ============ 空状态 ============ */
/**
 * 空状态占位。@param {{title:string, desc?:string, art?:string, action?:string}} opts
 */
export function emptyState(opts = {}) {
  const { title = '暂无数据', desc = '', art = 'empty', action = '' } = opts;
  return `<div class="empty-state">${emptyArt(art)}
    <div class="es-title">${title}</div>
    ${desc ? `<div class="es-desc">${desc}</div>` : ''}
    ${action || ''}
  </div>`;
}
