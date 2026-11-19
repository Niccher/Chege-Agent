/* Chege Agent playground — REST + SSE client for /api/v1. */
(function () {
  const state = {
    project: null, session: null, runId: null, es: null, lastSeq: 0,
    providers: [], tools: [], pending: [], toolSeq: 0
  };
  const $ = (id) => document.getElementById(id);

  function setStatus(text, kind) {
    const badge = $('run-status');
    if (!badge) return;
    badge.innerHTML = `<span class="status-dot status-${kind || 'warn'}"></span>${Chege.escapeHtml(text)}`;
  }

  function pushMessage(role, content, thinking) {
    const scroll = $('chat-scroll');
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble ' + (role === 'user' ? 'user' : '');
    bubble.innerHTML = `<div class="role">${role === 'user' ? 'You' : 'Agent'}</div>
      <div class="message-body">${Chege.markdown(content || '')}</div>`;
    if (thinking) {
      const t = document.createElement('div');
      t.className = 'thinking';
      t.textContent = thinking;
      bubble.prepend(t);
    }
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
      el.innerHTML = '<div class="role">Agent</div><div class="message-body"></div><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
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
    card.innerHTML = `<div><span class="tool-name"><i class="fas fa-wrench"></i> ${Chege.escapeHtml(name)}</span>
      <span class="text-muted ml-2 small">${Chege.escapeHtml(JSON.stringify(args || {}).slice(0, 120))}</span></div>
      <div class="tool-result">Running…</div>`;
    const bubble = liveBubble();
    bubble.appendChild(card);
    bubble.scrollIntoView({ behavior: 'smooth', block: 'end' });
    return card;
  }

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
          Approval required: ${Chege.escapeHtml(item.tool_name || item.tool || 'tool')}</div>
        <div class="small text-muted mb-2">Reason: ${Chege.escapeHtml(item.reason || 'high-risk action')}</div>
        <textarea class="form-control mb-2" spellcheck="false">${Chege.escapeHtml(JSON.stringify(item.arguments || {}, null, 2))}</textarea>
        <button class="btn btn-sm btn-success approve">Approve</button>
        <button class="btn btn-sm btn-outline-danger reject">Reject</button>`;
      card.querySelector('.approve').addEventListener('click', () => submitDecision(card, 'approve'));
      card.querySelector('.reject').addEventListener('click', () => submitDecision(card, 'reject'));
      zone.appendChild(card);
    });
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
      // The run may have closed its stream while paused; resume catchup.
      openStream(state.lastSeq);
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
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
      'run.started': (d) => setStatus('Running', 'warn'),
      'message.delta': (d) => {
        const bubble = liveBubble();
        const body = bubble.querySelector('.message-body');
        body.innerHTML = Chege.markdown((body.dataset.raw || '') + (d.content || ''));
        body.dataset.raw = (body.dataset.raw || '') + (d.content || '');
        bubble.querySelectorAll('.typing-dot').forEach((n) => n.remove());
        bubble.scrollIntoView({ behavior: 'smooth', block: 'end' });
      },
      'thinking.delta': (d) => {
        const bubble = liveBubble();
        let t = bubble.querySelector('.thinking');
        if (!t) { t = document.createElement('div'); t.className = 'thinking'; bubble.prepend(t); }
        t.textContent += (d.thinking || '');
      },
      'tool.started': (d) => addToolCard(d.tool, d.arguments),
      'tool.completed': (d) => {
        const cards = document.querySelectorAll('.tool-card[data-tool="' + CSS.escape(d.tool || '') + '"]');
        const card = cards[cards.length - 1];
        if (card) card.querySelector('.tool-result').textContent = d.result || '(no output)';
      },
      'tool.approval_required': (d) => renderApprovals(d.pending),
      'run.completed': () => finishRun('Completed', 'ok'),
      'run.failed': (d) => { finishRun('Failed', 'bad'); Chege.alertBox(d.error || 'Run failed', 'danger'); },
      'run.cancelled': () => finishRun('Cancelled', 'warn')
    };
    Object.keys(handlers).forEach((type) => {
      es.addEventListener(type, (event) => {
        if (event.lastEventId) state.lastSeq = Number(event.lastEventId);
        let data = {};
        try { data = JSON.parse(event.data || '{}'); } catch (_) {}
        handlers[type](data);
      });
    });
    es.onerror = () => setStatus('Stream interrupted — reconnecting…', 'warn');
  }

  function finishRun(label, kind) {
    closeStream();
    const live = $('assistant-live');
    if (live) live.removeAttribute('id');
    renderApprovals([]);
    setStatus(label, kind);
    refreshSideEffects();
  }

  function refreshSideEffects() {
    loadFiles();
    loadDiff();
    if (state.session) loadSession(state.session);
  }

  async function loadProjects() {
    try {
      const data = await Chege.api('/projects');
      state.projects = data.projects || [];
      const select = $('project-select');
      select.innerHTML = state.projects.length
        ? state.projects.map((p) => `<option value="${Chege.escapeHtml(p.slug)}">${Chege.escapeHtml(p.name)}</option>`).join('')
        : '<option value="">No projects yet</option>';
      $('empty-projects').classList.toggle('d-none', state.projects.length > 0);
      if (state.projects.length) await selectProject(state.projects[0].slug);
      else { $('chat-scroll').innerHTML = '<div class="empty-state"><i class="fas fa-folder-open fa-3x mb-3"></i><p>Create a project to begin.</p></div>'; }
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  async function selectProject(slug) {
    state.project = slug;
    try {
      const data = await Chege.api(`/sessions/by-project/${encodeURIComponent(slug)}`);
      state.sessions = data.sessions || [];
      const select = $('session-select');
      select.innerHTML = state.sessions.map((s) => `<option value="${Chege.escapeHtml(s.id)}">${Chege.escapeHtml(s.title)}</option>`).join('');
      if (state.sessions.length) await loadSession(state.sessions[0].id);
      loadFiles(); loadDiff();
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  async function loadSession(id) {
    state.session = id;
    try {
      const data = await Chege.api(`/sessions/${encodeURIComponent(id)}`);
      $('session-title').textContent = data.session.title || 'Thread';
      const scroll = $('chat-scroll');
      scroll.innerHTML = '';
      (data.messages || []).forEach((m) => pushMessage(m.role, m.content, m.thinking));
      if (!(data.messages || []).length) {
        scroll.innerHTML = '<div class="empty-state"><i class="fas fa-comments fa-3x mb-3"></i><p>Send a prompt to start the agent.</p></div>';
      }
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  async function createProject() {
    const name = $('new-project-name').value.trim();
    if (!name) { Chege.alertBox('Enter a project name', 'warning'); return; }
    try {
      const data = await Chege.api('/projects', {
        method: 'POST',
        body: { name: name, goal: $('new-project-goal').value.trim() }
      });
      $('new-project-name').value = ''; $('new-project-goal').value = '';
      await loadProjects();
      $('project-select').value = data.project.slug;
      await selectProject(data.project.slug);
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  async function createSession() {
    if (!state.project) return;
    try {
      const data = await Chege.api('/sessions', {
        method: 'POST', body: { project_slug: state.project, title: 'New Thread' }
      });
      await selectProject(state.project);
      $('session-select').value = data.session.id;
      await loadSession(data.session.id);
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
  }

  async function sendPrompt() {
    if (!state.session) { Chege.alertBox('Create a project and session first', 'warning'); return; }
    const input = $('prompt-input');
    const prompt = input.value.trim();
    if (!prompt) return;
    input.value = '';
    $('chat-scroll').querySelector('.empty-state')?.remove();
    pushMessage('user', prompt);
    setStatus('Starting run…', 'warn');
    try {
      const data = await Chege.api('/runs', {
        method: 'POST',
        body: {
          session_id: state.session,
          prompt: prompt,
          model: $('model-select').value || 'qwen2.5-coder:latest',
          provider: $('provider-select').value || null,
          policy_mode: $('policy-select').value,
          max_steps: 50
        }
      });
      state.runId = data.run_id;
      state.lastSeq = 0;
      openStream(0);
    } catch (e) { Chege.alertBox(e.message, 'danger'); setStatus('Failed to start', 'bad'); }
  }

  async function loadFiles() {
    if (!state.project) return;
    try {
      const data = await Chege.api(`/files?project_slug=${encodeURIComponent(state.project)}`);
      $('file-list').innerHTML = (data.files || []).length
        ? data.files.map((f) => `<a class="file-item" data-path="${Chege.escapeHtml(f)}"><i class="fas fa-file-code"></i> ${Chege.escapeHtml(f)}</a>`).join('')
        : '<span class="text-muted small">Workspace is empty</span>';
      $('file-list').querySelectorAll('.file-item').forEach((item) => {
        item.addEventListener('click', () => loadFile(item.dataset.path));
      });
    } catch (e) { Chege.alertBox(e.message, 'danger'); }
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

  async function loadProviders() {
    try {
      const data = await Chege.api('/providers');
      state.providers = data.providers || [];
      $('provider-select').innerHTML = '<option value="">Default (' + Chege.escapeHtml(data.active_provider || '') + ')</option>'
        + state.providers.map((p) => `<option value="${Chege.escapeHtml(p.name)}">${Chege.escapeHtml(p.name)}</option>`).join('');
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
        `<option value="${Chege.escapeHtml(name)}">${Chege.escapeHtml(name.split('/').pop())}</option>`).join('');
      if (selected && names.includes(selected)) select.value = selected;
      else if (names.includes(previous)) select.value = previous;
    } catch (e) {
      // Model manager may be unavailable; keep the existing selector intact.
    }
  }

  async function loadTools() {
    try {
      const data = await Chege.api('/tools');
      state.tools = data.tools || [];
      $('tool-list').innerHTML = state.tools.map((t) =>
        `<div class="d-flex justify-content-between border-bottom py-1 small"><span>${Chege.escapeHtml(t.name)}</span>
         <span class="badge bg-secondary">${Chege.escapeHtml(t.risk)}</span></div>`).join('');
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

  function bind() {
    $('project-select').addEventListener('change', (e) => selectProject(e.target.value));
    $('session-select').addEventListener('change', (e) => loadSession(e.target.value));
    $('new-project-btn').addEventListener('click', createProject);
    $('new-session-btn').addEventListener('click', createSession);
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
    $('refresh-files').addEventListener('click', () => { loadFiles(); loadDiff(); });
  }

  document.addEventListener('DOMContentLoaded', () => {
    Chege.shell('/app');
    bind();
    loadProviders();
    loadTools();
    loadProjects();
  });
})();
