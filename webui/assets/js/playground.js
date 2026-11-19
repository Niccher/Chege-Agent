/* Chege Agent playground — REST + SSE client for /api/v1. */
(function () {
  const state = {
    project: null, session: null, runId: null, es: null, lastSeq: 0,
    providers: [], tools: [], pending: [], toolSeq: 0,
    messages: [], todos: [], settings: null, activity: [],
    reasoning: '', reasoningStarted: false, reasoningFinished: false,
    reasoningSeq: 0, reasoningStartedAt: null, reasoningTimer: null
  };
  const RESUME_KEY = 'chege-run-resume';
  const $ = (id) => document.getElementById(id);
  const esc = (value) => Chege.escapeHtml(value);

  /* ------------------------------------------------------------------ */
  /* Status, chat and phase UI                                           */
  /* ------------------------------------------------------------------ */
  function setStatus(text, kind) {
    const badge = $('run-status');
    if (!badge) return;
    badge.innerHTML = `<span class="status-dot status-${kind || 'warn'}"></span>${esc(text)}`;
  }

  function setPhase(label, active) {
    const phase = $('run-phase');
    if (!phase) return;
    if (!active || !label) { phase.classList.add('d-none'); return; }
    phase.classList.remove('d-none');
    $('run-phase-label').textContent = label;
  }

  function updateReasoningView() {
    const view = $('reasoning-view');
    if (!view) return;
    view.textContent = state.reasoning || 'No reasoning yet.';
    view.scrollTop = view.scrollHeight;
  }

  function stopReasoningTimer() {
    if (state.reasoningTimer) {
      clearInterval(state.reasoningTimer);
      state.reasoningTimer = null;
    }
  }

  function resetReasoning() {
    stopReasoningTimer();
    state.reasoning = '';
    state.reasoningStarted = false;
    state.reasoningFinished = false;
    state.reasoningStartedAt = null;
    updateReasoningView();
  }

  function updateLiveReasoningDuration() {
    const el = $('reasoning-live');
    if (!el || !state.reasoningStartedAt) return;
    const duration = el.querySelector('.reasoning-duration');
    if (duration) duration.textContent = `thinking ${formatDuration(Date.now() - state.reasoningStartedAt)}`;
  }

  function reasoningAccordionId() {
    state.reasoningSeq += 1;
    return 'reasoning-' + state.reasoningSeq;
  }

  function reasoningAccordionMarkup(id, durationMs, expanded, metaLine) {
    const duration = durationMs ? `thinking ${formatDuration(durationMs)}` : 'thinking';
    const collapsedClass = expanded ? 'accordion-button' : 'accordion-button collapsed';
    const showClass = expanded ? ' show' : '';
    return `<div class="accordion reasoning-accordion" id="reasoning-acc-${id}">
      <div class="accordion-item">
        <h2 class="accordion-header" id="reasoning-heading-${id}">
          <button class="${collapsedClass}" type="button" data-bs-toggle="collapse"
                  data-bs-target="#reasoning-collapse-${id}" aria-expanded="${expanded ? 'true' : 'false'}"
                  aria-controls="reasoning-collapse-${id}">
            <i class="fas fa-brain me-2"></i><span class="reasoning-title">Reasoning</span>
            <span class="reasoning-duration">${esc(duration)}</span>
          </button>
        </h2>
        <div id="reasoning-collapse-${id}" class="accordion-collapse collapse${showClass}"
             aria-labelledby="reasoning-heading-${id}" data-bs-parent="#reasoning-acc-${id}">
          <div class="accordion-body">
            <div class="reasoning-content"></div>
            <div class="reasoning-footer">
              <span class="message-meta">${esc(metaLine || '')}</span>
              <button type="button" class="btn btn-xs btn-outline-secondary reasoning-copy">
                <i class="far fa-copy"></i> Copy
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>`;
  }

  function wireReasoningCopy(bubble, getText) {
    const button = bubble.querySelector('.reasoning-copy');
    if (button) button.addEventListener('click', () => copyText(getText() || ''));
  }

  function reasoningBubble() {
    let el = $('reasoning-live');
    if (!el) {
      el = document.createElement('div');
      el.className = 'chat-bubble reasoning-bubble';
      el.id = 'reasoning-live';
      const id = reasoningAccordionId();
      const started = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      el.innerHTML = reasoningAccordionMarkup(id, 0, true, started);
      wireReasoningCopy(el, () => state.reasoning);
      $('chat-scroll').appendChild(el);
    }
    return el;
  }

  function finishReasoning() {
    if (!state.reasoningStartedAt) {
      state.reasoningFinished = true;
      return;
    }
    const elapsed = Date.now() - state.reasoningStartedAt;
    stopReasoningTimer();
    const bubble = $('reasoning-live');
    if (bubble) {
      const duration = bubble.querySelector('.reasoning-duration');
      if (duration) duration.textContent = `thinking ${formatDuration(elapsed)}`;
      const collapseEl = bubble.querySelector('.accordion-collapse');
      if (collapseEl && window.bootstrap) {
        bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false }).hide();
      }
    }
    state.reasoningStartedAt = null;
    state.reasoningFinished = true;
  }

  function appendReasoning(text) {
    if (!text) return;
    state.reasoning += text;
    if (!state.reasoningStartedAt) {
      state.reasoningStartedAt = Date.now();
      state.reasoningTimer = setInterval(updateLiveReasoningDuration, 1000);
    }
    if (!state.reasoningStarted) {
      state.reasoningStarted = true;
      addActivity('thinking.delta', 'Reasoning stream started');
    }
    const bubble = reasoningBubble();
    bubble.querySelector('.reasoning-content').textContent += text;
    bubble.scrollIntoView({ behavior: 'smooth', block: 'end' });
    updateReasoningView();
    updateLiveReasoningDuration();
  }

  function parseDate(value) {
    if (!value) return null;
    const text = String(value);
    const normalized = /[zZ]|[+-]\d\d:?\d\d$/.test(text) ? text : text + 'Z';
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatDuration(ms) {
    if (ms == null || ms === 0) return '';
    if (ms < 1000) return `${ms} ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.round((ms % 60000) / 1000);
    return `${minutes}m ${seconds}s`;
  }

  function formatNumber(value) {
    return Number(value || 0).toLocaleString();
  }

  function parseMetrics(meta) {
    if (!meta) return null;
    let value = meta.metrics_json ?? meta.metrics;
    if (!value) return null;
    if (typeof value === 'string') {
      try { value = JSON.parse(value); } catch (_) { return null; }
    }
    return value && typeof value === 'object' ? value : null;
  }

  function messageTimeLine(meta) {
    const created = parseDate(meta && meta.created_at);
    return created ? created.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
  }

  function messageMetaLine(meta) {
    const bits = [];
    const time = messageTimeLine(meta);
    if (time) bits.push(time);
    const metrics = parseMetrics(meta);
    if (metrics) {
      if (metrics.duration_ms) bits.push(formatDuration(metrics.duration_ms));
      if (metrics.total_tokens) {
        const detail = [];
        if (metrics.prompt_tokens) detail.push(`${formatNumber(metrics.prompt_tokens)} in`);
        if (metrics.completion_tokens) detail.push(`${formatNumber(metrics.completion_tokens)} out`);
        bits.push(`${formatNumber(metrics.total_tokens)} tokens${detail.length ? ` (${detail.join(' / ')})` : ''}`);
        if (metrics.duration_ms && metrics.completion_tokens) {
          const tokensPerSecond = metrics.completion_tokens / (metrics.duration_ms / 1000);
          if (Number.isFinite(tokensPerSecond) && tokensPerSecond > 0) {
            bits.push(`${tokensPerSecond.toFixed(2)} tok/s`);
          }
        }
      }
      if (metrics.model) bits.push(String(metrics.model).split('/').pop());
    }
    return bits.join(' · ');
  }

  async function copyText(text) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement('textarea');
        area.value = text;
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        document.execCommand('copy');
        area.remove();
      }
      Chege.alertBox('Copied to clipboard.', 'success');
    } catch (_) {
      Chege.alertBox('Could not copy to clipboard.', 'danger');
    }
  }

  function resendPrompt(text) {
    if (!state.session) { Chege.alertBox('Create or select a thread first.', 'warning'); return; }
    if (state.es) { Chege.alertBox('A run is already active. Wait or cancel it before resending.', 'warning'); return; }
    $('prompt-input').value = text || '';
    $('prompt-input').focus();
    sendPrompt();
  }

  function addMessageActions(footer, role, content, getContent) {
    const actions = document.createElement('div');
    actions.className = 'message-actions';
    const copy = document.createElement('button');
    copy.type = 'button';
    copy.className = 'btn btn-xs btn-outline-secondary';
    copy.innerHTML = '<i class="far fa-copy"></i> Copy';
    copy.addEventListener('click', () => copyText(getContent ? getContent() : (content || '')));
    actions.appendChild(copy);
    if (role === 'user') {
      const resend = document.createElement('button');
      resend.type = 'button';
      resend.className = 'btn btn-xs btn-outline-primary';
      resend.innerHTML = '<i class="fas fa-rotate-right"></i> Resend';
      resend.addEventListener('click', () => resendPrompt(content || ''));
      actions.appendChild(resend);
    }
    footer.appendChild(actions);
  }

  function pushMessage(role, content, thinking, meta) {
    const scroll = $('chat-scroll');
    const roleLabel = role === 'user' ? 'You' : role === 'tool' ? 'Tool' : 'Agent';
    if (thinking) {
      const reasoning = document.createElement('div');
      reasoning.className = 'chat-bubble reasoning-bubble';
      const metrics = parseMetrics(meta);
      const id = reasoningAccordionId();
      reasoning.innerHTML = reasoningAccordionMarkup(
        id,
        metrics && metrics.thinking_ms ? metrics.thinking_ms : 0,
        false,
        messageTimeLine(meta),
      );
      reasoning.querySelector('.reasoning-content').textContent = thinking;
      wireReasoningCopy(reasoning, () => thinking);
      scroll.appendChild(reasoning);
      state.reasoning = thinking;
      updateReasoningView();
    }
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble ' + (role === 'user' ? 'user' : '');
    const metaLine = messageMetaLine(meta);
    bubble.innerHTML = `<div class="message-head"><span class="role">${esc(roleLabel)}</span></div>
      <div class="message-body">${Chege.markdown(content || '')}</div>`;
    const footer = document.createElement('div');
    footer.className = 'message-footer';
    const metaEl = document.createElement('span');
    metaEl.className = 'message-meta';
    metaEl.textContent = metaLine;
    footer.appendChild(metaEl);
    addMessageActions(footer, role, content);
    bubble.appendChild(footer);
    scroll.appendChild(bubble);
    scroll.scrollTop = scroll.scrollHeight;
    return bubble;
  }

  function liveBubble() {
    let el = $('assistant-live');
    if (!el) {
      el = document.createElement('div');
      el.className = 'chat-bubble';
      el.id = 'assistant-live';
      const started = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      el.innerHTML = `<div class="message-head"><span class="role">Agent</span></div>
        <div class="message-body"></div>
        <div class="message-footer">
          <span class="message-meta">${esc(started)} · streaming</span>
          <div class="message-actions">
            <button type="button" class="btn btn-xs btn-outline-secondary" id="assistant-live-copy">
              <i class="far fa-copy"></i> Copy
            </button>
          </div>
        </div>
        <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>`;
      el.querySelector('#assistant-live-copy').addEventListener('click', () => {
        copyText(el.querySelector('.message-body').dataset.raw || el.querySelector('.message-body').textContent || '');
      });
      $('chat-scroll').appendChild(el);
    }
    return el;
  }

  function addToolCard(name, args) {
    const id = 'tool-card-' + (++state.toolSeq);
    const card = document.createElement('div');
    card.className = 'tool-card';
    card.id = id;
    card.dataset.tool = name;
    card.innerHTML = `<div><span class="tool-name"><i class="fas fa-wrench"></i> ${esc(name)}</span>
      <span class="text-muted ml-2 small">${esc(JSON.stringify(args || {}).slice(0, 120))}</span></div>
      <div class="tool-result">Running…</div>`;
    const bubble = liveBubble();
    const footer = bubble.querySelector('.message-footer');
    if (footer) bubble.insertBefore(card, footer);
    else bubble.appendChild(card);
    bubble.scrollIntoView({ behavior: 'smooth', block: 'end' });
    return card;
  }

  /* ------------------------------------------------------------------ */
  /* Activity tab                                                        */
  /* ------------------------------------------------------------------ */
  const ACTIVITY_META = {
    'run.phase': { icon: 'fa-arrows-rotate', cls: 'phase', label: 'Phase' },
    'run.started': { icon: 'fa-play', cls: 'start', label: 'Started' },
    'run.completed': { icon: 'fa-check', cls: 'ok', label: 'Completed' },
    'run.failed': { icon: 'fa-xmark', cls: 'bad', label: 'Failed' },
    'run.cancelled': { icon: 'fa-stop', cls: 'warn', label: 'Cancelled' },
    'tool.started': { icon: 'fa-wrench', cls: 'tool', label: 'Tool' },
    'tool.completed': { icon: 'fa-check', cls: 'tool', label: 'Tool done' },
    'tool.approval_required': { icon: 'fa-triangle-exclamation', cls: 'warn', label: 'Approval' },
    'tool.ask_user': { icon: 'fa-circle-question', cls: 'ask', label: 'Question' },
    'todo.updated': { icon: 'fa-list-check', cls: 'todo', label: 'Plan' },
    'message.delta': { icon: 'fa-message', cls: 'msg', label: 'Reply' },
    'thinking.delta': { icon: 'fa-brain', cls: 'msg', label: 'Thinking' },
  };

  function addActivity(type, text, detail) {
    state.activity.push({ type, text, detail, at: new Date() });
    const list = $('activity-list');
    if (!list) return;
    const placeholder = list.querySelector('.text-muted');
    if (placeholder && state.activity.length === 1) list.innerHTML = '';
    const meta = ACTIVITY_META[type] || { icon: 'fa-circle', cls: 'other', label: type };
    const item = document.createElement('div');
    item.className = 'activity-item activity-' + meta.cls;
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    item.innerHTML = `<span class="activity-time">${esc(time)}</span>
      <i class="fas ${meta.icon} activity-icon"></i>
      <span class="activity-label">${esc(meta.label)}</span>
      <span class="activity-text">${esc(text || '')}</span>`;
    if (detail) {
      const pre = document.createElement('pre');
      pre.className = 'activity-detail';
      pre.textContent = typeof detail === 'string' ? detail : JSON.stringify(detail, null, 2);
      item.appendChild(pre);
    }
    list.prepend(item);
    while (list.children.length > 200) list.removeChild(list.lastChild);
  }

  function clearActivity() {
    state.activity = [];
    const list = $('activity-list');
    if (list) list.innerHTML = '<span class="small text-muted">Run activity will appear here.</span>';
  }

  /* ------------------------------------------------------------------ */
  /* Todos + project context                                             */
  /* ------------------------------------------------------------------ */
  function renderTodos(todos) {
    state.todos = todos || [];
    const host = $('todo-list');
    if (!host) return;
    if (!state.todos.length) { host.innerHTML = '<span class="small text-muted">No tasks yet.</span>'; return; }
    const icons = { completed: 'fa-circle-check done', in_progress: 'fa-circle-dot active', pending: 'fa-circle' };
    host.innerHTML = state.todos.map((t) => `
      <div class="todo-item">
        <i class="fas ${icons[t.status] || 'fa-circle'}"></i>
        <span class="todo-title${t.status === 'completed' ? ' done' : ''}">${esc(t.title || t.id || '')}</span>
        <span class="badge bg-secondary">${esc(t.status || 'pending')}</span>
      </div>`).join('');
  }

  async function loadContext() {
    if (!state.project) return;
    try {
      const proj = await Chege.api('/projects/' + encodeURIComponent(state.project));
      const p = proj.project || {};
      const base = state.settings && (state.settings.projects_dir || state.settings.workdir);
      const workspace = base ? `${String(base).replace(/\/+$/, '')}/${esc(p.slug || state.project)}` : esc(state.project);
      const host = $('project-context');
      host.innerHTML = `
        <div class="context-heading"><i class="fas fa-folder-open"></i> ${esc(p.name || state.project)}</div>
        <div class="context-row"><span class="context-key">Goal</span><span class="context-val">${esc(p.brain_goal || '—')}</span></div>
        <div class="context-row"><span class="context-key">Stack</span><span class="context-val">${esc(p.brain_stack || '—')}</span></div>
        <div class="context-row"><span class="context-key">Notes</span><span class="context-val">${esc(p.brain_notes || '—')}</span></div>
        <div class="context-row"><span class="context-key">Workspace</span><span class="context-val"><code>${workspace}</code></span></div>
        <div class="context-row"><span class="context-key">Todos</span><span class="context-val" id="context-todo-count">${state.todos.length} task(s)</span></div>`;
    } catch (e) {
      $('project-context').innerHTML = '<p class="small text-danger">Could not load project context: ' + esc(e.message) + '</p>';
    }
  }

  /* ------------------------------------------------------------------ */
  /* Tree-style file browser                                             */
  /* ------------------------------------------------------------------ */
  function treeNode(node, isLast) {
    const branch = isLast ? '└─' : '├─';
    const isDir = node.type === 'directory';
    const icon = isDir ? 'fa-folder' : node.type === 'symlink' ? 'fa-link' : 'fa-file-code';
    let html = `<li class="tree-node"><span class="tree-branch">${branch}</span>`;
    if (isDir) {
      html += `<span class="tree-label tree-dir" data-path="${esc(node.path)}"><i class="fas ${icon}"></i> ${esc(node.name)}</span>`;
      const kids = node.children || [];
      if (kids.length) {
        html += '<ul class="tree-children">' + kids.map((c, i) => treeNode(c, i === kids.length - 1)).join('') + '</ul>';
      }
    } else {
      html += `<span class="tree-label tree-file" data-path="${esc(node.path)}" data-type="${esc(node.type)}"><i class="fas ${icon}"></i> ${esc(node.name)}</span>`;
    }
    html += '</li>';
    return html;
  }

  async function loadFiles() {
    if (!state.project) return;
    try {
      const data = await Chege.api(`/files/tree?project_slug=${encodeURIComponent(state.project)}&max_depth=12&max_nodes=1000`);
      const nodes = data.nodes || [];
      $('file-tree').innerHTML = nodes.length
        ? `<div class="tree-root">${esc(state.project)}/</div><ul class="tree-root-list">${nodes.map((n, i) => treeNode(n, i === nodes.length - 1)).join('')}</ul>`
        : '<span class="text-muted small">Workspace is empty</span>';
      const trunc = $('tree-truncated');
      if (data.truncated) {
        trunc.classList.remove('d-none');
        trunc.textContent = `Showing first ${data.node_count} entries — tree was truncated.`;
      } else {
        trunc.classList.add('d-none');
      }
      $('file-tree').querySelectorAll('.tree-file').forEach((item) => {
        item.addEventListener('click', () => loadFile(item.dataset.path));
      });
    } catch (e) {
      $('file-tree').innerHTML = '<span class="small text-danger">Could not load tree: ' + esc(e.message) + '</span>';
    }
  }

  async function loadFile(path) {
    try {
      const data = await Chege.api(`/files/content?project_slug=${encodeURIComponent(state.project)}&filepath=${encodeURIComponent(path)}`);
      $('code-view').textContent = data.content || '';
      $('code-path').textContent = path;
      Chege.highlight($('code-view'));
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  async function loadDiff() {
    if (!state.project) return;
    try {
      const data = await Chege.api(`/files/diff?project_slug=${encodeURIComponent(state.project)}`);
      $('diff-view').textContent = data.diff || 'No uncommitted changes.';
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  /* ------------------------------------------------------------------ */
  /* Approvals + ask-user                                                */
  /* ------------------------------------------------------------------ */
  function renderApprovals(pending) {
    state.pending = pending || [];
    const zone = $('approval-zone');
    zone.innerHTML = '';
    if (!state.pending.length) { zone.classList.add('d-none'); return; }
    zone.classList.remove('d-none');
    state.pending.forEach((item) => {
      const card = document.createElement('div');
      card.className = 'approval-card';
      card.dataset.id = item.id;
      card.innerHTML = `
        <div class="font-weight-bold mb-1"><i class="fas fa-triangle-exclamation"></i>
          Approval required: ${esc(item.tool_name || item.tool || 'tool')}</div>
        <div class="small text-muted mb-2">Reason: ${esc(item.reason || 'high-risk action')}</div>
        <textarea class="form-control mb-2" spellcheck="false">${esc(JSON.stringify(item.arguments || {}, null, 2))}</textarea>
        <button class="btn btn-sm btn-success approve">Approve</button>
        <button class="btn btn-sm btn-outline-danger reject">Reject</button>`;
      card.querySelector('.approve').addEventListener('click', () => submitDecision(card, 'approve'));
      card.querySelector('.reject').addEventListener('click', () => submitDecision(card, 'reject'));
      zone.appendChild(card);
    });
  }

  function renderAskUser(data) {
    const zone = $('ask-zone');
    if (!zone) return;
    zone.classList.remove('d-none');
    const card = document.createElement('div');
    card.className = 'approval-card ask-card';
    card.innerHTML = `<div class="font-weight-bold mb-1"><i class="fas fa-circle-question"></i> Agent question</div>
      <div class="mb-2">${esc(data.question || '')}</div>
      <div class="ask-options"></div>
      <input class="form-control form-control-sm ask-custom mt-2" placeholder="Or type your answer…">`;
    const options = card.querySelector('.ask-options');
    (data.options || []).forEach((opt) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-sm btn-outline-primary me-1 mb-1';
      btn.textContent = opt;
      btn.addEventListener('click', () => answerQuestion(opt));
      options.appendChild(btn);
    });
    card.querySelector('.ask-custom').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); answerQuestion(e.target.value); }
    });
    zone.innerHTML = '';
    zone.appendChild(card);
  }

  function answerQuestion(answer) {
    if (!answer) return;
    $('ask-zone').classList.add('d-none');
    $('prompt-input').value = answer;
    $('prompt-input').focus();
    Chege.alertBox('Answer copied to the composer — press Send (or Ctrl/⌘+Enter) to reply.', 'info');
  }

  async function submitDecision(card, action) {
    if (!state.runId) return;
    let args = {};
    try { args = JSON.parse(card.querySelector('textarea').value || '{}'); }
    catch (e) { Chege.alertBox('Arguments are not valid JSON', 'warning'); return; }
    const payload = {
      approvals: [{ id: card.dataset.id, action: action, arguments: args }],
      model: $('model-select').value || 'qwen2.5-coder:latest'
    };
    try {
      await Chege.api(`/runs/${state.runId}/approvals`, { method: 'POST', body: payload });
      card.remove();
      setStatus('Running', 'warn');
      setPhase('Resuming after approval', true);
      openStream(state.lastSeq);
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  /* ------------------------------------------------------------------ */
  /* SSE stream                                                          */
  /* ------------------------------------------------------------------ */
  function saveResume() {
    if (!state.runId) return;
    try {
      sessionStorage.setItem(RESUME_KEY, JSON.stringify({
        runId: state.runId, lastSeq: state.lastSeq,
        sessionId: state.session, projectSlug: state.project
      }));
    } catch (_) {}
  }

  function clearResume() {
    try { sessionStorage.removeItem(RESUME_KEY); } catch (_) {}
  }

  function closeStream() {
    if (state.es) { state.es.close(); state.es = null; }
  }

  function openStream(after) {
    if (!state.runId) return;
    closeStream();
    const es = new EventSource(`${Chege.API}/runs/${state.runId}/events?after=${after || 0}`);
    state.es = es;
    const handlers = {
      'run.started': (d) => { setStatus('Running', 'warn'); addActivity('run.started', d.model || ''); },
      'run.phase': (d) => {
        const label = d.label || d.phase || 'Working…';
        setPhase(label, true);
        addActivity('run.phase', label, d.step ? `Step ${d.step} of ${d.max_steps}` : null);
      },
      'message.delta': (d) => {
        if (state.reasoningStartedAt) finishReasoning();
        const bubble = liveBubble();
        const body = bubble.querySelector('.message-body');
        body.dataset.raw = (body.dataset.raw || '') + (d.content || '');
        body.innerHTML = Chege.markdown(body.dataset.raw);
        bubble.querySelectorAll('.typing-dot').forEach((n) => n.remove());
        bubble.scrollIntoView({ behavior: 'smooth', block: 'end' });
      },
      'thinking.delta': (d) => appendReasoning(d.thinking || ''),
      'tool.started': (d) => {
        if (state.reasoningStartedAt) finishReasoning();
        addToolCard(d.tool, d.arguments);
        addActivity('tool.started', d.tool || '', d.arguments);
      },
      'tool.completed': (d) => {
        const cards = document.querySelectorAll('.tool-card[data-tool="' + CSS.escape(d.tool || '') + '"]');
        const card = cards[cards.length - 1];
        if (card) card.querySelector('.tool-result').textContent = d.result || '(no output)';
        addActivity('tool.completed', d.tool || '', d.result);
      },
      'tool.approval_required': (d) => { renderApprovals(d.pending); addActivity('tool.approval_required', (d.pending || []).map((p) => p.tool_name || p.tool).join(', ')); },
      'tool.ask_user': (d) => { renderAskUser(d); addActivity('tool.ask_user', d.question || ''); },
      'todo.updated': (d) => { renderTodos(d.todos || []); addActivity('todo.updated', `${(d.todos || []).length} task(s)`, (d.todos || []).map((t) => `${t.status}: ${t.title}`).join('\n')); loadContext(); },
      'run.completed': () => finishRun('Completed', 'ok'),
      'run.failed': (d) => { finishRun('Failed', 'bad'); addActivity('run.failed', d.error || 'Run failed'); Chege.alertBox(d.error || 'Run failed', 'danger'); },
      'run.cancelled': () => finishRun('Cancelled', 'warn')
    };
    Object.keys(handlers).forEach((type) => {
      es.addEventListener(type, (event) => {
        if (event.lastEventId) {
          state.lastSeq = Number(event.lastEventId);
          saveResume();
        }
        let data = {};
        try { data = JSON.parse(event.data || '{}'); } catch (_) {}
        handlers[type](data);
      });
    });
    es.onerror = () => setStatus('Stream interrupted — reconnecting…', 'warn');
  }

  function finishRun(label, kind) {
    finishReasoning();
    closeStream();
    clearResume();
    const live = $('assistant-live');
    if (live) live.removeAttribute('id');
    const reasoning = $('reasoning-live');
    if (reasoning) reasoning.removeAttribute('id');
    renderApprovals([]);
    setPhase('', false);
    setStatus(label, kind);
    addActivity(label === 'Completed' ? 'run.completed' : label === 'Failed' ? 'run.failed' : 'run.cancelled', label);
    refreshSideEffects();
  }

  function refreshSideEffects() {
    loadFiles();
    loadDiff();
    if (state.session) loadSession(state.session);
  }

  async function tryResume() {
    let saved = null;
    try { saved = JSON.parse(sessionStorage.getItem(RESUME_KEY) || 'null'); } catch (_) {}
    if (!saved || !saved.runId) return false;
    try {
      const info = await Chege.api('/runs/' + encodeURIComponent(saved.runId));
      const status = info.run && info.run.status;
      if (status !== 'running' && status !== 'awaiting_approval') { clearResume(); return false; }
      // Restore the project/thread if needed.
      if (saved.projectSlug && $('project-select').querySelector(`option[value="${CSS.escape(saved.projectSlug)}"]`)) {
        await selectProject(saved.projectSlug);
      }
      if (saved.sessionId && $('session-select').querySelector(`option[value="${CSS.escape(saved.sessionId)}"]`)) {
        await loadSession(saved.sessionId);
      }
      state.runId = saved.runId;
      state.lastSeq = saved.lastSeq || 0;
      setStatus(status === 'awaiting_approval' ? 'Awaiting approval' : 'Running (resumed)', 'warn');
      setPhase('Reconnecting to live run…', true);
      openStream(state.lastSeq);
      return true;
    } catch (_) { clearResume(); return false; }
  }

  /* ------------------------------------------------------------------ */
  /* Projects, sessions and modals                                       */
  /* ------------------------------------------------------------------ */
  async function loadProjects() {
    try {
      const data = await Chege.api('/projects');
      state.projects = data.projects || [];
      const select = $('project-select');
      select.innerHTML = state.projects.length
        ? state.projects.map((p) => `<option value="${esc(p.slug)}">${esc(p.name)}</option>`).join('')
        : '<option value="">No projects yet</option>';
      if (state.projects.length) {
        await selectProject($('project-select').value || state.projects[0].slug);
      } else {
        $('chat-scroll').innerHTML = '<div class="empty-state"><i class="fas fa-folder-open fa-3x mb-3"></i><p>Create a project to begin.</p></div>';
      }
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  async function selectProject(slug) {
    state.project = slug;
    try {
      const data = await Chege.api(`/sessions/by-project/${encodeURIComponent(slug)}`);
      state.sessions = data.sessions || [];
      const select = $('session-select');
      select.innerHTML = state.sessions.map((s) => `<option value="${esc(s.id)}">${esc(s.title)}</option>`).join('');
      if (state.sessions.length) await loadSession($('session-select').value || state.sessions[0].id);
      else { state.session = null; renderTodos([]); $('project-context').innerHTML = '<p class="small text-muted">No threads yet — create one to start chatting.</p>'; }
      loadFiles(); loadDiff();
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  async function loadSession(id) {
    state.session = id;
    try {
      const data = await Chege.api(`/sessions/${encodeURIComponent(id)}`);
      state.messages = data.messages || [];
      $('session-title').textContent = data.session.title || 'Thread';
      const scroll = $('chat-scroll');
      scroll.innerHTML = '';
      resetReasoning();
      state.messages.forEach((m) => pushMessage(m.role, m.content, m.thinking, m));
      if (!state.messages.length) {
        scroll.innerHTML = '<div class="empty-state"><i class="fas fa-comments fa-3x mb-3"></i><p>Send a prompt to start the agent.</p></div>';
      }
      renderTodos(data.todos || []);
      loadContext();
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  function openProjectModal() {
    $('new-project-name').value = '';
    $('new-project-goal').value = '';
    $('new-project-stack').value = '';
    $('new-project-notes').value = '';
    $('project-modal-error').classList.add('d-none');
    new bootstrap.Modal($('project-modal')).show();
    $('new-project-name').focus();
  }

  async function createProject() {
    const name = $('new-project-name').value.trim();
    const error = $('project-modal-error');
    if (!name) {
      error.textContent = 'Enter a project name.';
      error.classList.remove('d-none');
      return;
    }
    try {
      const data = await Chege.api('/projects', {
        method: 'POST',
        body: {
          name: name,
          goal: $('new-project-goal').value.trim(),
          stack: $('new-project-stack').value.trim(),
          notes: $('new-project-notes').value.trim(),
        }
      });
      bootstrap.Modal.getInstance($('project-modal')).hide();
      await loadProjects();
      $('project-select').value = data.project.slug;
      await selectProject(data.project.slug);
    } catch (e) {
      const msg = /already exists/i.test(e.message)
        ? `A project with that name already exists (${e.message}). Choose a different name.`
        : e.message;
      error.textContent = msg;
      error.classList.remove('d-none');
    }
  }

  function openSessionModal() {
    if (!state.project) { Chege.alertBox('Create a project first', 'warning'); return; }
    $('new-session-title').value = '';
    new bootstrap.Modal($('session-modal')).show();
  }

  async function createSession() {
    if (!state.project) return;
    try {
      const data = await Chege.api('/sessions', {
        method: 'POST', body: { project_slug: state.project, title: $('new-session-title').value.trim() || 'New Thread' }
      });
      bootstrap.Modal.getInstance($('session-modal')).hide();
      await selectProject(state.project);
      $('session-select').value = data.session.id;
      await loadSession(data.session.id);
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  function openForkModal() {
    if (!state.session) { Chege.alertBox('Select a thread to fork', 'warning'); return; }
    $('fork-title').value = '';
    $('fork-up-to').innerHTML = '<option value="">All messages</option>' +
      state.messages.map((m) => `<option value="${esc(m.id)}">${esc((m.content || m.role).slice(0, 60))}</option>`).join('');
    new bootstrap.Modal($('fork-modal')).show();
  }

  async function forkSession() {
    if (!state.session) return;
    try {
      const data = await Chege.api(`/sessions/${encodeURIComponent(state.session)}/fork`, {
        method: 'POST',
        body: { new_title: $('fork-title').value.trim() || 'Forked Thread', up_to_message_id: $('fork-up-to').value || null }
      });
      bootstrap.Modal.getInstance($('fork-modal')).hide();
      await selectProject(state.project);
      $('session-select').value = data.forked_session.id;
      await loadSession(data.forked_session.id);
      Chege.alertBox(`Forked thread (${data.messages_copied} messages copied).`, 'success');
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  async function sendPrompt() {
    if (!state.session) { Chege.alertBox('Create a project and thread first', 'warning'); return; }
    if (state.es) { Chege.alertBox('A run is already active. Wait for it to finish or cancel it first.', 'warning'); return; }
    const input = $('prompt-input');
    const prompt = input.value.trim();
    if (!prompt) return;
    input.value = '';
    $('chat-scroll').querySelector('.empty-state')?.remove();
    resetReasoning();
    pushMessage('user', prompt, null, { created_at: new Date().toISOString() });
    setStatus('Starting run…', 'warn');
    setPhase('Starting run…', true);
    try {
      const data = await Chege.api('/runs', {
        method: 'POST',
        body: {
          session_id: state.session,
          prompt: prompt,
          model: $('model-select').value || 'qwen2.5-coder:latest',
          provider: $('provider-select').value || null,
          policy_mode: $('policy-select').value,
        }
      });
      state.runId = data.run_id;
      state.lastSeq = 0;
      saveResume();
      clearActivity();
      openStream(0);
    } catch (e) { Chege.alertBox(e.message, 'danger'); setStatus('Failed to start', 'bad'); setPhase('', false); }
  }

  async function loadProviders() {
    try {
      const data = await Chege.api('/providers');
      state.providers = data.providers || [];
      $('provider-select').innerHTML = '<option value="">Default (' + esc(data.active_provider || '') + ')</option>'
        + state.providers.map((p) => `<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('');
      $('provider-health').textContent = state.providers.map((p) => `${p.name}: ${p.status || 'unknown'}`).join(' · ');
      await loadModelsForProvider();
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  async function loadModelsForProvider() {
    const select = $('model-select');
    if (!select) return;
    const previous = select.value;
    try {
      const data = await Chege.api('/models/overview');
      const provider = $('provider-select').value || data.active_provider || 'llama_cpp';
      const selected = (data.selected || {})[provider];
      let names = [];
      if (provider === 'ollama') {
        names = (data.ollama?.models || []).map((m) => m.name);
      } else if (provider === 'llama_cpp') {
        names = (data.llamacpp?.models || []).map((m) => m.path || m.name);
      } else {
        names = ['gpt-4o-mini'];
      }
      if (selected && !names.includes(selected)) names.unshift(selected);
      if (!names.length) names = [previous || 'qwen2.5-coder:latest'];
      select.innerHTML = names.map((name) =>
        `<option value="${esc(name)}">${esc(name.split('/').pop())}</option>`).join('');
      if (selected && names.includes(selected)) select.value = selected;
      else if (names.includes(previous)) select.value = previous;
    } catch (_) {}
  }

  async function loadTools() {
    try {
      const data = await Chege.api('/tools');
      state.tools = data.tools || [];
      $('tool-list').innerHTML = state.tools.map((t) =>
        `<div class="d-flex justify-content-between border-bottom py-1 small">
          <span>${esc(t.name)}${t.enabled ? '' : ' <span class="badge bg-secondary">off</span>'}</span>
          <span class="badge bg-secondary">${esc(t.risk)}</span></div>`).join('');
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  async function commit() {
    if (!state.project) return;
    try {
      const data = await Chege.api('/files/commit', {
        method: 'POST', body: { project_slug: state.project, message: $('commit-message').value || 'Agent update' }
      });
      $('commit-message').value = '';
      Chege.alertBox((data.output || 'Committed').slice(0, 200), 'success');
      loadDiff();
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  function confirmDialog({ title, message, confirmText, inputLabel, requireText }) {
    return new Promise((resolve) => {
      const modalEl = $('confirm-modal');
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      $('confirm-modal-label').textContent = title || 'Confirm';
      $('confirm-message').textContent = message || '';
      $('confirm-ok').textContent = confirmText || 'Delete';
      $('confirm-input-wrap').classList.toggle('d-none', !requireText);
      $('confirm-input-label').textContent = inputLabel || 'Type to confirm';
      $('confirm-input').value = '';
      $('confirm-error').classList.add('d-none');

      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        modal.hide();
        resolve(value);
      };
      const ok = () => {
        if (requireText && $('confirm-input').value !== requireText) {
          $('confirm-error').classList.remove('d-none');
          $('confirm-input').focus();
          return;
        }
        finish(true);
      };
      const cancel = () => finish(false);
      const onHidden = () => {
        if (!settled) { settled = true; resolve(false); }
      };

      $('confirm-ok').onclick = ok;
      $('confirm-cancel').onclick = cancel;
      modalEl.addEventListener('hidden.bs.modal', onHidden, { once: true });
      modal.show();
      if (requireText) {
        setTimeout(() => $('confirm-input').focus(), 180);
      }
    });
  }

  async function deleteThread() {
    if (!state.session) { Chege.alertBox('Select a thread first.', 'warning'); return; }
    const title = $('session-title').textContent || state.session;
    const confirmed = await confirmDialog({
      title: 'Delete thread',
      message: `Delete thread "${title}"?\n\nThis removes its messages and runs. The project workspace is kept. This cannot be undone.`,
      confirmText: 'Delete thread',
    });
    if (!confirmed) return;
    try {
      await Chege.api(`/sessions/${encodeURIComponent(state.session)}?confirm=${encodeURIComponent(state.session)}`, { method: 'DELETE' });
      Chege.alertBox('Thread deleted.', 'success');
      await selectProject(state.project);
      if (!state.sessions || !state.sessions.length) {
        $('session-title').textContent = 'Thread';
        $('chat-scroll').innerHTML = '<div class="empty-state"><i class="fas fa-comments fa-3x mb-3"></i><p>Create a thread to start chatting.</p></div>';
      }
    } catch (e) { Chege.alertBox('Could not delete thread: ' + e.message, 'danger'); }
  }

  async function deleteProject() {
    if (!state.project) { Chege.alertBox('Select a project first.', 'warning'); return; }
    const confirmed = await confirmDialog({
      title: 'Delete project',
      message: `This permanently deletes project "${state.project}", all its threads, runs and the workspace directory.\n\nThis cannot be undone.`,
      confirmText: 'Delete project',
      inputLabel: 'Type the exact project slug to confirm',
      requireText: state.project,
    });
    if (!confirmed) return;
    try {
      await Chege.api(`/projects/${encodeURIComponent(state.project)}?confirm=${encodeURIComponent(state.project)}`, { method: 'DELETE' });
      Chege.alertBox('Project deleted.', 'success');
      state.project = null;
      state.session = null;
      state.runId = null;
      closeStream();
      clearResume();
      clearActivity();
      resetReasoning();
      await loadProjects();
    } catch (e) { Chege.alertBox('Could not delete project: ' + e.message, 'danger'); }
  }

  function bind() {
    $('project-select').addEventListener('change', (e) => selectProject(e.target.value));
    $('session-select').addEventListener('change', (e) => loadSession(e.target.value));
    $('new-project-btn').addEventListener('click', openProjectModal);
    $('create-project-confirm').addEventListener('click', createProject);
    $('new-session-btn').addEventListener('click', openSessionModal);
    $('create-session-confirm').addEventListener('click', createSession);
    $('fork-session-btn').addEventListener('click', openForkModal);
    $('fork-confirm').addEventListener('click', forkSession);
    $('provider-select').addEventListener('change', loadModelsForProvider);
    $('send-btn').addEventListener('click', sendPrompt);
    $('prompt-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendPrompt(); }
    });
    $('cancel-btn').addEventListener('click', async () => {
      if (!state.runId) return;
      try { await Chege.api(`/runs/${state.runId}/cancel`, { method: 'POST' }); finishRun('Cancelled', 'warn'); }
      catch (e) { Chege.alertBox(e.message, 'danger'); }
    });
    $('revert-btn').addEventListener('click', async () => {
      if (!state.runId) return;
      try {
        const d = await Chege.api(`/runs/${state.runId}/revert`, { method: 'POST' });
        Chege.alertBox('Workspace reverted to ' + d.git_ref.slice(0, 8), 'success');
        refreshSideEffects();
      } catch (e) { Chege.alertBox(e.message, 'warning'); }
    });
    $('commit-btn').addEventListener('click', commit);
    $('delete-thread-btn').addEventListener('click', deleteThread);
    $('delete-project-btn').addEventListener('click', deleteProject);
    $('refresh-files').addEventListener('click', () => { loadFiles(); loadDiff(); });
    $('refresh-context').addEventListener('click', () => { loadContext(); if (state.session) loadSession(state.session); });
    $('clear-activity').addEventListener('click', clearActivity);
    $('clear-reasoning').addEventListener('click', resetReasoning);
  }

  document.addEventListener('DOMContentLoaded', async () => {
    Chege.shell('/app');
    bind();
    try { state.settings = await Chege.api('/settings'); } catch (_) {}
    await loadProviders();
    loadTools();
    await loadProjects();
    await tryResume();
  });
})();
