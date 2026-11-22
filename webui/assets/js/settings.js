/* Unified settings console — reads, tests and saves /api/v1/settings. */
(function () {
  const $ = (id) => document.getElementById(id);

  const NUMERIC_FIELDS = [
    'default_context_window', 'max_steps', 'default_temperature', 'default_top_p',
    'run_timeout_seconds', 'provider_timeout_seconds', 'llamacpp_ctx',
    'ollama_num_ctx'
  ];
  const TEXT_FIELDS = [
    'default_provider', 'llamacpp_url', 'ollama_url',
    'sandbox_backend', 'llamacpp_model', 'ollama_model',
    'ollama_keep_alive'
  ];

  // Provider catalog + per-provider cloud drafts. profiles[pid] mirrors the
  // backend's provider_configs entry; api_key stays masked until edited.
  let providerCatalog = [];
  let profiles = {};
  let savedMasks = {};
  let modelCache = {};
  let currentCloud = null;
  const dirtyProviders = new Set();

  function setResult(status, message) {
    const el = $('provider-test-result');
    const kind = status === 'ok' ? ' is-ok' : status === 'error' ? ' is-error' : '';
    el.className = 'chege-test-result' + kind;
    el.textContent = message;
  }

  function resetDiagnostics() {
    const el = $('provider-diagnostics');
    if (!el) return;
    el.classList.add('d-none');
    el.innerHTML = '';
  }

  function diagIcon(status) {
    if (status === 'ok') return 'fa-circle-check';
    if (status === 'warning') return 'fa-triangle-exclamation';
    return 'fa-circle-xmark';
  }

  function renderDiagnostics(result) {
    const el = $('provider-diagnostics');
    if (!el) return;
    if (!result || !Array.isArray(result.checks) || !result.checks.length) {
      resetDiagnostics();
      return;
    }
    const headBits = [];
    if (result.label || result.provider) headBits.push(`<b>${Chege.escapeHtml(result.label || result.provider)}</b>`);
    if (result.url) headBits.push(`<span class="text-muted">${Chege.escapeHtml(result.url)}</span>`);
    if (result.model) headBits.push(`model <code>${Chege.escapeHtml(result.model)}</code>`);
    if (result.token_source) {
      const tokenText = result.token_set
        ? `token ${Chege.escapeHtml(result.token_masked || 'set')} (${Chege.escapeHtml(result.token_source)})`
        : 'no token';
      headBits.push(`<span>${tokenText}</span>`);
    }
    if (result.latency_ms != null) headBits.push(`<span class="text-muted">${result.latency_ms} ms</span>`);

    const checks = result.checks.map((check) => {
      const status = ['ok', 'warning', 'error'].includes(check.status) ? check.status : 'error';
      const extra = check.http_status ? ` <span class="text-muted">HTTP ${check.http_status}</span>` : '';
      return `<div class="chege-diag-check is-${status}">
        <i class="fas ${diagIcon(status)}"></i>
        <span class="diag-name">${Chege.escapeHtml(check.name || 'check')}</span>
        <span class="diag-msg">${Chege.escapeHtml(check.message || '')}${extra}</span>
      </div>`;
    }).join('');

    el.innerHTML = `<div class="chege-diag-head">${headBits.join(' · ')}</div>${checks}`;
    el.classList.remove('d-none');
  }

  function providerById(id) {
    return providerCatalog.find((p) => p.id === id || p.name === id) || null;
  }

  function isCloudProvider(id) {
    const entry = providerById(id);
    return entry ? entry.kind === 'cloud' : !['llama_cpp', 'ollama', ''].includes(id);
  }

  function providerLabel(id) {
    const entry = providerById(id);
    return entry ? entry.label : id;
  }

  function providerIcon(id) {
    const entry = providerById(id);
    return entry && entry.icon ? entry.icon : 'fa-cloud';
  }

  function baseProfile(pid) {
    const entry = providerById(pid) || {};
    return {
      base_url: profiles[pid]?.base_url ?? entry.base_url ?? '',
      api_key: profiles[pid]?.api_key ?? '',
      api_key_set: Boolean(profiles[pid]?.api_key_set),
      model: profiles[pid]?.model ?? entry.default_model ?? '',
      max_tokens: profiles[pid]?.max_tokens ?? null,
    };
  }

  function captureCloudDraft() {
    if (!currentCloud || !$('cloud_base_url')) return;
    profiles[currentCloud] = {
      ...baseProfile(currentCloud),
      base_url: $('cloud_base_url').value.trim(),
      api_key: $('cloud_api_key').value.trim(),
      model: $('cloud_model').value.trim(),
      max_tokens: $('cloud_max_tokens').value === '' ? null : Number($('cloud_max_tokens').value),
    };
  }

  function setTokenStatus(status, message) {
    const el = $('token-status');
    if (!el) return;
    const icons = {
      ok: 'fa-circle-check',
      error: 'fa-circle-xmark',
      warning: 'fa-triangle-exclamation',
      info: 'fa-spinner fa-spin',
    };
    el.className = 'chege-token-status is-visible is-' + status;
    el.innerHTML = `<i class="fas ${icons[status] || 'fa-circle-info'}"></i><span>${Chege.escapeHtml(message)}</span>`;
  }

  function resetTokenStatus() {
    const el = $('token-status');
    if (!el) return;
    el.className = 'chege-token-status';
    el.innerHTML = '';
  }

  function setTokenVisible(visible) {
    const input = $('cloud_api_key');
    const btn = $('toggle-token-visibility');
    if (!input || !btn) return;
    input.type = visible ? 'text' : 'password';
    const icon = btn.querySelector('i');
    if (icon) icon.className = 'fas ' + (visible ? 'fa-eye-slash' : 'fa-eye');
    const label = visible ? 'Hide token' : 'Show token';
    btn.title = label;
    btn.setAttribute('aria-label', label);
  }

  function renderModelChoices(pid, selectedValue) {
    const models = modelCache[pid] || [];
    const select = $('cloud_model_select');
    const input = $('cloud_model');
    const value = (selectedValue ?? input.value ?? '').trim();
    const options = ['<option value="">Select a model…</option>']
      .concat(models.map((name) =>
        `<option value="${Chege.escapeHtml(name)}">${Chege.escapeHtml(name)}</option>`))
      .concat(['<option value="__custom__">Custom / type a model id…</option>']);
    select.innerHTML = options.join('');

    if (value && models.includes(value)) {
      select.value = value;
      input.value = value;
      input.classList.add('d-none');
    } else if (value) {
      select.value = '__custom__';
      input.value = value;
      input.classList.remove('d-none');
    } else if (models.length) {
      const preferred = providerById(pid)?.default_model;
      const picked = models.includes(preferred) ? preferred : models[0];
      select.value = picked;
      input.value = picked;
      input.classList.add('d-none');
    } else {
      select.value = '__custom__';
      input.value = '';
      input.classList.remove('d-none');
    }
  }

  function populateCloudModels(pid, models, note) {
    const clean = [...new Set((models || []).filter((name) => typeof name === 'string' && name.trim()))];
    modelCache[pid] = clean;
    const before = $('cloud_model').value.trim();
    renderModelChoices(pid, before);
    const after = $('cloud_model').value.trim();
    if (after && after !== before) dirtyProviders.add(pid);
    if (clean.length) {
      $('cloud-model-meta').textContent =
        `${note ? note + ' ' : ''}${clean.length} model(s) loaded — pick one, or choose Custom to type an id.`;
    } else {
      $('cloud-model-meta').textContent = note
        || 'The provider returned no models. Choose Custom and type a model id.';
    }
  }

  async function testTokenOnly() {
    if (!currentCloud) {
      setTokenStatus('error', 'Select a cloud provider first.');
      return;
    }
    captureCloudDraft();
    const pid = currentCloud;
    const profile = profiles[pid] || {};
    const token = (profile.api_key || '').trim();
    const body = {
      url: (profile.base_url || '').trim(),
      model: (profile.model || '').trim(),
    };
    // An unsaved token is tested exactly as typed; a mask means "use stored".
    if (token && token !== savedMasks[pid]) body.api_key = token;

    const btn = $('test-token-btn');
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Testing…';
    setTokenStatus('info', `Checking ${providerLabel(pid)} token…`);
    try {
      const result = await Chege.api(
        '/providers/' + encodeURIComponent(pid) + '/test-token',
        { method: 'POST', body: body },
      );
      const unsaved = Boolean(body.api_key);
      if (result.token_valid) {
        const suffix = unsaved ? ' Click Save as defaults to keep this token.' : '';
        setTokenStatus('ok', (result.message || 'Token is valid.') + suffix);
        populateCloudModels(pid, result.models || [], result.message);
      } else {
        setTokenStatus(result.status === 'warning' ? 'warning' : 'error',
          result.message || 'Token could not be verified.');
        if (Array.isArray(result.models) && result.models.length) {
          populateCloudModels(pid, result.models, result.message);
        }
      }
    } catch (e) {
      setTokenStatus('error', e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = original;
    }
  }

  function renderCloudPanel(pid) {
    resetTokenStatus();
    setTokenVisible(false);
    currentCloud = pid;
    const entry = providerById(pid) || {};
    const profile = baseProfile(pid);
    $('cloud-provider-title').textContent = entry.label || pid;
    $('cloud-provider-icon').className = 'fas ' + providerIcon(pid);
    $('cloud_base_url').value = profile.base_url || entry.base_url || '';
    $('cloud_base_url').placeholder = entry.base_url || 'https://api.example.com/v1';
    $('cloud_model').value = profile.model || '';
    $('cloud_model').placeholder = entry.default_model || 'Model id';
    renderModelChoices(pid, profile.model || '');
    $('cloud_api_key').value = profile.api_key || '';
    $('cloud_api_key').placeholder = profile.api_key_set
      ? 'Leave the masked token unchanged to keep it'
      : "Paste this provider's API token";
    $('cloud_max_tokens').value = profile.max_tokens ?? '';
    $('cloud-base-help').textContent = entry.base_url
      ? `Vendor default: ${entry.base_url}`
      : 'Enter the base URL of your OpenAI-compatible gateway.';
    $('cloud-provider-description').textContent = entry.description || '';
    $('cloud-provider-saved').classList.toggle('d-none', !profile.api_key_set);
    $('cloud-model-meta').textContent = modelCache[pid]?.length
      ? `${modelCache[pid].length} model(s) loaded. Pick one from the dropdown, or choose Custom to type an id.`
      : profile.api_key_set
        ? 'Token saved. Click Test token to refresh the model list, or type a model id.'
        : 'Paste the token above and click Test token to load this provider\'s models.';
    const link = $('cloud-docs-link');
    if (entry.docs_url) {
      link.href = entry.docs_url;
      link.classList.remove('d-none');
    } else {
      link.classList.add('d-none');
    }
  }

  function showProvider(provider) {
    const cloud = isCloudProvider(provider);
    resetDiagnostics();
    if (currentCloud && currentCloud !== provider) captureCloudDraft();
    document.querySelectorAll('.chege-provider-panel').forEach((panel) => {
      const target = panel.dataset.provider === '__cloud__' ? cloud : panel.dataset.provider === provider;
      panel.classList.toggle('d-none', !target);
    });
    if (cloud) renderCloudPanel(provider);
    else currentCloud = null;
    const badge = $('active-provider-badge');
    if (badge) badge.textContent = 'Active: ' + (cloud ? providerLabel(provider) : provider);
  }

  function fill(settings, savedTo) {
    if (!settings) return;
    TEXT_FIELDS.forEach((key) => {
      const el = $(key);
      if (el && settings[key] !== undefined && settings[key] !== null) el.value = settings[key];
    });
    const cloudGroup = $('cloud-provider-options');
    const clouds = providerCatalog.filter((p) => p.kind === 'cloud');
    if (cloudGroup && clouds.length) {
      cloudGroup.innerHTML = clouds.map((p) =>
        `<option value="${Chege.escapeHtml(p.id)}">${Chege.escapeHtml(p.label)}</option>`).join('');
    }

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

    // Build one persistent profile per cloud provider. The backend returns
    // masked tokens, so an untouched field is echoed back and recognised as
    // "keep the stored token".
    const savedProfiles = settings.provider_configs || {};
    profiles = {};
    savedMasks = {};
    providerCatalog.filter((p) => p.kind === 'cloud').forEach((entry) => {
      const saved = savedProfiles[entry.id] || {};
      savedMasks[entry.id] = saved.api_key || '';
      profiles[entry.id] = {
        base_url: saved.base_url ?? entry.base_url ?? '',
        api_key: saved.api_key ?? '',
        api_key_set: saved.api_key_set ?? Boolean(saved.api_key),
        model: saved.model ?? entry.default_model ?? '',
        max_tokens: saved.max_tokens ?? null,
      };
    });
    dirtyProviders.clear();
    currentCloud = null;

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
    captureCloudDraft();
    const payload = {
      default_provider: $('default_provider').value,
      llamacpp_url: $('llamacpp_url').value.trim(),
      ollama_url: $('ollama_url').value.trim(),
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

    // Only send provider profiles the operator actually touched. Untouched
    // providers keep whatever is already stored (or inherited from env).
    const configs = {};
    dirtyProviders.forEach((pid) => {
      const profile = profiles[pid];
      if (!profile) return;
      const config = {
        base_url: (profile.base_url || '').trim(),
        model: (profile.model || '').trim(),
        max_tokens: profile.max_tokens,
      };
      const token = (profile.api_key || '').trim();
      if (token) config.api_key = token;
      else if (profile.api_key_set) config.api_key = '';
      configs[pid] = config;
    });
    if (Object.keys(configs).length) payload.provider_configs = configs;
    return payload;
  }

  async function loadProviders() {
    try {
      const data = await Chege.api('/providers');
      providerCatalog = data.providers || [];
    } catch (_) {
      providerCatalog = [];
    }
  }

  async function load() {
    try {
      if (!providerCatalog.length) await loadProviders();
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
    resetDiagnostics();
    let pid = kind;
    let url = '';
    const body = {};

    if (kind === 'cloud') {
      captureCloudDraft();
      pid = currentCloud
        || (isCloudProvider($('default_provider').value) ? $('default_provider').value : null);
      if (!pid) {
        setResult('error', 'Select a cloud provider to test.');
        return;
      }
      const profile = profiles[pid] || {};
      url = (profile.base_url || '').trim();
      body.model = (profile.model || '').trim();
      const token = (profile.api_key || '').trim();
      // Send an unsaved token so Test works before pressing Save. Masked
      // values are left to the backend, which resolves the stored token.
      if (token && token !== savedMasks[pid]) body.api_key = token;
    } else if (kind === 'llama_cpp') {
      url = $('llamacpp_url').value.trim();
    } else {
      url = $('ollama_url').value.trim();
    }

    body.provider = pid;
    body.url = url;
    setResult('info', `Testing ${providerLabel(pid)} — endpoint, token and live model…`);
    try {
      const result = await Chege.api('/providers/test', { method: 'POST', body: body });
      renderDiagnostics(result);
      const status = result.status === 'ok' ? 'ok'
        : result.status === 'warning' ? 'info' : 'error';
      setResult(status, result.message || 'Test finished.');
    } catch (e) {
      setResult('error', e.message);
    }
  }

  async function loadModels() {
    const provider = $('default_provider').value;
    const cloud = isCloudProvider(provider);
    const label = cloud ? providerLabel(provider) : provider;
    setResult('info', `Loading models from ${label}…`);
    try {
      let models = [];
      let message = '';
      if (cloud) {
        const result = await Chege.api('/providers/' + encodeURIComponent(provider) + '/models');
        models = (result.models || []).map((m) =>
          typeof m === 'string' ? m : (m.id || m.name || '')).filter(Boolean);
        message = result.message || '';
        if (provider === currentCloud) {
          populateCloudModels(provider, models, message || undefined);
          if (!models.length) {
            $('cloud-model-meta').textContent = 'No models returned. Choose Custom and type a model id.';
          }
        }
      } else {
        const result = await Chege.api('/settings/models?provider=' + encodeURIComponent(provider));
        models = result.models || [];
      }
      const names = models.slice(0, 20).map((m) =>
        typeof m === 'string' ? m : (m.id || m.name || m.path || JSON.stringify(m)));
      $('model-list').textContent = names.length
        ? 'Models: ' + names.join(', ') + (models.length > 20 ? ` … (+${models.length - 20})` : '')
        : 'Provider returned no models. Test the token first, then retry.';
      setResult(models.length ? 'ok' : 'info', models.length
        ? `Found ${models.length} model(s) on ${label}.`
        : (message || `No models found on ${label}.`));
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
    $('test-cloud').addEventListener('click', () => testProvider('cloud'));
    $('test-token-btn').addEventListener('click', testTokenOnly);
    $('toggle-token-visibility').addEventListener('click', () => {
      setTokenVisible($('cloud_api_key').type === 'password');
    });
    $('cloud_api_key').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        testTokenOnly();
      }
    });
    ['cloud_base_url', 'cloud_api_key'].forEach((id) => {
      $(id).addEventListener('input', () => {
        if (currentCloud) dirtyProviders.add(currentCloud);
        resetTokenStatus();
      });
    });
    $('cloud_model_select').addEventListener('change', (event) => {
      if (!currentCloud) return;
      const value = event.target.value;
      const input = $('cloud_model');
      if (value === '__custom__') {
        input.classList.remove('d-none');
        input.focus();
        return;
      }
      input.value = value;
      input.classList.add('d-none');
      dirtyProviders.add(currentCloud);
    });
    $('cloud_model').addEventListener('input', () => {
      if (!currentCloud) return;
      dirtyProviders.add(currentCloud);
      const value = $('cloud_model').value.trim();
      const select = $('cloud_model_select');
      const values = Array.from(select.options)
        .map((option) => option.value)
        .filter((item) => item && item !== '__custom__');
      select.value = values.includes(value) ? value : '__custom__';
    });
    $('cloud_max_tokens').addEventListener('input', () => {
      if (currentCloud) dirtyProviders.add(currentCloud);
    });
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
