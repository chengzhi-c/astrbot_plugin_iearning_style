// api.js — 对 window.AstrBotPluginPage 桥接的封装（API 契约层）。
// 路由与后端 web_ui.py 保持一致（以插件名前缀开头）：
//   GET  snapshot / stats
//   POST layer / learn / clear / export
// 桥接返回结构可能是 {status, data} 包裹，也可能是直接数据，统一在此解包。
// ⚠️ 此文件是前后端衔接的契约边界，修改路由/字段需同步后端。

let bridge = null;

export function setBridge(b) { bridge = b; }

async function get(path) {
  if (!bridge) throw new Error('面板桥接未初始化');
  return bridge.apiGet(path);
}
async function post(path, body) {
  if (!bridge) throw new Error('面板桥接未初始化');
  try {
    const result = await bridge.apiPost(path, body);
    if (result?.status === 'error') {
      const error = new Error(result.message || '请求失败');
      error.code = result.data?.code || 'request_failed';
      throw error;
    }
    return result;
  } catch (error) {
    if (!error.code && String(error.message || error).includes('revision_conflict')) {
      error.code = 'revision_conflict';
    }
    throw error;
  }
}

export const unwrap = (r) => (r && typeof r === 'object' && r.data !== undefined ? r.data : r);

export const Api = {
  async snapshot() { return unwrap(await get('snapshot')); },
  async stats() { return unwrap(await get('stats')); },
  async saveLayer(sid, layer, entries, baseRevision) {
    return unwrap(await post('layer', {
      sid, layer, entries, base_revision: baseRevision,
    }));
  },
  async learn(sid) { return post('learn', { sid }); },
  async clear(sid) { return post('clear', { sid }); },
  // 导出返回原始结果（可能为包裹结构），由调用方二次解包。
  async exportSession(sid) { return post('export', { sid }); },
};
