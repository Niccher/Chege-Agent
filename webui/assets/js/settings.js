/* Unified settings console — reads, tests and saves /api/v1/settings. */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => Chege.escapeHtml(value);
  let maskedApiKey = '';

  function setResult(status, message) {
    const el = $('provider-test-result');
    const kind = status === 'ok' ? ' is-ok' : status === 'error' ? ' is-error' : '';
    el.className = 'chege-test-result' + kind;
    el.textContent = message;
  }

  function fill(settings, savedTo) {
    if (!settings) return;
    $('default_provider').value = settings.default_provider || 'llama_cpp';
    $('llamacpp_url').value = settings.llamacpp_url || '';
    $('ollama_url').value = settings.ollama_url || '';
    $('openai_base_url').value = settings.openai_base_url || '';
    maskedApiKey = settings.openai_api_key || '';
    $('openai_api_key').value = maskedApiKey;
    $('sandbox_backend').value = settings.sandbox_backend || 'docker';
    $('default_context_window').value = settings.default_context_window || 16384;
    $('max_steps').value = settings.max_steps || 50;
    $('run_timeout_seconds').value = settings.run_timeout_seconds || 600;

    const db = settings.database_url && settings.database_url.startsWith('postgres') ? 'Postgres' : 'SQLite';
    $('settings-summary').textContent =
      `${settings.default_provider} · ${settings.sandbox_backend} sandbox · ${db} · ${settings.max_steps} steps`;
    $('settings-source').textContent = savedTo
      ? `Saved defaults loaded from ${savedTo}`
      : 'Runtime values from env/.env — use Save as defaults to persist';
    $('active-provider-badge').textContent = 'Active: ' + settings.default_provider;

    $('ref-host').textContent = settings.host || '—';
    $('ref-port').textContent = String(settings.port || '—');
    $('ref-database').textContent = settings.database_url || 'embedded SQLite';
    $('ref-data').textContent = settings.data_dir || '—';
    $('ref-workdir').textContent = settings.workdir || '—';
    $('ref-logs').textContent = settings.logs_dir || '—';

    Chege.syncTheme(Chege.themePreference());
  }

  function collect() {
    const payload = {
      default_provider: $('default_provider').value,
      llamacpp_url: $('llamacpp_url').value.trim(),
      ollama_url: $('ollama_url').value.trim(),
      openai_base_url: $('openai_base_url').value.trim(),
      sandbox_backend: $('sandbox_backend').value,
      default_context_window: Number($('default_context_window').value),
      max_steps: Number($('max_steps').value),
      run_timeout_seconds: Number($('run_timeout_seconds').value),
    };
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
      const names = models.slice(0, 12).map((m) => typeof m === 'string' ? m : (m.id || m.name || JSON.stringify(m)));
      $('model-list').textContent = names.length
        ? 'Models: ' + names.join(', ') + (models.length > 12 ? ` … (+${models.length - 12})` : '')
        : 'Provider returned no models.';
      setResult(models.length ? 'ok' : 'info', models.length ? `Found ${models.length} model(s).` : 'No models found.');
    } catch (e) {
      $('model-list').textContent = '';
      setResult('error', e.message);
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
    $('apply-settings').addEventListener('click', () => write(false));
    $('save-settings').addEventListener('click', () => write(true));
    $('reset-settings').addEventListener('click', load);
    $('clear-defaults').addEventListener('click', clearDefaults);
    $('test-llamacpp').addEventListener('click', () => testProvider('llama_cpp'));
    $('test-ollama').addEventListener('click', () => testProvider('ollama'));
    $('test-openai').addEventListener('click', () => testProvider('openai'));
    $('load-models').addEventListener('click', loadModels);
    load();
  });
})();
