const screens = {
  setup: document.getElementById("screen-setup"),
  login: document.getElementById("screen-login"),
  mode: document.getElementById("screen-mode"),
  main: document.getElementById("screen-main"),
};

function showScreen(name) {
  Object.values(screens).forEach((el) => el.classList.remove("active"));
  screens[name].classList.add("active");
}

function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("uz-UZ", { hour: "2-digit", minute: "2-digit" });
}

// ---------- Login ----------
const passwordInput = document.getElementById("password-input");
const loginBtn = document.getElementById("login-btn");
const loginError = document.getElementById("login-error");

async function doLogin() {
  const password = passwordInput.value;
  if (!password) return;

  loginError.textContent = "";
  loginBtn.disabled = true;
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    const data = await res.json();
    if (data.ok) {
      passwordInput.value = "";
      applyProfile(data.profile);
      showScreen("mode");
    } else {
      loginError.textContent = data.error || "Xato parol!";
    }
  } catch (err) {
    loginError.textContent = "Serverga ulanib bo'lmadi.";
  } finally {
    loginBtn.disabled = false;
  }
}

loginBtn.addEventListener("click", doLogin);
passwordInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") doLogin();
});

// ---------- First-run setup ----------
const setupUsername = document.getElementById("setup-username");
const setupPassword = document.getElementById("setup-password");
const setupPasswordConfirm = document.getElementById("setup-password-confirm");
const setupApiKey = document.getElementById("setup-api-key");
const setupRelayUrl = document.getElementById("setup-relay-url");
const setupAdvanced = document.getElementById("setup-advanced");
const setupAdvancedToggle = document.getElementById("setup-advanced-toggle");
const setupBtn = document.getElementById("setup-btn");
const setupError = document.getElementById("setup-error");

setupAdvancedToggle.addEventListener("click", () => {
  setupAdvanced.classList.toggle("hidden");
});

setupBtn.addEventListener("click", async () => {
  setupError.textContent = "";
  const payload = {
    username: setupUsername.value.trim(),
    password: setupPassword.value,
    password_confirm: setupPasswordConfirm.value,
    api_key: setupApiKey.value.trim(),
    relay_url: setupRelayUrl.value.trim(),
  };
  if (!payload.username || !payload.password || !payload.api_key) {
    setupError.textContent = "Ism, parol va API kalit to'ldirilishi shart.";
    return;
  }
  setupBtn.disabled = true;
  try {
    const res = await fetch("/api/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.ok) {
      applyProfile(data.profile);
      showScreen("mode");
    } else {
      setupError.textContent = data.error || "Xatolik yuz berdi.";
    }
  } catch (err) {
    setupError.textContent = "Serverga ulanib bo'lmadi.";
  } finally {
    setupBtn.disabled = false;
  }
});

// ---------- Profile ----------
let currentProfile = null;
const emptyGreetingEl = document.getElementById("empty-greeting");
const profileAvatarEl = document.getElementById("profile-avatar");
const profileNameEl = document.getElementById("profile-name");
const profileRowEl = document.getElementById("profile-row");
const profileEditEl = document.getElementById("profile-edit");
const profileNameInput = document.getElementById("profile-name-input");
const profileSaveBtn = document.getElementById("profile-save-btn");

function applyProfile(profile) {
  currentProfile = profile && profile.username ? profile : null;
  if (currentProfile) {
    profileAvatarEl.textContent = currentProfile.username.trim().charAt(0);
    profileNameEl.textContent = currentProfile.username;
    emptyGreetingEl.textContent = `Salom, ${currentProfile.username}!`;
  } else {
    profileAvatarEl.textContent = "?";
    profileNameEl.textContent = "Profilni sozlash";
    emptyGreetingEl.textContent = "Salom!";
  }
}

profileRowEl.addEventListener("click", () => {
  profileNameInput.value = currentProfile ? currentProfile.username : "";
  profileEditEl.classList.toggle("hidden");
  if (!profileEditEl.classList.contains("hidden")) profileNameInput.focus();
});

profileSaveBtn.addEventListener("click", async () => {
  const username = profileNameInput.value.trim();
  if (!username) return;
  profileSaveBtn.disabled = true;
  try {
    const res = await fetch("/api/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    });
    const data = await res.json();
    if (data.ok) {
      applyProfile(data.profile);
      profileEditEl.classList.add("hidden");
    }
  } finally {
    profileSaveBtn.disabled = false;
  }
});

// ---------- Mode select ----------
document.getElementById("mode-open-btn").addEventListener("click", () => {
  showScreen("main");
  enterMainScreen();
});
document.getElementById("mode-closed-btn").addEventListener("click", () => {});

// ---------- Tab navigation ----------
const tabButtons = document.querySelectorAll(".tab-btn");
const panels = {
  ai: document.getElementById("panel-ai"),
  computer: document.getElementById("panel-computer"),
  messages: document.getElementById("panel-messages"),
};

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    Object.values(panels).forEach((p) => p.classList.remove("active"));
    panels[btn.dataset.panel].classList.add("active");
  });
});

let mainScreenEntered = false;

function enterMainScreen() {
  if (mainScreenEntered) return;
  mainScreenEntered = true;
  initChat();
  loadComputerStatus();
  loadScreenshotsGallery();
  loadChatList();
  connectEvents();
}

// ================= AI chat =================

const messagesEl = document.getElementById("chat-messages");
const chatEmptyState = document.getElementById("chat-empty-state");
const textInput = document.getElementById("text-input");
const imageInput = document.getElementById("image-input");
const audioInput = document.getElementById("audio-input");
const fileInput = document.getElementById("file-input");
const attachmentPreview = document.getElementById("attachment-preview");
const chatForm = document.getElementById("chat-form");
const sendBtn = document.getElementById("send-btn");
const attachBtn = document.getElementById("attach-btn");
const attachMenu = document.getElementById("attach-menu");

attachBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  attachMenu.classList.toggle("hidden");
});

attachMenu.querySelectorAll(".attach-menu-item").forEach((item) => {
  item.addEventListener("click", () => {
    document.getElementById(item.dataset.target).click();
    attachMenu.classList.add("hidden");
  });
});

document.addEventListener("click", (e) => {
  if (!attachMenu.classList.contains("hidden") && !attachMenu.contains(e.target) && e.target !== attachBtn) {
    attachMenu.classList.add("hidden");
  }
});

const hamburgerBtn = document.getElementById("hamburger-btn");
const sidebar = document.getElementById("sidebar");
const sidebarOverlay = document.getElementById("sidebar-overlay");
const sidebarCloseBtn = document.getElementById("sidebar-close-btn");
const newChatBtn = document.getElementById("new-chat-btn");
const conversationListEl = document.getElementById("conversation-list");

let pendingImage = null;
let pendingAudio = null;
let pendingFile = null;
let currentConversationId = null;

// ---------- Lightweight markdown rendering for AI responses ----------

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderMarkdown(raw) {
  const codeBlocks = [];
  let text = raw.replace(/```([a-zA-Z0-9_+-]*)\n?([\s\S]*?)```/g, (_, _lang, code) => {
    codeBlocks.push(escapeHtml(code.replace(/\n$/, "")));
    return ` CB${codeBlocks.length - 1} `;
  });

  text = escapeHtml(text);
  text = text.replace(/`([^`\n]+)`/g, (_, code) => `<code>${code}</code>`);
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  text = text.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, "$1<em>$2</em>");
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  text = text.replace(/^### (.*)$/gm, "<h3>$1</h3>");
  text = text.replace(/^## (.*)$/gm, "<h2>$1</h2>");
  text = text.replace(/^# (.*)$/gm, "<h1>$1</h1>");

  text = text.replace(/(^|\n)((?:[-*] .*(?:\n|$))+)/g, (_, lead, block) => {
    const items = block.trim().split("\n").map((l) => `<li>${l.replace(/^[-*]\s+/, "")}</li>`).join("");
    return `${lead}<ul>${items}</ul>`;
  });
  text = text.replace(/(^|\n)((?:\d+\. .*(?:\n|$))+)/g, (_, lead, block) => {
    const items = block.trim().split("\n").map((l) => `<li>${l.replace(/^\d+\.\s+/, "")}</li>`).join("");
    return `${lead}<ol>${items}</ol>`;
  });

  text = text.replace(/\n{2,}/g, "</p><p>");
  text = text.replace(/\n/g, "<br>");
  text = `<p>${text}</p>`;
  text = text.replace(/<p>(<h[1-3]>|<ul>|<ol>)/g, "$1").replace(/(<\/h[1-3]>|<\/ul>|<\/ol>)<\/p>/g, "$1");
  text = text.replace(/<p><\/p>/g, "");
  text = text.replace(/ CB(\d+) /g, (_, i) => `<pre><code>${codeBlocks[Number(i)]}</code></pre>`);
  return text;
}

function buildCopyAction(getRaw) {
  const actions = document.createElement("div");
  actions.className = "msg-actions";
  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "msg-action-btn";
  copyBtn.title = "Nusxalash";
  copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>';
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(getRaw());
      copyBtn.classList.add("copied");
      setTimeout(() => copyBtn.classList.remove("copied"), 1200);
    } catch (err) { /* clipboard unavailable */ }
  });
  actions.appendChild(copyBtn);
  return actions;
}

function addMessage(container, text, who, ts) {
  const isAiChat = container === messagesEl;
  const div = document.createElement("div");
  div.className = `msg msg-${who}`;

  const body = who === "ai" ? document.createElement("div") : div;
  if (who === "ai") {
    body.className = "msg-body";
    div.appendChild(body);
  }

  if (who === "ai" && isAiChat) {
    const textEl = document.createElement("div");
    textEl.className = "msg-text";
    textEl.innerHTML = renderMarkdown(text);
    body.appendChild(textEl);
    body.appendChild(buildCopyAction(() => text));
  } else {
    const textNode = document.createElement("span");
    textNode.textContent = text;
    body.appendChild(textNode);
    if (ts && !isAiChat) {
      const timeEl = document.createElement("span");
      timeEl.className = "msg-time";
      timeEl.append(fmtTime(ts));
      if (who === "me") {
        const check = document.createElement("span");
        check.className = "msg-check";
        check.innerHTML = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 8.5 6 11.5 13 4.5"/></svg>';
        timeEl.appendChild(check);
      }
      body.appendChild(timeEl);
    }
  }
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  if (isAiChat) updateEmptyState();
  return body;
}

function addAiMessage(container) {
  const div = document.createElement("div");
  div.className = "msg msg-ai";
  const body = document.createElement("div");
  body.className = "msg-body";
  div.appendChild(body);

  const typing = document.createElement("div");
  typing.className = "typing-dots";
  typing.innerHTML = "<span></span><span></span><span></span>";
  body.appendChild(typing);

  const textEl = document.createElement("div");
  textEl.className = "msg-text";
  body.appendChild(textEl);

  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  updateEmptyState();

  let raw = "";
  let actionsAdded = false;

  function removeTyping() {
    if (typing.parentNode) typing.remove();
  }

  function ensureActions() {
    if (actionsAdded) return;
    actionsAdded = true;
    body.appendChild(buildCopyAction(() => raw));
  }

  return {
    appendDelta(piece) {
      removeTyping();
      raw += piece;
      textEl.innerHTML = renderMarkdown(raw);
      container.scrollTop = container.scrollHeight;
    },
    setText(text) {
      removeTyping();
      raw = text;
      textEl.innerHTML = renderMarkdown(raw);
      ensureActions();
      container.scrollTop = container.scrollHeight;
    },
    setError(text) {
      removeTyping();
      div.classList.add("msg-error-wrap");
      textEl.textContent = text;
      textEl.classList.add("msg-error-text");
      container.scrollTop = container.scrollHeight;
    },
    finish() {
      removeTyping();
      ensureActions();
    },
  };
}

const inputSlotCenter = document.getElementById("input-slot-center");
const inputSlotBottom = document.getElementById("input-slot-bottom");

function updateEmptyState() {
  const isEmpty = messagesEl.children.length === 0;
  chatEmptyState.classList.toggle("hidden", !isEmpty);
  const targetSlot = isEmpty ? inputSlotCenter : inputSlotBottom;
  if (!targetSlot.contains(attachmentPreview)) {
    targetSlot.appendChild(attachmentPreview);
    targetSlot.appendChild(chatForm);
  }
}

document.querySelectorAll(".suggestion-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    textInput.value = chip.dataset.prompt || "";
    textInput.focus();
    const len = textInput.value.length;
    textInput.setSelectionRange(len, len);
    updateSendState();
  });
});

function openSidebar() {
  sidebar.classList.add("open");
  sidebarOverlay.classList.remove("hidden");
}

function closeSidebar() {
  sidebar.classList.remove("open");
  sidebarOverlay.classList.add("hidden");
}

hamburgerBtn.addEventListener("click", () => {
  openSidebar();
  loadConversationList();
});
sidebarCloseBtn.addEventListener("click", closeSidebar);
sidebarOverlay.addEventListener("click", closeSidebar);

function renderConversationList(conversations) {
  conversationListEl.innerHTML = "";
  if (!conversations.length) {
    const hint = document.createElement("p");
    hint.className = "empty-hint";
    hint.textContent = "Hozircha suhbat yo'q.";
    conversationListEl.appendChild(hint);
    return;
  }
  conversations.forEach((conv) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "conversation-item" + (conv.id === currentConversationId ? " active" : "");
    const title = document.createElement("span");
    title.className = "conversation-title";
    title.textContent = conv.title;
    item.appendChild(title);
    if (conv.preview) {
      const preview = document.createElement("span");
      preview.className = "conversation-preview";
      preview.textContent = conv.preview;
      item.appendChild(preview);
    }
    item.addEventListener("click", () => selectConversation(conv.id));
    conversationListEl.appendChild(item);
  });
}

async function loadConversationList() {
  try {
    const res = await fetch("/api/chat/conversations");
    const data = await res.json();
    renderConversationList(data.conversations || []);
    return data.conversations || [];
  } catch (err) {
    return [];
  }
}

async function selectConversation(id) {
  try {
    const res = await fetch(`/api/chat/conversations/${id}`);
    const data = await res.json();
    if (data.error) return;
    currentConversationId = data.id;
    messagesEl.innerHTML = "";
    (data.messages || []).forEach((item) => {
      addMessage(messagesEl, item.text, item.role === "user" ? "user" : "ai", item.ts);
    });
    updateEmptyState();
  } finally {
    closeSidebar();
  }
}

async function startNewConversation() {
  try {
    const res = await fetch("/api/chat/conversations", { method: "POST" });
    const conv = await res.json();
    currentConversationId = conv.id;
    messagesEl.innerHTML = "";
    updateEmptyState();
  } finally {
    closeSidebar();
  }
}

newChatBtn.addEventListener("click", startNewConversation);

async function initChat() {
  const conversations = await loadConversationList();
  if (conversations.length) {
    await selectConversation(conversations[0].id);
  } else {
    await startNewConversation();
  }
}

function renderPreview() {
  attachmentPreview.innerHTML = "";

  const addChip = (inner, onRemove) => {
    const chip = document.createElement("div");
    chip.className = "preview-chip";
    chip.append(inner);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-preview";
    remove.textContent = "✕";
    remove.addEventListener("click", onRemove);
    chip.appendChild(remove);
    attachmentPreview.appendChild(chip);
  };

  if (pendingImage) {
    const img = document.createElement("img");
    img.src = URL.createObjectURL(pendingImage);
    addChip(img, () => {
      pendingImage = null;
      imageInput.value = "";
      renderPreview();
    });
  }

  if (pendingAudio) {
    addChip(pendingAudio.name, () => {
      pendingAudio = null;
      audioInput.value = "";
      renderPreview();
    });
  }

  if (pendingFile) {
    addChip(pendingFile.name, () => {
      pendingFile = null;
      fileInput.value = "";
      renderPreview();
    });
  }

  attachmentPreview.classList.toggle("hidden", !pendingImage && !pendingAudio && !pendingFile);
  updateSendState();
}

function updateSendState() {
  const hasContent = !!textInput.value.trim() || !!pendingImage || !!pendingAudio || !!pendingFile;
  sendBtn.classList.toggle("ready", hasContent);
}

textInput.addEventListener("input", updateSendState);

function clearOtherAttachments(keep) {
  if (keep !== "image") { pendingImage = null; imageInput.value = ""; }
  if (keep !== "audio") { pendingAudio = null; audioInput.value = ""; }
  if (keep !== "file") { pendingFile = null; fileInput.value = ""; }
}

imageInput.addEventListener("change", () => {
  pendingImage = imageInput.files[0] || null;
  clearOtherAttachments("image");
  renderPreview();
});

audioInput.addEventListener("change", () => {
  pendingAudio = audioInput.files[0] || null;
  clearOtherAttachments("audio");
  renderPreview();
});

fileInput.addEventListener("change", () => {
  pendingFile = fileInput.files[0] || null;
  clearOtherAttachments("file");
  renderPreview();
});

async function streamTextReply(text, aiMsg) {
  let res;
  try {
    res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, conversation_id: currentConversationId }),
    });
  } catch (err) {
    aiMsg.setError("Serverga ulanib bo'lmadi.");
    return;
  }

  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => ({}));
    aiMsg.setError(data.error || "Xatolik yuz berdi.");
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let gotError = false;
  let gotAnyDelta = false;

  try {
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = chunk.startsWith("data: ") ? chunk.slice(6) : "";
      if (!line) continue;
      let payload;
      try { payload = JSON.parse(line); } catch { continue; }
      if (payload.delta) {
        gotAnyDelta = true;
        aiMsg.appendDelta(payload.delta);
      } else if (payload.error) {
        gotError = true;
        aiMsg.setError(payload.error);
      } else if (payload.done) {
        currentConversationId = payload.conversation_id;
        loadConversationList();
      }
    }
  }
  } catch (err) {
    if (!gotAnyDelta) { aiMsg.setError("Serverga ulanib bo'lmadi."); return; }
    gotError = true;
  }
  if (!gotError) aiMsg.finish();
}

async function sendAttachmentReply(aiMsg, text) {
  const fd = new FormData();
  let url;
  if (pendingImage) {
    fd.append("image", pendingImage);
    url = "/api/chat/image";
  } else if (pendingAudio) {
    fd.append("audio", pendingAudio);
    url = "/api/chat/audio";
  } else {
    fd.append("file", pendingFile);
    url = "/api/chat/file";
  }
  if (text) fd.append("message", text);
  if (currentConversationId) fd.append("conversation_id", currentConversationId);

  try {
    const res = await fetch(url, { method: "POST", body: fd });
    const data = await res.json();
    if (data.error) {
      aiMsg.setError(data.error);
    } else {
      aiMsg.setText(data.reply || "Xatolik yuz berdi.");
      if (data.conversation_id) {
        currentConversationId = data.conversation_id;
        loadConversationList();
      }
    }
  } catch (err) {
    aiMsg.setError("Serverga ulanib bo'lmadi.");
  }
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = textInput.value.trim();
  if (!text && !pendingImage && !pendingAudio && !pendingFile) return;

  const attachmentLabel = pendingImage ? "[Rasm]" : pendingAudio ? "[Audio]" : pendingFile ? "[Fayl]" : "";
  const hasAttachment = !!(pendingImage || pendingAudio || pendingFile);
  sendBtn.disabled = true;
  addMessage(messagesEl, text || attachmentLabel, "user", Date.now() / 1000);
  const aiMsg = addAiMessage(messagesEl);

  // Clear the composer immediately on send, before waiting for the reply -
  // matches Gemini/ChatGPT; it used to only clear after the full response
  // finished streaming, leaving the sent text visibly stuck in the input.
  textInput.value = "";
  updateSendState();

  try {
    if (hasAttachment) {
      await sendAttachmentReply(aiMsg, text);
    } else {
      await streamTextReply(text, aiMsg);
    }
  } finally {
    pendingImage = null;
    pendingAudio = null;
    pendingFile = null;
    imageInput.value = "";
    audioInput.value = "";
    fileInput.value = "";
    renderPreview();
    sendBtn.disabled = false;
  }
});

// ================= Kompyuterim =================

const statusBadge = document.getElementById("computer-status-badge");
const computerBody = document.getElementById("computer-body");
const computerUnconfigured = document.getElementById("computer-unconfigured");
const fileEventsEl = document.getElementById("file-events");
const consoleOutput = document.getElementById("console-output");
const consoleForm = document.getElementById("console-form");
const consoleInput = document.getElementById("console-input");
const screenshotPreview = document.getElementById("screenshot-preview");
const screenshotImg = document.getElementById("screenshot-img");
const screenshotZoomBtn = document.getElementById("screenshot-zoom");
const deviceSubstatus = document.getElementById("device-substatus");
const screenshotsGallery = document.getElementById("screenshots-gallery");
const screenshotsGalleryBody = document.getElementById("screenshots-gallery-body");
const screenshotLightbox = document.getElementById("screenshot-lightbox");
const screenshotLightboxImg = document.getElementById("screenshot-lightbox-img");
const screenshotLightboxClose = document.getElementById("screenshot-lightbox-close");

function openLightbox(src) {
  screenshotLightboxImg.src = src;
  screenshotLightbox.classList.remove("hidden");
}
screenshotZoomBtn.addEventListener("click", () => {
  if (screenshotImg.src) openLightbox(screenshotImg.src);
});
screenshotLightboxClose.addEventListener("click", () => screenshotLightbox.classList.add("hidden"));
screenshotLightbox.addEventListener("click", (e) => {
  if (e.target === screenshotLightbox) screenshotLightbox.classList.add("hidden");
});

const GALLERY_MONTHS = [
  "yanvar", "fevral", "mart", "aprel", "may", "iyun",
  "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr",
];

function formatGalleryDate(dateKey) {
  const [y, m, d] = dateKey.split("-").map((n) => parseInt(n, 10));
  return `${d} ${GALLERY_MONTHS[m - 1]} ${y}`;
}

async function loadScreenshotsGallery() {
  try {
    const res = await fetch("/api/computer/screenshots");
    const data = await res.json();
    const groups = data.groups || {};
    const dateKeys = Object.keys(groups);
    screenshotsGalleryBody.innerHTML = "";
    if (dateKeys.length === 0) {
      screenshotsGalleryBody.innerHTML = '<p class="empty-hint">Hozircha skrinshot yoʻq.</p>';
      return;
    }
    dateKeys.forEach((dateKey) => {
      const group = document.createElement("div");
      group.className = "gallery-date-group";

      const label = document.createElement("span");
      label.className = "gallery-date-label";
      label.textContent = formatGalleryDate(dateKey);
      group.appendChild(label);

      const row = document.createElement("div");
      row.className = "gallery-thumb-row";
      groups[dateKey].forEach((relPath) => {
        const src = `/api/computer/screenshots/${relPath}`;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "gallery-thumb";
        const img = document.createElement("img");
        img.src = src;
        img.alt = "Skrinshot";
        btn.appendChild(img);
        btn.addEventListener("click", () => openLightbox(src));
        row.appendChild(btn);
      });
      group.appendChild(row);
      screenshotsGalleryBody.appendChild(group);
    });
  } catch (err) {
    /* jim */
  }
}

function setOnlineBadge(online) {
  statusBadge.classList.toggle("status-online", online);
  statusBadge.classList.toggle("status-offline", !online);
  statusBadge.querySelector(".status-label").textContent = online ? "Onlayn" : "Oflayn";
  deviceSubstatus.textContent = online ? "Ulangan va tayyor" : "Hozircha oflayn";
  if (messagesStatusEl) {
    messagesStatusEl.textContent = online ? "aloqada" : "aloqa yo'q";
    messagesStatusEl.classList.toggle("online", online);
  }
}

const FILE_EVENT_KIND = { created: "created", deleted: "deleted", modified: "modified" };

function addFileEvent(evt) {
  if (fileEventsEl.querySelector(".empty-hint")) fileEventsEl.innerHTML = "";
  const row = document.createElement("div");
  const kind = FILE_EVENT_KIND[evt.event] || "modified";
  row.className = `file-event-row file-event-${kind}`;
  const dot = document.createElement("span");
  dot.className = "file-event-dot";
  const tag = document.createElement("span");
  tag.className = "file-event-tag";
  tag.textContent = evt.event || "";
  const path = document.createElement("span");
  path.className = "file-event-path";
  path.textContent = evt.path || "";
  row.appendChild(dot);
  row.appendChild(tag);
  row.appendChild(path);
  fileEventsEl.prepend(row);
  while (fileEventsEl.children.length > 30) {
    fileEventsEl.removeChild(fileEventsEl.lastChild);
  }
}

async function loadComputerStatus() {
  try {
    const res = await fetch("/api/computer/status");
    const data = await res.json();
    if (!data.configured) {
      computerUnconfigured.classList.remove("hidden");
      computerBody.classList.add("hidden");
      return;
    }
    setOnlineBadge(!!data.online);
    (data.file_events || []).forEach(addFileEvent);
  } catch (err) {
    /* jim */
  }
}

document.querySelectorAll(".quick-action-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const action = btn.dataset.action;
    btn.disabled = true;
    try {
      const res = await fetch("/api/computer/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, payload: {} }),
      });
      const data = await res.json();
      if (data.image_base64) {
        screenshotImg.src = `data:image/png;base64,${data.image_base64}`;
        screenshotPreview.classList.remove("hidden");
        loadScreenshotsGallery();
      } else if (data.error) {
        consoleOutput.textContent += `\n[${action}] xato: ${data.error}`;
      } else if (data.ok) {
        consoleOutput.textContent += `\n[${action}] bajarildi.`;
      }
    } catch (err) {
      consoleOutput.textContent += `\n[${action}] aloqa xatosi.`;
    } finally {
      btn.disabled = false;
    }
  });
});

const ACTION_LABELS = {
  screenshot: "skrinshot olindi",
  lock: "kompyuter qulflandi",
  restart: "kompyuter qayta yoqilmoqda",
  shutdown: "kompyuter o'chirilmoqda",
  open_app: "dastur ochilmoqda",
  close_app: "dastur yopilmoqda",
  report: "hisobot tayyorlandi",
  transfer_images: "rasmlar o'tkazilmoqda",
  browser_history: "sayt tarixi tayyorlandi",
  app_usage_report: "dasturlar hisoboti tayyorlandi",
  shell: "buyruq bajarildi",
};

consoleForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const cmd = consoleInput.value.trim();
  if (!cmd) return;
  consoleOutput.textContent += `\n$ ${cmd}`;
  consoleInput.value = "";
  try {
    const res = await fetch("/api/computer/nl_command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: cmd }),
    });
    const data = await res.json();
    if (data.error) {
      consoleOutput.textContent += `\n${data.error}`;
    } else {
      const label = ACTION_LABELS[data.interpreted_action] || data.interpreted_action;
      if (data.interpreted_action && data.interpreted_action !== "shell") {
        consoleOutput.textContent += `\n[${label}]`;
      }
      if (data.image_base64) {
        screenshotImg.src = `data:image/png;base64,${data.image_base64}`;
        screenshotPreview.classList.remove("hidden");
        loadScreenshotsGallery();
      }
      if (typeof data.saved_to_gallery === "number") {
        consoleOutput.textContent += `\n${data.folder || ""}: ${data.total_found} ta rasm topildi, ${data.saved_to_gallery} tasi o'tkazildi.`;
        loadScreenshotsGallery();
      }
      if (data.report) consoleOutput.textContent += `\n${data.report}`;
      if (data.stdout) consoleOutput.textContent += `\n${data.stdout}`;
      if (data.stderr) consoleOutput.textContent += `\n${data.stderr}`;
    }
  } catch (err) {
    consoleOutput.textContent += "\naloqa xatosi.";
  }
  consoleOutput.scrollTop = consoleOutput.scrollHeight;
});

// ================= Xabarlar =================

const messagesListEl = document.getElementById("messages-list");
const messagesUnconfigured = document.getElementById("messages-unconfigured");
const messagesForm = document.getElementById("messages-form");
const messagesInput = document.getElementById("messages-input");
const messagesSendBtn = document.getElementById("messages-send-btn");
const messagesScrollBtn = document.getElementById("messages-scroll-btn");
const chatListView = document.getElementById("chat-list-view");
const chatListEl = document.getElementById("chat-list");
const chatListEmpty = document.getElementById("chat-list-empty");
const threadView = document.getElementById("thread-view");
const messagesBackBtn = document.getElementById("messages-back-btn");
const messagesHeaderAvatar = document.getElementById("messages-header-avatar");
const messagesHeaderTitle = document.getElementById("messages-header-title");
const newChatSocialBtn = document.getElementById("new-chat-social-btn");
const newChatModal = document.getElementById("new-chat-modal");
const newChatCloseBtn = document.getElementById("new-chat-close-btn");
const newChatError = document.getElementById("new-chat-error");
const dmUsernameInput = document.getElementById("dm-username-input");
const dmStartBtn = document.getElementById("dm-start-btn");
const groupNameInput = document.getElementById("group-name-input");
const groupMembersInput = document.getElementById("group-members-input");
const groupCreateBtn = document.getElementById("group-create-btn");
const socialRegisterCard = document.getElementById("social-register-card");
const socialUsernameInput = document.getElementById("social-username-input");
const socialPasswordInput = document.getElementById("social-password-input");
const socialRegisterBtn = document.getElementById("social-register-btn");
const socialRegisterError = document.getElementById("social-register-error");

let currentChatId = null;
let currentChatSource = null;
let telegramConfigured = false;
let socialRegistered = false;
let cachedChats = [];

messagesInput.addEventListener("input", () => {
  messagesSendBtn.classList.toggle("ready", !!messagesInput.value.trim());
});

let lastFamilyDateStr = null;

function addDateSeparatorIfNeeded(ts) {
  if (!ts) return;
  const d = new Date(ts * 1000);
  const dateStr = d.toDateString();
  if (dateStr === lastFamilyDateStr) return;
  lastFamilyDateStr = dateStr;
  const today = new Date().toDateString();
  const yesterday = new Date(Date.now() - 86400000).toDateString();
  let label;
  if (dateStr === today) label = "Bugun";
  else if (dateStr === yesterday) label = "Kecha";
  else label = d.toLocaleDateString("uz-UZ", { day: "numeric", month: "long" });
  const sep = document.createElement("div");
  sep.className = "date-separator";
  const inner = document.createElement("span");
  inner.textContent = label;
  sep.appendChild(inner);
  messagesListEl.appendChild(sep);
}

messagesListEl.addEventListener("scroll", () => {
  const distanceFromBottom = messagesListEl.scrollHeight - messagesListEl.scrollTop - messagesListEl.clientHeight;
  messagesScrollBtn.classList.toggle("hidden", distanceFromBottom < 80);
});

messagesScrollBtn.addEventListener("click", () => {
  messagesListEl.scrollTo({ top: messagesListEl.scrollHeight, behavior: "smooth" });
});

function addFamilyMessage(msg) {
  const who = msg.from === "men" ? "me" : "them";
  addDateSeparatorIfNeeded(msg.ts);
  addMessage(messagesListEl, msg.text, who, msg.ts);
}

function renderChatList(chats) {
  cachedChats = chats;
  chatListEl.innerHTML = "";
  chatListEmpty.classList.toggle("hidden", chats.length > 0);
  chats.forEach((chat) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "chat-list-item";

    const avatar = document.createElement("span");
    avatar.className = "contact-avatar" + (chat.type !== "private" ? " group" : "");
    avatar.textContent = (chat.title || "?").charAt(0).toUpperCase();

    const meta = document.createElement("div");
    meta.className = "chat-list-meta";
    const titleRow = document.createElement("div");
    titleRow.className = "chat-list-title-row";
    const title = document.createElement("span");
    title.className = "chat-list-title";
    title.textContent = chat.title;
    titleRow.appendChild(title);
    if (chat.type !== "private") {
      const badge = document.createElement("span");
      badge.className = "chat-list-badge";
      badge.textContent = "Guruh";
      titleRow.appendChild(badge);
    }
    if (chat.source === "social") {
      const badge = document.createElement("span");
      badge.className = "chat-list-badge";
      badge.textContent = "PultOSgram";
      titleRow.appendChild(badge);
    }
    const preview = document.createElement("span");
    preview.className = "chat-list-preview";
    preview.textContent = chat.preview || "";
    meta.appendChild(titleRow);
    meta.appendChild(preview);

    const time = document.createElement("span");
    time.className = "chat-list-time";
    time.textContent = chat.last_ts ? fmtTime(chat.last_ts) : "";

    item.appendChild(avatar);
    item.appendChild(meta);
    item.appendChild(time);
    item.addEventListener("click", () => openChat(chat));
    chatListEl.appendChild(item);
  });
}

async function loadChatList() {
  let telegramChats = [];
  let socialChats = [];

  try {
    const res = await fetch("/api/messages/chats");
    const data = await res.json();
    telegramConfigured = !!data.configured;
    if (data.configured) telegramChats = (data.chats || []).map((c) => ({ ...c, source: "telegram" }));
  } catch (err) {
    /* jim */
  }

  try {
    const res = await fetch("/api/social/status");
    const statusData = await res.json();
    socialRegistered = !!statusData.registered;
    if (socialRegistered) {
      const res2 = await fetch("/api/social/chats");
      const data2 = await res2.json();
      socialChats = (data2.chats || []).map((c) => ({ ...c, source: "social" }));
    }
  } catch (err) {
    /* jim */
  }

  messagesUnconfigured.classList.toggle("hidden", telegramConfigured);
  socialRegisterCard.classList.toggle("hidden", socialRegistered);
  newChatSocialBtn.classList.toggle("hidden", !socialRegistered);

  const merged = [...telegramChats, ...socialChats].sort((a, b) => (b.last_ts || 0) - (a.last_ts || 0));
  renderChatList(merged);
}

async function openChat(chat) {
  currentChatId = chat.chat_id;
  currentChatSource = chat.source;
  messagesHeaderAvatar.textContent = (chat.title || "?").charAt(0).toUpperCase();
  messagesHeaderAvatar.className = "contact-avatar" + (chat.type !== "private" ? " group" : "");
  messagesHeaderAvatar.classList.remove("hidden");
  messagesHeaderTitle.textContent = chat.title;
  messagesBackBtn.classList.remove("hidden");
  newChatSocialBtn.classList.add("hidden");
  chatListView.classList.add("hidden");
  threadView.classList.remove("hidden");

  messagesListEl.innerHTML = "";
  lastFamilyDateStr = null;

  const url = chat.source === "social" ? `/api/social/${encodeURIComponent(chat.chat_id)}` : `/api/messages/${encodeURIComponent(chat.chat_id)}`;
  try {
    const res = await fetch(url);
    const data = await res.json();
    (data.messages || []).forEach(addFamilyMessage);
  } catch (err) {
    /* jim */
  }
}

function closeChat() {
  currentChatId = null;
  currentChatSource = null;
  messagesBackBtn.classList.add("hidden");
  messagesHeaderAvatar.classList.add("hidden");
  messagesHeaderTitle.textContent = "Xabarlar";
  threadView.classList.add("hidden");
  chatListView.classList.remove("hidden");
  loadChatList();
}

messagesBackBtn.addEventListener("click", closeChat);

messagesForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = messagesInput.value.trim();
  if (!text || !currentChatId) return;
  messagesInput.value = "";
  messagesSendBtn.classList.remove("ready");
  const url = currentChatSource === "social" ? `/api/social/${encodeURIComponent(currentChatId)}/send` : `/api/messages/${encodeURIComponent(currentChatId)}/send`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    if (data.error) {
      addFamilyMessage({ from: "them", text: `(xatolik: ${data.error})`, ts: Date.now() / 1000 });
    }
  } catch (err) {
    addFamilyMessage({ from: "them", text: "(aloqa xatosi)", ts: Date.now() / 1000 });
  }
});

// ---- PultOSgram registration ----

socialRegisterBtn.addEventListener("click", async () => {
  const username = socialUsernameInput.value.trim();
  const password = socialPasswordInput.value;
  socialRegisterError.textContent = "";
  if (!username || !password) {
    socialRegisterError.textContent = "Username va parolni to'ldiring.";
    return;
  }
  socialRegisterBtn.disabled = true;
  try {
    const res = await fetch("/api/social/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (data.ok) {
      socialUsernameInput.value = "";
      socialPasswordInput.value = "";
      loadChatList();
    } else {
      socialRegisterError.textContent = data.error || "Xatolik yuz berdi.";
    }
  } catch (err) {
    socialRegisterError.textContent = "Serverga ulanib bo'lmadi.";
  } finally {
    socialRegisterBtn.disabled = false;
  }
});

// ---- New chat modal (PultOSgram) ----

newChatSocialBtn.addEventListener("click", () => {
  newChatError.textContent = "";
  dmUsernameInput.value = "";
  groupNameInput.value = "";
  groupMembersInput.value = "";
  newChatModal.classList.remove("hidden");
});

newChatCloseBtn.addEventListener("click", () => newChatModal.classList.add("hidden"));

dmStartBtn.addEventListener("click", async () => {
  const username = dmUsernameInput.value.trim();
  if (!username) return;
  newChatError.textContent = "";
  dmStartBtn.disabled = true;
  try {
    const res = await fetch("/api/social/dm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    });
    const data = await res.json();
    if (data.error) {
      newChatError.textContent = data.error;
      return;
    }
    newChatModal.classList.add("hidden");
    await loadChatList();
    openChat({ chat_id: data.conversation_id, title: data.title, type: "private", source: "social" });
  } catch (err) {
    newChatError.textContent = "Serverga ulanib bo'lmadi.";
  } finally {
    dmStartBtn.disabled = false;
  }
});

groupCreateBtn.addEventListener("click", async () => {
  const name = groupNameInput.value.trim();
  const members = groupMembersInput.value.split(",").map((m) => m.trim()).filter(Boolean);
  if (!name || !members.length) {
    newChatError.textContent = "Guruh nomi va kamida bitta a'zo kerak.";
    return;
  }
  newChatError.textContent = "";
  groupCreateBtn.disabled = true;
  try {
    const res = await fetch("/api/social/group", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, members }),
    });
    const data = await res.json();
    if (data.error) {
      newChatError.textContent = data.error;
      return;
    }
    newChatModal.classList.add("hidden");
    await loadChatList();
    openChat({ chat_id: data.conversation_id, title: name, type: "group", source: "social" });
  } catch (err) {
    newChatError.textContent = "Serverga ulanib bo'lmadi.";
  } finally {
    groupCreateBtn.disabled = false;
  }
});

// ================= Live events (SSE) =================

function connectEvents() {
  const source = new EventSource("/api/events");
  source.onmessage = (e) => {
    let event;
    try {
      event = JSON.parse(e.data);
    } catch (err) {
      return;
    }
    if (event.type === "status") {
      setOnlineBadge(!!event.online);
    } else if (event.type === "file_event") {
      addFileEvent(event);
    } else if (event.type === "chats_list") {
      if (!currentChatId) loadChatList();
    } else if (event.type === "chat_message") {
      if (currentChatSource === "telegram" && event.chat_id === currentChatId) addFamilyMessage(event);
      if (!currentChatId) loadChatList();
    } else if (event.type === "social_chats_list") {
      if (!currentChatId) loadChatList();
    } else if (event.type === "social_chat_message") {
      if (currentChatSource === "social" && event.conversation_id === currentChatId) addFamilyMessage(event);
      if (!currentChatId) loadChatList();
    }
  };
}

// ================= Bootstrap =================

(async function bootstrap() {
  try {
    const res = await fetch("/api/setup/status");
    const data = await res.json();
    if (!data.configured) {
      showScreen("setup");
      return;
    }
    if (data.authed) {
      applyProfile(data.profile);
      showScreen("main");
      enterMainScreen();
      return;
    }
  } catch (err) {
    // fall through to login on any bootstrap failure
  }
  showScreen("login");
})();
