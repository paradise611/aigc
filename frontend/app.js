const state = {
  sessionId: null,
  selectedImageName: "",
  sessions: [],
  mistakes: [],
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
  newChatButton: document.getElementById("newChatButton"),
  historyCount: document.getElementById("historyCount"),
  mistakeCount: document.getElementById("mistakeCount"),
  historyList: document.getElementById("historyList"),
  historyDetail: document.getElementById("historyDetail"),
  historyDetailTitle: document.getElementById("historyDetailTitle"),
  refreshHistoryButton: document.getElementById("refreshHistoryButton"),
  analysisForm: document.getElementById("analysisForm"),
  analysisInput: document.getElementById("analysisInput"),
  analysisOutput: document.getElementById("analysisOutput"),
  mistakeList: document.getElementById("mistakeList"),
  subjectFilter: document.getElementById("subjectFilter"),
  errorFilter: document.getElementById("errorFilter"),
  refreshMistakesButton: document.getElementById("refreshMistakesButton"),
};

function switchView(viewName) {
  els.navButtons.forEach((button) => button.classList.toggle("active", button.dataset.view === viewName));
  els.views.forEach((view) => view.classList.toggle("active", view.id === `${viewName}View`));
  if (viewName === "history") loadHistory();
  if (viewName === "analysis") loadMistakes();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function appendMessage(role, content) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  article.innerHTML = `
    <div class="avatar">${role === "user" ? "我" : "AI"}</div>
    <div class="bubble">${formatText(content)}</div>
  `;
  els.messageList.appendChild(article);
  els.messageList.scrollTop = els.messageList.scrollHeight;
}

function formatText(text) {
  return escapeHtml(text)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function setLoading(button, isLoading, text) {
  if (!button.dataset.label) button.dataset.label = button.textContent;
  button.disabled = isLoading;
  button.textContent = isLoading ? text : button.dataset.label;
}

async function submitChat(event) {
  event.preventDefault();
  const raw = els.messageInput.value.trim();
  if (!raw && !state.selectedImageName) return;

  const message = state.selectedImageName ? `${raw}\n\n[已上传图片：${state.selectedImageName}]` : raw;
  appendMessage("user", message);
  els.messageInput.value = "";
  state.selectedImageName = "";
  els.uploadHint.textContent = "支持文本问诊；图片入口会把文件名作为上下文附加到问题中。";
  const submitButton = els.chatForm.querySelector("button[type='submit']");
  setLoading(submitButton, true, "诊疗中");

  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ session_id: state.sessionId, message }),
    });
    state.sessionId = data.session_id;
    appendMessage("assistant", data.reply);
    await refreshCounts();
  } catch (error) {
    appendMessage("assistant", `请求失败：${error.message}`);
  } finally {
    setLoading(submitButton, false);
  }
}

function startNewChat() {
  state.sessionId = null;
  els.messageList.innerHTML = "";
  appendMessage(
    "assistant",
    "新的问诊已经开始。请发来题目、你的原答案和困惑点，我会先定位错误节点，再给出认知修复建议。"
  );
}

async function loadHealth() {
  try {
    const data = await api("/api/health");
    els.modelStatus.textContent = data.llm_enabled ? data.model : "本地演示";
  } catch {
    els.modelStatus.textContent = "离线";
  }
}

async function loadHistory() {
  const data = await api("/api/history");
  state.sessions = data.sessions;
  els.historyCount.textContent = data.sessions.length;
  renderHistoryList();
}

function renderHistoryList() {
  if (!state.sessions.length) {
    els.historyList.innerHTML = `<div class="empty-state">还没有聊天记录，先去主聊天页面发起一次错题问诊。</div>`;
    return;
  }
  els.historyList.innerHTML = state.sessions
    .map(
      (session) => `
        <button class="history-item" data-session="${session.id}">
          <strong>${escapeHtml(session.title)}</strong>
          <span>${session.message_count} 条消息 · ${formatDate(session.updated_at)}</span>
        </button>
      `
    )
    .join("");
}

async function showHistoryDetail(sessionId) {
  const session = await api(`/api/history/${sessionId}`);
  state.sessionId = session.id;
  els.historyDetailTitle.textContent = session.title;
  els.historyDetail.innerHTML = session.messages
    .map(
      (message) => `
        <article class="message ${message.role}">
          <div class="avatar">${message.role === "user" ? "我" : "AI"}</div>
          <div class="bubble">${formatText(message.content)}</div>
        </article>
      `
    )
    .join("");
}

async function loadMistakes() {
  const params = new URLSearchParams();
  if (els.subjectFilter.value) params.set("subject", els.subjectFilter.value);
  if (els.errorFilter.value) params.set("error_type", els.errorFilter.value);
  const query = params.toString() ? `?${params}` : "";
  const data = await api(`/api/mistakes${query}`);
  state.mistakes = data.mistakes;
  els.mistakeCount.textContent = data.mistakes.length;
  renderFilters(data.mistakes);
  renderMistakes();
}

function renderFilters(items) {
  const currentSubject = els.subjectFilter.value;
  const currentError = els.errorFilter.value;
  const allSubjects = unique([...items.map((item) => item.subject), currentSubject].filter(Boolean));
  const allErrors = unique([...items.map((item) => item.error_type), currentError].filter(Boolean));
  els.subjectFilter.innerHTML = `<option value="">全部学科</option>${allSubjects
    .map((subject) => `<option value="${escapeHtml(subject)}">${escapeHtml(subject)}</option>`)
    .join("")}`;
  els.errorFilter.innerHTML = `<option value="">全部错因</option>${allErrors
    .map((error) => `<option value="${escapeHtml(error)}">${escapeHtml(error)}</option>`)
    .join("")}`;
  els.subjectFilter.value = currentSubject;
  els.errorFilter.value = currentError;
}

function renderMistakes() {
  if (!state.mistakes.length) {
    els.mistakeList.innerHTML = `<div class="empty-state">暂无错题档案。你可以从聊天页自动沉淀，也可以在左侧手动生成。</div>`;
    return;
  }
  els.mistakeList.innerHTML = state.mistakes
    .map(
      (item) => `
        <article class="mistake-item">
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(item.subject)} · ${escapeHtml(item.error_type)} · ${formatDate(item.created_at)}</span>
          <p>${escapeHtml(item.root_cause)}</p>
          <div class="tag-row">${(item.tags || []).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
        </article>
      `
    )
    .join("");
}

async function submitAnalysis(event) {
  event.preventDefault();
  const question = els.analysisInput.value.trim();
  if (!question) return;
  const button = els.analysisForm.querySelector("button[type='submit']");
  setLoading(button, true, "分析中");
  els.analysisOutput.textContent = "正在生成错题档案...";
  try {
    const data = await api("/api/analyze", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    els.analysisOutput.innerHTML = formatText(data.analysis);
    els.analysisInput.value = "";
    await loadMistakes();
    await refreshCounts();
  } catch (error) {
    els.analysisOutput.textContent = `分析失败：${error.message}`;
  } finally {
    setLoading(button, false);
  }
}

async function refreshCounts() {
  const [history, mistakes] = await Promise.all([api("/api/history"), api("/api/mistakes")]);
  els.historyCount.textContent = history.sessions.length;
  els.mistakeCount.textContent = mistakes.mistakes.length;
}

function formatDate(value) {
  if (!value) return "";
  return value.replace("T", " ").slice(0, 16);
}

function unique(items) {
  return [...new Set(items)];
}

els.navButtons.forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

els.chatForm.addEventListener("submit", submitChat);
els.newChatButton.addEventListener("click", startNewChat);
els.refreshHistoryButton.addEventListener("click", loadHistory);
els.refreshMistakesButton.addEventListener("click", loadMistakes);
els.analysisForm.addEventListener("submit", submitAnalysis);
els.subjectFilter.addEventListener("change", loadMistakes);
els.errorFilter.addEventListener("change", loadMistakes);

els.imageInput.addEventListener("change", (event) => {
  const file = event.target.files[0];
  state.selectedImageName = file ? file.name : "";
  els.uploadHint.textContent = state.selectedImageName
    ? `已选择图片：${state.selectedImageName}。发送后会作为题目上下文。`
    : "支持文本问诊；图片入口会把文件名作为上下文附加到问题中。";
});

els.historyList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-session]");
  if (button) showHistoryDetail(button.dataset.session);
});

loadHealth();
refreshCounts();
