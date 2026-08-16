// bus.js — 轻量事件总线：解耦视图模块间的刷新通知。
// 例：layer.js 保存成功后 emit('data-changed')，
//     app.js / sidebar.js / overview.js 各自监听刷新，互不引用。

const listeners = new Map();

export const bus = {
  on(evt, fn) {
    if (!listeners.has(evt)) listeners.set(evt, new Set());
    listeners.get(evt).add(fn);
    return () => listeners.get(evt)?.delete(fn);
  },
  off(evt, fn) {
    listeners.get(evt)?.delete(fn);
  },
  emit(evt, payload) {
    listeners.get(evt)?.forEach((fn) => {
      try { fn(payload); } catch (e) { console.error('[bus]', evt, e); }
    });
  },
};
