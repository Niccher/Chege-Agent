/* Models page — installed models, capabilities, selection and downloads. */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => Chege.escapeHtml(value);

  const CAP_META = {
    tools: { label: 'Tools', icon: 'fa-wrench', cls: 'cap-tools' },
    vision: { label: 'Vision', icon: 'fa-eye', cls: 'cap-vision' },
    ocr: { label: 'OCR', icon: 'fa-image', cls: 'cap-vision' },
    code: { label: 'Code', icon: 'fa-code', cls: 'cap-tools' },
    general: { label: 'General', icon: 'fa-comment', cls: 'cap-unknown' },
    reasoning: { label: 'Reasoning', icon: 'fa-brain', cls: 'cap-reasoning' },
    thinking: { label: 'Thinking', icon: 'fa-brain', cls: 'cap-reasoning' },
    lightweight: { label: 'Light', icon: 'fa-feather', cls: 'cap-unknown' },
    completion: { label: 'Text', icon: 'fa-align-left', cls: 'cap-unknown' },
    insert: { label: 'Insert', icon: 'fa-i-cursor', cls: 'cap-unknown' },
    'no-tools': { label: 'No tools', icon: 'fa-ban', cls: 'cap-no-tools' },
  };

  function capBadge(cap) {
    const meta = CAP_META[cap] || { label: cap, icon: 'fa-circle', cls: 'cap-unknown' };
    return `<span class="cap-badge ${meta.cls}"><i class="fas ${meta.icon}"></i> ${esc(meta.label)}</span>`;
  }

  function capabilityBadges(model) {
    const caps = Array.isArray(model.capabilities) ? model.capabilities.slice() : [];
    const badges = [];
    if (model.supports_tools === true) badges.push(capBadge('tools'));
    else if (model.supports_tools === false && model.capabilities_known) badges.push(capBadge('no-tools'));
    else badges.push(`<span class="cap-badge cap-unknown"><i class="fas fa-question"></i> Unknown</span>`);

    caps.forEach((cap) => {
      if (cap === 'tools' || cap === 'completion') return;
      badges.push(capBadge(cap));
    });
    return `<div class="model-capabilities">${badges.join('')}</div>`;
  }

  function catalogBadges(caps) {
    return `<div class="model-capabilities">${(caps || []).map(capBadge).join('')}</div>`;
  }

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

  function modelRow(name, meta, isActive, actionLabel, actionValue, model) {
    const caps = model || {};
    return `<div class="chege-model-row${isActive ? ' is-active' : ''}">
      <div class="chege-model-info">
        <span class="chege-model-name" title="${esc(name)}">${esc(name)}</span>
        <span class="chege-model-meta">${esc(meta)}</span>
        ${capabilityBadges(caps)}
      </div>
      <div class="chege-model-actions">
        ${isActive
          ? '<span class="badge bg-success">Active</span>'
          : `<button class="btn btn-sm btn-outline-primary" data-model-action="${esc(actionValue)}" type="button">${esc(actionLabel)}</button>`}
      </div>
    </div>`;
  }

  async function load() {
    try {
      const data = await Chege.api('/models/overview');
      const lc = data.llamacpp || {};
      const ol = data.ollama || {};
      const selected = data.selected || {};
      const activeProvider = data.active_provider || '—';

      stateBadge($('llamacpp-state'), !!lc.available, lc.available ? 'Serving' : 'Unavailable');
      stateBadge($('ollama-state'), !!ol.available, ol.available ? 'Ready' : 'Unavailable');
      $('active-provider-badge').innerHTML = `<i class="fas fa-plug"></i> Active: ${esc(activeProvider)}`;

      const lcModels = lc.models || [];
      $('llamacpp-models').innerHTML = lcModels.length
        ? lcModels.map((m) => {
            const active = !!m.active && activeProvider === 'llama_cpp';
            return modelRow(
              m.name, formatSize(m.size) + ' · ' + m.path,
              active, 'Use', 'llamacpp:' + m.path, m
            );
          }).join('')
        : `<div class="text-muted small">${esc(lc.error || 'No GGUF models found. Download one below.')}</div>`;

      const olModels = ol.models || [];
      $('ollama-models').innerHTML = olModels.length
        ? olModels.map((m) => {
            const active = m.name === selected.ollama && activeProvider === 'ollama';
            const size = formatSize(m.size);
            const bits = [size, m.family, m.parameter_size, m.quantization, m.context_length ? m.context_length + ' ctx' : '']
              .filter(Boolean).join(' · ');
            return modelRow(m.name, bits, active, 'Use', 'ollama:' + m.name, m);
          }).join('')
        : `<div class="text-muted small">${esc(ol.error || 'No Ollama models found. Pull one below.')}</div>`;

      const toolCount = lcModels.filter((m) => m.supports_tools === true).length
        + olModels.filter((m) => m.supports_tools === true).length;
      const visionCount = lcModels.filter((m) => m.supports_vision).length
        + olModels.filter((m) => m.supports_vision).length;
      $('models-summary').textContent =
        `${lcModels.length} GGUF · ${olModels.length} Ollama model${olModels.length === 1 ? '' : 's'}`;
      $('models-detail').textContent =
        `Active provider: ${activeProvider} · ${toolCount} tool-capable · ${visionCount} vision/OCR · ` +
        'Selection switches the active provider.';
      $('models-updated').textContent = 'Updated ' + new Date().toLocaleTimeString();

      loadCatalog();
    } catch (e) {
      Chege.alertBox('Could not load models: ' + e.message, 'danger');
      $('models-summary').textContent = 'Model manager unavailable';
      $('models-detail').textContent = e.message;
    }
  }

  function progress(prefix, event) {
    const bar = $(prefix + '-progress-bar');
    const label = $(prefix + '-progress');
    if (!bar || !label) return;
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
    if (bar) bar.style.width = '5%';
    if (label) label.textContent = 'Starting…';
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

  function downloadUrl() {
    return $('gguf-url').value.trim();
  }

  function downloadName() {
    return $('gguf-name').value.trim();
  }

  function hfToken() {
    return $('hf-token').value.trim();
  }

  function startCustomDownload() {
    const url = downloadUrl();
    if (!url) { Chege.alertBox('Paste a GGUF URL first.', 'warning'); return; }
    stream('/models/llamacpp/download', { url, name: downloadName() || null, hf_token: hfToken() || null }, 'gguf');
  }

  function startCatalogDownload(url, name) {
    stream('/models/llamacpp/download', { url, name, hf_token: hfToken() || null }, 'catalog');
  }

  async function loadCatalog() {
    try {
      const data = await Chege.api('/models/catalog');
      const models = data.models || [];
      $('catalog-list').innerHTML = models.length
        ? models.map((m) => {
            const bits = [
              m.parameters, m.quantization, formatSize(m.size_bytes), m.license,
            ].filter(Boolean).join(' · ');
            return `<div class="model-catalog-row">
              <div class="model-catalog-main">
                <span class="model-catalog-title">${esc(m.name)}${m.recommended ? ' <span class="badge bg-success">Recommended</span>' : ''}</span>
                <span class="model-catalog-meta">${esc(m.repo)} / ${esc(m.file)} · ${esc(bits)}</span>
                ${catalogBadges(m.capabilities)}
                <span class="chege-setting-help">${esc(m.notes || '')}${m.requires_mmproj ? ' Requires an mmproj file for images.' : ''}</span>
              </div>
              <div class="model-catalog-actions">
                <button class="btn btn-sm btn-primary" type="button"
                  data-catalog-url="${esc(m.url)}" data-catalog-name="${esc(m.file)}">
                  <i class="fas fa-download"></i> Download
                </button>
              </div>
            </div>`;
          }).join('')
        : '<div class="text-muted small">Catalog unavailable.</div>';
    } catch (e) {
      $('catalog-list').innerHTML = '<div class="text-danger small">Could not load catalog: ' + esc(e.message) + '</div>';
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

    $('gguf-download').addEventListener('click', startCustomDownload);
    $('ollama-pull').addEventListener('click', () => {
      const name = $('ollama-tag').value.trim();
      if (!name) { Chege.alertBox('Enter an Ollama model tag first.', 'warning'); return; }
      stream('/models/ollama/pull', { name }, 'ollama');
    });

    document.addEventListener('click', (event) => {
      const catalogBtn = event.target.closest('[data-catalog-url]');
      if (catalogBtn) {
        startCatalogDownload(catalogBtn.dataset.catalogUrl, catalogBtn.dataset.catalogName);
        return;
      }
      const btn = event.target.closest('[data-model-action]');
      if (btn) selectModel(btn.dataset.modelAction);
    });

    load();
  });
})();
