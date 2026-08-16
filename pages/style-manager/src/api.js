// api.js — 对 window.AstrBotPluginPage 桥接的封装。
// 所有方法基于插件名前缀的路由：snapshot / stats / layer / learn / clear / export。
// 桥接返回结构可能是 {status, data} 包裹，也可能是直接数据，统一在此处解包。

let bridge = null;

export function setBridge(b) { bridge = b; }
export function getBridge() { return bridge; }

async function get(path) {
  if (!bridge) throw new Error('面板桥接未初始化');
  return bridge.apiGet(path);
}
async function post(path, body) {
  if (!bridge) throw new Error('面板桥接未初始化');
  return bridge.apiPost(path, body);
}

const unwrap = (r) => (r && typeof r === 'object' && r.data !== undefined ? r.data : r);

export const Api = {
  async snapshot() { return unwrap(await get('snapshot')); },
  async stats() { return unwrap(await get('stats')); },
  async saveLayer(sid, layer, entries) { return post('layer', { sid, layer, entries }); },
  async learn(sid) { return post('learn', { sid }); },
  async clear(sid) { return post('clear', { sid }); },
  // 导出返回原始结果（可能为包裹结构），由调用方二次解包。
  async exportSession(sid) { return post('export', { sid }); },
};
