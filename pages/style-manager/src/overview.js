// overview.js — 总览视图：统计卡、三层分布、全量数据预览、Top 梗榜。
// 所有用户内容一律 textContent 渲染（XSS 防护约定，见 AGENTS.md）。

import { store, LAYERS, counts } from "./store.js";
import { $, el } from "./util.js";
import { icon } from "./icons.js";
import { emptyState, toast } from "./ui.js";

const LAYER_ORDER = ["universal", "contextual", "specific"];

export function donutSegments(n) {
	return [
		{ key: "universal", value: n.u },
		{ key: "contextual", value: n.c },
		{ key: "specific", value: n.p },
	].filter((segment) => segment.value > 0);
}

/** 三层分布环形图（纯 SVG，无依赖） */
function donutHTML(n) {
	const total = n.u + n.c + n.p;
	const R = 26,
		C = 2 * Math.PI * R;
	if (total === 0) {
		return `<svg class="donut" viewBox="0 0 64 64" width="76" height="76" aria-hidden="true">
      <circle cx="32" cy="32" r="${R}" fill="none" stroke="var(--surf-3)" stroke-width="7"/>
      <text x="32" y="32" text-anchor="middle" dominant-baseline="central" class="donut-empty">0</text>
    </svg>`;
	}
	const segments = donutSegments(n);
	let offset = 0;
	const arcs = segments
		.map((segment) => {
			const r = segment.value / total;
			const len = r * C;
			const dash = `${Math.max(0, len - 1.5)} ${C - Math.max(0, len - 1.5)}`;
			const arc = `<circle cx="32" cy="32" r="${R}" fill="none"
      stroke="var(--c-${segment.key})" stroke-width="7"
      stroke-dasharray="${dash}" stroke-dashoffset="${-offset * C}"
      transform="rotate(-90 32 32)" stroke-linecap="round"/>`;
			offset += r;
			return arc;
		})
		.join("");
	return `<svg class="donut" viewBox="0 0 64 64" width="76" height="76" aria-hidden="true">
    <circle cx="32" cy="32" r="${R}" fill="none" stroke="var(--surf-3)" stroke-width="7"/>
    ${arcs}
    <text x="32" y="28" text-anchor="middle" dominant-baseline="central" class="donut-n">${total}</text>
    <text x="32" y="41" text-anchor="middle" dominant-baseline="central" class="donut-l">总表征</text>
  </svg>`;
}

export function buildFullDataPreview(model) {
	const universal =
		model.universal.map((item) => item.content).join("；") || "（暂无）";
	const contextual =
		model.contextual
			.map((item) => `${item.scene}→${item.behavior}`)
			.join("；") || "（暂无）";
	const specific =
		model.specific.map((item) => item.content).join("；") || "（暂无）";
	return `通用风格：${universal}；情境提示：${contextual}；特定层数据：${specific}`;
}

export function renderOverview(onLearn) {
	const sid = store.sid;
	if (!sid) return;
	const n = counts(sid);
	const total = n.u + n.c + n.p;
	const caps = store.caps || {};
	const specSorted = [
		...((store.snapshot.specific && store.snapshot.specific[sid]) || []),
	]
		.sort((a, b) => (b.trigger_count || 0) - (a.trigger_count || 0))
		.slice(0, 5);

	const portrait = buildFullDataPreview(store.model);

	const box = $("tabOverview");
	if (total === 0) {
		box.innerHTML =
			`<div class="ov-empty-wrap">` +
			emptyState({
				title: "该会话暂无学习沉淀",
				desc: "随着群聊或私聊进行，插件会自动调用大模型分析并提取风格。\n你也可以点击下方按钮立即触发单次分析学习。",
				art: "chat",
			}) +
			`<button class="btn btn-primary" id="ovLearn">${icon("sparkles", 15)} 立即触发学习分析</button></div>`;
		const ov = $("ovLearn");
		if (ov) ov.onclick = () => onLearn?.();
		return;
	}

	box.innerHTML = `
    <div class="stat-grid">
      <div class="stat total-card">
        <div class="stat-inner">
          <div class="stat-header-sub">
            <span class="stat-tag-badge">综合全览</span>
          </div>
          <div class="stat-val-group">
            <div class="stat-n">${total}</div>
            <div class="stat-l">已捕获特征条目</div>
          </div>
        </div>
        <div class="stat-donut-wrap">
          ${donutHTML(n)}
        </div>
      </div>
      ${LAYER_ORDER.map((k, i) => {
				const L = LAYERS[i];
				const cnt =
					counts(sid)[{ universal: "u", contextual: "c", specific: "p" }[k]];
				const cap =
					caps[k] ?? { universal: 10, contextual: 150, specific: 200 }[k];
				const pct = cap > 0 ? Math.min(100, Math.round((cnt / cap) * 100)) : 0;
				return `<div class="stat layer-stat-card card-${k}">
          <div class="stat-head">
            <div class="stat-l">${icon(L.icon, 14)} <span class="layer-title-text">${L.name}表征</span></div>
            <span class="stat-cap-tag">${cnt} / ${cap}</span>
          </div>
          <div class="stat-body-val">
            <div class="stat-n stat-color-${k}">${cnt}</div>
            <div class="cap-track-wrap">
              <div class="cap-track" title="已用容量 ${pct}%">
                <span class="cap-fill cap-${k}" style="width:${pct}%"></span>
              </div>
              <span class="cap-pct-text">${pct}%</span>
            </div>
          </div>
        </div>`;
			}).join("")}
    </div>

    <div class="ov-2col">
      <div class="card-box terminal-card">
        <div class="card-head terminal-head">
          <div class="card-head-title">
            <div class="terminal-dots" aria-hidden="true">
              <span class="t-dot t-red"></span>
              <span class="t-dot t-yellow"></span>
              <span class="t-dot t-green"></span>
            </div>
            ${icon("edit", 14)} 
            <h3>全量风格注入画像预览</h3>
          </div>
          <button class="mini-btn copy-action-btn" id="copyPortrait" type="button" title="复制提示词内容">
            ${icon("copy", 12)} <span>复制</span>
          </button>
        </div>
        <div class="terminal-body">
          <div class="quote" id="ovPortrait"></div>
        </div>
        <div class="ov-note">
          <span class="note-dot"></span>
          <span>此内容将注入每次回复以引导语气和表达方式，不得覆盖原有身份、安全要求或任务约束；<code>trigger_count</code> 仍按正则命中累加。</span>
        </div>
      </div>

      <div class="card-box meme-leaderboard-card">
        <div class="card-head">
          <div class="card-head-title">
            ${icon("bolt", 15)} 
            <h3>热门群梗排行榜</h3>
          </div>
          <span class="card-head-sub">Top 5 触发频次</span>
        </div>
        <div class="meme-list-wrapper" id="ovTopList"></div>
        <div class="ov-note">
          <span class="note-dot"></span>
          <span>按触发次数自动降序排列 · 仅统计匹配成功的词条</span>
        </div>
      </div>
    </div>`;

	$("ovPortrait").textContent = portrait;

	// 复制预览文本；clipboard 不可用时使用浏览器原生降级路径。
	const copyBtn = $("copyPortrait");
	if (copyBtn) {
		copyBtn.addEventListener("click", async () => {
			const text = portrait;
			let ok = false;
			try {
				if (navigator.clipboard && navigator.clipboard.writeText) {
					await navigator.clipboard.writeText(text);
					ok = true;
				}
			} catch (e) {
				/* 降级到 execCommand */
			}
			if (!ok) {
				try {
					const ta = document.createElement("textarea");
					ta.value = text;
					ta.style.position = "fixed";
					ta.style.opacity = "0";
					document.body.appendChild(ta);
					ta.select();
					ok = document.execCommand("copy");
					ta.remove();
				} catch (e) {
					ok = false;
				}
			}
			if (ok) {
				copyBtn.innerHTML = `${icon("check", 12)} <span>已复制</span>`;
				copyBtn.classList.add("copied");
				setTimeout(() => {
					copyBtn.innerHTML = `${icon("copy", 12)} <span>复制</span>`;
					copyBtn.classList.remove("copied");
				}, 2000);
				toast("已复制全量风格数据预览");
			} else {
				toast("复制失败，请手动选择文本复制", "error");
			}
		});
	}

	const topBox = $("ovTopList");
	if (specSorted.length) {
		const ol = el("ol", "top-list");
		specSorted.forEach((x, i) => {
			const li = el("li", `top-item rank-${i + 1}`);
			const rank = el("span", `top-rank-badge rank-badge-${i + 1}`);
			rank.textContent = String(i + 1);
			const txt = el("span", "top-txt");
			txt.textContent = x.content;
			const regexPill = el("span", "top-regex-pill");
			regexPill.textContent = x.trigger_regex || "-";
			const tc = el("span", "top-count");
			tc.textContent = `${x.trigger_count} 次`;
			li.append(rank, txt, regexPill, tc);
			ol.appendChild(li);
		});
		topBox.appendChild(ol);
	} else {
		topBox.innerHTML = emptyState({
			title: "暂无特定群梗记录",
			desc: "插件在识别到群内高频用语后会自动提炼。",
			art: "empty",
		});
	}
}
