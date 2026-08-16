// store.js — 中央状态（单一数据源）与派生计算。
// 视图层只读 store 并调用这里的 mutation；不负责 DOM 操作。

import { clone } from './util.js';

export const LAYERS = [
  {
    key: 'universal', name: '通用', color: 'var(--c-universal)',
    hint: '这个会话整体说话是什么风格（语气/用词/氛围），全部注入每次回复，上限 10 条。编辑后内容由服务器保留 proficiency / confirmed_rounds 等学习统计。',
  },
  {
    key: 'contextual', name: '情境', color: 'var(--c-contextual)',
    hint: '某场景出现时的固定反应（场景 → 行为），超出容量按 FIFO 淘汰最早的。带虚线标签的为「缓冲位」条目（最近 20%）。',
  },
  {
    key: 'specific', name: '特定', color: 'var(--c-specific)',
    hint: '群内梗与释义。trigger_regex 命中用户消息时该梗才会被注入回复（按需注入，prompt 不膨胀）；正则非法时该层拒绝保存并提示具体条目。',
  },
];

export const store = {
  snapshot: null,    // 服务器原始三层快照
  sid: null,         // 当前选中的会话
  model: null,       // 当前会话三层表征的可编辑副本
  dirty: {},         // { universal, contextual, specific } 是否未保存
  tab: 'overview',   // 当前 Tab
  sessFilter: '',    // 侧栏会话检索
  layerFilter: '',   // 当前层内检索
  caps: null,        // { universal, contextual, specific } 容量上限
  injectOn: null,    // 风格注入开关（null=未知/旧后端）
};

export function setSnapshot(snap) { store.snapshot = snap; }

export function allSids() {
  const s = new Set();
  if (!store.snapshot) return [];
  ['universal', 'contextual', 'specific'].forEach((k) =>
    Object.keys(store.snapshot[k] || {}).forEach((id) => s.add(id))
  );
  return [...s].sort();
}

export function counts(sid) {
  const s = store.snapshot || {};
  return {
    u: ((s.universal && s.universal[sid]) || []).length,
    c: ((s.contextual && s.contextual[sid]) || []).length,
    p: ((s.specific && s.specific[sid]) || []).length,
  };
}

export function isAnyDirty() {
  return LAYERS.some((l) => store.dirty[l.key]);
}

export function rebuildModel(sid) {
  const s = store.snapshot || {};
  store.model = {
    universal: clone((s.universal && s.universal[sid]) || []),
    contextual: clone((s.contextual && s.contextual[sid]) || []),
    specific: clone((s.specific && s.specific[sid]) || []),
  };
}

export function selectSession(sid) {
  store.sid = sid;
  store.dirty = {};
  store.layerFilter = '';
  store.tab = 'overview';
  rebuildModel(sid);
}
