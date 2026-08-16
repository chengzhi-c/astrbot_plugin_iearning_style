// store.js — 中央状态（单一数据源）与派生计算。
// 视图层只读 store 并调用这里的 mutation；不负责 DOM 操作。

import { clone } from './util.js';

/** 三层表征元信息（名称/配色/说明），视觉与语义统一由这里驱动 */
export const LAYERS = [
  {
    key: 'universal', name: '通用', color: 'var(--c-universal)',
    soft: 'var(--c-universal-soft)',
    hint: '这个会话整体说话是什么风格（语气/用词/氛围），全部注入每次回复，上限 10 条。编辑后内容由服务器保留 proficiency / confirmed_rounds 等学习统计。',
    icon: 'layers',
  },
  {
    key: 'contextual', name: '情境', color: 'var(--c-contextual)',
    soft: 'var(--c-contextual-soft)',
    hint: '某场景出现时的固定反应（场景 → 行为），超出容量按 FIFO 淘汰最早的。带虚线标签的为「缓冲位」条目（最近 20%，供维护任务合并）。',
    icon: 'sitemap',
  },
  {
    key: 'specific', name: '特定', color: 'var(--c-specific)',
    soft: 'var(--c-specific-soft)',
    hint: '群内梗与释义。trigger_regex 命中用户消息时该梗才会被注入回复（按需注入，prompt 不膨胀）；正则非法时该层拒绝保存并提示具体条目。',
    icon: 'hash',
  },
];

export const LAYER_KEYS = LAYERS.map((l) => l.key);

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
  loading: false,    // 全局加载中（骨架屏）
};

export function setSnapshot(snap) { store.snapshot = snap; }

export function revisionFor(key, sid = store.sid) {
  return store.snapshot?.revisions?.[key]?.[sid] || null;
}

export function acceptSavedLayer(key, entries, revision, sid = store.sid) {
  if (!sid || !store.snapshot) return false;
  store.snapshot[key] ||= {};
  store.snapshot[key][sid] = clone(entries);
  store.snapshot.revisions ||= {};
  store.snapshot.revisions[key] ||= {};
  store.snapshot.revisions[key][sid] = revision;
  if (store.sid !== sid) return false;
  store.model[key] = clone(entries);
  return true;
}

/** 全部会话 ID（三层并集，排序稳定） */
export function allSids() {
  const s = new Set();
  if (!store.snapshot) return [];
  LAYER_KEYS.forEach((k) =>
    Object.keys(store.snapshot[k] || {}).forEach((id) => s.add(id))
  );
  return [...s].sort();
}

/** 某会话三层条目数 */
export function counts(sid) {
  const s = store.snapshot || {};
  return {
    u: ((s.universal && s.universal[sid]) || []).length,
    c: ((s.contextual && s.contextual[sid]) || []).length,
    p: ((s.specific && s.specific[sid]) || []).length,
  };
}

export function isAnyDirty() {
  return LAYER_KEYS.some((k) => store.dirty[k]);
}

/** 从快照重建当前会话的可编辑副本（丢弃本地未保存修改） */
export function rebuildModel(sid) {
  const s = store.snapshot || {};
  store.model = {
    universal: clone((s.universal && s.universal[sid]) || []),
    contextual: clone((s.contextual && s.contextual[sid]) || []),
    specific: clone((s.specific && s.specific[sid]) || []),
  };
}

/** 选中会话：重置脏标记、过滤与 Tab，重建模型 */
export function selectSession(sid) {
  store.sid = sid;
  store.dirty = {};
  store.layerFilter = '';
  store.tab = 'overview';
  rebuildModel(sid);
}
