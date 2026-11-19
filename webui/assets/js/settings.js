/* Unified settings console — reads, tests and saves /api/v1/settings. */
(function () {
  const $ = (id) => document.getElementById(id);
  let maskedApiKey = '';

  const NUMERIC_FIELDS = [
    'default_context_window', 'max_steps', 'default_temperature', 'default_top_p',
    'run_timeout_seconds', 'provider_timeout_seconds', 'llamacpp_ctx',
    'ollama_num_ctx', 'openai_max_tokens'
  ];
  const TEXT_FIELDS = [
    'default_provider', 'llamacpp_url', 'ollama_url', 'openai_base_url',
    'sandbox_backend', 'llamacpp_model', 'ollama_model',
    'ollama_keep_alive'
  ];

  function setResult(status, message) {
    const el = $('provider-test-result');
    const kind = status === 'ok' ? ' is-ok' : status === 'error' ? ' is-error' : '';
    el.className = 'chege-test-result' + kind;
    el.textContent = message;
  }

  function showProvider(provider) {
    document.querySelectorAll('.chege-provider-panel').forEach((panel) => {
      panel.classList.toggle('d-none', panel.dataset.provider !== provider);
    });
    const badge = $('active-provider-badge');
    if (badge) badge.textContent = 'Active: ' + provider;
  }

  function fill(settings, savedTo) {
    if (!settings) return;
    TEXT_FIELDS.forEach((key) => {
      const el = $(key);
      if (el && settings[key] !== undefined && settings[key] !== null) el.value = settings[key];
    });
    $('default_provider').value = settings.default_provider || 'llama_cpp';
    $('sandbox_backend').value = settings.sandbox_backend || 'docker';

    NUMERIC_FIELDS.forEach((key) => {
      const el = $(key);
      if (!el) return;
      const value = settings[key];
      el.value = (value === undefined || value === null) ? '' : value;
    });
    // Sensible visible fallbacks for first-run installs.
    if ($('default_context_window').value === '') $('default_context_window').value = 8192;
    if ($('llamacpp_ctx').value === '') $('llamacpp_ctx').value = 8192;
    if ($('ollama_num_ctx').value === '') $('ollama_num_ctx').value = 8192;

    maskedApiKey = settings.openai_api_key || '';
    $('openai_api_key').value = maskedApiKey;

    showProvider($('default_provider').value);

    const db = settings.database_url && settings.database_url.startsWith('postgres') ? 'Postgres' : 'SQLite';
    $('settings-summary').textContent =
      `${settings.default_provider} · ${settings.sandbox_backend} sandbox · ${db} · ${settings.max_steps} steps`;
    $('settings-source').textContent = savedTo
      ? `Saved defaults loaded from ${savedTo}`
      : 'Runtime values from env/.env — use Save as defaults to persist';

    $('ref-host').textContent = settings.host || '—';
    $('ref-port').textContent = String(settings.port || '—');
    $('ref-database').textContent = settings.database_url || 'embedded SQLite';
    $('ref-data').textContent = settings.data_dir || '—';
    $('ref-workdir').textContent = settings.workdir || '—';
    $('ref-logs').textContent = settings.logs_dir || '—';
    $('ref-projects').textContent = settings.projects_dir || (settings.workdir || '—') + ' (workdir)';
    $('ref-sandbox-image').textContent = settings.default_sandbox_image || '—';

    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
      if (!el.__chegeTooltip) {
        el.__chegeTooltip = new bootstrap.Tooltip(el, { html: false, delay: { show: 120, hide: 60 } });
      }
    });

    Chege.syncTheme(Chege.themePreference());
  }

  function collect() {
    const payload = {
      default_provider: $('default_provider').value,
      llamacpp_url: $('llamacpp_url').value.trim(),
      ollama_url: $('ollama_url').value.trim(),
      openai_base_url: $('openai_base_url').value.trim(),
      sandbox_backend: $('sandbox_backend').value,
      llamacpp_model: $('llamacpp_model').value.trim() || null,
      ollama_model: $('ollama_model').value.trim() || null,
      ollama_keep_alive: $('ollama_keep_alive').value.trim() || '15m'
    };
    NUMERIC_FIELDS.forEach((key) => {
      const el = $(key);
      if (!el || el.value === '') return;
      const n = Number(el.value);
      if (Number.isFinite(n)) payload[key] = n;
    });
    const key = $('openai_api_key').value.trim();
    if (key !== maskedApiKey) payload.openai_api_key = key || null;
    return payload;
  }

  async function load() {
    try {
      const settings = await Chege.api('/settings');
      fill(settings);
    } catch (e) {
      Chege.alertBox('Could not load settings: ' + e.message, 'danger');
    }
  }

  async function write(persist) {
    const payload = collect();
    try {
      const result = await Chege.api(persist ? '/settings/defaults' : '/settings', {
        method: persist ? 'PUT' : 'PATCH',
        body: payload,
      });
      fill(result.settings, result.saved_to);
      Chege.alertBox(persist
        ? 'Settings applied and saved as defaults.'
        : 'Settings applied to this running process only.', 'success');
    } catch (e) {
      Chege.alertBox('Could not save settings: ' + e.message, 'danger');
    }
  }

  async function testProvider(kind) {
    const url = kind === 'llama_cpp' ? $('llamacpp_url').value.trim()
      : kind === 'ollama' ? $('ollama_url').value.trim()
      : $('openai_base_url').value.trim();
    setResult('info', `Testing ${kind}…`);
    try {
      let result;
      if (kind === 'llama_cpp') {
        result = await Chege.api('/settings/test-llamacpp?url=' + encodeURIComponent(url));
      } else if (kind === 'ollama') {
        result = await Chege.api('/settings/test-ollama?url=' + encodeURIComponent(url));
      } else {
        result = await Chege.api('/providers/test', {
          method: 'POST', body: { provider: 'openai', url: url },
        });
      }
      const status = result.status === 'ok' ? 'ok' : result.status === 'error' ? 'error' : 'info';
      const message = result.message || result.error ||
        `Connected. ${result.count != null ? result.count + ' model(s) found.' : 'Endpoint responded.'}`;
      setResult(status, message);
    } catch (e) {
      setResult('error', e.message);
    }
  }

  async function loadModels() {
    const provider = $('default_provider').value;
    setResult('info', `Loading models from ${provider}…`);
    try {
      const result = await Chege.api('/settings/models?provider=' + encodeURIComponent(provider));
      const models = result.models || [];
      const names = models.slice(0, 12).map((m) => typeof m === 'string' ? m : (m.id || m.name || m.path || JSON.stringify(m)));
      $('model-list').textContent = names.length
        ? 'Models: ' + names.join(', ') + (models.length > 12 ? ` … (+${models.length - 12})` : '')
        : 'Provider returned no models.';
      setResult(models.length ? 'ok' : 'info', models.length ? `Found ${models.length} model(s).` : 'No models found.');
    } catch (e) {
      $('model-list').textContent = '';
      setResult('error', e.message);
    }
  }

  const CAP_META = {
    tools: { label: 'Tools', icon: 'fa-wrench', cls: 'cap-tools' },
    vision: { label: 'Vision', icon: 'fa-eye', cls: 'cap-vision' },
    ocr: { label: 'OCR', icon: 'fa-image', cls: 'cap-vision' },
    code: { label: 'Code', icon: 'fa-code', cls: 'cap-tools' },
    general: { label: 'General', icon: 'fa-comment', cls: 'cap-unknown' },
    reasoning: { label: 'Reasoning', icon: 'fa-brain', cls: 'cap-reasoning' },
    thinking: { label: 'Thinking', icon: 'fa-brain', cls: 'cap-reasoning' },
    lightweight: { label: 'Light', icon: 'fa-feather', cls: 'cap-unknown' },
    insert: { label: 'Insert', icon: 'fa-i-cursor', cls: 'cap-unknown' },
    'no-tools': { label: 'No tools', icon: 'fa-ban', cls: 'cap-no-tools' },
    unknown: { label: 'Unknown', icon: 'fa-question', cls: 'cap-unknown' },
  };

  function formatSize(bytes) {
    if (!bytes || bytes <= 0) return 'unknown size';
    const units = ['B', 'KB', 'MB', 'GB'];
    let value = bytes, unit = 0;
    while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
    return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
  }

  function capBadge(cap) {
    const meta = CAP_META[cap] || { label: cap, icon: 'fa-circle', cls: 'cap-unknown' };
    return `<span class="cap-badge ${meta.cls}"><i class="fas ${meta.icon}"></i> ${Chege.escapeHtml(meta.label)}</span>`;
  }

  function modelCaps(model) {
    const badges = [];
    if (model.supports_tools === true) badges.push(capBadge('tools'));
    else if (model.supports_tools === false && model.capabilities_known) badges.push(capBadge('no-tools'));
    else badges.push(capBadge('unknown'));
    (model.capabilities || []).forEach((cap) => {
      if (cap !== 'tools' && cap !== 'completion') badges.push(capBadge(cap));
    });
    return badges.join('');
  }

  async function loadModelChoices() {
    try {
      const data = await Chege.api('/models/overview');
      const lc = data.llamacpp || {};
      const ol = data.ollama || {};
      const lcModels = lc.models || [];
      const olModels = ol.models || [];
      const active = data.active_provider || '—';

      $('llamacpp-model-options').innerHTML = lcModels.map((m) =>
        `<option value="${Chege.escapeHtml(m.path)}">${Chege.escapeHtml(m.name)}</option>`).join('');
      $('ollama-model-options').innerHTML = olModels.map((m) =>
        `<option value="${Chege.escapeHtml(m.name)}">${Chege.escapeHtml(m.name)}</option>`).join('');

      const selectedLc = lcModels.find((m) => m.path === data.selected?.llamacpp);
      const selectedOl = olModels.find((m) => m.name === data.selected?.ollama);
      $('llamacpp-model-meta').innerHTML =
        `${lcModels.length} installed GGUF · active provider: <b>${Chege.escapeHtml(active)}</b>` +
        (selectedLc ? `<div class="model-capabilities mt-1">${modelCaps(selectedLc)}</div>` : '');
      $('ollama-model-meta').innerHTML =
        `${olModels.length} installed Ollama model${olModels.length === 1 ? '' : 's'} · active provider: <b>${Chege.escapeHtml(active)}</b>` +
        (selectedOl ? `<div class="model-capabilities mt-1">${modelCaps(selectedOl)}</div>` : '');
    } catch (e) {
      $('llamacpp-model-meta').textContent = 'Could not load installed GGUF models: ' + e.message;
      $('ollama-model-meta').textContent = 'Could not load installed Ollama models: ' + e.message;
    }
  }

  function downloadProgress(event) {
    const bar = $('settings-download-progress-bar');
    const label = $('settings-download-progress');
    if (!bar || !label) return;
    if (event.status === 'downloading' && event.downloaded) {
      bar.style.width = '65%';
      label.textContent = `Downloading… ${(event.downloaded / 1024 / 1024).toFixed(1)} MB received`;
    } else if (event.status === 'done') {
      bar.style.width = '100%';
      label.textContent = event.message || 'Downloaded.';
      Chege.alertBox(event.message || 'Model downloaded.', 'success');
      loadModelChoices();
      loadCatalog();
    } else if (event.status === 'error') {
      bar.style.width = '0';
      label.textContent = 'Failed: ' + event.message;
      Chege.alertBox(event.message, 'danger');
    } else {
      label.textContent = event.message || 'Working…';
    }
  }

  async function streamDownload(url, name) {
    const bar = $('settings-download-progress-bar');
    const label = $('settings-download-progress');
    if (bar) bar.style.width = '5%';
    if (label) label.textContent = 'Starting download…';
    try {
      const res = await fetch(Chege.API + '/models/llamacpp/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url,
          name: name || null,
          hf_token: $('settings-hf-token').value.trim() || null,
        }),
      });
      if (!res.ok || !res.body) throw new Error((await res.text()).slice(0, 300));
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
          try { downloadProgress(JSON.parse(line.slice(6))); } catch (_) {}
        }
      }
    } catch (e) {
      downloadProgress({ status: 'error', message: e.message });
    }
  }

  function startCustomDownload() {
    const url = $('settings-gguf-url').value.trim();
    if (!url) { Chege.alertBox('Paste a GGUF URL first.', 'warning'); return; }
    streamDownload(url, $('settings-gguf-name').value.trim());
  }

  async function loadCatalog() {
    try {
      const data = await Chege.api('/models/catalog');
      const models = data.models || [];
      $('settings-catalog').innerHTML = models.length
        ? models.map((m) => {
            const bits = [m.parameters, m.quantization, formatSize(m.size_bytes), m.license]
              .filter(Boolean).join(' · ');
            return `<div class="model-catalog-row">
              <div class="model-catalog-main">
                <span class="model-catalog-title">${Chege.escapeHtml(m.name)}${m.recommended ? ' <span class="badge bg-success">Recommended</span>' : ''}</span>
                <span class="model-catalog-meta">${Chege.escapeHtml(m.repo)} / ${Chege.escapeHtml(m.file)} · ${Chege.escapeHtml(bits)}</span>
                <div class="model-capabilities">${(m.capabilities || []).map(capBadge).join('')}</div>
                <span class="chege-setting-help">${Chege.escapeHtml(m.notes || '')}${m.requires_mmproj ? ' Requires an mmproj file for images.' : ''}</span>
              </div>
              <div class="model-catalog-actions">
                <button class="btn btn-sm btn-primary" type="button"
                  data-settings-catalog-url="${Chege.escapeHtml(m.url)}" data-settings-catalog-name="${Chege.escapeHtml(m.file)}">
                  <i class="fas fa-download"></i> Download
                </button>
              </div>
            </div>`;
          }).join('')
        : '<div class="text-muted small">Catalog unavailable.</div>';
    } catch (e) {
      $('settings-catalog').innerHTML = '<div class="text-danger small">Could not load catalog: ' + Chege.escapeHtml(e.message) + '</div>';
    }
  }

  async function clearDefaults() {
    if (!window.confirm('Remove saved defaults? Runtime values stay until the next restart.')) return;
    try {
      const result = await Chege.api('/settings/defaults', { method: 'DELETE' });
      Chege.alertBox(result.message || 'Saved defaults cleared.', result.removed ? 'success' : 'info');
      await load();
    } catch (e) {
      Chege.alertBox('Could not clear defaults: ' + e.message, 'danger');
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    Chege.shell('/settings');
    $('default_provider').addEventListener('change', (e) => showProvider(e.target.value));
    $('apply-settings').addEventListener('click', () => write(false));
    $('save-settings').addEventListener('click', () => write(true));
    $('reset-settings').addEventListener('click', load);
    $('clear-defaults').addEventListener('click', clearDefaults);
    $('test-llamacpp').addEventListener('click', () => testProvider('llama_cpp'));
    $('test-ollama').addEventListener('click', () => testProvider('ollama'));
    $('test-openai').addEventListener('click', () => testProvider('openai'));
    $('load-models').addEventListener('click', loadModels);
    $('settings-gguf-download').addEventListener('click', startCustomDownload);
    $('refresh-catalog').addEventListener('click', () => { loadModelChoices(); loadCatalog(); });
    document.addEventListener('click', (event) => {
      const btn = event.target.closest('[data-settings-catalog-url]');
      if (btn) streamDownload(btn.dataset.settingsCatalogUrl, btn.dataset.settingsCatalogName);
    });
    load();
    loadModelChoices();
    loadCatalog();
  });
})();
