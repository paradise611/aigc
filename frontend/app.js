// ====== 赛博错题医生 - 前端主脚本 ======
const state = {
  sessionId: null,
  selectedImageBase64: "",
  selectedImageName: "",
  allMistakes: [],
  isRecording: false,
  recognition: null,
  activeAnalysisTab: "knowledge",
  bubbleChart: null,
  chatHistory: [],
  currentHistoryId: null,
};

const els = {
  navButtons: document.querySelectorAll(".nav-button"),
  views: document.querySelectorAll(".view"),
  modelStatus: document.getElementById("modelStatus"),
  messageList: document.getElementById("messageList"),
  chatForm: document.getElementById("chatForm"),
  messageInput: document.getElementById("messageInput"),
  imageInput: document.getElementById("imageInput"),
  uploadHint: document.getElementById("uploadHint"),
  voiceButton: document.getElementById("voiceButton"),
  newChatButton: document.getElementById("newChatButton"),
  analysisTotal: document.getElementById("analysisTotal"),
  statMastered: document.getElementById("statMastered"),
  statDifficult: document.getElementById("statDifficult"),
  statUnmastered: document.getElementById("statUnmastered"),
  analysisTabs: document.querySelectorAll(".analysis-tab"),
  analysisPanels: document.querySelectorAll(".analysis-panel"),
  bubbleChartEl: document.getElementById("bubble-chart"),
  abilityGrid: document.getElementById("abilityGrid"),
  abilitySummary: document.getElementById("abilitySummary"),
  mistakeInsightList: document.getElementById("mistakeInsightList"),
  historyList: document.getElementById("historyList"),
  clearHistoryBtn: document.getElementById("clearHistoryBtn"),
};

// ====== 页面切换 ======
function switchView(viewName) {
  els.navButtons.forEach((b) => b.classList.toggle("active", b.dataset.view === viewName));
  els.views.forEach((v) => v.classList.toggle("active", v.id === `${viewName}View`));
  if (viewName === "analysis") loadMistakes();
}

// ====== API 请求 ======
async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || "请求失败");
  return data;
}

// ====== 工具函数 ======
function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatText(text) {
  let html = escapeHtml(text);

  // 修复不匹配的 LaTeX 定界符：$$...$ → $$...$$（支持多行）
  html = html.replace(/\$\$([\s\S]+?)\$(?!\$)/g, "$$$1$$");
  // 修复 $...$$ → $...$
  html = html.replace(/(?<!\$)\$([\s\S]+?)\$\$/g, "$$$1$$");

  // 处理标题：### xxx 或 ## xxx
  html = html.replace(/^#{2,3}\s*(.+)$/gm, '<strong style="font-size:1.05em">$1</strong>');

  // 处理粗体：**xxx**
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  // 处理斜体：*xxx*（但不匹配列表项开头的 *）
  html = html.replace(/(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)/g, "<em>$1</em>");

  // 处理无序列表项：- item 或 * item（行首）
  html = html.replace(/^[\-\*]\s+(.+)$/gm, '&nbsp;&nbsp;● $1');

  // 处理有序列表项：1. item
  html = html.replace(/^(\d+)\.\s+(.+)$/gm, '&nbsp;&nbsp;$1. $2');

  // 清理残留的 # 号（行首独立的 # 标记）
  html = html.replace(/^#+\s*/gm, "");

  // 清理残留的 * 号（行首或独立的 *）
  html = html.replace(/^\*\s*/gm, "");

  // 换行转 <br>
  html = html.replace(/\n/g, "<br>");

  return html;
}

function formatDate(value) {
  if (!value) return "";
  return value.replace("T", " ").slice(0, 16);
}

function unique(items) {
  return [...new Set(items)];
}

// ====== 历史记录管理 (localStorage持久化) ======
const HISTORY_STORAGE_KEY = "cyber_mistake_chat_history";

function loadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_STORAGE_KEY);
    state.chatHistory = raw ? JSON.parse(raw) : [];
  } catch {
    state.chatHistory = [];
  }
  renderHistoryList();
}

function saveHistoryToStorage() {
  try {
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(state.chatHistory));
  } catch {
    // localStorage 可能已满，忽略
  }
}

function renderHistoryList() {
  if (!els.historyList) return;

  if (!state.chatHistory.length) {
    els.historyList.innerHTML = '<div class="history-empty">暂无历史记录</div>';
    return;
  }

  els.historyList.innerHTML = state.chatHistory
    .slice()
    .reverse()
    .map((item) => {
      const isActive = item.id === state.currentHistoryId;
      const title = escapeHtml(item.title || "未命名对话");
      const time = item.updatedAt ? formatDate(item.updatedAt) : "";
      return `
        <div class="history-item${isActive ? " active" : ""}" data-history-id="${item.id}">
          <div class="history-item__title">${title}</div>
          <div class="history-item__meta">
            <span>${time}</span>
            <button class="history-item__delete" data-action="delete-history" data-history-id="${item.id}">✕</button>
          </div>
        </div>
      `;
    })
    .join("");
}

function saveCurrentChatToHistory() {
  const messages = els.messageList.querySelectorAll(".message");
  if (messages.length === 0) return;

  const msgs = [];
  messages.forEach((msg) => {
    const role = msg.classList.contains("user") ? "user" : "assistant";
    const bubble = msg.querySelector(".bubble");
    if (bubble) {
      // Get raw text (innerText preserves visible text without HTML tags)
      msgs.push({ role, content: bubble.innerText });
    }
  });

  if (msgs.length === 0) return;

  // Use first user message as title
  const firstUser = msgs.find((m) => m.role === "user");
  const title = firstUser ? firstUser.content.slice(0, 40) : "对话记录";

  const now = new Date().toISOString();

  if (state.currentHistoryId) {
    // Update existing entry
    const idx = state.chatHistory.findIndex((h) => h.id === state.currentHistoryId);
    if (idx >= 0) {
      state.chatHistory[idx].messages = msgs;
      state.chatHistory[idx].title = title;
      state.chatHistory[idx].updatedAt = now;
    }
  } else {
    // Create new entry
    const id = "hist_" + Date.now();
    state.chatHistory.push({
      id,
      title,
      messages: msgs,
      createdAt: now,
      updatedAt: now,
    });
    state.currentHistoryId = id;
  }

  saveHistoryToStorage();
  renderHistoryList();
}

function restoreChat(id) {
  const item = state.chatHistory.find((h) => h.id === id);
  if (!item) return;

  state.currentHistoryId = id;
  els.messageList.innerHTML = "";
  item.messages.forEach((m) => {
    appendMessage(m.role, m.content);
  });
  renderHistoryList();
  switchView("chat");
}

function deleteHistoryItem(id, event) {
  if (event) event.stopPropagation();
  state.chatHistory = state.chatHistory.filter((h) => h.id !== id);
  if (state.currentHistoryId === id) {
    state.currentHistoryId = null;
  }
  saveHistoryToStorage();
  renderHistoryList();
}

function clearAllHistory() {
  if (!confirm("确定清空全部历史记录吗？此操作不可撤销。")) return;
  state.chatHistory = [];
  state.currentHistoryId = null;
  saveHistoryToStorage();
  renderHistoryList();
}

// 历史记录点击事件（事件委托）
els.historyList.addEventListener("click", (e) => {
  // 删除按钮
  const delBtn = e.target.closest("[data-action='delete-history']");
  if (delBtn) {
    deleteHistoryItem(delBtn.dataset.historyId, e);
    return;
  }

  // 点击历史条目
  const historyItem = e.target.closest(".history-item");
  if (historyItem) {
    const id = historyItem.dataset.historyId;
    if (id) restoreChat(id);
  }
});

// 清空历史按钮
els.clearHistoryBtn.addEventListener("click", clearAllHistory);

// ====== 消息处理 ======
function appendMessage(role, content) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  article.innerHTML = `<div class="avatar">${role === "user" ? "我" : "AI"}</div><div class="bubble">${formatText(content)}</div>`;
  els.messageList.appendChild(article);
  // KaTeX 渲染数学公式
  const bubble = article.querySelector(".bubble");
  if (bubble && typeof renderMathInElement !== "undefined") {
    try { renderMathInElement(bubble, { delimiters: [{ left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false }] }); } catch (e) {}
  }
  els.messageList.scrollTop = els.messageList.scrollHeight;
}

// 显示/移除思考中状态
function showThinking() {
  const think = document.createElement("article");
  think.className = "message assistant";
  think.id = "thinkingMsg";
  think.innerHTML = '<div class="avatar">AI</div><div class="bubble thinking-bubble"><span class="thinking-dot"></span><span class="thinking-dot"></span><span class="thinking-dot"></span> AI 正在思考中...</div>';
  els.messageList.appendChild(think);
  els.messageList.scrollTop = els.messageList.scrollHeight;
}

function hideThinking() {
  const el = document.getElementById("thinkingMsg");
  if (el) el.remove();
}

// ====== 发送聊天 ======
async function submitChat(event) {
  event.preventDefault();
  const raw = els.messageInput.value.trim();
  if (!raw && !state.selectedImageBase64) return;

  const imageData = state.selectedImageBase64;
  const imageName = state.selectedImageName;
  let message = raw;
  if (imageData) {
    message = raw ? `${raw}\n\n[已上传图片：${imageName}]` : `[已上传图片：${imageName}]`;
  }

  appendMessage("user", message);
  els.messageInput.value = "";
  state.selectedImageBase64 = "";
  state.selectedImageName = "";
  els.imageInput.value = "";
  els.uploadHint.textContent = "支持文本问诊、图片上传（自动OCR识别）、语音输入。";

  const sendBtn = els.chatForm.querySelector("button[type='submit']");
  sendBtn.disabled = true;
  const origText = sendBtn.textContent;
  sendBtn.textContent = "思考中...";

  // 显示思考动画
  showThinking();

  try {
    const body = { session_id: state.sessionId, message };
    if (imageData) body.image = imageData;
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify(body),
    });
    state.sessionId = data.session_id;
    hideThinking();
    appendMessage("assistant", data.reply);
    saveCurrentChatToHistory();
  } catch (error) {
    hideThinking();
    appendMessage("assistant", `请求失败：${error.message}`);
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = origText;
  }
}

function startNewChat() {
  saveCurrentChatToHistory();
  state.sessionId = null;
  state.currentHistoryId = null;
  els.messageList.innerHTML = "";
  appendMessage("assistant", "新的问诊已经开始。请发来题目、你的原答案和困惑点，我会先定位错误节点，再给出认知修复建议。");
  renderHistoryList();
}

// ====== 健康检测 ======
async function loadHealth() {
  try {
    const data = await api("/api/health");
    els.modelStatus.textContent = data.llm_enabled ? data.model : "本地演示";
  } catch {
    els.modelStatus.textContent = "离线";
  }
}

// ====== 错题分析 - 学习看板 ======
async function loadMistakes() {
  try {
    const data = await api("/api/mistakes");
    const items = data.mistakes || [];
    state.allMistakes = items;
    renderStatsCards(items);
    renderKnowledgeAnalysis(items);
    renderAbilityAnalysis(items);
    renderMistakeInsightList(items);
  } catch (error) {
    els.analysisTotal.textContent = "0";
    els.abilityGrid.innerHTML = '<div class="empty-state">暂时无法生成能力分析</div>';
    els.mistakeInsightList.innerHTML = '<div class="empty-state">暂无可展示的错题记录</div>';
    if (state.bubbleChart) {
      state.bubbleChart.dispose();
      state.bubbleChart = null;
    }
    if (els.bubbleChartEl) els.bubbleChartEl.style.display = "none";
  }
}

function renderStatsCards(items) {
  const total = items.length;
  const buckets = { mastered: 0, difficult: 0, unmastered: 0 };
  items.forEach((item) => {
    const level = getMasteryLevel(item);
    if (level >= 80) buckets.mastered += 1;
    else if (level >= 40) buckets.difficult += 1;
    else buckets.unmastered += 1;
  });

  els.analysisTotal.textContent = total;
  els.statMastered.textContent = buckets.mastered;
  els.statDifficult.textContent = buckets.difficult;
  els.statUnmastered.textContent = buckets.unmastered;
}

function getMasteryLevel(item) {
  const titleLen = (item.title || "").replace(/\s+/g, "").length;
  const tagsWeight = (item.tags || []).join("").length * 4;
  const subjectWeight = (item.subject || "").length * 5;
  const errorPenaltyMap = {
    概念混淆: 34,
    方法误用: 30,
    逻辑跳跃: 26,
    审题偏差: 22,
    步骤遗漏: 18,
    计算失误: 15,
  };
  const errorPenalty = errorPenaltyMap[item.error_type] || 20;
  const level = 96 - errorPenalty + ((titleLen + tagsWeight + subjectWeight) % 18) - ((item.tags || []).length > 2 ? 3 : 0);
  return Math.max(22, Math.min(95, level));
}

function getMasteryBucket(level) {
  if (level >= 80) return "mastered";
  if (level >= 40) return "difficult";
  return "unmastered";
}

function renderKnowledgeAnalysis(items) {
  const chartDom = els.bubbleChartEl;
  if (!chartDom) return;

  // Dispose existing chart instance
  if (state.bubbleChart) {
    state.bubbleChart.dispose();
    state.bubbleChart = null;
  }

  if (!items.length) {
    chartDom.style.display = "none";
    return;
  }

  chartDom.style.display = "block";

  // Aggregate data by tags/subjects
  const pointMap = new Map();
  items.forEach((item) => {
    const points = (item.tags && item.tags.length ? item.tags : [item.subject || item.error_type || "综合"]).slice(0, 3);
    const level = getMasteryLevel(item);
    points.forEach((point) => {
      if (!pointMap.has(point)) {
        pointMap.set(point, { name: point, count: 0, totalLevel: 0 });
      }
      const record = pointMap.get(point);
      record.count += 1;
      record.totalLevel += level;
    });
  });

  const bubbles = [...pointMap.values()]
    .map((point) => {
      const level = Math.round(point.totalLevel / point.count);
      return { ...point, level };
    })
    .sort((a, b) => b.count - a.count)
    .slice(0, 20);

  // Build ECharts scatter data with centered, tight-packing bubbles
  const byCount = [...bubbles].sort((a, b) => a.count - b.count);
  const byLevel = [...bubbles].sort((a, b) => a.level - b.level);
  const centerX = 5, centerY = 5;
  const n = bubbles.length - 1 || 1;

  // Auto-adapt bubble size to fill space
  const maxCount = Math.max(...bubbles.map(b => b.count), 1);
  const fillScale = bubbles.length <= 5 ? 1.5 : bubbles.length <= 10 ? 1.2 : 1.0;
  const baseSize = 55 + (10 - Math.min(bubbles.length, 15)) * 3;

  // Measure actual chart container for accurate px-per-unit ratio
  const containerWidth = chartDom.clientWidth || 550;
  const containerHeight = chartDom.clientHeight || 400;
  const pxPerUnit = Math.min(containerWidth, containerHeight) / 10;
  const radiusOverestimate = 1.2; // overestimate to ensure zero gaps

  // Build initial nodes with rank-order positions and sizes
  let nodes = bubbles.map((item) => {
    let color;
    if (item.level >= 80) color = "#32bc73";
    else if (item.level >= 40) color = "#ffaa22";
    else color = "#f2496c";

    const xRank = byCount.findIndex(b => b.name === item.name);
    const yRank = byLevel.findIndex(b => b.name === item.name);
    const x = centerX + ((xRank / n) - 0.5) * 1.5;
    const y = centerY + ((yRank / n) - 0.5) * 1.5;
    const rawSize = baseSize + (item.count / Math.max(maxCount, 1)) * 60 * fillScale;
    const size = Math.max(55, Math.min(170, Math.round(rawSize)));
    // radius in chart units using actual container size
    const radius = (size / 2) / pxPerUnit * radiusOverestimate;

    return { name: item.name, x, y, size, radius, rate: item.level, count: item.count, color };
  });

  // Repulsion simulation: push overlapping apart, pull to center, zero gaps
  for (let iter = 0; iter < 120; iter++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[j].x - nodes[i].x;
        const dy = nodes[j].y - nodes[i].y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 0.001;
        const minDist = nodes[i].radius + nodes[j].radius;
        if (dist < minDist) {
          const force = (minDist - dist) / dist * 0.5;
          const fx = dx * force;
          const fy = dy * force;
          nodes[i].x -= fx;
          nodes[i].y -= fy;
          nodes[j].x += fx;
          nodes[j].y += fy;
        }
      }
    }
    // Pull toward center, clamp to bounds
    for (const node of nodes) {
      node.x += (centerX - node.x) * 0.03;
      node.y += (centerY - node.y) * 0.03;
      const pad = node.radius * 0.5;
      node.x = Math.max(pad, Math.min(10 - pad, node.x));
      node.y = Math.max(pad, Math.min(10 - pad, node.y));
    }
  }

  const seriesData = nodes.map(n => ({
    name: n.name,
    value: [n.x, n.y, n.size],
    rate: n.rate,
    count: n.count,
    itemStyle: { color: n.color },
  }));

  const chart = echarts.init(chartDom);
  state.bubbleChart = chart;

  const option = {
    tooltip: {
      formatter: function (params) {
        return params.name + "<br>掌握率: " + params.data.rate + "%<br>错题数: " + (params.data.count || 0);
      },
    },
    xAxis: { show: false, min: 0, max: 10 },
    yAxis: { show: false, min: 0, max: 10 },
    grid: { left: 5, right: 5, top: 5, bottom: 5 },
    series: [
      {
        type: "scatter",
        data: seriesData,
        symbolSize: function (val) {
          return val[2];
        },
        label: {
          show: true,
          color: "#fff",
          fontSize: 13,
          formatter: function (params) {
            return params.name + "\n" + params.data.rate + "%";
          },
        },
        emphasis: {
          scale: true,
        },
      },
    ],
  };

  chart.setOption(option);
}

function renderAbilityAnalysis(items) {
  if (!items.length) {
    els.abilitySummary.textContent = "暂无数据，请先新增错题记录。";
    els.abilityGrid.innerHTML = `<div class="empty-state">当前没有足够的数据生成能力画像。</div>`;
    return;
  }

  const counts = CounterLike(items.map((item) => item.error_type || "思路不完整"));
  const total = items.length;
  const scoreConfig = [
    { key: "reading", title: "审题能力", errors: ["审题偏差"], desc: "读取条件、提炼关键限制" },
    { key: "logic", title: "逻辑推理", errors: ["逻辑跳跃", "步骤遗漏"], desc: "推导链路是否完整清晰" },
    { key: "calculation", title: "计算执行", errors: ["计算失误"], desc: "过程稳定度与细节控制" },
    { key: "strategy", title: "方法选择", errors: ["方法误用", "概念混淆", "思路不完整"], desc: "模型匹配与知识调用" },
  ];

  const abilityCards = scoreConfig.map((config) => {
    const penalty = config.errors.reduce((sum, errorType) => sum + (counts[errorType] || 0), 0);
    const score = Math.max(35, Math.min(96, Math.round(100 - (penalty / total) * 58)));
    return { ...config, score };
  });

  const weakest = [...abilityCards].sort((a, b) => a.score - b.score)[0];
  els.abilitySummary.textContent = `当前最需要优先提升的是「${weakest.title}」，建议先围绕相关错题做定向复盘。`;
  els.abilityGrid.innerHTML = abilityCards.map((card) => `
    <article class="ability-card">
      <div class="ability-card__top">
        <div>
          <h4>${card.title}</h4>
          <p>${card.desc}</p>
        </div>
        <strong>${card.score}</strong>
      </div>
      <div class="ability-progress">
        <span class="ability-progress__bar" style="width:${card.score}%"></span>
      </div>
      <span class="ability-card__hint">${abilityComment(card.score)}</span>
    </article>
  `).join("");
}

function abilityComment(score) {
  if (score >= 85) return "状态稳定，可继续用变式题巩固。";
  if (score >= 65) return "基础不错，建议结合错因做针对训练。";
  return "相对薄弱，优先安排专项复盘与练习。";
}

function renderMistakeInsightList(items) {
  if (!items.length) {
    els.mistakeInsightList.innerHTML = `<div class="empty-state">还没有可供复盘的错题。</div>`;
    return;
  }

  els.mistakeInsightList.innerHTML = items.map((item) => {
    const level = getMasteryLevel(item);
    const bucket = getMasteryBucket(level);
    const tags = (item.tags || []).slice(0, 3).map((tag) => `<span class="tag-sm">${escapeHtml(tag)}</span>`).join("");
    return `
      <article class="mistake-insight-card">
        <div class="mistake-insight-card__meta">
          <span class="subject-badge">${escapeHtml(item.subject || "综合")}</span>
          <span class="mistake-level mistake-level--${bucket}">${level}%</span>
        </div>
        <h4>${escapeHtml(item.title || "未命名错题")}</h4>
        <p>${escapeHtml(item.error_type || "思路不完整")} · ${formatDate(item.created_at) || "刚刚"}</p>
        <div class="title-tags">${tags}</div>
        <div class="action-btns">
          <button class="detail-btn" data-action="view" data-id="${item.id}">查看</button>
          <button class="edit-btn" data-action="edit" data-id="${item.id}">编辑</button>
          <button class="delete-btn" data-action="delete" data-id="${item.id}">删除</button>
        </div>
      </article>
    `;
  }).join("");
}

function CounterLike(values) {
  return values.reduce((acc, value) => {
    acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, {});
}

function showMistakeDetail(id) {
  const item = state.allMistakes.find((m) => m.id === id);
  if (!item) return;
  const detail = [
    `📝 题目: ${item.title}`,
    `📚 科目: ${item.subject || "未知"}`,
    `❌ 错误类型: ${item.error_type || "未知"}`,
    `🏷 知识点标签: ${(item.tags || []).join("、") || "无"}`,
    `🔍 根因分析: ${item.root_cause || "暂无"}`,
    `✅ 正确思路: ${item.correct_idea || "暂无"}`,
    `📋 训练建议: ${(item.training_plan || []).join("；") || "暂无"}`,
    `🕐 时间: ${formatDate(item.created_at)}`,
  ].join("\n\n");
  alert(detail);
}

// ====== 图片上传 ======
els.imageInput.addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (!file) return;
  state.selectedImageName = file.name;
  els.uploadHint.textContent = `处理中：${file.name}...`;
  const reader = new FileReader();
  reader.onload = (e) => {
    state.selectedImageBase64 = e.target.result;
    els.uploadHint.textContent = `已加载：${file.name}，发送后自动OCR识别`;
  };
  reader.onerror = () => {
    state.selectedImageName = "";
    els.uploadHint.textContent = "图片读取失败，请重试";
  };
  reader.readAsDataURL(file);
});

// ====== 语音输入 ======
els.voiceButton.addEventListener("click", () => {
  if (state.isRecording) { stopRecording(); return; }
  startRecording();
});

function startRecording() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    alert("您的浏览器不支持语音输入，请使用 Chrome 或 Edge 浏览器。");
    return;
  }
  state.recognition = new SR();
  state.recognition.lang = "zh-CN";
  state.recognition.interimResults = true;
  state.recognition.continuous = true;

  // 保存输入框中已有的文字，防止多次录音互相覆盖
  state.voiceBaseText = els.messageInput.value;

  state.recognition.onresult = (event) => {
    let transcript = "";
    // 从 0 开始遍历全部结果，避免新句子覆盖旧句子
    for (let i = 0; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    // 拼接之前已有的文字 + 当前语音识别结果，防止多次录音覆盖
    els.messageInput.value = (state.voiceBaseText ? state.voiceBaseText + " " : "") + transcript;
  };
  state.recognition.onerror = (event) => {
    console.error("语音错误:", event.error);
    stopRecording();
  };
  state.recognition.onend = () => { if (state.isRecording) stopRecording(); };

  state.recognition.start();
  state.isRecording = true;
  els.voiceButton.classList.add("recording");
  els.voiceButton.textContent = "⏹";
  els.uploadHint.textContent = "正在录音...请说话";
}

function stopRecording() {
  if (state.recognition) { state.recognition.stop(); state.recognition = null; }
  state.isRecording = false;
  els.voiceButton.classList.remove("recording");
  els.voiceButton.textContent = "🎤";
  els.uploadHint.textContent = "语音输入已停止。支持文本问诊、图片上传、语音输入。";
}

// ====== 事件绑定 ======
els.navButtons.forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});
els.chatForm.addEventListener("submit", submitChat);
els.newChatButton.addEventListener("click", startNewChat);
els.analysisTabs.forEach((tab) => {
  tab.addEventListener("click", () => switchAnalysisTab(tab.dataset.tab));
});

// 允许按 Enter 发送（Ctrl+Enter 换行）
els.messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.ctrlKey && !e.shiftKey) {
    e.preventDefault();
    els.chatForm.dispatchEvent(new Event("submit"));
  }
});

// 卡片操作按钮（事件委托）
document.getElementById("analysisView").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const action = btn.dataset.action;
  const id = btn.dataset.id;
  if (action === "view") showMistakeDetail(id);
  else if (action === "edit") editMistake(id);
  else if (action === "delete") deleteMistake(id);
});

function switchAnalysisTab(tabName) {
  state.activeAnalysisTab = tabName;
  els.analysisTabs.forEach((tab) => {
    const isActive = tab.dataset.tab === tabName;
    tab.classList.toggle("active", isActive);
    tab.setAttribute("aria-selected", String(isActive));
  });
  els.analysisPanels.forEach((panel) => {
    const isActive = panel.id === `${tabName}Panel`;
    panel.classList.toggle("active", isActive);
    panel.hidden = !isActive;
  });
  // Resize chart when switching to knowledge tab
  if (tabName === "knowledge" && state.bubbleChart) {
    setTimeout(() => state.bubbleChart.resize(), 100);
  }
}

async function editMistake(id) {
  const item = state.allMistakes.find((m) => m.id === id);
  if (!item) return;
  const newTitle = prompt("修改题目：", item.title);
  if (newTitle === null) return;
  try {
    await api(`/api/mistakes/${id}`, {
      method: "PUT",
      body: JSON.stringify({ title: newTitle }),
    });
    loadMistakes();
  } catch (error) {
    alert("编辑失败：" + error.message);
  }
}

async function deleteMistake(id) {
  if (!confirm("确定删除这条错题记录吗？此操作不可撤销。")) return;
  try {
    await api(`/api/mistakes/${id}`, { method: "DELETE" });
    loadMistakes();
  } catch (error) {
    alert("删除失败：" + error.message);
  }
}

// ====== 窗口自适应 - 图表 resize ======
window.addEventListener("resize", () => {
  if (state.bubbleChart) state.bubbleChart.resize();
});

// ====== 启动 ======
loadHealth();
loadHistory();
