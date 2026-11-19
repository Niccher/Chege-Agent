/* Models page — download and select local models for llama.cpp and Ollama. */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => Chege.escapeHtml(value);

  function formatSize(bytes) {
    if (!bytes || bytes <= 0) return 'unknown size';
    const units = ['B', 'KB', 'MB', 'GB'];
    let value = bytes, unit = 0;
    while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
    return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
  }

  function stateBadge(el, available, label) {
    el.textContent = available ? label || 'Online' : 'Offline';
    el.className = 'chege-status-badge ' + (available ? 'is-ok' : 'is-bad');
  }

  function modelRow(name, meta, isActive, actionLabel, actionFn, extra) {
    return `<div class="chege-model-row${isActive ? ' is-active' : ''}">
      <div class="chege-model-info">
        <span class="chege-model-name" title="${esc(name)}">${esc(name)}</span>
        <span class="chege-model-meta">${esc(meta)}</span>
        ${extra || ''}
      </div>
      <div class="chege-model-actions">
        ${isActive
          ? '<span class="badge bg-success">In use</span>'
          : `<button class="btn btn-sm btn-outline-primary" data-model-action="${esc(actionLabel)}" type="button">${esc(actionLabel)}</button>`}
      </div>
    </div>`;
  }

  async function load() {
    try {
      const data = await Chege.api('/models/overview');
      const lc = data.llamacpp || {};
      const ol = data.ollama || {};
      const selected = data.selected || {};

      stateBadge($('llamacpp-state'), !!lc.available, lc.available ? 'Serving' : 'Unavailable');
      stateBadge($('ollama-state'), !!ol.available, ol.available ? 'Ready' : 'Unavailable');

      const lcModels = lc.models || [];
      $('llamacpp-models').innerHTML = lcModels.length
        ? lcModels.map((m) => {
            const active = !!m.active || (!selected.llamacpp && !!lc.active && m.path === lc.active);
            return modelRow(
              m.name, formatSize(m.size) + ' · ' + m.path,
              active, 'Use', 'llamacpp:' + m.path
            );
          }).join('')
        : `<div class="text-muted small">${esc(lc.error || 'No GGUF models found. Download one below.')}</div>`;

      const olModels = ol.models || [];
      $('ollama-models').innerHTML = olModels.length
        ? olModels.map((m) => {
            const active = m.name === selected.ollama;
            return modelRow(m.name, formatSize(m.size) + (m.family ? ' · ' + m.family : ''),
              active, 'Use', 'ollama:' + m.name);
          }).join('')
        : `<div class="text-muted small">${esc(ol.error || 'No Ollama models found. Pull one below.')}</div>`;

      $('models-summary').textContent =
        `${lcModels.length} GGUF · ${olModels.length} Ollama model${olModels.length === 1 ? '' : 's'}`;
      $('models-detail').textContent =
        `Active provider: ${data.active_provider || '—'} · selection saved automatically for new runs.`;
      $('models-updated').textContent = 'Updated ' + new Date().toLocaleTimeString();

      // Persist action details on the buttons for the click handler.
      document.querySelectorAll('[data-model-action]').forEach((btn) => {
        btn.dataset.value = btn.getAttribute('data-model-action');
      });
    } catch (e) {
      Chege.alertBox('Could not load models: ' + e.message, 'danger');
      $('models-summary').textContent = 'Model manager unavailable';
      $('models-detail').textContent = e.message;
    }
  }

  function progress(prefix, event) {
    const bar = $(prefix + '-progress-bar');
    const label = $(prefix + '-progress');
    if (event.status === 'downloading' && event.downloaded) {
      const mb = (event.downloaded / 1024 / 1024).toFixed(1);
      bar.style.width = '65%';
      label.textContent = `Downloading… ${mb} MB received`;
    } else if (event.status === 'pulling') {
      bar.style.width = '70%';
      label.textContent = event.message || 'Pulling…';
    } else if (event.status === 'done') {
      bar.style.width = '100%';
      label.textContent = event.message || 'Done.';
      Chege.alertBox(event.message || 'Model ready.', 'success');
      load();
    } else if (event.status === 'error') {
      bar.style.width = '0';
      label.textContent = 'Failed: ' + event.message;
      Chege.alertBox(event.message, 'danger');
    } else {
      label.textContent = event.message || 'Working…';
    }
  }

  async function stream(url, body, prefix) {
    const bar = $(prefix + '-progress-bar');
    const label = $(prefix + '-progress');
    bar.style.width = '5%';
    label.textContent = 'Starting…';
    try {
      const res = await fetch(Chege.API + url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok || !res.body) {
        const text = await res.text();
        throw new Error(text.slice(0, 300));
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split('\n\n');
        buffer = chunks.pop();
        for (const chunk of chunks) {
          const line = chunk.split('\n').find((x) => x.startsWith('data: '));
          if (!line) continue;
          try { progress(prefix, JSON.parse(line.slice(6))); } catch (_) {}
        }
      }
    } catch (e) {
      progress(prefix, { status: 'error', message: e.message });
    }
  }

  async function selectModel(value) {
    const [provider, ...rest] = value.split(':');
    const model = rest.join(':');
    try {
      if (provider === 'ollama') {
        const result = await Chege.api('/models/ollama/select', {
          method: 'POST', body: { path: model },
        });
        Chege.alertBox(result.message, 'success');
      } else {
        Chege.alertBox('Restarting llama-server with ' + model.split('/').pop() + '…', 'info');
        const result = await Chege.api('/models/llamacpp/select', {
          method: 'POST', body: { path: model },
        });
        Chege.alertBox(result.message, result.status === 'warning' ? 'warning' : 'success');
      }
      await load();
    } catch (e) {
      Chege.alertBox('Could not select model: ' + e.message, 'danger');
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    Chege.shell('/models');
    $('refresh-models').addEventListener('click', load);

    $('gguf-download').addEventListener('click', () => {
      const url = $('gguf-url').value.trim();
      if (!url) { Chege.alertBox('Paste a GGUF URL first.', 'warning'); return; }
      stream('/models/llamacpp/download', { url }, 'gguf');
    });

    $('ollama-pull').addEventListener('click', () => {
      const name = $('ollama-tag').value.trim();
      if (!name) { Chege.alertBox('Enter an Ollama model tag first.', 'warning'); return; }
      stream('/models/ollama/pull', { name }, 'ollama');
    });

    document.addEventListener('click', (event) => {
      const btn = event.target.closest('[data-model-action]');
      if (btn) selectModel(btn.dataset.value);
    });

    load();
  });
})();
