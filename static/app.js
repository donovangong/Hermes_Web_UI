const state = { sessions: [], selectedId: null, selected: null, attachments: [], sending: false };
const MAX_ATTACHMENTS = 5;
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const headers = options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' };
  const res = await fetch(path, {
    headers,
    ...options,
  });
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || data.output || 'Request failed');
  return data;
}

function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>'"]/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[c]));
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function stripInternalInstructions(content) {
  const text = String(content || '');
  const marker = '\n\n[web_ui_download_instructions]';
  const index = text.indexOf(marker);
  return index >= 0 ? text.slice(0, index) : text;
}

function renderDownloadLinks(downloads = []) {
  if (!downloads.length) return '';
  return `
    <div class="download-links">
      ${downloads.map(file => `
        <a class="download-link" href="${escapeHtml(file.url)}" download>
          下载 ${escapeHtml(file.name)}${file.size_display ? ` (${escapeHtml(file.size_display)})` : ''}
        </a>
      `).join('')}
    </div>
  `;
}

function parseAttachmentMessage(content, explicitAttachments = []) {
  const text = stripInternalInstructions(content);
  const attachments = explicitAttachments.map(file => ({
    name: file.name,
    size: typeof file.size === 'number' ? formatFileSize(file.size) : (file.size_display || file.size || ''),
  }));

  let messageText = text.trim();
  const markers = ['\n\n[attachments]', '\n\n[附件]', '\n\n用户上传了以下附件', '\n\n[web_ui_download_instructions]'];
  const marker = markers
    .map(value => ({ value, index: text.indexOf(value) }))
    .filter(item => item.index >= 0)
    .sort((a, b) => a.index - b.index)[0];

  if (marker) {
    messageText = text.slice(0, marker.index).trim();
    const attachmentText = text.slice(marker.index);
    const newPattern = /^\d+\.\s*(.+)\npath:\s*(.+)\nsize:\s*(.+)$/gmi;
    const oldPattern = /附件\s+\d+:\s*(.+)\n路径：\s*(.+)\n大小：\s*(.+)/g;
    for (const pattern of [newPattern, oldPattern]) {
      let match;
      while ((match = pattern.exec(attachmentText)) !== null) {
        attachments.push({ name: match[1].trim(), size: match[3].trim() });
      }
    }
  }

  return { text: messageText, attachments };
}

function renderMessageContent(message) {
  if (message.role !== 'user') {
    return `<div class="content">${escapeHtml(stripInternalInstructions(message.content || ''))}</div>${renderDownloadLinks(message.downloads || [])}`;
  }

  const parsed = parseAttachmentMessage(message.content, message.attachments || []);
  const pieces = [];
  if (parsed.attachments.length) {
    pieces.push(`
      <div class="message-attachments">
        ${parsed.attachments.map(file => `
          <div class="attachment-chip">
            <span>${escapeHtml(file.name)}</span>
            ${file.size ? `<small>${escapeHtml(file.size)}</small>` : ''}
          </div>
        `).join('')}
      </div>
    `);
  }
  if (parsed.text) {
    pieces.push(`<div class="content">${escapeHtml(parsed.text)}</div>`);
  }
  return pieces.join('') || '<div class="content">[attachment]</div>';
}

function renderAttachments() {
  const box = $('attachmentList');
  if (!state.attachments.length) {
    box.innerHTML = '';
    return;
  }
  box.innerHTML = state.attachments.map((file, index) => `
    <div class="attachment-chip">
      <span>${escapeHtml(file.name)}</span>
      <small>${formatFileSize(file.size)}</small>
      <button type="button" data-index="${index}" aria-label="Delete attachment">delete</button>
    </div>
  `).join('');
  box.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', () => {
      state.attachments.splice(Number(btn.dataset.index), 1);
      renderAttachments();
    });
  });
}

function addAttachments(fileList) {
  const incoming = Array.from(fileList || []);
  const validFiles = incoming.filter(file => {
    if (file.size > MAX_ATTACHMENT_BYTES) {
      alert(`${file.name} is too large. Each attachment can be up to 10 MB.`);
      return false;
    }
    return true;
  });
  const remaining = MAX_ATTACHMENTS - state.attachments.length;
  if (remaining <= 0) {
    alert(`You can attach up to ${MAX_ATTACHMENTS} files.`);
    return;
  }
  if (validFiles.length > remaining) {
    alert(`You can add ${remaining} attachment(s)`);
  }
  state.attachments.push(...validFiles.slice(0, remaining));
  renderAttachments();
}

function renderSessions() {
  const list = $('sessionList');
  if (!state.sessions.length) {
    list.innerHTML = '<div class="empty"><p>No sessions found</p></div>';
    return;
  }
  list.innerHTML = state.sessions.map(s => `
    <article class="session-card ${s.id === state.selectedId ? 'active' : ''}" data-id="${escapeHtml(s.id)}">
      <h3>${escapeHtml(s.title)}</h3>
      <p>${escapeHtml(s.preview || 'No preview')}</p>
      <div class="badges">
        <span class="badge">${escapeHtml(s.last_active || '')}</span>
        <span class="badge">${escapeHtml(s.source || '')}</span>
        <span class="badge">${escapeHtml(s.model || '')}</span>
        <span class="badge">${s.message_count || 0} msgs</span>
      </div>
    </article>
  `).join('');
  document.querySelectorAll('.session-card').forEach(card => {
    card.addEventListener('click', () => loadSession(card.dataset.id));
  });
}

async function loadSessions(options = {}) {
  const q = encodeURIComponent($('searchInput').value.trim());
  const data = await api(`/api/sessions?q=${q}`);
  state.sessions = data.sessions;
  renderSessions();

  if (options.selectFirst && !state.selectedId && state.sessions.length) {
    await loadSession(state.sessions[0].id);
  }
}

async function loadSession(id) {
  state.selectedId = id;
  state.attachments = [];
  renderAttachments();
  renderSessions();
  const data = await api(`/api/sessions/${encodeURIComponent(id)}`);
  state.selected = data.session;
  renderDetail();
}

function scrollMessageContentsToBottom() {
  document.querySelectorAll('#messages .content').forEach(content => {
    if (content.scrollHeight > content.clientHeight) {
      content.scrollTop = content.scrollHeight;
    }
  });
}

function updateChatInputSize() {
  const input = $('chatInput');
  if (!input) return;

  input.classList.remove('two-lines', 'scroll-lines');

  const style = getComputedStyle(input);
  const lineHeight = parseFloat(style.lineHeight) || 22;
  const paddingLeft = parseFloat(style.paddingLeft) || 0;
  const paddingRight = parseFloat(style.paddingRight) || 0;
  const measure = document.createElement('div');
  measure.style.position = 'absolute';
  measure.style.visibility = 'hidden';
  measure.style.pointerEvents = 'none';
  measure.style.zIndex = '-1';
  measure.style.width = `${Math.max(0, input.clientWidth - paddingLeft - paddingRight)}px`;
  measure.style.font = style.font;
  measure.style.lineHeight = style.lineHeight;
  measure.style.whiteSpace = 'pre-wrap';
  measure.style.overflowWrap = 'break-word';
  measure.style.wordBreak = 'break-word';
  measure.textContent = input.value ? input.value.replace(/\n$/u, '\n ') : 'x';
  document.body.appendChild(measure);
  const lineCount = input.value ? Math.max(1, Math.round(measure.scrollHeight / lineHeight)) : 1;
  measure.remove();

  if (lineCount >= 2) {
    input.classList.add('two-lines');
  }
  if (lineCount > 2) {
    input.classList.add('scroll-lines');
  }
}

function renderDetail() {
  const s = state.selected;
  $('emptyState').classList.add('hidden');
  $('detail').classList.remove('hidden');
  $('sessionTitle').textContent = s.title;
  $('sessionMeta').textContent = `${s.id} · ${s.source || ''} · ${s.model || ''} · ${s.started_at || ''}`;
  $('commandBox').textContent = s.resume_command;
  const tokenTotal = Object.values(s.tokens || {}).reduce((a, b) => a + (Number(b) || 0), 0);
  $('stats').innerHTML = `
    <span class="stat">Messages: ${s.message_count || 0}</span>
    <span class="stat">Tool calls: ${s.tool_call_count || 0}</span>
    <span class="stat">Tokens: ${tokenTotal}</span>
    <span class="stat">JSON: ${escapeHtml(s.json_path || '')}</span>
  `;
  const chatMessages = (s.messages || [])
    .filter(m => ['user', 'assistant'].includes(m.role) && (m.content || '').trim())
    .map(m => ({
      ...m,
      label: m.role === 'user' ? 'You' : 'Hermes',
    }));

  $('messages').innerHTML = chatMessages.length ? chatMessages.map(m => `
    <article class="message ${escapeHtml(m.role)}">
      <div class="avatar">${escapeHtml(m.label)}</div>
      <div class="bubble">
        ${renderMessageContent(m)}
      </div>
    </article>
  `).join('') : '<div class="empty inline"><p>No user/assistant messages to display in this session.</p></div>';

  requestAnimationFrame(() => {
    scrollMessageContentsToBottom();
    const main = document.querySelector('.main');
    main.scrollTo({ top: main.scrollHeight, behavior: 'smooth' });
  });
}

async function createNewChat() {
  if (state.sending) return;
  const btn = $('newChatBtn');
  btn.disabled = true;
  btn.textContent = 'Creating...';
  try {
    const data = await api('/api/sessions/new', { method: 'POST', body: '{}' });
    await loadSessions();
    if (data.session && data.session.id) {
      await loadSession(data.session.id);
    }
  } catch (err) {
    alert(err.message || String(err));
  } finally {
    btn.disabled = false;
    btn.textContent = '＋ New Chat';
  }
}

async function sendMessage(event) {
  event.preventDefault();
  if (!state.selected || state.sending) return;
  const input = $('chatInput');
  const message = input.value.trim();
  if (!message && !state.attachments.length) return;

  const filesToSend = [...state.attachments];
  state.sending = true;
  $('sendBtn').disabled = true;
  $('sendBtn').textContent = 'Sending...';
  input.disabled = true;

  const previousMessages = state.selected.messages || [];
  state.selected.messages = [
    ...previousMessages,
    { role: 'user', content: message, attachments: filesToSend, timestamp: '' },
    { role: 'assistant', content: 'Hermes is replying...', timestamp: '' },
  ];
  input.value = '';
  updateChatInputSize();
  state.attachments = [];
  renderAttachments();
  renderDetail();

  try {
    const formData = new FormData();
    formData.append('message', message);
    filesToSend.forEach(file => formData.append('files', file, file.name));
    const data = await api(`/api/sessions/${encodeURIComponent(state.selected.id)}/chat`, {
      method: 'POST',
      body: formData,
    });
    state.selected = data.session;
    renderDetail();
    await loadSessions();
  } catch (err) {
    state.selected.messages = previousMessages;
    state.attachments = filesToSend;
    renderAttachments();
    renderDetail();
    alert(err.message || String(err));
  } finally {
    state.sending = false;
    input.disabled = false;
    $('sendBtn').disabled = false;
    $('sendBtn').textContent = 'Send';
    input.focus();
    updateChatInputSize();
  }
}

async function copyResume() {
  if (!state.selected) return;
  await navigator.clipboard.writeText(state.selected.resume_command);
  $('copyResumeBtn').textContent = 'Copied';
  setTimeout(() => $('copyResumeBtn').textContent = 'Copy Resume Command', 1000);
}

async function renameSession() {
  if (!state.selected) return;
  const title = prompt('Enter a new title:', state.selected.title);
  if (!title || !title.trim()) return;
  const data = await api(`/api/sessions/${encodeURIComponent(state.selected.id)}/rename`, {
    method: 'POST',
    body: JSON.stringify({ title: title.trim() }),
  });
  if (!data.ok) throw new Error(data.output || 'Rename failed');
  await loadSessions();
  await loadSession(state.selected.id);
}

async function deleteSession() {
  if (!state.selected) return;
  if (!confirm(`Delete this session?\n${state.selected.title}\n${state.selected.id}`)) return;
  const id = state.selected.id;
  const data = await api(`/api/sessions/${encodeURIComponent(id)}/delete`, { method: 'POST', body: '{}' });
  if (!data.ok) throw new Error(data.output || 'Delete failed');
  state.selectedId = null;
  state.selected = null;
  $('detail').classList.add('hidden');
  $('emptyState').classList.remove('hidden');
  await loadSessions();
}

let searchTimer;
$('searchInput').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadSessions, 250);
});
$('refreshBtn').addEventListener('click', loadSessions);
$('newChatBtn').addEventListener('click', createNewChat);
$('copyResumeBtn').addEventListener('click', copyResume);
$('renameBtn').addEventListener('click', () => renameSession().catch(alert));
$('deleteBtn').addEventListener('click', () => deleteSession().catch(alert));
$('chatForm').addEventListener('submit', sendMessage);
$('attachBtn').addEventListener('click', () => $('fileInput').click());
$('fileInput').addEventListener('change', event => {
  addAttachments(event.target.files);
  event.target.value = '';
});
$('chatInput').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    $('chatForm').requestSubmit();
  }
});
$('chatInput').addEventListener('input', updateChatInputSize);
updateChatInputSize();

loadSessions({ selectFirst: true }).catch(err => {
  $('sessionList').innerHTML = `<div class="empty"><p>${escapeHtml(err.message)}</p></div>`;
});
