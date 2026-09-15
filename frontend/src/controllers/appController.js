import { state } from "../stores/appState.js";
import { api, setUnauthorizedHandler } from "../services/api.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
setUnauthorizedHandler(showAuthScreen);

function newIdempotencyKey() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function syncKnownTask(task) {
  if (!task?.id) return;
  const index = state.tasks.findIndex((item) => item.id === task.id);
  if (index >= 0) state.tasks[index] = task;
  else state.tasks.unshift(task);
  renderTaskCenterBadge();
  if ($("#task-center-dialog")?.open) renderTaskCenter();
}

async function submitMessageTask(conversationId, message) {
  const idempotencyKey = message.idempotencyKey || newIdempotencyKey();
  let task;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      task = await api(`/api/conversations/${conversationId}/message-tasks`, {
        method: "POST",
        body: JSON.stringify({ ...message, idempotencyKey })
      });
      break;
    } catch (error) {
      if (attempt || error.detail) throw error;
      await new Promise((resolve) => setTimeout(resolve, 400));
    }
  }
  if (!task) throw new Error("Unable to create task");
  syncKnownTask(task);
  for (let index = 0; index < 600; index += 1) {
    if (task.status === "completed") return task.result;
    if (["failed", "cancelled", "dead_letter"].includes(task.status)) {
      if (task.status === "dead_letter") await loadTaskCenter({ quiet: true });
      const error = new Error(task.error?.message || "Task execution failed");
      error.detail = task.error || null;
      throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
    task = await api(task.pollUrl || `/api/tasks/${task.id}`);
    syncKnownTask(task);
  }
  throw new Error("Task timed out. You can retry it from the task status endpoint.");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function richText(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .split(/\n{2,}/).map((part) => `<p>${part.replace(/\n/g, "<br>")}</p>`).join("");
}

function markdownInline(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
}

function markdownText(value) {
  const lines = String(value ?? "").replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let paragraph = [];
  let listType = "";
  let code = [];
  let inCode = false;
  const flushParagraph = () => {
    if (paragraph.length) html.push(`<p>${paragraph.map(markdownInline).join("<br>")}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (listType) html.push(`</${listType}>`);
    listType = "";
  };
  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      flushParagraph(); closeList();
      if (inCode) { html.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`); code = []; }
      inCode = !inCode;
      continue;
    }
    if (inCode) { code.push(line); continue; }
    if (!line.trim()) { flushParagraph(); closeList(); continue; }
    const heading = line.match(/^\s*(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph(); closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${markdownInline(heading[2])}</h${level}>`);
      continue;
    }
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const type = unordered ? "ul" : "ol";
      if (listType !== type) { closeList(); html.push(`<${type}>`); listType = type; }
      html.push(`<li>${markdownInline((unordered || ordered)[1])}</li>`);
      continue;
    }
    const quote = line.match(/^\s*>\s?(.+)$/);
    if (quote) { flushParagraph(); closeList(); html.push(`<blockquote>${markdownInline(quote[1])}</blockquote>`); continue; }
    closeList();
    paragraph.push(line);
  }
  if (inCode && code.length) html.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
  flushParagraph(); closeList();
  return html.join("");
}

function uiIcon(name) {
  const icons = {
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    undo: '<path d="m9 14-4-4 4-4"/><path d="M5 10h8a6 6 0 0 1 6 6v1"/>',
    regenerate: '<path d="M20 11a8 8 0 0 0-14.9-4M4 4v5h5"/><path d="M4 13a8 8 0 0 0 14.9 4M20 20v-5h-5"/>',
    save: '<path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M5 19h14"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    eye: '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/>',
    trash: '<path d="M4 7h16"/><path d="M10 11v6m4-6v6"/><path d="m6 7 1 13h10l1-13M9 7V4h6v3"/>',
    loader: '<path d="M21 12a9 9 0 1 1-6.2-8.6"/>'
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || ""}</svg>`;
}

function toast(message, type = "") {
  const element = document.createElement("div");
  element.className = `toast ${type}`;
  element.textContent = message;
  $("#toast-region").append(element);
  setTimeout(() => element.remove(), 4200);
}

function formatDate(value) {
  if (!value) return "";
  const normalized = String(value).endsWith("Z") ? value : `${value.replace(" ", "T")}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const authCountdownTimers = new Map();
let authMode = "password";

function switchAuthMode(mode) {
  authMode = ["password", "sms", "register"].includes(mode) ? mode : "password";
  const passwordMode = authMode === "password";
  const smsMode = authMode === "sms";
  const registerMode = authMode === "register";
  $("#auth-sms-fields").hidden = !smsMode;
  $("#auth-password-fields").hidden = !passwordMode;
  $("#auth-register-fields").hidden = !registerMode;
  $("#auth-phone").required = smsMode;
  $("#auth-code").required = smsMode;
  $("#auth-account").required = passwordMode;
  $("#auth-password").required = passwordMode;
  $("#register-username").required = registerMode;
  $("#register-password").required = registerMode;
  $("#register-confirm-password").required = registerMode;
  $$('[data-auth-mode]').forEach((button) => {
    const active = button.dataset.authMode === authMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $("#auth-hint").textContent = "";
  $("#auth-hint").classList.remove("error");
  const focusTarget = passwordMode ? "#auth-account" : (smsMode ? "#auth-phone" : "#register-username");
  requestAnimationFrame(() => $(focusTarget).focus());
}

function showAuthScreen(message = "") {
  $("#auth-screen").hidden = false;
  $("#auth-hint").textContent = message;
  $("#auth-hint").classList.toggle("error", Boolean(message));
  const focusTarget = authMode === "password" ? "#auth-account" : (authMode === "sms" ? "#auth-phone" : "#register-username");
  requestAnimationFrame(() => $(focusTarget).focus());
}

function renderCurrentUser() {
  const user = state.currentUser;
  if (!user) return;
  $("#sidebar-user").hidden = !state.authEnabled;
  $("#sidebar-user-name").textContent = user.displayName || user.username || user.phone || "用户";
  $("#sidebar-user-role").textContent = user.role === "admin" ? "管理员" : "成员";
  $("#sidebar-user-avatar").textContent = (user.displayName || user.username || user.phone || "用").slice(0, 1);
  const admin = user.role === "admin";
  $("#open-user-management").hidden = !admin;
  $("#open-email-settings").hidden = !admin;
  $("#open-task-center").hidden = !admin;
  $("#configure-email-from-compose").hidden = !admin;
}

async function restoreAuthentication() {
  try {
    const result = await api("/api/auth/me");
    state.authEnabled = result.authEnabled !== false;
    state.currentUser = result.user;
    $("#auth-screen").hidden = true;
    renderCurrentUser();
    return true;
  } catch (error) {
    showAuthScreen(error.status === 401 ? "" : error.message);
    return false;
  }
}

async function sendSmsCode(phoneSelector, codeSelector, buttonSelector, useAuthHint = true) {
  const phone = $(phoneSelector).value.trim();
  const button = $(buttonSelector);
  if (!phone) {
    if (useAuthHint) showAuthScreen("请输入手机号码");
    else toast("请输入手机号码", "error");
    return;
  }
  button.disabled = true;
  try {
    const result = await api("/api/auth/sms/send", { method: "POST", body: JSON.stringify({ phone }) });
    if (result.debugCode) {
      $(codeSelector).value = result.debugCode;
      if (useAuthHint) $("#auth-hint").textContent = `开发模式验证码：${result.debugCode}`;
      else toast(`开发模式验证码：${result.debugCode}`, "success");
    } else {
      if (useAuthHint) $("#auth-hint").textContent = "验证码已发送，请查收短信";
      else toast("验证码已发送，请查收短信", "success");
    }
    if (useAuthHint) $("#auth-hint").classList.remove("error");
    let remaining = Number(result.retryAfter || 60);
    button.textContent = `${remaining}s 后重试`;
    clearInterval(authCountdownTimers.get(buttonSelector));
    const timer = setInterval(() => {
      remaining -= 1;
      button.textContent = remaining > 0 ? `${remaining}s 后重试` : "重新获取";
      if (remaining <= 0) { clearInterval(timer); authCountdownTimers.delete(buttonSelector); button.disabled = false; }
    }, 1000);
    authCountdownTimers.set(buttonSelector, timer);
  } catch (error) {
    if (useAuthHint) {
      $("#auth-hint").textContent = error.message;
      $("#auth-hint").classList.add("error");
    } else {
      toast(error.message, "error");
    }
    button.disabled = false;
  }
}

function sendAuthCode() {
  return sendSmsCode("#auth-phone", "#auth-code", "#send-auth-code");
}

function sendRegisterCode() {
  return sendSmsCode("#register-phone", "#register-code", "#send-register-code");
}

async function submitAuth(event) {
  event.preventDefault();
  const button = $("#auth-submit");
  button.disabled = true;
  try {
    let url = "/api/auth/password/login";
    let payload = { account: $("#auth-account").value.trim(), password: $("#auth-password").value };
    if (authMode === "sms") {
      url = "/api/auth/sms/login";
      payload = { phone: $("#auth-phone").value.trim(), code: $("#auth-code").value.trim() };
    } else if (authMode === "register") {
      const password = $("#register-password").value;
      if (password !== $("#register-confirm-password").value) throw new Error("两次输入的密码不一致");
      const phone = $("#register-phone").value.trim();
      const code = $("#register-code").value.trim();
      if (phone && !code) throw new Error("填写手机号时请输入短信验证码");
      url = "/api/auth/register";
      payload = { username: $("#register-username").value.trim(), password, phone: phone || null, code: code || null };
    }
    const result = await api(url, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    state.currentUser = result.user;
    state.authEnabled = result.authEnabled !== false;
    $("#auth-screen").hidden = true;
    renderCurrentUser();
    await loadAppData();
  } catch (error) {
    $("#auth-hint").textContent = error.message;
    $("#auth-hint").classList.add("error");
  } finally {
    button.disabled = false;
  }
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST" }); } catch { /* local logout still proceeds */ }
  state.currentUser = null;
  window.location.reload();
}

function openAccountSettings() {
  const user = state.currentUser;
  if (!user) return;
  $("#account-settings-form").reset();
  $("#account-username").value = user.username || "";
  $("#account-phone").value = user.phone || "";
  $("#account-current-password-field").hidden = !user.hasPassword;
  $("#account-current-password").required = Boolean(user.hasPassword);
  $("#account-settings-dialog").showModal();
  requestAnimationFrame(() => $("#account-username").focus());
}

function sendAccountPhoneCode() {
  return sendSmsCode("#account-phone", "#account-phone-code", "#send-account-phone-code", false);
}

async function bindAccountPhone() {
  const phone = $("#account-phone").value.trim();
  const code = $("#account-phone-code").value.trim();
  if (!phone || !code) return toast("请输入手机号和验证码", "error");
  const button = $("#bind-account-phone");
  button.disabled = true;
  try {
    const updated = await api("/api/account/phone", {
      method: "PUT",
      body: JSON.stringify({ phone, code })
    });
    state.currentUser = updated;
    renderCurrentUser();
    $("#account-phone-code").value = "";
    toast("手机号已绑定", "success");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function saveAccountSettings(event) {
  event.preventDefault();
  const password = $("#account-new-password").value;
  if (password !== $("#account-confirm-password").value) {
    return toast("两次输入的新密码不一致", "error");
  }
  const button = $("#save-account-settings");
  button.disabled = true;
  try {
    const updated = await api("/api/account/credentials", {
      method: "PUT",
      body: JSON.stringify({
        username: $("#account-username").value.trim(),
        currentPassword: $("#account-current-password").value || null,
        password
      })
    });
    state.currentUser = updated;
    renderCurrentUser();
    $("#account-settings-dialog").close();
    toast("账号密码已保存", "success");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function openUserManagement() {
  try {
    state.users = await api("/api/admin/users");
    renderUserManagement();
    $("#user-management-dialog").showModal();
  } catch (error) { toast(error.message, "error"); }
}

function renderUserManagement() {
  $("#user-management-list").innerHTML = state.users.map((user) => `<div class="user-role-row" data-user-id="${user.id}"><span class="sidebar-user-avatar">${escapeHtml((user.displayName || user.username || user.phone || "用").slice(0, 1))}</span><span><strong>${escapeHtml(user.displayName || user.username || user.phone || "用户")}</strong><small>${escapeHtml(user.username ? `@${user.username} · ${user.phone || "未绑定手机号"}` : (user.phone || "未设置登录账号"))} · ${user.status === "active" ? "正常" : "已停用"}</small></span><select aria-label="用户角色"><option value="member" ${user.role === "member" ? "selected" : ""}>成员</option><option value="admin" ${user.role === "admin" ? "selected" : ""}>管理员</option></select></div>`).join("");
  $$(".user-role-row select").forEach((select) => select.addEventListener("change", async () => {
    const row = select.closest(".user-role-row");
    const userId = Number(row.dataset.userId);
    const previous = state.users.find((user) => user.id === userId)?.role;
    select.disabled = true;
    try {
      const updated = await api(`/api/admin/users/${userId}/role`, { method: "PATCH", body: JSON.stringify({ role: select.value }) });
      state.users = state.users.map((user) => user.id === userId ? updated : user);
      if (state.currentUser?.id === userId) { state.currentUser = updated; renderCurrentUser(); }
      toast("用户角色已更新", "success");
    } catch (error) {
      select.value = previous;
      toast(error.message, "error");
    } finally { select.disabled = false; }
  }));
}

async function initialize() {
  bindEvents();
  if (!await restoreAuthentication()) return;
  await loadAppData();
}

async function loadAppData() {
  try {
    const admin = state.currentUser?.role === "admin";
    const [health, conversations, projects, emailSettings, tasks, deadLetters, emailFailures] = await Promise.all([
      api("/api/health"), api("/api/conversations"), api("/api/projects"), api("/api/settings/email"),
      admin ? api("/api/tasks?limit=100") : Promise.resolve([]), admin ? api("/api/dead-letters?active_only=true&limit=100") : Promise.resolve([]),
      admin ? api("/api/email-deliveries?status=failed&active_only=true&limit=100") : Promise.resolve([])
    ]);
    state.conversations = conversations;
    state.projects = projects;
    state.emailSettings = emailSettings;
    state.tasks = tasks;
    state.deadLetters = deadLetters;
    state.emailFailures = emailFailures;
    renderHealth(health);
    renderEmailSettingsStatus();
    renderTaskCenterBadge();
    renderAllSideData();
    if (!state.conversations.length) await newConversation();
    else await selectConversation(state.conversations[0].id);
  } catch (error) {
    toast(error.message, "error");
    $("#sidebar-status span").textContent = "服务连接失败";
  }
}

function bindEvents() {
  $("#auth-form").addEventListener("submit", submitAuth);
  $$('[data-auth-mode]').forEach((button) => button.addEventListener("click", () => switchAuthMode(button.dataset.authMode)));
  $("#send-auth-code").addEventListener("click", sendAuthCode);
  $("#send-register-code").addEventListener("click", sendRegisterCode);
  $("#logout").addEventListener("click", logout);
  $("#open-account-settings").addEventListener("click", openAccountSettings);
  $("#account-settings-form").addEventListener("submit", saveAccountSettings);
  $("#send-account-phone-code").addEventListener("click", sendAccountPhoneCode);
  $("#bind-account-phone").addEventListener("click", bindAccountPhone);
  $$(".account-settings-close").forEach((button) => button.addEventListener("click", () => $("#account-settings-dialog").close()));
  $("#open-user-management").addEventListener("click", openUserManagement);
  $$(".user-management-close").forEach((button) => button.addEventListener("click", () => $("#user-management-dialog").close()));
  $("#manage-project-members").addEventListener("click", openProjectMembers);
  $("#project-member-form").addEventListener("submit", addProjectMember);
  $$(".project-members-close").forEach((button) => button.addEventListener("click", () => $("#project-members-dialog").close()));
  $("#new-project").addEventListener("click", openProjectDialog);
  $$(".project-switch-button").forEach((button) => button.addEventListener("click", toggleProjectSwitchMenu));
  $$(".project-exit-button").forEach((button) => button.addEventListener("click", exitProjectChat));
  $("#chat-form").addEventListener("submit", sendMessage);
  $("#message-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); $("#chat-form").requestSubmit(); }
  });
  $("#message-input").addEventListener("input", autoSizeComposer);
  $("#project-chat-form").addEventListener("submit", sendProjectMessage);
  $("#project-message-input").addEventListener("keydown", (event) => {
    if (handleProjectMentionKeydown(event)) return;
    if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); $("#project-chat-form").requestSubmit(); }
  });
  $("#project-message-input").addEventListener("input", () => { autoSizeProjectComposer(); updateProjectMentionMenu(); });
  $("#project-message-input").addEventListener("blur", () => setTimeout(closeProjectMentionMenu, 120));
  $("#knowledge-input").addEventListener("change", (event) => uploadKnowledgeFiles([...event.target.files]));
  $("#project-knowledge-input").addEventListener("change", (event) => uploadProjectKnowledgeFiles([...event.target.files]));
  $("#add-meeting-form").addEventListener("submit", submitAddMeeting);
  $("#add-meeting-file").addEventListener("change", suggestMeetingName);
  $("#open-tencent-meeting-import").addEventListener("click", openTencentMeetingImport);
  $$(".add-meeting-cancel").forEach((button) => button.addEventListener("click", closeAddMeetingDialog));
  $("#add-meeting-dialog").addEventListener("close", () => { state.addMeetingProjectId = null; });
  $$(".tencent-meeting-close").forEach((button) => button.addEventListener("click", () => $("#tencent-meeting-dialog").close()));
  $("#refresh-tencent-meetings").addEventListener("click", loadTencentMeetingRecords);
  $("#tencent-meeting-dialog").addEventListener("close", () => {
    state.tencentMeetingProjectId = null;
    state.tencentMeetingRecords = [];
    state.tencentMeetingLoading = false;
  });
  $("#open-sidebar").addEventListener("click", () => $("#sidebar").classList.add("open"));
  $("#close-sidebar").addEventListener("click", () => $("#sidebar").classList.remove("open"));
  $("#toggle-sidebar").addEventListener("click", toggleSidebar);

  $$(".suggestion").forEach((button) => button.addEventListener("click", () => {
    if (button.classList.contains("project-suggestion")) return;
    if (button.dataset.viewTarget === "project") return openProjectFromSuggestion();
    $("#message-input").value = button.dataset.prompt;
    autoSizeComposer();
    $("#message-input").focus();
  }));
  $$(".project-suggestion").forEach((button) => button.addEventListener("click", () => {
    $("#project-message-input").value = button.dataset.projectPrompt;
    autoSizeProjectComposer();
    $("#project-message-input").focus();
  }));
  $("#email-form").addEventListener("submit", submitEmail);
  $$(".dialog-cancel").forEach((button) => button.addEventListener("click", () => $("#email-dialog").close()));
  $("#configure-email-from-compose").addEventListener("click", openEmailSettings);
  $("#project-form").addEventListener("submit", createProject);
  $$(".project-dialog-cancel").forEach((button) => button.addEventListener("click", () => $("#project-dialog").close()));
  $("#open-project-menu").addEventListener("click", toggleProjectActionMenu);
  $("#open-chat-history").addEventListener("click", openChatHistory);
  $("#open-chat-memory").addEventListener("click", openChatMemory);
  $("#rename-project-action").addEventListener("click", openRenameProject);
  $("#open-project-chat-history").addEventListener("click", openProjectChatHistory);
  $("#open-project-memory").addEventListener("click", openProjectMemory);
  $("#delete-project").addEventListener("click", deleteActiveProject);
  $$(".project-management-close").forEach((button) => button.addEventListener("click", () => $("#project-management-dialog").close()));
  $("#add-memory").addEventListener("click", () => openMemoryEditor());
  $("#memory-search").addEventListener("input", (event) => { state.memorySearch = event.target.value; renderMemories(); });
  $("#memory-type-filter").addEventListener("change", (event) => { state.memoryTypeFilter = event.target.value; renderMemories(); });
  $("#memory-editor-form").addEventListener("submit", saveMemory);
  $$(".memory-editor-cancel").forEach((button) => button.addEventListener("click", () => $("#memory-editor-dialog").close()));
  $("#memory-editor-dialog").addEventListener("close", () => { state.memoryEditTarget = null; });
  $("#project-rename-form").addEventListener("submit", renameActiveProject);
  $$(".project-rename-cancel").forEach((button) => button.addEventListener("click", () => $("#project-rename-dialog").close()));
  $("#resource-rename-form").addEventListener("submit", submitResourceRename);
  $$(".resource-rename-cancel").forEach((button) => button.addEventListener("click", closeResourceRename));
  $("#resource-rename-dialog").addEventListener("close", () => { state.resourceRenameTarget = null; });
  $("#file-preview-title").addEventListener("click", beginPreviewFilenameEdit);
  $("#file-preview-title").addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); beginPreviewFilenameEdit(); }
  });
  $("#file-preview-title-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); }
    if (event.key === "Escape") cancelPreviewFilenameEdit();
  });
  $("#file-preview-title-input").addEventListener("blur", savePreviewFilename);
  $("#file-preview-edit").addEventListener("click", beginPreviewContentEdit);
  $("#file-preview-cancel-edit").addEventListener("click", cancelPreviewContentEdit);
  $("#file-preview-save").addEventListener("click", savePreviewContent);
  $$(".file-preview-close").forEach((button) => button.addEventListener("click", closeFilePreview));
  $("#file-preview-dialog").addEventListener("close", () => {
    state.previewDocument = null;
    state.previewEditing = false;
    state.previewSaving = false;
  });
  $("#file-preview-dialog").addEventListener("cancel", (event) => {
    if (!state.previewEditing) return;
    event.preventDefault();
    closeFilePreview();
  });
  $("#file-preview-dialog").addEventListener("click", (event) => {
    if (event.target === $("#file-preview-dialog")) closeFilePreview();
  });
  $$(".project-chat-history-close").forEach((button) => button.addEventListener("click", () => $("#project-chat-history-dialog").close()));
  $("#project-chat-history-dialog").addEventListener("click", (event) => {
    if (event.target === $("#project-chat-history-dialog")) $("#project-chat-history-dialog").close();
  });
  $("#project-chat-history-search").addEventListener("input", (event) => {
    state.projectChatSearch = event.target.value;
    renderProjectChatHistoryDialog();
  });
  $$(".chat-history-close").forEach((button) => button.addEventListener("click", () => $("#chat-history-dialog").close()));
  $("#chat-history-dialog").addEventListener("click", (event) => {
    if (event.target === $("#chat-history-dialog")) $("#chat-history-dialog").close();
  });
  $("#chat-history-search").addEventListener("input", (event) => {
    state.conversationSearch = event.target.value;
    renderConversations();
  });
  document.addEventListener("click", (event) => {
    const menu = $("#project-action-menu");
    if (!menu.hidden && !menu.contains(event.target) && !$("#open-project-menu").contains(event.target)) closeProjectActionMenu();
    const projectSwitchMenu = $("#project-switch-menu");
    if (!projectSwitchMenu.hidden && !projectSwitchMenu.contains(event.target) && !event.target.closest(".project-switch-button")) closeProjectSwitchMenu();
  });
  $("#open-email-settings").addEventListener("click", openEmailSettings);
  $("#open-task-center").addEventListener("click", openTaskCenter);
  $("#refresh-task-center").addEventListener("click", () => loadTaskCenter());
  $("#task-status-filter").addEventListener("change", (event) => {
    state.taskStatusFilter = event.target.value;
    renderTaskCenter();
  });
  $$(".task-center-close").forEach((button) => button.addEventListener("click", () => $("#task-center-dialog").close()));
  $("#task-center-dialog").addEventListener("close", stopTaskCenterRefresh);
  $("#email-settings-form").addEventListener("submit", saveEmailSettings);
  $("#test-email-settings").addEventListener("click", testEmailSettings);
  $("#clear-email-settings").addEventListener("click", clearEmailSettings);
  $$(".email-settings-cancel").forEach((button) => button.addEventListener("click", () => $("#email-settings-dialog").close()));
  $("#smtp-security").addEventListener("change", (event) => {
    const port = Number($("#smtp-port").value);
    if (event.target.value === "ssl" && port === 587) $("#smtp-port").value = "465";
    if (event.target.value === "starttls" && port === 465) $("#smtp-port").value = "587";
  });
}

function toggleProjectSwitchMenu(event) {
  const menu = $("#project-switch-menu");
  closeProjectActionMenu();
  const shouldOpen = menu.hidden;
  closeProjectSwitchMenu();
  if (!shouldOpen) return;
  menu.hidden = false;
  event.currentTarget.setAttribute("aria-expanded", "true");
  renderProjectSwitcher();
  positionProjectSwitchMenu(event.currentTarget);
}

function closeProjectSwitchMenu() {
  $("#project-switch-menu").hidden = true;
  $$(".project-switch-button").forEach((button) => button.setAttribute("aria-expanded", "false"));
}

function positionProjectSwitchMenu(anchor) {
  const menu = $("#project-switch-menu");
  const rect = anchor.getBoundingClientRect();
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - menu.offsetWidth - 8));
  const desiredBottom = window.innerHeight - rect.top + 8;
  const bottom = Math.max(8, Math.min(desiredBottom, window.innerHeight - menu.offsetHeight - 8));
  menu.style.left = `${left}px`;
  menu.style.top = "auto";
  menu.style.bottom = `${bottom}px`;
}

function exitProjectChat() {
  closeProjectSwitchMenu();
  if (state.activeConversationId) selectConversation(state.activeConversationId);
  else newConversation();
}

function renderProjectSwitcher() {
  const projectViewActive = $("#view-project").classList.contains("active");
  const activeProject = state.projects.find((item) => item.id === state.activeProjectId);
  $$(".project-switch-label").forEach((label) => { label.textContent = projectViewActive ? (activeProject?.name || "项目") : "选择项目"; });
  $$(".project-exit-button").forEach((button) => { button.hidden = !projectViewActive; });
  $("#project-switch-list").innerHTML = state.projects.length
    ? state.projects.map((project) => `<button type="button" class="project-switch-option ${projectViewActive && project.id === state.activeProjectId ? "active" : ""}" data-project-switch="${project.id}"><span class="project-switch-icon">${escapeHtml(project.name.slice(0, 1).toUpperCase())}</span><span><strong>${escapeHtml(project.name)}</strong><small>${project.meeting_count || 0} 次会议 · ${project.document_count || 0} 份资料</small></span>${projectViewActive && project.id === state.activeProjectId ? "<b>✓</b>" : ""}</button>`).join("")
    : '<div class="project-switch-menu-empty">还没有项目</div>';
  $$("[data-project-switch]").forEach((button) => button.addEventListener("click", () => {
    closeProjectSwitchMenu();
    openProjectHome(Number(button.dataset.projectSwitch));
  }));
}

function toggleSidebar() {
  state.sidebarCollapsed = !state.sidebarCollapsed;
  $(".app-shell").classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  const button = $("#toggle-sidebar");
  const label = state.sidebarCollapsed ? "展开侧边栏" : "收起侧边栏";
  button.title = label;
  button.setAttribute("aria-label", label);
}

function renderHealth(health) {
  state.health = health;
  const enabled = [health.capabilities.llm ? "AI 已连接" : "本地模式", health.capabilities.smtp ? "邮箱已连接" : "邮件草稿模式"];
  $("#sidebar-status").classList.add("ready");
  $("#sidebar-status span").textContent = enabled.join(" · ");
  $("#capability-pills").innerHTML = [
    ["文件", true], ["记忆", true], ["联网", true], ["PPT", true], ["模型", health.capabilities.llm]
  ].map(([name, on]) => `<span class="capability-pill ${on ? "on" : ""}">${on ? "●" : "○"} ${name}</span>`).join("");
}

const taskStatusNames = { queued: "等待执行", running: "执行中", completed: "已完成", failed: "失败", cancelled: "已取消", dead_letter: "死信" };
const taskKindNames = { message: "对话请求", memory_extract: "长期记忆提取" };
const traceStageNames = { task: "任务执行", routing: "识别请求", context: "构建上下文", workflow: "生成内容", provider: "调用外部服务", artifact: "生成文件", persistence: "保存结果", memory: "记忆处理", compensation: "失败补偿" };

function renderTaskCenterBadge() {
  const active = state.tasks.filter((task) => ["queued", "running"].includes(task.status)).length;
  const dead = state.deadLetters.filter((item) => !item.resolvedAt).length;
  const count = active + dead + state.emailFailures.length;
  $("#task-center-badge").textContent = count ? String(count) : "";
  $("#open-task-center").classList.toggle("has-alert", dead + state.emailFailures.length > 0);
}

function taskFilterMatch(task) {
  if (state.taskStatusFilter === "all") return true;
  if (state.taskStatusFilter === "active") return ["queued", "running"].includes(task.status);
  return task.status === state.taskStatusFilter;
}

function taskTitle(task) {
  const trace = task.id === state.selectedTaskId ? state.selectedTaskTrace : null;
  const intentNames = { chat: "智能对话", ppt: "生成 PPT", meeting_detail: "生成会议详情", email_content: "生成邮件内容" };
  return intentNames[trace?.intent] || taskKindNames[task.kind] || task.kind || "Agent 任务";
}

function renderTaskCenter() {
  renderTaskCenterBadge();
  const active = state.tasks.filter((task) => ["queued", "running"].includes(task.status)).length;
  const completed = state.tasks.filter((task) => task.status === "completed").length;
  const failed = state.tasks.filter((task) => task.status === "failed").length;
  const dead = state.deadLetters.filter((item) => !item.resolvedAt).length + state.emailFailures.length;
  $("#task-center-summary").innerHTML = [
    [active, "执行中与等待中", ""], [completed, "已完成", ""], [failed, "普通失败", ""], [dead, "待处理死信", dead ? "alert" : ""]
  ].map(([count, label, className]) => `<div class="task-summary-card ${className}"><b>${count}</b><span>${label}</span></div>`).join("");
  $("#task-status-filter").value = state.taskStatusFilter;
  const tasks = state.tasks.filter(taskFilterMatch);
  const emailFailures = ["all", "failed", "dead_letter"].includes(state.taskStatusFilter) ? state.emailFailures : [];
  const selectedEmailExists = emailFailures.some((item) => item.id === state.selectedEmailFailureId);
  if (!selectedEmailExists && !tasks.some((task) => task.id === state.selectedTaskId)) {
    state.selectedTaskId = tasks[0]?.id || null;
    state.selectedEmailFailureId = state.selectedTaskId ? null : (emailFailures[0]?.id || null);
    state.selectedTaskTrace = null;
  }
  const rows = [
    ...tasks.map((task) => `<button class="task-list-item status-${task.status} ${task.id === state.selectedTaskId ? "active" : ""}" type="button" data-task-id="${task.id}"><i></i><span class="task-list-item-copy"><strong>${escapeHtml(taskTitle(task))}</strong><small>${formatDate(task.updatedAt || task.createdAt)} · 尝试 ${task.attempts}/${task.maxAttempts}</small></span><b>${taskStatusNames[task.status] || task.status}</b></button>`),
    ...emailFailures.map((delivery) => `<button class="task-list-item status-failed ${delivery.id === state.selectedEmailFailureId ? "active" : ""}" type="button" data-email-failure-id="${delivery.id}"><i></i><span class="task-list-item-copy"><strong>邮件投递异常</strong><small>${escapeHtml(delivery.recipient)} · ${formatDate(delivery.updatedAt || delivery.createdAt)}</small></span><b>需确认</b></button>`)
  ];
  $("#task-center-list").innerHTML = rows.length
    ? rows.join("")
    : '<div class="task-center-empty">当前筛选条件下没有任务</div>';
  $$('[data-task-id]').forEach((button) => button.addEventListener("click", () => selectTask(String(button.dataset.taskId))));
  $$('[data-email-failure-id]').forEach((button) => button.addEventListener("click", () => selectEmailFailure(String(button.dataset.emailFailureId))));
  renderTaskDetail();
}

function traceEventDescription(event) {
  const metadata = event.metadata || {};
  if (metadata.provider) return `${metadata.provider}${event.attempt ? ` · 第 ${event.attempt} 次` : ""}`;
  if (metadata.intent) return `识别为 ${metadata.intent}`;
  if (metadata.errorCode) return metadata.errorCode;
  if (metadata.messageId) return `消息 #${metadata.messageId}`;
  if (event.attempt) return `第 ${event.attempt} 次尝试`;
  return event.event || "";
}

function renderTaskDetail() {
  const emailFailure = state.emailFailures.find((item) => item.id === state.selectedEmailFailureId);
  if (emailFailure) {
    const error = emailFailure.error || {};
    $("#task-center-detail").innerHTML = `
      <div class="task-detail-head"><div><h4>邮件投递异常</h4><p>${escapeHtml(emailFailure.provider || "email")} · 已尝试 ${emailFailure.attempts || 1} 次</p></div><span class="task-status-pill failed">需人工确认</span></div>
      <div class="task-error-box"><strong>${escapeHtml(error.code || "email_send_failed")}</strong>${escapeHtml(error.message || "邮件未能成功投递")}</div>
      <div class="task-compensation-box"><strong>安全处理建议</strong>系统无法撤回或确定超时请求是否已被邮箱服务接收，因此不会自动重复发送。请先到发件箱确认；需要时从原 Artifact 或待办重新发送。</div>
      <dl class="task-email-meta"><dt>收件人</dt><dd>${escapeHtml(emailFailure.recipient)}</dd><dt>主题</dt><dd>${escapeHtml(emailFailure.subject)}</dd><dt>来源</dt><dd>${escapeHtml(emailFailure.sourceType)} #${escapeHtml(emailFailure.sourceId)}</dd></dl>
      <div class="task-detail-actions"><button type="button" data-email-failure-command="resolve">标记已处理</button></div>`;
    $$('[data-email-failure-command]').forEach((button) => button.addEventListener("click", resolveSelectedEmailFailure));
    return;
  }
  const task = state.tasks.find((item) => item.id === state.selectedTaskId);
  if (!task) {
    $("#task-center-detail").innerHTML = '<div class="task-center-empty">选择一个任务查看执行详情</div>';
    return;
  }
  const trace = state.selectedTaskTrace;
  const deadLetter = state.deadLetters.find((item) => item.taskId === task.id);
  const progress = Math.max(0, Math.min(100, Number(task.progress) || 0));
  const error = task.error || deadLetter?.error;
  const compensationNames = { pending: "等待补偿", completed: "补偿完成", failed: "补偿失败", skipped: "无需补偿" };
  const actions = [];
  if (task.status === "queued") actions.push('<button type="button" data-task-command="cancel">取消任务</button>');
  if (["failed", "cancelled", "dead_letter"].includes(task.status)) actions.push('<button class="primary" type="button" data-task-command="retry">重新执行</button>');
  if (task.status === "dead_letter" && ["pending", "failed"].includes(deadLetter?.compensationStatus)) actions.push('<button type="button" data-task-command="compensate">执行补偿</button>');
  if (task.status === "dead_letter" && deadLetter && !deadLetter.resolvedAt) actions.push('<button type="button" data-task-command="resolve">关闭死信</button>');
  const events = trace?.events || [];
  const duration = trace?.duration_ms != null ? ` · 耗时 ${(Number(trace.duration_ms) / 1000).toFixed(1)} 秒` : "";
  $("#task-center-detail").innerHTML = `
    <div class="task-detail-head"><div><h4>${escapeHtml(taskTitle(task))}</h4><p>任务 ${escapeHtml(task.id.slice(0, 12))} · Trace ${escapeHtml((task.traceId || "").slice(0, 12))}${duration}</p></div><span class="task-status-pill ${task.status}">${taskStatusNames[task.status] || task.status}</span></div>
    <div class="task-progress"><i style="width:${progress}%"></i></div><div class="task-progress-label"><span>${task.status === "completed" ? "处理完成" : `当前进度 ${progress}%`}</span><span>尝试 ${task.attempts}/${task.maxAttempts}</span></div>
    ${error ? `<div class="task-error-box"><strong>${escapeHtml(error.code || "执行失败")}</strong>${escapeHtml(error.message || "任务未能完成")}${error.retryable ? " · 可重试" : ""}</div>` : ""}
    ${deadLetter ? `<div class="task-compensation-box"><strong>${compensationNames[deadLetter.compensationStatus] || deadLetter.compensationStatus}</strong>${deadLetter.compensationResult ? escapeHtml(JSON.stringify(deadLetter.compensationResult)) : "系统会清理本次执行产生的半成品数据。"}</div>` : ""}
    ${actions.length ? `<div class="task-detail-actions">${actions.join("")}</div>` : ""}
    <h5 class="task-trace-title">执行时间线</h5>
    <div class="task-trace">${events.length ? events.map((event) => `<div class="task-trace-event ${event.status}"><i></i><span class="task-trace-event-copy"><strong>${escapeHtml(traceStageNames[event.stage] || event.stage)} · ${escapeHtml(event.status === "completed" ? "完成" : event.status === "running" ? "进行中" : event.status === "retrying" ? "准备重试" : event.status)}</strong><small>${escapeHtml(traceEventDescription(event))}</small></span><time>${formatDate(event.created_at)}</time></div>`).join("") : '<div class="task-center-empty">尚无 Trace 事件</div>'}</div>`;
  $$('[data-task-command]').forEach((button) => button.addEventListener("click", () => runTaskCommand(button.dataset.taskCommand)));
}

async function selectTask(taskId) {
  state.selectedTaskId = taskId;
  state.selectedEmailFailureId = null;
  state.selectedTaskTrace = null;
  renderTaskCenter();
  try {
    const task = state.tasks.find((item) => item.id === taskId);
    if (task?.traceId) state.selectedTaskTrace = await api(`/api/traces/${task.traceId}`);
  } catch (error) {
    toast(error.message, "error");
  }
  renderTaskCenter();
}

function selectEmailFailure(deliveryId) {
  state.selectedEmailFailureId = deliveryId;
  state.selectedTaskId = null;
  state.selectedTaskTrace = null;
  renderTaskCenter();
}

async function loadTaskCenter({ quiet = false } = {}) {
  try {
    const [tasks, deadLetters, emailFailures] = await Promise.all([
      api("/api/tasks?limit=100"), api("/api/dead-letters?active_only=true&limit=100"),
      api("/api/email-deliveries?status=failed&active_only=true&limit=100")
    ]);
    state.tasks = tasks;
    state.deadLetters = deadLetters;
    state.emailFailures = emailFailures;
    const selectedEmailExists = emailFailures.some((item) => item.id === state.selectedEmailFailureId);
    if (!selectedEmailExists && (!state.selectedTaskId || !tasks.some((task) => task.id === state.selectedTaskId))) {
      state.selectedTaskId = tasks[0]?.id || null;
      state.selectedEmailFailureId = state.selectedTaskId ? null : (emailFailures[0]?.id || null);
      state.selectedTaskTrace = null;
    }
    if (state.selectedTaskId) {
      const selected = tasks.find((task) => task.id === state.selectedTaskId);
      state.selectedTaskTrace = selected?.traceId ? await api(`/api/traces/${selected.traceId}`) : null;
    }
    $("#task-center-updated").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    renderTaskCenter();
  } catch (error) {
    if (!quiet) toast(error.message, "error");
  }
}

async function openTaskCenter() {
  $("#task-center-dialog").showModal();
  await loadTaskCenter();
  if (!state.selectedTaskId && !state.selectedEmailFailureId && state.tasks.length) await selectTask(state.tasks[0].id);
  stopTaskCenterRefresh();
  state.taskRefreshTimer = setInterval(() => loadTaskCenter({ quiet: true }), 2000);
}

function stopTaskCenterRefresh() {
  if (state.taskRefreshTimer) clearInterval(state.taskRefreshTimer);
  state.taskRefreshTimer = null;
}

async function runTaskCommand(command) {
  const taskId = state.selectedTaskId;
  if (!taskId) return;
  try {
    if (command === "retry") await api(`/api/tasks/${taskId}/retry`, { method: "POST" });
    if (command === "cancel") await api(`/api/tasks/${taskId}`, { method: "DELETE" });
    if (command === "compensate") await api(`/api/dead-letters/${taskId}/compensate`, { method: "POST" });
    if (command === "resolve") await api(`/api/dead-letters/${taskId}/resolve`, { method: "POST" });
    toast({ retry: "任务已重新入队", cancel: "任务已取消", compensate: "补偿已执行", resolve: "死信已关闭" }[command], "success");
    await loadTaskCenter();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function resolveSelectedEmailFailure() {
  const deliveryId = state.selectedEmailFailureId;
  if (!deliveryId) return;
  try {
    await api(`/api/email-deliveries/${deliveryId}/resolve`, { method: "POST" });
    state.selectedEmailFailureId = null;
    toast("邮件异常已标记为处理完成", "success");
    await loadTaskCenter();
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderEmailSettingsStatus() {
  const configured = Boolean(state.emailSettings?.configured);
  $("#open-email-settings").classList.toggle("configured", configured);
  $("#email-settings-badge").textContent = state.emailSettings?.agentMailConfigured
    ? "系统邮箱"
    : (state.emailSettings?.smtpConfigured ? "个人邮箱" : "未配置");
}

function emailSettingsPayload() {
  return {
    host: $("#smtp-host").value.trim(),
    port: Number($("#smtp-port").value),
    secure: $("#smtp-security").value === "ssl",
    user: $("#smtp-user").value.trim(),
    password: $("#smtp-password").value || null,
    fromAddress: $("#smtp-from").value.trim()
  };
}

function setEmailSettingsNote(message, type = "") {
  const note = $("#email-settings-note");
  note.textContent = message;
  note.className = `settings-note ${type}`;
}

function fillEmailSettingsForm() {
  const settings = state.emailSettings || {};
  const systemConfigured = Boolean(settings.agentMailConfigured);
  $("#agentmail-provider-card").classList.toggle("configured", systemConfigured);
  $("#agentmail-provider-status").textContent = systemConfigured ? "已启用" : "未配置";
  $("#agentmail-provider-description").textContent = systemConfigured
    ? (settings.agentMailInbox ? `系统邮箱：${settings.agentMailInbox}` : "首次发送邮件时会自动创建系统邮箱。")
    : "管理员在后端配置 AGENTMAIL_API_KEY 后即可启用。";
  $("#smtp-host").value = settings.host || "";
  $("#smtp-port").value = settings.port || 587;
  $("#smtp-security").value = settings.secure ? "ssl" : "starttls";
  $("#smtp-user").value = settings.user || "";
  $("#smtp-password").value = "";
  $("#smtp-from").value = settings.fromAddress || "";
  $("#clear-email-settings").hidden = settings.source !== "frontend";
  if (settings.source === "environment") {
    setEmailSettingsNote("当前使用后端 .env 配置。保存后将切换为前端管理的加密配置。");
  } else if (settings.passwordConfigured) {
    setEmailSettingsNote("授权码已配置。密码框留空会保留当前授权码，页面不会读取明文。");
  } else {
    setEmailSettingsNote("授权码只会加密保存在后端，页面不会读取明文。");
  }
}

function renderEmailProviderOptions() {
  const settings = state.emailSettings || {};
  const options = [];
  if (settings.agentMailConfigured) options.push(["agentmail", "AgentMail 系统邮箱（推荐）"]);
  if (settings.smtpConfigured) options.push(["smtp", "个人 SMTP 邮箱"]);
  $("#email-provider").innerHTML = options.length
    ? options.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")
    : '<option value="">未配置发件邮箱</option>';
  $("#email-provider").disabled = !options.length;
  $("#email-compose-warning").hidden = Boolean(options.length);
  const preferred = settings.defaultProvider;
  if (options.some(([value]) => value === preferred)) $("#email-provider").value = preferred;
}

function openEmailSettings() {
  fillEmailSettingsForm();
  $("#email-settings-dialog").showModal();
  requestAnimationFrame(() => $("#smtp-host").focus());
}

async function saveEmailSettings(event) {
  event.preventDefault();
  const button = $("#save-email-settings");
  button.disabled = true;
  button.textContent = "保存中…";
  try {
    state.emailSettings = await api("/api/settings/email", { method: "PUT", body: JSON.stringify(emailSettingsPayload()) });
    if (state.health) {
      state.health.capabilities.smtp = state.emailSettings.configured;
      renderHealth(state.health);
    }
    renderEmailSettingsStatus();
    renderEmailProviderOptions();
    fillEmailSettingsForm();
    setEmailSettingsNote("邮件设置已加密保存。建议继续点击“测试连接”。", "success");
    toast("邮件设置已保存", "success");
  } catch (error) { setEmailSettingsNote(error.message, "error"); }
  finally { button.disabled = false; button.textContent = "保存"; }
}

async function testEmailSettings() {
  const button = $("#test-email-settings");
  button.disabled = true;
  button.textContent = "连接中…";
  setEmailSettingsNote("正在连接 SMTP 服务器，请稍候…");
  try {
    await api("/api/settings/email/test", { method: "POST", body: JSON.stringify(emailSettingsPayload()) });
    setEmailSettingsNote("连接成功，服务器和授权信息可用。", "success");
  } catch (error) { setEmailSettingsNote(error.message, "error"); }
  finally { button.disabled = false; button.textContent = "测试连接"; }
}

async function clearEmailSettings() {
  if (!confirm("确定清除前端保存的 SMTP 配置和授权码吗？")) return;
  try {
    await api("/api/settings/email", { method: "DELETE" });
    state.emailSettings = await api("/api/settings/email");
    if (state.health) {
      state.health.capabilities.smtp = state.emailSettings.configured;
      renderHealth(state.health);
    }
    renderEmailSettingsStatus();
    renderEmailProviderOptions();
    fillEmailSettingsForm();
    toast("前端邮件配置已清除", "success");
  } catch (error) { setEmailSettingsNote(error.message, "error"); }
}

function switchView(view) {
  $$(".view").forEach((element) => element.classList.toggle("active", element.id === `view-${view}`));
  $("#sidebar").classList.remove("open");
  const project = state.projects.find((item) => item.id === state.activeProjectId);
  const title = view === "project"
    ? [project?.name || "项目", "聊天、资料库、会议、待办和记忆都归档在项目中"]
    : [state.conversations.find((item) => item.id === state.activeConversationId)?.title || "新对话", "知识、记忆和工具，都在同一个对话里"];
  $("#page-title").textContent = title[0];
  $("#page-subtitle").textContent = title[1];
  $("#open-project-menu").hidden = false;
  $("#open-project-menu").title = view === "project" ? "项目管理" : "聊天管理";
  $$('[data-action-scope]').forEach((button) => { button.hidden = button.dataset.actionScope !== view; });
  if (view === "project") {
    const accessRole = project?.access_role || "owner";
    $("#rename-project-action").hidden = accessRole === "viewer";
    $("#manage-project-members").hidden = accessRole !== "owner";
    $("#delete-project").hidden = accessRole !== "owner";
  }
  closeProjectActionMenu();
  closeProjectSwitchMenu();
  $(".main-content").classList.toggle("project-mode", view === "project");
  if (view === "project") renderProject();
  else renderProjects();
  renderConversations();
  renderProjectSwitcher();
}

async function loadConversations() {
  try { state.conversations = await api("/api/conversations"); renderConversations(); }
  catch (error) { toast(error.message, "error"); }
}

function openProjectDialog() {
  $("#project-form").reset();
  $("#project-dialog").showModal();
  requestAnimationFrame(() => $("#project-name").focus());
}

async function createProject(event) {
  event.preventDefault();
  const name = $("#project-name").value.trim();
  if (!name) return;
  try {
    const project = await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, description: $("#project-description-input").value.trim() })
    });
    state.projects.unshift(project);
    $("#project-dialog").close();
    await selectProject(project.id);
    toast(`项目“${project.name}”已创建`, "success");
  } catch (error) { toast(error.message, "error"); }
}

async function openProjectFromSuggestion() {
  if (state.activeProjectId) return openProjectHome(state.activeProjectId);
  if (state.projects.length) return openProjectHome(state.projects[0].id);
  openProjectDialog();
}

async function selectProject(id) {
  try {
    const projectChanged = state.activeProjectId !== id;
    const data = await api(`/api/projects/${id}`);
    state.activeProjectId = id;
    if (projectChanged) {
      state.expandedProjectId = id;
      state.sidebarSelection = null;
      clearProjectMentions();
      state.projectTab = "home";
      state.projectChatSearch = "";
      state.activeProjectConversationId = null;
    }
    state.projectConversations = data.conversations || [];
    state.projectDocuments = data.documents || [];
    state.meetings = data.meetings;
    state.todos = data.todos;
    state.memories = data.memories;
    state.activeMeetingId = !projectChanged && state.meetings.some((meeting) => meeting.id === state.activeMeetingId)
      ? state.activeMeetingId
      : null;
    const activeProjectConversation = state.projectConversations.find((item) => item.id === state.activeProjectConversationId);
    state.activeProjectConversationId = activeProjectConversation?.id || null;
    state.projectMessages = state.activeProjectConversationId
      ? (await api(`/api/conversations/${state.activeProjectConversationId}`)).messages
      : [];
    const index = state.projects.findIndex((item) => item.id === id);
    if (index >= 0) state.projects[index] = { ...state.projects[index], ...data.project };
    else state.projects.unshift(data.project);
    renderProjects();
    switchView("project");
  } catch (error) { toast(error.message, "error"); }
}

async function createProjectConversation() {
  if (!state.activeProjectId) return;
  try {
    const conversation = await api(`/api/projects/${state.activeProjectId}/conversations`, {
      method: "POST",
      body: JSON.stringify({})
    });
    state.projectConversations.unshift(conversation);
    state.activeProjectConversationId = conversation.id;
    state.projectMessages = [];
    state.sidebarSelection = null;
    state.projectTab = "chat";
    syncActiveProjectCounts();
    requestAnimationFrame(() => $("#project-message-input").focus());
    return conversation;
  } catch (error) { toast(error.message, "error"); }
  return null;
}

async function selectProjectConversation(id) {
  try {
    const data = await api(`/api/conversations/${id}`);
    if (data.conversation.project_id !== state.activeProjectId) throw new Error("该对话不属于当前项目");
    state.activeProjectConversationId = id;
    state.projectMessages = data.messages;
    state.sidebarSelection = null;
    state.projectTab = "chat";
    if ($("#project-chat-history-dialog").open) $("#project-chat-history-dialog").close();
    renderProject();
    requestAnimationFrame(() => $("#project-message-input").focus());
  } catch (error) { toast(error.message, "error"); }
}

async function deleteProjectConversation(id) {
  if (!state.activeProjectId || !confirm("确定删除这个项目对话及其消息吗？")) return;
  try {
    await api(`/api/projects/${state.activeProjectId}/conversations/${id}`, { method: "DELETE" });
    state.projectConversations = state.projectConversations.filter((item) => item.id !== id);
    if (state.activeProjectConversationId === id) {
      state.activeProjectConversationId = null;
      state.projectMessages = [];
      state.sidebarSelection = null;
      state.projectTab = "home";
    }
    syncActiveProjectCounts();
    if ($("#project-chat-history-dialog").open) renderProjectChatHistoryDialog();
  } catch (error) { toast(error.message, "error"); }
}

function renderProjectChat() {
  const project = state.projects.find((item) => item.id === state.activeProjectId);
  const readOnly = project?.access_role === "viewer";
  $("#project-messages").innerHTML = state.projectMessages.map(messageHtml).join("");
  const empty = $("#project-chat-empty");
  empty.classList.toggle("hidden", Boolean(state.projectMessages.length));
  $("#project-message-input").disabled = readOnly;
  $("#project-message-input").placeholder = readOnly ? "当前项目为只读权限" : "输入 @ 引用项目文件…";
  $("#project-send-button").disabled = state.projectSending || readOnly;
  scrollProjectChat();
}

function autoSizeProjectComposer() {
  const input = $("#project-message-input");
  input.value = input.value.replace(/[\r\n]+/g, " ");
}

function projectFileMentionOptions() {
  const knowledge = state.projectDocuments.map((document) => ({
    id: document.id,
    name: document.name,
    type: "document",
    detail: "资料库"
  }));
  const meetings = state.meetings.flatMap((meeting) => (meeting.files || []).map((file) => ({
    id: file.id,
    name: file.name,
    type: "meeting-file",
    meetingId: meeting.id,
    detail: `${meeting.title} · ${file.is_source ? "会议原文" : file.metadata?.role === "email_content" ? "邮件内容" : "Artifact"}`
  })));
  return [...knowledge, ...meetings];
}

function closeProjectMentionMenu() {
  state.projectMentionOptions = [];
  state.projectMentionIndex = 0;
  $("#project-mention-menu").hidden = true;
}

function updateProjectMentionMenu() {
  const input = $("#project-message-input");
  const beforeCursor = input.value.slice(0, input.selectionStart ?? input.value.length);
  const match = beforeCursor.match(/(?:^|\s)@([^\s@]*)$/);
  if (!match) return closeProjectMentionMenu();
  const query = match[1].toLocaleLowerCase("zh-CN");
  const selectedIds = new Set(state.projectMentions.map((item) => item.id));
  state.projectMentionOptions = projectFileMentionOptions()
    .filter((item) => !selectedIds.has(item.id) && item.name.toLocaleLowerCase("zh-CN").includes(query))
    .slice(0, 12);
  state.projectMentionIndex = Math.min(state.projectMentionIndex, Math.max(0, state.projectMentionOptions.length - 1));
  const menu = $("#project-mention-menu");
  if (!state.projectMentionOptions.length) {
    menu.innerHTML = '<div class="project-mention-empty">没有匹配的项目文件</div>';
  } else {
    menu.innerHTML = state.projectMentionOptions.map((item, index) => `<button type="button" class="project-mention-option ${index === state.projectMentionIndex ? "active" : ""}" data-project-mention-index="${index}" role="option" aria-selected="${index === state.projectMentionIndex}"><span>${item.type === "meeting-file" ? "◇" : "▤"}</span><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.detail)}</small></span></button>`).join("");
    $$("[data-project-mention-index]").forEach((button) => button.addEventListener("mousedown", (event) => {
      event.preventDefault();
      selectProjectMention(Number(button.dataset.projectMentionIndex));
    }));
  }
  menu.hidden = false;
}

function handleProjectMentionKeydown(event) {
  if ($("#project-mention-menu").hidden) return false;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const step = event.key === "ArrowDown" ? 1 : -1;
    const count = state.projectMentionOptions.length;
    if (count) state.projectMentionIndex = (state.projectMentionIndex + step + count) % count;
    updateProjectMentionMenu();
    return true;
  }
  if (event.key === "Enter" && state.projectMentionOptions.length) {
    event.preventDefault();
    selectProjectMention(state.projectMentionIndex);
    return true;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    closeProjectMentionMenu();
    return true;
  }
  return false;
}

function selectProjectMention(index) {
  const option = state.projectMentionOptions[index];
  if (!option) return;
  if (state.projectMentions.length >= 8) {
    closeProjectMentionMenu();
    return toast("一次最多引用 8 个项目文件", "error");
  }
  const input = $("#project-message-input");
  const cursor = input.selectionStart ?? input.value.length;
  const atIndex = input.value.lastIndexOf("@", cursor - 1);
  if (atIndex >= 0) input.value = `${input.value.slice(0, atIndex)}${input.value.slice(cursor)}`.trimStart();
  state.projectMentions.push(option);
  renderProjectMentions();
  closeProjectMentionMenu();
  input.focus();
}

function renderProjectMentions() {
  const strip = $("#project-mention-strip");
  strip.hidden = !state.projectMentions.length;
  strip.innerHTML = state.projectMentions.map((item) => `<span class="project-mention-chip"><span>${item.type === "meeting-file" ? "◇" : "▤"}</span><strong>${escapeHtml(item.name)}</strong><button type="button" data-remove-project-mention="${item.id}" aria-label="移除 ${escapeHtml(item.name)}">×</button></span>`).join("");
  $$("[data-remove-project-mention]").forEach((button) => button.addEventListener("click", () => {
    state.projectMentions = state.projectMentions.filter((item) => item.id !== Number(button.dataset.removeProjectMention));
    renderProjectMentions();
  }));
}

function clearProjectMentions() {
  state.projectMentions = [];
  renderProjectMentions();
  closeProjectMentionMenu();
}

function scrollProjectChat() {
  requestAnimationFrame(() => { $("#project-chat-scroll").scrollTop = $("#project-chat-scroll").scrollHeight; });
}

async function sendProjectMessage(event) {
  event.preventDefault();
  const content = $("#project-message-input").value.trim();
  if (!content || state.projectSending || !state.activeProjectId) return;
  const mentions = [...state.projectMentions];
  const mentionText = mentions.map((item) => `@${item.name}`).join(" ");
  const displayContent = [mentionText, content].filter(Boolean).join(" ");
  if (!state.activeProjectConversationId) {
    const conversation = await createProjectConversation();
    if (!conversation) return;
  }
  const conversationId = state.activeProjectConversationId;
  state.projectSending = true;
  $("#project-message-input").value = "";
  clearProjectMentions();
  autoSizeProjectComposer();
  state.projectMessages.push({ role: "user", content: displayContent, sources: [] });
  renderProjectChat();
  $("#project-messages").insertAdjacentHTML("beforeend", '<article class="message assistant typing" id="project-typing"><div class="avatar">M</div><div class="message-body"><p class="message-role">Memora 正在思考</p><div class="message-content"><i></i><i></i><i></i></div></div></article>');
  scrollProjectChat();
  try {
    const result = await submitMessageTask(conversationId, {
      content: displayContent,
      documentIds: mentions.map((item) => item.id)
    });
    $("#project-typing")?.remove();
    if (result.artifactDraft) {
      state.projectMessages.pop();
      const draft = result.artifactDraft;
      state.activeMeetingId = draft.meetingId;
      state.sidebarSelection = { type: "meeting", id: draft.meetingId };
      state.projectTab = "meetings";
      state.meetingDrafts[draft.meetingId] = {
        ...draft,
        prompt: displayContent,
        instruction: content,
        editing: false,
        editBase: null,
        history: [],
        savedFileId: null
      };
      state.meetingDraftRequest = null;
    } else {
      state.projectMessages.push(result.message);
    }
    state.projectConversations = state.projectConversations.map((conversation) => conversation.id === conversationId
      ? { ...conversation, title: conversation.title === "新对话" ? displayContent.slice(0, 28) : conversation.title, updated_at: new Date().toISOString() }
      : conversation);
    renderProject();
    if (result.artifact) toast("PPT 已生成，可以下载", "success");
    if (result.artifactDraft) toast("草稿已生成，请确认后保存", "success");
  } catch (error) {
    $("#project-typing")?.remove();
    state.projectMessages.push({ role: "assistant", content: `处理失败：${error.message}`, sources: [] });
    renderProjectChat();
    toast(error.message, "error");
  } finally {
    state.projectSending = false;
    renderProjectChat();
    $("#project-message-input").focus();
  }
}

function openProjectHome(id) {
  state.activeProjectConversationId = null;
  state.projectMessages = [];
  state.sidebarSelection = null;
  state.projectTab = "home";
  return selectProject(id);
}

function renderProjectHome() {
  const project = state.projects.find((item) => item.id === state.activeProjectId);
  if (!project) return;
  const searchInput = $("#project-chat-search");
  if (searchInput.value !== state.projectChatSearch) searchInput.value = state.projectChatSearch;
  const query = state.projectChatSearch.trim().toLocaleLowerCase("zh-CN");
  const conversations = query
    ? state.projectConversations.filter((conversation) => String(conversation.title || "").toLocaleLowerCase("zh-CN").includes(query))
    : state.projectConversations;
  $("#project-home-chats").innerHTML = conversations.length
    ? conversations.map((conversation) => `<div class="project-home-chat-row" data-project-conversation-id="${conversation.id}"><button class="project-home-chat-open"><span>◇</span><span><strong>${escapeHtml(conversation.title)}</strong><small>${formatDate(conversation.updated_at)}</small></span></button><button class="icon-btn project-home-chat-delete" title="删除对话">•••</button></div>`).join("")
    : state.projectConversations.length
      ? '<div class="project-home-empty">未找到匹配的聊天</div>'
      : '<div class="project-home-empty">还没有项目聊天。在底部输入消息即可开始对话。</div>';
  $$(".project-home-chat-row").forEach((row) => {
    const id = Number(row.dataset.projectConversationId);
    row.querySelector(".project-home-chat-open").addEventListener("click", () => selectProjectConversation(id));
    row.querySelector(".project-home-chat-delete").addEventListener("click", () => deleteProjectConversation(id));
  });
}

function renderProjects() {
  const projectViewActive = $("#view-project").classList.contains("active");
  const activeSection = state.projectTab;
  $("#project-list").innerHTML = state.projects.length ? state.projects.map((project) => {
    const isCurrent = project.id === state.activeProjectId;
    const isActive = projectViewActive && isCurrent;
    const selection = null;
    const projectSelected = isActive && !selection && !["meetings", "files"].includes(activeSection);
    const isExpanded = project.id === state.expandedProjectId;
    const meetingsCollapsed = Boolean(state.collapsedProjectSections[`${project.id}:meetings`]);
    const filesCollapsed = Boolean(state.collapsedProjectSections[`${project.id}:files`]);
    const meetingRows = isCurrent ? state.meetings.map((meeting) => {
      const meetingFiles = meeting.files || [];
      return `<div class="project-nav-resource-group">
        <div class="project-nav-resource-row project-nav-meeting-row">
          <div class="project-nav-resource-open project-nav-meeting-open" title="${escapeHtml(meeting.title)}"><span>◇</span><span>${escapeHtml(meeting.title)}</span></div>
          <span class="project-nav-resource-actions"><button type="button" data-project-meeting-rename="${meeting.id}" title="修改会议名称" aria-label="修改会议名称 ${escapeHtml(meeting.title)}">${uiIcon("edit")}</button><button class="danger" type="button" data-project-meeting-remove="${meeting.id}" title="删除会议" aria-label="删除会议 ${escapeHtml(meeting.title)}">${uiIcon("trash")}</button></span>
        </div>
        ${meetingFiles.length ? `<div class="project-nav-meeting-files">${meetingFiles.map((file) => `<div class="project-nav-resource-row project-nav-meeting-file-row"><div class="project-nav-resource-open project-nav-meeting-file" title="${escapeHtml(file.name)}"><span>${file.is_source ? "▤" : "✦"}</span><span>${escapeHtml(file.name)}</span></div><span class="project-nav-resource-actions project-nav-file-actions"><button class="preview-action" type="button" data-project-meeting-file-preview="${file.id}" data-project-id="${project.id}" data-meeting-id="${meeting.id}" title="预览文件" aria-label="预览 ${escapeHtml(file.name)}">${uiIcon("eye")}</button>${file.is_source ? "" : `<button type="button" data-project-artifact-email="${file.id}" data-meeting-id="${meeting.id}" title="发送邮件" aria-label="发送 ${escapeHtml(file.name)}">${uiIcon("mail")}</button>`}<button class="danger" type="button" data-project-meeting-file-remove="${file.id}" data-meeting-id="${meeting.id}" title="删除文件" aria-label="删除文件 ${escapeHtml(file.name)}">${uiIcon("trash")}</button></span></div>`).join("")}</div>` : ""}
      </div>`;
    }).join("") : "";
    const documentRows = isCurrent ? state.projectDocuments.map((document) => `<div class="project-nav-resource-row project-nav-meeting-file-row">
      <div class="project-nav-resource-open" title="${escapeHtml(document.name)}"><span>▤</span><span>${escapeHtml(document.name)}</span></div>
      <span class="project-nav-resource-actions project-nav-file-actions"><button class="preview-action" type="button" data-project-document-preview="${document.id}" data-project-id="${project.id}" title="预览文件" aria-label="预览 ${escapeHtml(document.name)}">${uiIcon("eye")}</button><button class="danger" type="button" data-project-document-remove="${document.id}" title="从项目移除 ${escapeHtml(document.name)}" aria-label="从项目移除 ${escapeHtml(document.name)}">${uiIcon("trash")}</button></span>
    </div>`).join("") : "";
    return `
      <div class="project-nav-group ${isExpanded ? "expanded" : ""}">
        <button class="project-item ${projectSelected ? "active" : ""}" data-project-id="${project.id}" aria-expanded="${isExpanded}">
          <span class="project-icon">${escapeHtml(project.name.slice(0, 1).toUpperCase())}</span>
          <span class="project-item-copy"><strong>${escapeHtml(project.name)}</strong><small>项目</small></span>
          <span class="project-expand-icon" aria-hidden="true">›</span>
        </button>
        <div class="project-nav-children" ${isExpanded ? "" : "hidden"}>
          <button class="project-nav-section ${isActive && activeSection === "meetings" && !selection ? "active" : ""}" data-project-id="${project.id}" data-project-section="meetings" aria-expanded="${!meetingsCollapsed}"><span>◇</span><span>会议</span><b>${project.meeting_count || 0}</b><span class="project-section-chevron">›</span></button>
          ${!meetingsCollapsed && meetingRows ? `<div class="project-nav-resource-list project-nav-meeting-list">${meetingRows}</div>` : ""}
          ${isCurrent && !meetingsCollapsed ? `<button class="project-nav-upload" type="button" data-project-upload-meeting="${project.id}"><span>＋</span><span>添加会议</span></button>` : ""}
          <button class="project-nav-section ${isActive && activeSection === "files" && !selection ? "active" : ""}" data-project-id="${project.id}" data-project-section="files" aria-expanded="${!filesCollapsed}"><span>▤</span><span>资料库</span><b>${project.document_count || 0}</b><span class="project-section-chevron">›</span></button>
          ${!filesCollapsed && documentRows ? `<div class="project-nav-resource-list">${documentRows}</div>` : ""}
          ${isCurrent && !filesCollapsed ? `<button class="project-nav-upload" type="button" data-project-upload-document="${project.id}"><span>＋</span><span>添加资料</span></button>` : ""}
        </div>
      </div>`;
  }).join("") : '<div class="project-list-empty">还没有项目。点击右上角的 ＋ 创建。</div>';
  $$(".project-item").forEach((button) => button.addEventListener("click", async () => {
    const projectId = Number(button.dataset.projectId);
    if (state.expandedProjectId === projectId && projectViewActive && state.activeProjectId === projectId) {
      state.expandedProjectId = null;
      renderProjects();
      return;
    }
    state.expandedProjectId = projectId;
    if (state.activeProjectId !== projectId || !projectViewActive) await openProjectHome(projectId);
    else renderProjects();
  }));
  $$(".project-nav-section").forEach((button) => button.addEventListener("click", () => toggleProjectResourceSection(Number(button.dataset.projectId), button.dataset.projectSection)));
  $$("[data-project-meeting-file-preview]").forEach((button) => button.addEventListener("click", () => previewProjectMeetingFile(Number(button.dataset.projectId), Number(button.dataset.meetingId), Number(button.dataset.projectMeetingFilePreview))));
  $$("[data-project-meeting-rename]").forEach((button) => button.addEventListener("click", () => renameMeetingFromSidebar(Number(button.dataset.projectMeetingRename))));
  $$("[data-project-meeting-remove]").forEach((button) => button.addEventListener("click", () => deleteMeetingFromSidebar(Number(button.dataset.projectMeetingRemove))));
  $$("[data-project-meeting-file-remove]").forEach((button) => button.addEventListener("click", () => deleteMeetingFileFromSidebar(Number(button.dataset.meetingId), Number(button.dataset.projectMeetingFileRemove))));
  $$("[data-project-artifact-email]").forEach((button) => button.addEventListener("click", () => openArtifactEmail(Number(button.dataset.meetingId), Number(button.dataset.projectArtifactEmail))));
  $$("[data-project-document-preview]").forEach((button) => button.addEventListener("click", () => previewProjectDocument(Number(button.dataset.projectId), Number(button.dataset.projectDocumentPreview))));
  $$("[data-project-document-remove]").forEach((button) => button.addEventListener("click", () => removeProjectDocument(Number(button.dataset.projectDocumentRemove))));
  $$("[data-project-upload-meeting]").forEach((button) => button.addEventListener("click", () => openAddMeetingDialog(Number(button.dataset.projectUploadMeeting))));
  $$("[data-project-upload-document]").forEach((button) => button.addEventListener("click", () => $("#project-knowledge-input").click()));
}

function openProjectChatHistory() {
  closeProjectActionMenu();
  state.projectChatSearch = "";
  $("#project-chat-history-search").value = "";
  renderProjectChatHistoryDialog();
  $("#project-chat-history-dialog").showModal();
  requestAnimationFrame(() => $("#project-chat-history-search").focus());
}

function renderProjectChatHistoryDialog() {
  const project = state.projects.find((item) => item.id === state.activeProjectId);
  if (!project) return;
  const query = state.projectChatSearch.trim().toLocaleLowerCase("zh-CN");
  const conversations = query
    ? state.projectConversations.filter((conversation) => String(conversation.title || "").toLocaleLowerCase("zh-CN").includes(query))
    : state.projectConversations;
  $("#project-chat-history-meta").textContent = `${project.name} · ${state.projectConversations.length} 个对话`;
  $("#project-chat-history-list").innerHTML = conversations.length
    ? conversations.map((conversation) => `<div class="project-chat-history-row ${state.activeProjectConversationId === conversation.id ? "active" : ""}"><button type="button" data-history-conversation="${conversation.id}"><span>◇</span><span><strong>${escapeHtml(conversation.title)}</strong><small>${formatDate(conversation.updated_at)}</small></span></button><button class="project-chat-history-delete" type="button" data-history-conversation-remove="${conversation.id}" title="删除对话" aria-label="删除 ${escapeHtml(conversation.title)}">×</button></div>`).join("")
    : `<div class="project-chat-history-empty">${state.projectConversations.length ? "未找到匹配的对话" : "这个项目还没有对话"}</div>`;
  $$("[data-history-conversation]").forEach((button) => button.addEventListener("click", () => selectProjectConversation(Number(button.dataset.historyConversation))));
  $$("[data-history-conversation-remove]").forEach((button) => button.addEventListener("click", () => deleteProjectConversation(Number(button.dataset.historyConversationRemove))));
}

async function toggleProjectResourceSection(projectId, section) {
  const key = `${projectId}:${section}`;
  state.collapsedProjectSections[key] = !Boolean(state.collapsedProjectSections[key]);
  state.expandedProjectId = projectId;
  if (state.activeProjectId !== projectId || !$("#view-project").classList.contains("active")) await selectProject(projectId);
  if (state.activeProjectId !== projectId) return;
  state.sidebarSelection = null;
  state.projectTab = section;
  renderProject();
}

async function openProjectSection(projectId, section) {
  state.expandedProjectId = projectId;
  if (state.activeProjectId !== projectId || !$("#view-project").classList.contains("active")) await selectProject(projectId);
  if (state.activeProjectId !== projectId) return;
  state.sidebarSelection = null;
  state.projectTab = section;
  if (section === "meetings") state.activeMeetingId = null;
  if (section === "home") {
    state.activeProjectConversationId = null;
    state.projectMessages = [];
  }
  renderProject();
  $("#sidebar").classList.remove("open");
}

async function ensureProjectOpen(projectId) {
  state.expandedProjectId = projectId;
  if (state.activeProjectId !== projectId || !$("#view-project").classList.contains("active")) await selectProject(projectId);
  return state.activeProjectId === projectId;
}

async function openProjectMeeting(projectId, meetingId) {
  if (!await ensureProjectOpen(projectId)) return;
  state.sidebarSelection = { type: "meeting", id: meetingId };
  state.projectTab = "meetings";
  state.activeMeetingId = meetingId;
  renderProject();
  $("#sidebar").classList.remove("open");
}

async function openProjectMeetingFile(projectId, meetingId, documentId) {
  if (!await ensureProjectOpen(projectId)) return;
  state.sidebarSelection = { type: "meeting-file", id: documentId, meetingId };
  state.projectTab = "meetings";
  state.activeMeetingId = meetingId;
  renderProject();
  $("#sidebar").classList.remove("open");
}

async function previewProjectMeetingFile(projectId, meetingId, documentId) {
  if (!await ensureProjectOpen(projectId)) return;
  $("#sidebar").classList.remove("open");
  openDocumentPreview(documentId);
}

async function openProjectDocument(projectId, documentId) {
  if (!await ensureProjectOpen(projectId)) return;
  state.sidebarSelection = { type: "document", id: documentId };
  state.projectTab = "files";
  renderProject();
  $("#sidebar").classList.remove("open");
}

async function previewProjectDocument(projectId, documentId) {
  if (!await ensureProjectOpen(projectId)) return;
  $("#sidebar").classList.remove("open");
  openDocumentPreview(documentId);
}

function openResourceRename(target) {
  state.resourceRenameTarget = target;
  const isMeeting = target.type === "meeting";
  $("#resource-rename-title").textContent = isMeeting ? "修改会议名称" : "修改文件名";
  $("#resource-rename-description").textContent = isMeeting
    ? "只修改会议显示名称，不会改变原始文件名。"
    : "修改后，侧边栏和文件预览将使用新文件名。";
  $("#resource-rename-label").textContent = isMeeting ? "会议名称" : "文件名";
  const input = $("#resource-rename-input");
  input.maxLength = isMeeting ? 120 : 180;
  input.value = target.name;
  $("#resource-rename-dialog").showModal();
  requestAnimationFrame(() => input.select());
}

function closeResourceRename() {
  $("#resource-rename-dialog").close();
  state.resourceRenameTarget = null;
}

function renameMeetingFromSidebar(meetingId) {
  const meeting = state.meetings.find((item) => item.id === meetingId);
  if (!meeting) return;
  openResourceRename({ type: "meeting", meetingId, name: meeting.title });
}

function beginPreviewFilenameEdit() {
  const document = state.previewDocument;
  if (!document?.meetingId) return;
  const title = $("#file-preview-title");
  const input = $("#file-preview-title-input");
  input.value = document.name;
  title.hidden = true;
  input.hidden = false;
  requestAnimationFrame(() => input.select());
}

function cancelPreviewFilenameEdit() {
  const input = $("#file-preview-title-input");
  input.hidden = true;
  $("#file-preview-title").hidden = false;
}

async function savePreviewFilename() {
  const input = $("#file-preview-title-input");
  const document = state.previewDocument;
  if (input.hidden || !document?.meetingId) return;
  const name = input.value.trim();
  input.hidden = true;
  $("#file-preview-title").hidden = false;
  if (!name || name === document.name) return;
  try {
    const updated = await api(`/api/meetings/${document.meetingId}/files/${document.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name })
    });
    state.meetings = state.meetings.map((meeting) => meeting.id === document.meetingId ? {
      ...meeting,
      files: (meeting.files || []).map((file) => file.id === document.id ? { ...file, ...updated } : file)
    } : meeting);
    const draft = state.meetingDrafts[document.meetingId];
    if (draft?.savedFileId === document.id) draft.name = updated.name;
    state.previewDocument = { ...document, ...updated, meetingId: document.meetingId };
    state.projectMentions = state.projectMentions.map((item) => item.id === document.id ? { ...item, name: updated.name } : item);
    renderProjectMentions();
    $("#file-preview-title").textContent = updated.name;
    renderProjects();
    toast("文件名已更新", "success");
  } catch (error) {
    toast(error.message, "error");
  }
}

function setPreviewEditActions(editing = false) {
  $("#file-preview-edit").hidden = editing || !state.previewDocument || state.previewDocument.truncated;
  $("#file-preview-cancel-edit").hidden = !editing;
  $("#file-preview-save").hidden = !editing;
}

function previewNotice(document) {
  if (document.truncated) return '<div class="file-preview-notice">文件内容较长，当前只显示前 500,000 个字符，因此不能直接编辑。</div>';
  const format = String(document.metadata?.format || "").toLowerCase();
  if (["pdf", "pptx"].includes(format)) return `<div class="file-preview-notice">当前编辑的是 ${format.toUpperCase()} 解析文本，原始文件不会被改写。</div>`;
  return "";
}

function renderPreviewContent(document) {
  $("#file-preview-body").innerHTML = `${previewNotice(document)}<pre>${escapeHtml(document.content || "文件没有可预览的文本内容。")}</pre>`;
}

function beginPreviewContentEdit() {
  const document = state.previewDocument;
  if (!document || document.truncated || state.previewSaving) return;
  state.previewEditing = true;
  setPreviewEditActions(true);
  $("#file-preview-body").innerHTML = `${previewNotice(document)}<textarea class="file-preview-editor" id="file-preview-editor" maxlength="500000" aria-label="文件内容">${escapeHtml(document.content || "")}</textarea>`;
  requestAnimationFrame(() => $("#file-preview-editor")?.focus());
}

function cancelPreviewContentEdit() {
  if (!state.previewDocument || state.previewSaving) return;
  state.previewEditing = false;
  setPreviewEditActions(false);
  renderPreviewContent(state.previewDocument);
}

function closeFilePreview() {
  if (state.previewSaving) return toast("文件内容正在保存，请稍候", "error");
  const editor = $("#file-preview-editor");
  if (state.previewEditing && editor && editor.value !== (state.previewDocument?.content || "") && !window.confirm("内容尚未保存，确定关闭预览吗？")) return;
  $("#file-preview-dialog").close();
}

async function savePreviewContent() {
  const document = state.previewDocument;
  const editor = $("#file-preview-editor");
  if (!document || !editor || state.previewSaving) return;
  const content = editor.value;
  if (!content.trim()) return toast("文件内容不能为空", "error");
  if (content === document.content) return cancelPreviewContentEdit();
  state.previewSaving = true;
  const button = $("#file-preview-save");
  button.disabled = true;
  try {
    const updated = await api(`/api/documents/${document.id}/content`, {
      method: "PATCH",
      body: JSON.stringify({ content })
    });
    state.previewDocument = { ...document, ...updated, meetingId: document.meetingId };
    const updateMetadata = (item) => item.id === document.id ? { ...item, metadata: updated.metadata } : item;
    state.documents = state.documents.map(updateMetadata);
    state.projectDocuments = state.projectDocuments.map(updateMetadata);
    state.meetings = state.meetings.map((meeting) => ({
      ...meeting,
      files: (meeting.files || []).map(updateMetadata)
    }));
    state.previewEditing = false;
    renderPreviewContent(state.previewDocument);
    setPreviewEditActions(false);
    renderDocuments();
    renderProjects();
    toast("文件内容已保存，后续提问和生成将使用新内容", "success");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    state.previewSaving = false;
    button.disabled = false;
  }
}

async function submitResourceRename(event) {
  event.preventDefault();
  const target = state.resourceRenameTarget;
  const name = $("#resource-rename-input").value.trim();
  if (!target || !name) return;
  if (name === target.name) return closeResourceRename();
  const button = $("#resource-rename-submit");
  button.disabled = true;
  button.textContent = "保存中…";
  try {
    const url = target.type === "meeting"
      ? `/api/meetings/${target.meetingId}`
      : `/api/meetings/${target.meetingId}/files/${target.documentId}`;
    const updated = await api(url, {
      method: "PATCH",
      body: JSON.stringify({ name })
    });
    if (target.type === "meeting") {
      state.meetings = state.meetings.map((item) => item.id === target.meetingId ? updated : item);
      if (state.activeMeetingId === target.meetingId) {
        $("#project-message-input").placeholder = "输入 @ 引用项目文件…";
      }
    } else {
      state.meetings = state.meetings.map((item) => item.id === target.meetingId ? {
        ...item,
        files: (item.files || []).map((file) => file.id === target.documentId ? { ...file, ...updated } : file)
      } : item);
      const draft = state.meetingDrafts[target.meetingId];
      if (draft?.savedFileId === target.documentId) draft.name = updated.name;
      if (state.previewDocument?.id === target.documentId) {
        state.previewDocument = { ...state.previewDocument, ...updated, meetingId: target.meetingId };
        $("#file-preview-title").textContent = updated.name;
      }
    }
    closeResourceRename();
    renderProject();
    toast(target.type === "meeting" ? "会议名称已更新" : "文件名已更新", "success");
  } catch (error) { toast(error.message, "error"); }
  finally {
    button.disabled = false;
    button.textContent = "保存";
  }
}

async function deleteMeetingFromSidebar(meetingId) {
  const meeting = state.meetings.find((item) => item.id === meetingId);
  if (!meeting || !confirm(`确定删除会议“${meeting.title}”吗？会议原文、所有 Artifact、待办和会议记忆也会一起删除。`)) return;
  try {
    await api(`/api/meetings/${meetingId}`, { method: "DELETE" });
    state.meetings = state.meetings.filter((item) => item.id !== meetingId);
    state.todos = state.todos.filter((item) => item.meeting_id !== meetingId);
    state.memories = state.memories.filter((item) => !(item.source_type === "meeting" && item.source_id === meetingId));
    state.projectMentions = state.projectMentions.filter((item) => item.meetingId !== meetingId);
    renderProjectMentions();
    delete state.meetingDrafts[meetingId];
    if (state.sidebarSelection?.id === meetingId || state.sidebarSelection?.meetingId === meetingId) {
      state.sidebarSelection = null;
    }
    if (state.activeMeetingId === meetingId) {
      state.activeMeetingId = null;
      state.artifactRenamingId = null;
      state.meetingDraftRequest = null;
    }
    syncActiveProjectCounts();
    toast(`会议“${meeting.title}”已删除`, "success");
  } catch (error) { toast(error.message, "error"); }
}

async function deleteMeetingFileFromSidebar(meetingId, documentId) {
  const meeting = state.meetings.find((item) => item.id === meetingId);
  const file = meeting?.files?.find((item) => item.id === documentId);
  if (!file) return;
  if (file.is_source) return deleteMeetingFromSidebar(meetingId);
  if (!confirm(`确定删除文件“${file.name}”吗？此操作无法撤销。`)) return;
  try {
    await api(`/api/meetings/${meetingId}/files/${documentId}`, { method: "DELETE" });
    state.meetings = state.meetings.map((item) => item.id === meetingId ? {
      ...item,
      files: (item.files || []).filter((document) => document.id !== documentId)
    } : item);
    state.projectMentions = state.projectMentions.filter((item) => item.id !== documentId);
    renderProjectMentions();
    const draft = state.meetingDrafts[meetingId];
    if (draft?.savedFileId === documentId) draft.savedFileId = null;
    if (state.artifactRenamingId === documentId) state.artifactRenamingId = null;
    if (state.sidebarSelection?.type === "meeting-file" && state.sidebarSelection.id === documentId) {
      state.sidebarSelection = { type: "meeting", id: meetingId };
    }
    renderProject();
    toast(`文件“${file.name}”已删除`, "success");
  } catch (error) { toast(error.message, "error"); }
}

async function deleteActiveProject() {
  closeProjectActionMenu();
  const project = state.projects.find((item) => item.id === state.activeProjectId);
  if (!project || !confirm(`确定删除项目“${project.name}”及其中的聊天、资料、会议、待办和项目记忆吗？`)) return;
  try {
    await api(`/api/projects/${project.id}`, { method: "DELETE" });
    state.projects = state.projects.filter((item) => item.id !== project.id);
    state.activeProjectId = null;
    state.expandedProjectId = null;
    state.sidebarSelection = null;
    clearProjectMentions();
    state.projectConversations = [];
    state.activeProjectConversationId = null;
    state.projectMessages = [];
    state.projectDocuments = [];
    state.meetings = [];
    state.todos = [];
    state.memories = [];
    if ($("#project-management-dialog").open) $("#project-management-dialog").close();
    renderProjects();
    switchView("chat");
    toast(`项目“${project.name}”已删除`, "success");
  } catch (error) { toast(error.message, "error"); }
}

function toggleProjectActionMenu() {
  closeProjectSwitchMenu();
  $("#project-action-menu").hidden = !$("#project-action-menu").hidden;
}

function closeProjectActionMenu() {
  $("#project-action-menu").hidden = true;
}

async function openProjectMembers() {
  if (!state.activeProjectId) return;
  closeProjectActionMenu();
  try {
    state.projectMembers = await api(`/api/projects/${state.activeProjectId}/members`);
    $("#project-member-form").reset();
    renderProjectMembers();
    $("#project-members-dialog").showModal();
  } catch (error) { toast(error.message, "error"); }
}

function renderProjectMembers() {
  const roles = { owner: "所有者", editor: "编辑者", viewer: "查看者" };
  $("#project-members-list").innerHTML = state.projectMembers.map((member) => `<div class="user-role-row" data-project-member-id="${member.id}"><span class="sidebar-user-avatar">${escapeHtml((member.displayName || member.phone).slice(0, 1))}</span><span><strong>${escapeHtml(member.displayName || member.phone)}</strong><small>${escapeHtml(member.phone)} · ${roles[member.role] || member.role}</small></span>${member.role === "owner" ? '<small>项目所有者</small>' : `<button class="project-member-remove" type="button">移除</button>`}</div>`).join("");
  $$("[data-project-member-id] .project-member-remove").forEach((button) => button.addEventListener("click", async () => {
    const userId = Number(button.closest("[data-project-member-id]").dataset.projectMemberId);
    if (!confirm("确定从项目中移除该成员吗？")) return;
    try {
      await api(`/api/projects/${state.activeProjectId}/members/${userId}`, { method: "DELETE" });
      state.projectMembers = state.projectMembers.filter((member) => member.id !== userId);
      renderProjectMembers();
      toast("项目成员已移除", "success");
    } catch (error) { toast(error.message, "error"); }
  }));
}

async function addProjectMember(event) {
  event.preventDefault();
  const phone = $("#project-member-phone").value.trim();
  if (!phone || !state.activeProjectId) return;
  try {
    const member = await api(`/api/projects/${state.activeProjectId}/members`, {
      method: "POST",
      body: JSON.stringify({ phone, role: $("#project-member-role").value })
    });
    state.projectMembers = [
      ...state.projectMembers.filter((item) => item.id !== member.id),
      member
    ];
    $("#project-member-phone").value = "";
    renderProjectMembers();
    toast("项目成员已添加", "success");
  } catch (error) { toast(error.message, "error"); }
}

async function openProjectMemory() {
  if (!state.activeProjectId) return;
  closeProjectActionMenu();
  try {
    state.memories = await api(`/api/memories?scope=project&project_id=${state.activeProjectId}`);
    state.memoryDialogScope = "project";
    state.memorySearch = "";
    state.memoryTypeFilter = "all";
    $("#memory-search").value = "";
    $("#memory-type-filter").value = "all";
    $("#memory-dialog-title").textContent = "项目记忆";
    $("#memory-dialog-description").textContent = "从项目聊天和会议中沉淀的人物、主题、决策与风险。";
    renderMemories();
    $("#project-management-dialog").showModal();
  } catch (error) { toast(error.message, "error"); }
}

async function openChatMemory() {
  closeProjectActionMenu();
  try {
    state.ordinaryMemories = await api("/api/memories?scope=ordinary");
    state.memoryDialogScope = "ordinary";
    state.memorySearch = "";
    state.memoryTypeFilter = "all";
    $("#memory-search").value = "";
    $("#memory-type-filter").value = "all";
    $("#memory-dialog-title").textContent = "记忆";
    $("#memory-dialog-description").textContent = "从普通聊天中提取并长期保留的人物、偏好与事实。";
    renderMemories();
    $("#project-management-dialog").showModal();
  } catch (error) { toast(error.message, "error"); }
}

function openRenameProject() {
  const project = state.projects.find((item) => item.id === state.activeProjectId);
  if (!project) return;
  closeProjectActionMenu();
  $("#project-rename-input").value = project.name;
  $("#project-rename-dialog").showModal();
  requestAnimationFrame(() => $("#project-rename-input").select());
}

async function renameActiveProject(event) {
  event.preventDefault();
  const projectId = state.activeProjectId;
  const name = $("#project-rename-input").value.trim();
  if (!projectId || !name) return;
  try {
    const project = await api(`/api/projects/${projectId}`, {
      method: "PATCH",
      body: JSON.stringify({ name })
    });
    state.projects = state.projects.map((item) => item.id === projectId ? { ...item, ...project } : item);
    $("#page-title").textContent = project.name;
    $("#project-rename-dialog").close();
    renderProjects();
    renderProjectSwitcher();
    toast("项目名称已更新", "success");
  } catch (error) { toast(error.message, "error"); }
}

function switchProjectTab(tab) {
  state.projectTab = tab;
  if (tab !== "meetings" || !state.activeMeetingId) {
    $("#project-message-input").placeholder = "输入 @ 引用项目文件…";
  }
  renderProjectChat();
  renderProjectContextResponse();
}

function renderProject() {
  const project = state.projects.find((item) => item.id === state.activeProjectId);
  if (!project) return;
  if (!state.expandedProjectId) state.expandedProjectId = project.id;
  $("#project-memory-count").textContent = state.memories.length;
  renderProjects();
  switchProjectTab(state.projectTab);
}

function syncActiveProjectCounts() {
  state.projects = state.projects.map((project) => project.id === state.activeProjectId ? {
    ...project,
    conversation_count: state.projectConversations.length,
    meeting_count: state.meetings.length,
    document_count: state.projectDocuments.length,
    open_todo_count: state.todos.filter((todo) => todo.status === "open").length
  } : project);
  renderProject();
}

async function newConversation() {
  try {
    const conversation = await api("/api/conversations", { method: "POST", body: JSON.stringify({}) });
    state.conversations.unshift(conversation);
    await selectConversation(conversation.id);
    switchView("chat");
    $("#message-input").focus();
  } catch (error) { toast(error.message, "error"); }
}

async function selectConversation(id) {
  try {
    const data = await api(`/api/conversations/${id}`);
    state.activeConversationId = id;
    state.messages = data.messages;
    state.documents = data.documents.filter((doc) => doc.kind === "knowledge");
    renderConversations();
    renderMessages();
    renderDocuments();
    if ($("#chat-history-dialog").open) $("#chat-history-dialog").close();
    switchView("chat");
  } catch (error) { toast(error.message, "error"); }
}

function renderConversations() {
  const list = $("#chat-history-list");
  if (list) {
    const query = state.conversationSearch.trim().toLocaleLowerCase("zh-CN");
    const conversations = query
      ? state.conversations.filter((conversation) => String(conversation.title || "").toLocaleLowerCase("zh-CN").includes(query))
      : state.conversations;
    $("#chat-history-meta").textContent = `${state.conversations.length} 个对话`;
    list.innerHTML = conversations.length
      ? conversations.map((conversation) => `<div class="project-chat-history-row ${$("#view-chat").classList.contains("active") && state.activeConversationId === conversation.id ? "active" : ""}"><button type="button" data-ordinary-conversation="${conversation.id}"><span>◇</span><span><strong>${escapeHtml(conversation.title)}</strong><small>${formatDate(conversation.updated_at)}</small></span></button><button class="project-chat-history-delete" type="button" data-ordinary-conversation-remove="${conversation.id}" title="删除对话" aria-label="删除 ${escapeHtml(conversation.title)}">×</button></div>`).join("")
      : `<div class="project-chat-history-empty">${state.conversations.length ? "未找到匹配的对话" : "还没有历史对话"}</div>`;
    $$("[data-ordinary-conversation]").forEach((button) => button.addEventListener("click", () => selectConversation(Number(button.dataset.ordinaryConversation))));
    $$("[data-ordinary-conversation-remove]").forEach((button) => button.addEventListener("click", () => deleteConversation(Number(button.dataset.ordinaryConversationRemove))));
  }
  renderProjectSwitcher();
}

function openChatHistory() {
  closeProjectActionMenu();
  state.conversationSearch = "";
  $("#chat-history-search").value = "";
  renderConversations();
  $("#chat-history-dialog").showModal();
  requestAnimationFrame(() => $("#chat-history-search").focus());
}

async function deleteConversation(id) {
  if (!confirm("确定删除这个会话及其消息吗？")) return;
  try {
    await api(`/api/conversations/${id}`, { method: "DELETE" });
    state.conversations = state.conversations.filter((item) => item.id !== id);
    if (state.activeConversationId === id) {
      if (state.conversations.length) await selectConversation(state.conversations[0].id);
      else await newConversation();
    } else renderConversations();
  } catch (error) { toast(error.message, "error"); }
}

function renderMessages() {
  $("#chat-empty").classList.toggle("hidden", state.messages.length > 0);
  $("#messages").innerHTML = state.messages.map(messageHtml).join("");
  scrollChat();
}

function messageHtml(message) {
  const sources = (message.sources || []).map((source) => {
    const text = source.type === "document" ? `▤ ${source.title}${source.page ? ` · 第${source.page}页` : ""}` : `⌁ ${source.title}`;
    if (source.type === "web" && /^https?:\/\//.test(source.url || "")) return `<a class="source-chip" href="${escapeHtml(source.url)}" target="_blank" rel="noopener">${escapeHtml(text)}</a>`;
    return `<span class="source-chip">${escapeHtml(text)}</span>`;
  }).join("");
  const artifact = message.artifact_id ? `<div class="artifact-card"><div class="artifact-icon">▰</div><div class="artifact-info"><b>演示文稿</b><small>PowerPoint · 可继续编辑</small></div><a class="download-link" href="${apiUrl(`/api/artifacts/${message.artifact_id}/download`)}">下载</a></div>` : "";
  return `<article class="message ${message.role}"><div class="avatar">${message.role === "user" ? "你" : "M"}</div><div class="message-body"><p class="message-role">${message.role === "user" ? "你" : "Memora"}</p><div class="message-content">${richText(message.content)}</div>${sources ? `<div class="sources">${sources}</div>` : ""}${artifact}</div></article>`;
}

function showTyping() {
  $("#chat-empty").classList.add("hidden");
  $("#messages").insertAdjacentHTML("beforeend", '<article class="message assistant typing" id="typing"><div class="avatar">M</div><div class="message-body"><p class="message-role">Memora 正在思考</p><div class="message-content"><i></i><i></i><i></i></div></div></article>');
  scrollChat();
}

function scrollChat() { requestAnimationFrame(() => { $("#chat-scroll").scrollTop = $("#chat-scroll").scrollHeight; }); }

function autoSizeComposer() {
  const input = $("#message-input");
  input.value = input.value.replace(/[\r\n]+/g, " ");
}

async function sendMessage(event) {
  event.preventDefault();
  const content = $("#message-input").value.trim();
  if (!content || state.sending || !state.activeConversationId) return;
  state.sending = true;
  $("#send-button").disabled = true;
  $("#message-input").value = "";
  autoSizeComposer();
  state.messages.push({ role: "user", content, sources: [] });
  renderMessages();
  showTyping();
  try {
    const result = await submitMessageTask(state.activeConversationId, { content });
    $("#typing")?.remove();
    state.messages[state.messages.length - 1] = { ...state.messages[state.messages.length - 1], id: result.message?.id - 1 };
    state.messages.push(result.message);
    renderMessages();
    await loadConversations();
    if (result.artifact) toast("PPT 已生成，可以下载", "success");
  } catch (error) {
    $("#typing")?.remove();
    state.messages.push({ role: "assistant", content: `处理失败：${error.message}`, sources: [] });
    renderMessages();
    toast(error.message, "error");
  } finally {
    state.sending = false;
    $("#send-button").disabled = false;
    $("#message-input").focus();
  }
}

async function uploadKnowledgeFiles(files) {
  const supported = files.filter((file) => /\.(pdf|pptx|txt|md|markdown)$/i.test(file.name));
  if (supported.length !== files.length) toast("仅支持 PDF、PPTX、TXT、Markdown 文件", "error");
  for (const file of supported) await uploadKnowledgeFile(file);
  $("#knowledge-input").value = "";
}

async function uploadKnowledgeFile(file) {
  if (!state.activeConversationId) return;
  const form = new FormData();
  form.append("file", file);
  toast(`正在解析 ${file.name}…`);
  try {
    const document = await api(`/api/conversations/${state.activeConversationId}/documents`, { method: "POST", body: form });
    state.documents.unshift(document);
    renderDocuments();
    toast(`${file.name} 已就绪`, "success");
  } catch (error) { toast(error.message, "error"); }
}

function renderDocuments() {
  $("#document-strip").innerHTML = state.documents.map((doc) => {
    const format = String(doc.metadata?.format || doc.name.split(".").pop() || "文件").toUpperCase();
    const pages = doc.metadata?.pages ? ` · ${doc.metadata.pages} 页` : "";
    return `<span class="doc-chip">
      <span class="doc-label doc-preview" data-document-id="${doc.id}" role="button" tabindex="0" title="预览 ${escapeHtml(doc.name)}">▤ ${escapeHtml(doc.name)} · ${escapeHtml(format)}${pages}</span>
      <button type="button" class="doc-remove" data-document-id="${doc.id}" aria-label="移除 ${escapeHtml(doc.name)}" title="从当前对话移除">×</button>
    </span>`;
  }).join("");
  $$(".doc-preview").forEach((button) => {
    button.addEventListener("click", () => openDocumentPreview(Number(button.dataset.documentId)));
    button.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openDocumentPreview(Number(button.dataset.documentId)); }
    });
  });
  $$(".doc-remove").forEach((button) => button.addEventListener("click", () => removeDocument(Number(button.dataset.documentId))));
}

async function openDocumentPreview(documentId) {
  const dialog = $("#file-preview-dialog");
  dialog.dataset.documentId = String(documentId);
  state.previewDocument = null;
  state.previewEditing = false;
  state.previewSaving = false;
  setPreviewEditActions(false);
  const previewTitle = $("#file-preview-title");
  previewTitle.textContent = "文件预览";
  previewTitle.hidden = false;
  previewTitle.classList.remove("editable");
  previewTitle.removeAttribute("tabindex");
  previewTitle.removeAttribute("title");
  $("#file-preview-title-input").hidden = true;
  $("#file-preview-meta").textContent = "正在读取解析内容…";
  $("#file-preview-body").innerHTML = '<div class="file-preview-loading">正在加载预览…</div>';
  if (!dialog.open) dialog.showModal();
  try {
    const document = await api(`/api/documents/${documentId}/preview`);
    if (dialog.dataset.documentId !== String(documentId)) return;
    const meeting = state.meetings.find((item) => (item.files || []).some((file) => file.id === documentId));
    const meetingId = Number(document.meeting_id || meeting?.id || 0) || null;
    state.previewDocument = { ...document, meetingId };
    if (document.kind === "meeting" && meetingId) {
      previewTitle.classList.add("editable");
      previewTitle.tabIndex = 0;
      previewTitle.title = "点击修改文件名";
    }
    const format = String(document.metadata?.format || document.name.split(".").pop() || "文件").toUpperCase();
    const detail = [format, document.metadata?.pages ? `${document.metadata.pages} 页` : "", document.metadata?.size ? `${Math.max(1, Math.round(document.metadata.size / 1024))} KB` : ""].filter(Boolean).join(" · ");
    previewTitle.textContent = document.name;
    $("#file-preview-meta").textContent = `${detail}${document.kind === "meeting" ? " · 会议原文" : " · 文本预览"}`;
    renderPreviewContent(state.previewDocument);
    setPreviewEditActions(false);
  } catch (error) {
    if (dialog.dataset.documentId !== String(documentId)) return;
    $("#file-preview-meta").textContent = "加载失败";
    $("#file-preview-body").innerHTML = `<div class="file-preview-error">${escapeHtml(error.message)}</div>`;
  }
}

async function removeDocument(documentId) {
  const document = state.documents.find((item) => item.id === documentId);
  if (!document || !state.activeConversationId) return;
  try {
    await api(`/api/conversations/${state.activeConversationId}/documents/${documentId}`, { method: "DELETE" });
    state.documents = state.documents.filter((item) => item.id !== documentId);
    renderDocuments();
    toast(`已移除 ${document.name}`, "success");
  } catch (error) { toast(error.message, "error"); }
}

async function uploadProjectKnowledgeFiles(files) {
  if (!state.activeProjectId) return toast("请先创建或选择一个项目", "error");
  const supported = files.filter((file) => /\.(pdf|pptx|txt|md|markdown)$/i.test(file.name));
  if (supported.length !== files.length) toast("仅支持 PDF、PPTX、TXT、Markdown 文件", "error");
  state.sidebarSelection = null;
  state.projectTab = "files";
  renderProject();
  for (const file of supported) await uploadProjectKnowledgeFile(file);
  $("#project-knowledge-input").value = "";
}

async function uploadProjectKnowledgeFile(file) {
  const projectId = state.activeProjectId;
  if (!projectId) return;
  const form = new FormData();
  form.append("file", file);
  toast(`正在解析项目资料 ${file.name}…`);
  try {
    const document = await api(`/api/projects/${projectId}/documents`, { method: "POST", body: form });
    if (state.activeProjectId === projectId) {
      state.projectDocuments.unshift(document);
      syncActiveProjectCounts();
    }
    toast(`${file.name} 已加入项目资料库`, "success");
  } catch (error) { toast(error.message, "error"); }
}

function renderProjectFiles() {
  renderProjects();
  return;
  $("#project-file-list").innerHTML = `<div class="project-sidebar-list-note"><span>▤</span><strong>${state.projectDocuments.length ? "资料文件已移到左侧导航栏" : "资料库还没有文件"}</strong><p>${state.projectDocuments.length ? "从左侧文件列表打开预览，或在这里继续添加资料。" : "上传 PDF、PPTX、TXT 或 Markdown，作为项目知识背景。"}</p></div>`;
}

async function removeProjectDocument(documentId) {
  const projectId = state.activeProjectId;
  const document = state.projectDocuments.find((item) => item.id === documentId);
  if (!projectId || !document) return;
  try {
    await api(`/api/projects/${projectId}/documents/${documentId}`, { method: "DELETE" });
    state.projectDocuments = state.projectDocuments.filter((item) => item.id !== documentId);
    state.projectMentions = state.projectMentions.filter((item) => item.id !== documentId);
    renderProjectMentions();
    if (state.sidebarSelection?.type === "document" && state.sidebarSelection.id === documentId) {
      state.sidebarSelection = null;
    }
    syncActiveProjectCounts();
    toast(`已从项目移除 ${document.name}`, "success");
  } catch (error) { toast(error.message, "error"); }
}

function openAddMeetingDialog(projectId) {
  if (!projectId) return toast("请先创建或选择一个项目", "error");
  state.addMeetingProjectId = projectId;
  $("#add-meeting-form").reset();
  $("#open-tencent-meeting-import").hidden = state.authEnabled && state.currentUser?.role !== "admin";
  $("#add-meeting-dialog").showModal();
  requestAnimationFrame(() => $("#add-meeting-name").focus());
}

function closeAddMeetingDialog() {
  $("#add-meeting-dialog").close();
  state.addMeetingProjectId = null;
}

function suggestMeetingName() {
  const file = $("#add-meeting-file").files[0];
  const input = $("#add-meeting-name");
  if (file && !input.value.trim()) input.value = file.name.replace(/\.[^.]+$/, "");
}

async function submitAddMeeting(event) {
  event.preventDefault();
  const projectId = state.addMeetingProjectId;
  const name = $("#add-meeting-name").value.trim();
  const file = $("#add-meeting-file").files[0];
  if (!projectId || !name || !file) return;
  if (!file.name.toLowerCase().endsWith(".txt")) return toast("请选择 TXT 文件", "error");
  const form = new FormData();
  form.append("name", name);
  form.append("file", file);
  const button = $("#add-meeting-submit");
  button.disabled = true;
  button.textContent = "添加中…";
  toast(`正在添加会议“${name}”…`);
  try {
    const result = await api(`/api/projects/${projectId}/meetings`, { method: "POST", body: form });
    state.projectTab = "meetings";
    await selectProject(projectId);
    state.activeMeetingId = result.meeting.id;
    state.sidebarSelection = { type: "meeting", id: result.meeting.id };
    closeAddMeetingDialog();
    renderProject();
    toast(`会议“${result.meeting.title}”已添加`, "success");
  } catch (error) { toast(error.message, "error"); }
  finally {
    button.disabled = false;
    button.textContent = "添加";
  }
}

async function openTencentMeetingImport() {
  const projectId = state.addMeetingProjectId;
  if (!projectId) return toast("请先创建或选择一个项目", "error");
  state.tencentMeetingProjectId = projectId;
  state.tencentMeetingRecords = [];
  closeAddMeetingDialog();
  $("#tencent-meeting-dialog").showModal();
  await loadTencentMeetingRecords();
}

async function loadTencentMeetingRecords() {
  if (!state.tencentMeetingProjectId || state.tencentMeetingLoading) return;
  state.tencentMeetingLoading = true;
  const statusHost = $("#tencent-meeting-status");
  const recordsHost = $("#tencent-meeting-records");
  const refreshButton = $("#refresh-tencent-meetings");
  statusHost.className = "tencent-meeting-status";
  statusHost.textContent = "正在连接腾讯会议…";
  recordsHost.innerHTML = '<div class="tencent-meeting-empty">正在读取云录制列表…</div>';
  refreshButton.disabled = true;
  try {
    const status = await api("/api/integrations/tencent-meeting/status");
    if (!status.configured) {
      statusHost.classList.add("error");
      statusHost.innerHTML = `尚未配置腾讯会议 Token。请在后端环境变量中设置 <code>TENCENT_MEETING_TOKEN</code>。<br><a href="${escapeHtml(status.tokenUrl)}" target="_blank" rel="noreferrer">前往腾讯会议官方页面获取 Token</a>`;
      recordsHost.innerHTML = '<div class="tencent-meeting-empty">配置并重启后端后，点击“刷新”。</div>';
      return;
    }
    const result = await api("/api/integrations/tencent-meeting/records?days=30");
    state.tencentMeetingRecords = result.records || [];
    statusHost.textContent = `已连接官方 MCP · 最近 ${result.days || 30} 天 · ${state.tencentMeetingRecords.length} 个录制文件`;
    renderTencentMeetingRecords();
  } catch (error) {
    statusHost.classList.add("error");
    statusHost.textContent = error.message;
    recordsHost.innerHTML = '<div class="tencent-meeting-empty">未能读取腾讯会议录制，请检查 Token、录制权限和网络。</div>';
  } finally {
    state.tencentMeetingLoading = false;
    refreshButton.disabled = false;
  }
}

function renderTencentMeetingRecords() {
  const host = $("#tencent-meeting-records");
  if (!state.tencentMeetingRecords.length) {
    host.innerHTML = '<div class="tencent-meeting-empty">最近 30 天没有可导入的云录制。录制处理通常需要 5–30 分钟。</div>';
    return;
  }
  host.innerHTML = state.tencentMeetingRecords.map((record, index) => {
    const title = record.subject || record.fileName || "未命名腾讯会议";
    const details = [record.startTime ? formatDate(record.startTime) : "时间未知", record.fileType || record.fileName || "录制文件", record.status].filter(Boolean).join(" · ");
    return `<article class="tencent-meeting-record"><span><strong title="${escapeHtml(title)}">${escapeHtml(title)}</strong><small title="${escapeHtml(details)}">${escapeHtml(details)}</small></span><button class="secondary-button" type="button" data-tencent-record-index="${index}" ${record.recordFileId ? "" : "disabled"}>导入逐字稿</button></article>`;
  }).join("");
  $$('[data-tencent-record-index]').forEach((button) => button.addEventListener("click", () => importTencentMeetingRecord(Number(button.dataset.tencentRecordIndex), button)));
}

async function importTencentMeetingRecord(index, button) {
  const projectId = state.tencentMeetingProjectId;
  const record = state.tencentMeetingRecords[index];
  if (!projectId || !record?.recordFileId || button.disabled) return;
  button.disabled = true;
  button.textContent = "导入中…";
  try {
    const result = await api(`/api/projects/${projectId}/integrations/tencent-meeting/import`, {
      method: "POST",
      body: JSON.stringify({
        recordFileId: record.recordFileId,
        meetingId: record.meetingId,
        meetingRecordId: record.meetingRecordId,
        title: record.subject || record.fileName || "腾讯会议记录"
      })
    });
    $("#tencent-meeting-dialog").close();
    state.projectTab = "meetings";
    await selectProject(projectId);
    state.activeMeetingId = result.meeting.id;
    state.sidebarSelection = { type: "meeting", id: result.meeting.id };
    renderProject();
    toast(result.idempotent ? "该腾讯会议已经导入，已打开现有记录" : `腾讯会议“${result.meeting.title}”已导入`, "success");
  } catch (error) {
    toast(error.message, "error");
    button.disabled = false;
    button.textContent = "导入逐字稿";
  }
}

function renderMeetings() {
  {
    $("#project-message-input").placeholder = "输入 @ 引用项目文件…";
    renderProjects();
    renderProjectContextResponse();
    return;
  }
  const openTodoCount = state.todos.filter((todo) => todo.status === "open").length;
  const activeMeeting = state.meetings.find((meeting) => meeting.id === state.activeMeetingId);
  if (activeMeeting) {
    $("#project-message-input").placeholder = "输入 @ 引用会议文件，然后要求生成内容…";
    const files = activeMeeting.files || [];
    const sourceFiles = files.filter((file) => file.is_source);
    const artifactFiles = files.filter((file) => !file.is_source);
    const fileCard = (file, artifact = false) => {
      const format = String(file.metadata?.format || file.name.split(".").pop() || "文件").toUpperCase();
      const label = file.is_source ? "会议原文" : file.metadata?.role === "email_content" ? "邮件内容" : "会议详情";
      if (!artifact) return `<button class="meeting-file-card" type="button" data-document-id="${file.id}"><span class="meeting-file-icon">▤</span><span><strong>${escapeHtml(file.name)}</strong><small>${label} · ${escapeHtml(format)} · ${formatDate(file.created_at)}</small></span><b>预览</b></button>`;
      if (state.artifactRenamingId === file.id) {
        return `<article class="meeting-file-card meeting-artifact-card renaming" data-artifact-id="${file.id}"><span class="meeting-file-icon">✦</span><span><input class="artifact-rename-input" data-artifact-rename-input="${file.id}" maxlength="180" value="${escapeHtml(file.name)}" aria-label="Artifact 文件名"><small>${label} · 保存扩展名为 Markdown</small></span><span class="artifact-inline-actions"><button class="artifact-rename-confirm" type="button" data-artifact-id="${file.id}" title="确认重命名" aria-label="确认重命名">${uiIcon("check")}</button><button class="artifact-rename-cancel" type="button" title="取消" aria-label="取消重命名">${uiIcon("close")}</button></span></article>`;
      }
      return `<article class="meeting-file-card meeting-artifact-card" role="button" tabindex="0" data-document-id="${file.id}" data-artifact-id="${file.id}"><span class="meeting-file-icon">✦</span><span><strong>${escapeHtml(file.name)}</strong><small>${label} · ${escapeHtml(format)} · ${formatDate(file.created_at)}</small></span><span class="artifact-card-actions"><b>预览</b><button class="artifact-email-send" type="button" data-artifact-id="${file.id}" title="发送邮件" aria-label="发送邮件">${uiIcon("mail")}</button><button class="artifact-rename-start" type="button" data-artifact-id="${file.id}" title="修改文件名" aria-label="修改文件名">${uiIcon("edit")}</button></span></article>`;
    };
    const sourceCards = sourceFiles.map((file) => fileCard(file)).join("");
    const artifactCards = artifactFiles.map((file) => fileCard(file, true)).join("");
    $("#meeting-view-title").innerHTML = `<nav class="meeting-view-breadcrumb" aria-label="会议导航"><button id="meeting-detail-back" type="button">会议列表</button><span>/</span><strong title="${escapeHtml(activeMeeting.title)}">${escapeHtml(activeMeeting.title)}</strong></nav>`;
    $("#meeting-dropzone").hidden = true;
    $("#meeting-list").innerHTML = `<section class="meeting-detail-page">
      <div class="meeting-detail-page-content">
        <section class="meeting-files-section"><div class="meeting-files-head"><h3>会议文件</h3><span>${sourceFiles.length} 个文件</span></div><div class="meeting-file-grid">${sourceCards || '<div class="meeting-todo-empty">暂无会议文件</div>'}</div></section>
        <section class="meeting-artifacts-section"><div class="meeting-files-head"><div><h3>Artifacts</h3><p>确认保存的会议详情和邮件内容</p></div><span>${artifactFiles.length} 个文件</span></div><div class="meeting-file-grid">${artifactCards || '<div class="meeting-artifact-empty"><span>✦</span><strong>暂无 Artifact</strong><p>在底部输入“生成会议详情”或“生成邮件内容”，确认后点击保存。</p></div>'}</div></section>
      </div>
    </section>`;
    $("#meeting-detail-back").addEventListener("click", () => { state.activeMeetingId = null; state.sidebarSelection = null; state.artifactRenamingId = null; renderProjects(); renderMeetings(); });
    $$(".meeting-file-card[data-document-id]").forEach((card) => {
      card.addEventListener("click", (event) => {
        if (event.target.closest(".artifact-rename-start,.artifact-email-send")) return;
        openDocumentPreview(Number(card.dataset.documentId));
      });
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.target.closest("button,input")) openDocumentPreview(Number(card.dataset.documentId));
      });
    });
    $$(".artifact-rename-start").forEach((button) => button.addEventListener("click", (event) => {
      event.stopPropagation();
      state.artifactRenamingId = Number(button.dataset.artifactId);
      renderMeetings();
      requestAnimationFrame(() => $(`[data-artifact-rename-input="${button.dataset.artifactId}"]`)?.select());
    }));
    $$(".artifact-email-send").forEach((button) => button.addEventListener("click", (event) => {
      event.stopPropagation();
      openArtifactEmail(activeMeeting.id, Number(button.dataset.artifactId));
    }));
    $$(".artifact-rename-cancel").forEach((button) => button.addEventListener("click", () => { state.artifactRenamingId = null; renderMeetings(); }));
    $$(".artifact-rename-confirm").forEach((button) => button.addEventListener("click", () => renameMeetingArtifact(activeMeeting.id, Number(button.dataset.artifactId))));
    $$(".artifact-rename-input").forEach((input) => input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") renameMeetingArtifact(activeMeeting.id, Number(input.dataset.artifactRenameInput));
      if (event.key === "Escape") { state.artifactRenamingId = null; renderMeetings(); }
    }));
    renderProjectContextResponse();
    return;
  }
  state.activeMeetingId = null;
  $("#project-message-input").placeholder = "输入 @ 引用项目文件…";
  $("#meeting-view-title").innerHTML = `<strong>会议列表</strong><span>${state.meetings.length} 次会议 · ${openTodoCount} 项进行中待办 · 文件列表位于左侧导航栏</span>`;
  $("#meeting-dropzone").hidden = false;
  $("#meeting-list").innerHTML = `<div class="project-sidebar-list-note"><span>◇</span><strong>${state.meetings.length ? "会议文件已移到左侧导航栏" : "还没有会议"}</strong><p>${state.meetings.length ? "从左侧选择会议或其中的文件，或在这里继续添加会议原文。" : "添加 TXT 会议原文后，将显示在左侧。"}</p></div>`;
  renderProjectContextResponse();
}

async function renameMeetingArtifact(meetingId, documentId) {
  const input = $(`[data-artifact-rename-input="${documentId}"]`);
  const name = input?.value.trim();
  if (!name) return toast("文件名不能为空", "error");
  try {
    const updated = await api(`/api/meetings/${meetingId}/artifacts/${documentId}`, {
      method: "PATCH",
      body: JSON.stringify({ name })
    });
    state.meetings = state.meetings.map((meeting) => meeting.id === meetingId ? {
      ...meeting,
      files: (meeting.files || []).map((file) => file.id === documentId ? { ...file, ...updated } : file)
    } : meeting);
    const draft = state.meetingDrafts[meetingId];
    if (draft?.savedFileId === documentId) draft.name = updated.name;
    state.artifactRenamingId = null;
    renderProjects();
    renderMeetings();
    toast("Artifact 文件名已更新", "success");
  } catch (error) { toast(error.message, "error"); }
}

function renderProjectContextResponse() {
  const host = $("#project-context-response");
  if (!host) return;
  const meeting = state.meetings.find((item) => item.id === state.activeMeetingId);
  if (state.projectTab !== "meetings" || !meeting) {
    host.innerHTML = "";
    $("#project-chat-empty").classList.toggle("hidden", Boolean(state.projectMessages.length));
    return;
  }
  const draft = state.meetingDrafts[meeting.id];
  const request = state.meetingDraftRequest?.meetingId === meeting.id ? state.meetingDraftRequest : null;
  if (!draft && !request) {
    host.innerHTML = "";
    $("#project-chat-empty").classList.toggle("hidden", Boolean(state.projectMessages.length));
    return;
  }
  const prompt = request?.prompt || draft?.prompt || "生成会议详情";
  const type = request?.contentType || draft?.contentType || "meeting_detail";
  const typeName = type === "email_content" ? "邮件内容" : "会议详情";
  const response = request
    ? `<article class="meeting-ai-response generating"><div class="meeting-response-avatar">M</div><div><strong>Memora 正在生成${typeName}</strong><p>正在读取当前会议原文并结合项目资料生成可编辑的 Markdown 草稿…</p><div class="meeting-response-dots"><i></i><i></i><i></i></div></div></article>`
    : `<article class="meeting-ai-response chatgpt-file-response">
        <span class="meeting-response-avatar">M</span>
        <div class="chatgpt-file-response-body">
          <strong class="chatgpt-response-author">Memora</strong>
          <section class="chatgpt-file-card">
            <header class="chatgpt-file-head">
              <div class="chatgpt-file-title"><strong>${escapeHtml(draft.name)}</strong><small>Markdown 文档 · 保存后可在 Artifacts 中修改文件名</small></div>
              <div class="chatgpt-file-head-actions meeting-response-actions">
                <button class="chatgpt-icon-action" type="button" id="meeting-detail-edit" title="${draft.editing ? "完成编辑" : "编辑内容"}" aria-label="${draft.editing ? "完成编辑" : "编辑内容"}">${uiIcon(draft.editing ? "check" : "edit")}</button>
                <button class="chatgpt-icon-action" type="button" id="meeting-detail-undo" title="撤销" aria-label="撤销" ${!draft.history.length && (!draft.editBase || draft.content === draft.editBase) ? "disabled" : ""}>${uiIcon("undo")}</button>
                <button class="chatgpt-icon-action" type="button" id="meeting-detail-regenerate" title="重新生成" aria-label="重新生成">${uiIcon("regenerate")}</button>
                <button class="chatgpt-file-save" type="button" id="meeting-detail-save" title="${draft.savedFileId ? "再次保存" : "保存到 Artifacts"}" aria-label="${draft.savedFileId ? "再次保存" : "保存到 Artifacts"}" ${state.meetingDetailSaving ? "disabled" : ""}>${uiIcon(state.meetingDetailSaving ? "loader" : "save")}</button>
              </div>
            </header>
            <div class="chatgpt-file-content">${draft.editing ? `<textarea class="meeting-draft-editor" id="meeting-draft-editor">${escapeHtml(draft.content)}</textarea>` : `<div class="meeting-markdown meeting-draft-preview">${markdownText(draft.content)}</div>`}</div>
          </section>
          ${draft.savedFileId ? `<p class="meeting-draft-saved">✓ 已保存到 Artifacts 区域，可在会议中打开预览。</p>` : ""}
        </div>
      </article>`;
  host.innerHTML = `<div class="meeting-context-turn"><div class="meeting-context-user"><span>${escapeHtml(prompt)}</span></div>${response}</div>`;
  $("#project-chat-empty").classList.add("hidden");
  if (request) return;
  $("#meeting-detail-regenerate")?.addEventListener("click", () => generateMeetingContent(meeting.id, draft.contentType, draft.prompt, draft.instruction));
  $("#meeting-detail-edit")?.addEventListener("click", () => toggleMeetingDraftEdit(meeting.id));
  $("#meeting-detail-undo")?.addEventListener("click", () => undoMeetingDraft(meeting.id));
  $("#meeting-detail-save")?.addEventListener("click", () => saveMeetingDetail(meeting.id));
  $("#meeting-draft-editor")?.addEventListener("input", (event) => { state.meetingDrafts[meeting.id].content = event.target.value; });
}

async function generateMeetingContent(meetingId, contentType, prompt, savedInstruction = "") {
  if (state.meetingDetailGenerating) return;
  const current = state.meetingDrafts[meetingId];
  const instruction = savedInstruction || prompt;
  state.meetingDetailGenerating = true;
  state.meetingDraftRequest = { meetingId, contentType, prompt, instruction };
  renderProjectContextResponse();
  try {
    const result = await api(`/api/meetings/${meetingId}/detail-draft`, {
      method: "POST",
      body: JSON.stringify({ instruction, contentType })
    });
    const sameType = current?.contentType === contentType;
    state.meetingDrafts[meetingId] = {
      ...result,
      contentType,
      prompt,
      instruction,
      editing: false,
      editBase: null,
      history: sameType && current?.content ? [...(current.history || []), current.content] : [],
      savedFileId: null
    };
  } catch (error) { toast(error.message, "error"); }
  finally {
    state.meetingDetailGenerating = false;
    state.meetingDraftRequest = null;
    renderProjectContextResponse();
  }
}

function toggleMeetingDraftEdit(meetingId) {
  const draft = state.meetingDrafts[meetingId];
  if (!draft) return;
  if (!draft.editing) draft.editBase = draft.content;
  draft.editing = !draft.editing;
  renderProjectContextResponse();
  if (draft.editing) requestAnimationFrame(() => $("#meeting-draft-editor")?.focus());
}

function undoMeetingDraft(meetingId) {
  const draft = state.meetingDrafts[meetingId];
  if (!draft) return;
  if (draft.editBase && draft.content !== draft.editBase) {
    draft.content = draft.editBase;
    draft.editBase = null;
  } else if (draft.history.length) {
    draft.content = draft.history.pop();
    draft.editBase = null;
  }
  draft.editing = false;
  renderProjectContextResponse();
}

async function saveMeetingDetail(meetingId) {
  const draft = state.meetingDrafts[meetingId];
  if (!draft || !draft.content.trim() || state.meetingDetailSaving) return;
  state.meetingDetailSaving = true;
  renderProjectContextResponse();
  try {
    const result = await api(`/api/meetings/${meetingId}/details`, {
      method: "POST",
      body: JSON.stringify({
        name: draft.name,
        content: draft.content,
        analysis: draft.analysis,
        contentType: draft.contentType,
        idempotencyKey: draft.idempotencyKey
      })
    });
    state.meetings = state.meetings.map((meeting) => meeting.id === meetingId ? result.meeting : meeting);
    state.todos = [...state.todos.filter((todo) => todo.meeting_id !== meetingId), ...result.todos];
    draft.savedFileId = result.file.id;
    draft.editing = false;
    draft.editBase = null;
    const project = state.projects.find((item) => item.id === state.activeProjectId);
    if (project) project.open_todo_count = state.todos.filter((todo) => todo.status === "open").length;
    renderProjects();
    toast(result.idempotent
      ? "该版本已经保存，没有重复创建 Artifact"
      : `${draft.contentType === "email_content" ? "邮件内容" : "会议详情"}已保存到 Artifacts`, "success");
  } catch (error) { toast(error.message, "error"); }
  finally { state.meetingDetailSaving = false; renderMeetings(); }
}

function todoHtml(todo) {
  return `<article class="todo-card ${todo.status === "done" ? "done" : ""}" data-id="${todo.id}"><input class="todo-check" type="checkbox" ${todo.status === "done" ? "checked" : ""} aria-label="完成待办"><div class="todo-info"><h3>${escapeHtml(todo.title)}</h3>${todo.description ? `<div class="meeting-markdown todo-description">${markdownText(todo.description)}</div>` : ""}<p>${todo.owner ? `负责人 ${escapeHtml(todo.owner)}` : "负责人待确认"}${todo.due_date ? ` · 截止 ${escapeHtml(todo.due_date)}` : ""}</p></div><div class="todo-actions"><span class="level ${todo.risk_level}">${{high:"高风险",medium:"中风险",low:"低风险"}[todo.risk_level] || todo.risk_level}</span><button class="email-button">✉ ${todo.email_status === "sent" ? "已发送" : "发邮件"}</button></div></article>`;
}

function bindTodoActions(root) {
  root.querySelectorAll(".todo-card").forEach((card) => {
    const id = Number(card.dataset.id);
    card.querySelector(".todo-check").addEventListener("change", (event) => updateTodo(id, event.target.checked ? "done" : "open"));
    card.querySelector(".email-button").addEventListener("click", () => openEmail(id));
  });
}

function renderTodos() { renderMeetings(); }

async function updateTodo(id, status) {
  try {
    const updated = await api(`/api/todos/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
    state.todos = state.todos.map((todo) => todo.id === id ? { ...todo, ...updated } : todo);
    syncActiveProjectCounts();
  } catch (error) { toast(error.message, "error"); }
}

async function openEmail(id) {
  try {
    const draft = await api(`/api/todos/${id}/email-draft`);
    state.emailTodoId = id;
    state.emailArtifactTarget = null;
    state.emailIdempotencyKey = newIdempotencyKey();
    renderEmailProviderOptions();
    $("#email-dialog-title").textContent = "发送待办邮件";
    $("#email-dialog-description").textContent = "发送前请确认收件人与正文";
    $("#email-to").value = ""; $("#email-subject").value = draft.subject; $("#email-body").value = draft.body;
    $("#email-dialog").showModal();
  } catch (error) { toast(error.message, "error"); }
}

async function openArtifactEmail(meetingId, documentId) {
  try {
    const draft = await api(`/api/meetings/${meetingId}/artifacts/${documentId}/email-draft`);
    state.emailTodoId = null;
    state.emailArtifactTarget = { meetingId, documentId };
    state.emailIdempotencyKey = newIdempotencyKey();
    renderEmailProviderOptions();
    $("#email-dialog-title").textContent = "发送 Artifact 邮件";
    $("#email-dialog-description").textContent = "已读取保存的 Artifact 内容，请填写收件人并确认发送";
    $("#email-to").value = "";
    $("#email-subject").value = draft.subject;
    $("#email-body").value = draft.body;
    $("#email-dialog").showModal();
    requestAnimationFrame(() => $("#email-to").focus());
  } catch (error) { toast(error.message, "error"); }
}

async function submitEmail(event) {
  event.preventDefault();
  if (!state.emailSettings?.configured) {
    toast("请先配置发件邮箱，再确认发送", "error");
    openEmailSettings();
    return;
  }
  const button = $("#confirm-email"); button.disabled = true; button.textContent = "发送中…";
  try {
    const targetUrl = state.emailArtifactTarget
      ? `/api/meetings/${state.emailArtifactTarget.meetingId}/artifacts/${state.emailArtifactTarget.documentId}/send-email`
      : `/api/todos/${state.emailTodoId}/send-email`;
    await api(targetUrl, { method: "POST", body: JSON.stringify({ provider: $("#email-provider").value, to: $("#email-to").value, subject: $("#email-subject").value, body: $("#email-body").value, idempotencyKey: state.emailIdempotencyKey }) });
    if (state.emailTodoId) {
      state.todos = state.todos.map((todo) => todo.id === state.emailTodoId ? { ...todo, email_status: "sent" } : todo);
      renderTodos();
    }
    $("#email-dialog").close();
    toast("邮件已发送", "success");
  } catch (error) { toast(error.message, "error"); }
  finally { button.disabled = false; button.textContent = "确认发送"; }
}

function renderMemories() {
  const names = { person: "人物", time: "时间", location: "地点", topic: "主题", decision: "决策", risk: "风险", preference: "偏好", fact: "事实" };
  const memories = state.memoryDialogScope === "ordinary" ? state.ordinaryMemories : state.memories;
  const counts = memories.reduce((map, item) => ({ ...map, [item.type]: (map[item.type] || 0) + 1 }), {});
  const summaryTypes = ["person", "time", "location", "topic", "preference", "fact", "decision", "risk"];
  $("#memory-summary").innerHTML = summaryTypes.map((type) => `<div class="summary-tile"><b>${counts[type] || 0}</b><span>${names[type]}</span></div>`).join("");
  $("#project-memory-count").textContent = memories.length;
  const query = state.memorySearch.trim().toLowerCase();
  const filtered = memories.filter((memory) => {
    if (state.memoryTypeFilter !== "all" && memory.type !== state.memoryTypeFilter) return false;
    return !query || `${memory.subject} ${memory.content}`.toLowerCase().includes(query);
  }).sort((left, right) => Number(right.pinned) - Number(left.pinned) || (right.importance || 3) - (left.importance || 3) || right.id - left.id);
  const sourceNames = { manual: "手动添加", chat: "来自聊天", meeting: "来自会议" };
  const emptyText = state.memoryDialogScope === "ordinary"
    ? "还没有聊天记忆。对话中明确表达的偏好、人物和事实会自动沉淀在这里。"
    : "还没有项目记忆。添加会议或进行项目聊天后会自动沉淀人物、主题、决策与风险。";
  $("#memory-grid").innerHTML = filtered.length ? filtered.map((memory) => `<article class="memory-card ${memory.pinned ? "pinned" : ""}" data-id="${memory.id}">
    <div class="memory-card-head"><span class="tag">${names[memory.type] || memory.type}</span><span class="memory-importance" title="重要度 ${memory.importance || 3}">${"●".repeat(memory.importance || 3)}${"○".repeat(5 - (memory.importance || 3))}</span></div>
    <div class="memory-card-actions"><button class="icon-btn memory-pin" type="button" title="${memory.pinned ? "取消置顶" : "置顶记忆"}" aria-label="${memory.pinned ? "取消置顶" : "置顶记忆"}">${memory.pinned ? "★" : "☆"}</button><button class="icon-btn memory-edit" type="button" title="编辑记忆" aria-label="编辑记忆">${uiIcon("edit")}</button><button class="icon-btn memory-delete" type="button" title="删除记忆" aria-label="删除记忆">${uiIcon("trash")}</button></div>
    <h3>${escapeHtml(memory.subject || names[memory.type] || "记忆")}</h3><p>${escapeHtml(memory.content)}</p>
    <small>${sourceNames[memory.source_type] || "自动沉淀"} · 置信度 ${Math.round((memory.confidence ?? 0.8) * 100)}%${memory.valid_until ? ` · 有效至 ${escapeHtml(memory.valid_until)}` : ""}${memory.sensitivity === "sensitive" ? " · 敏感" : ""} · 使用 ${memory.use_count || 0} 次 · ${formatDate(memory.updated_at || memory.created_at)}</small>
  </article>`).join("") : `<div class="empty-list">${memories.length ? "没有符合筛选条件的记忆。" : emptyText}</div>`;
  $$(".memory-delete").forEach((button) => button.addEventListener("click", () => deleteMemory(Number(button.closest(".memory-card").dataset.id))));
  $$(".memory-edit").forEach((button) => button.addEventListener("click", () => editMemory(Number(button.closest(".memory-card").dataset.id))));
  $$(".memory-pin").forEach((button) => button.addEventListener("click", () => toggleMemoryPin(Number(button.closest(".memory-card").dataset.id))));
}

function currentMemories() {
  return state.memoryDialogScope === "ordinary" ? state.ordinaryMemories : state.memories;
}

function replaceCurrentMemory(memory) {
  if (state.memoryDialogScope === "ordinary") state.ordinaryMemories = state.ordinaryMemories.map((item) => item.id === memory.id ? memory : item);
  else state.memories = state.memories.map((item) => item.id === memory.id ? memory : item);
}

function openMemoryEditor(memory = null) {
  state.memoryEditTarget = memory;
  $("#memory-editor-title").textContent = memory ? "编辑记忆" : "添加记忆";
  $("#memory-editor-description").textContent = state.memoryDialogScope === "project" ? "这条记忆仅在当前项目中生效。" : "这条记忆仅在普通聊天中生效。";
  $("#memory-editor-type").value = memory?.type || "fact";
  $("#memory-editor-importance").value = String(memory?.importance || 3);
  $("#memory-editor-confidence").value = String(memory?.confidence ?? 1);
  $("#memory-editor-sensitivity").value = memory?.sensitivity || "private";
  $("#memory-editor-valid-from").value = memory?.valid_from || "";
  $("#memory-editor-valid-until").value = memory?.valid_until || "";
  $("#memory-editor-subject").value = memory?.subject || "";
  $("#memory-editor-content").value = memory?.content || "";
  $("#memory-editor-pinned").checked = Boolean(memory?.pinned);
  $("#memory-editor-dialog").showModal();
  requestAnimationFrame(() => $("#memory-editor-subject").focus());
}

function editMemory(id) {
  const memory = currentMemories().find((item) => item.id === id);
  if (memory) openMemoryEditor(memory);
}

async function saveMemory(event) {
  event.preventDefault();
  const content = $("#memory-editor-content").value.trim();
  if (!content) return toast("记忆内容不能为空", "error");
  const body = {
    type: $("#memory-editor-type").value,
    subject: $("#memory-editor-subject").value.trim(),
    content,
    importance: Number($("#memory-editor-importance").value),
    pinned: $("#memory-editor-pinned").checked,
    confidence: Number($("#memory-editor-confidence").value),
    sensitivity: $("#memory-editor-sensitivity").value,
    validFrom: $("#memory-editor-valid-from").value || null,
    validUntil: $("#memory-editor-valid-until").value || null
  };
  if (!state.memoryEditTarget && state.memoryDialogScope === "project") body.projectId = state.activeProjectId;
  const editing = Boolean(state.memoryEditTarget);
  const targetId = state.memoryEditTarget?.id;
  const button = $("#memory-editor-submit");
  button.disabled = true;
  try {
    const memory = await api(editing ? `/api/memories/${targetId}` : "/api/memories", {
      method: editing ? "PATCH" : "POST",
      body: JSON.stringify(body)
    });
    if (editing) replaceCurrentMemory(memory);
    else if (state.memoryDialogScope === "ordinary") state.ordinaryMemories = [memory, ...state.ordinaryMemories.filter((item) => item.id !== memory.id && item.id !== memory.supersedes_id)];
    else state.memories = [memory, ...state.memories.filter((item) => item.id !== memory.id && item.id !== memory.supersedes_id)];
    $("#memory-editor-dialog").close();
    renderMemories();
    toast(editing ? "记忆已更新" : "记忆已添加", "success");
  } catch (error) { toast(error.message, "error"); }
  finally { button.disabled = false; }
}

async function toggleMemoryPin(id) {
  const memory = currentMemories().find((item) => item.id === id);
  if (!memory) return;
  try {
    replaceCurrentMemory(await api(`/api/memories/${id}`, { method: "PATCH", body: JSON.stringify({ pinned: !memory.pinned }) }));
    renderMemories();
  } catch (error) { toast(error.message, "error"); }
}

async function deleteMemory(id) {
  try {
    await api(`/api/memories/${id}`, { method: "DELETE" });
    if (state.memoryDialogScope === "ordinary") state.ordinaryMemories = state.ordinaryMemories.filter((item) => item.id !== id);
    else state.memories = state.memories.filter((item) => item.id !== id);
    if (state.memoryDialogScope === "project") renderProject();
    renderMemories();
  }
  catch (error) { toast(error.message, "error"); }
}

function renderAllSideData() {
  renderConversations();
  renderProjects();
}

initialize();
