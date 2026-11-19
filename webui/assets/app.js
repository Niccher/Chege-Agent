/* Chege Agent — shared shell, theme, API helper and markdown rendering.
   Theme state uses AdminLTE 4's ColorMode (localStorage key `lte-theme`) so
   every page and every Bootstrap/AdminLTE component switches together. */
(function () {
  const API = '/api/v1';
  const THEME_KEY = 'lte-theme';
  const THEME_ORDER = ['light', 'dark', 'auto'];

  function colorMode() {
    return window.adminlte && window.adminlte.ColorMode
      ? new window.adminlte.ColorMode()
      : null;
  }

  function storedTheme() {
    try {
      const value = localStorage.getItem(THEME_KEY);
      return THEME_ORDER.includes(value) ? value : null;
    } catch (_) {
      return null;
    }
  }

  function themePreference() {
    const mode = colorMode();
    if (mode) return mode.getStoredTheme() || mode.getMarkupTheme() || 'light';
    return storedTheme() || 'light';
  }

  function resolveTheme(preference) {
    if (preference === 'auto') {
      return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark' : 'light';
    }
    return preference === 'dark' ? 'dark' : 'light';
  }

  function syncTheme(preference) {
    const pref = THEME_ORDER.includes(preference) ? preference : 'light';
    const resolved = resolveTheme(pref);
    const root = document.documentElement;

    root.setAttribute('data-bs-theme', resolved);
    root.style.colorScheme = resolved;
    document.body.classList.toggle('dark-mode', resolved === 'dark');
    document.body.dataset.chegeTheme = pref;

    document.querySelectorAll('[data-bs-theme-value]').forEach(function (btn) {
      const active = btn.getAttribute('data-bs-theme-value') === pref;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', String(active));
    });

    document.querySelectorAll('[data-chege-theme-toggle]').forEach(function (btn) {
      const icon = resolved === 'dark' ? 'fa-moon' : resolved === 'light' ? 'fa-sun' : 'fa-circle-half-stroke';
      const next = THEME_ORDER[(THEME_ORDER.indexOf(pref) + 1) % THEME_ORDER.length];
      btn.innerHTML = '<i class="fas ' + icon + '"></i>';
      btn.setAttribute('aria-label', 'Theme: ' + pref + ' — switch to ' + next);
      btn.title = 'Theme: ' + pref + ' (click for ' + next + ')';
    });
  }

  function setTheme(preference) {
    const pref = THEME_ORDER.includes(preference) ? preference : 'light';
    const mode = colorMode();
    if (mode) {
      mode.setTheme(pref); // fires changed.lte.color-mode → syncTheme()
    } else {
      try { localStorage.setItem(THEME_KEY, pref); } catch (_) {}
      syncTheme(pref);
    }
  }

  function cycleTheme() {
    const pref = themePreference();
    setTheme(THEME_ORDER[(THEME_ORDER.indexOf(pref) + 1) % THEME_ORDER.length]);
  }

  document.addEventListener('changed.lte.color-mode', function (event) {
    syncTheme(event.detail && event.detail.theme ? event.detail.theme : themePreference());
  });

  document.addEventListener('click', function (event) {
    if (event.target.closest('[data-chege-theme-toggle]')) cycleTheme();
  });

  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
      if (themePreference() === 'auto') syncTheme('auto');
    });
  }

  syncTheme(themePreference());

  async function api(path, options = {}) {
    const opts = Object.assign({}, options);
    if (opts.body && typeof opts.body !== 'string') {
      opts.body = JSON.stringify(opts.body);
      opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
    }
    const res = await fetch(API + path, opts);
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok) {
      const detail = data && (data.detail || data.message) ? (data.detail || data.message) : res.statusText;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
  }

  function escapeHtml(value) {
    const el = document.createElement('div');
    el.textContent = value == null ? '' : String(value);
    return el.innerHTML;
  }

  function markdown(text) {
    if (typeof marked === 'undefined') return escapeHtml(text);
    const raw = marked.parse(text || '', { breaks: true, gfm: true });
    return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(raw) : raw;
  }

  function highlight(element) {
    if (typeof hljs !== 'undefined' && element) {
      element.querySelectorAll('pre code').forEach((block) => hljs.highlightElement(block));
    }
  }

  function navItem(href, icon, label, active, external) {
    const cls = 'nav-link' + (active === href ? ' active' : '');
    return `<li class="nav-item"><a href="${href}" class="${cls}"${external ? ' target="_blank" rel="noopener"' : ''}>
      <i class="nav-icon ${icon}"></i><span>${label}</span></a></li>`;
  }

  const TOP_LINKS = [
    ['/', 'Overview'],
    ['/guide', 'Guide'],
    ['/api', 'API'],
    ['/security', 'Safety'],
    ['/settings', 'Settings'],
    ['/models', 'Models'],
    ['/status', 'Status'],
  ];

  function shell(active) {
    const nav = document.getElementById('chege-navbar');
    const side = document.getElementById('chege-sidebar');
    const foot = document.getElementById('chege-footer');

    // AdminLTE 4 assigns grid areas by class, so the placeholders themselves
    // must carry the app-* classes (a nested <header> would break the layout).
    if (nav) {
      nav.className = 'app-header navbar navbar-expand bg-body';
      nav.innerHTML = `
        <div class="container-fluid">
          <ul class="navbar-nav align-items-center">
            <li class="nav-item">
              <button class="nav-link px-2" type="button" data-lte-toggle="sidebar" aria-label="Toggle sidebar">
                <i class="fas fa-bars"></i>
              </button>
            </li>
            <li class="nav-item d-none d-sm-flex align-items-center">
              <a href="/" class="navbar-brand chege-brand ms-2 mb-0">
                <span class="chege-brand-mark"><i class="fas fa-robot"></i></span>Chege Agent
              </a>
            </li>
          </ul>
          <ul class="navbar-nav ms-auto align-items-center chege-top-nav">
            ${TOP_LINKS.map(([href, label]) => `<li class="nav-item chege-top-link">
              <a href="${href}" class="nav-link${active === href ? ' active' : ''}">${label}</a></li>`).join('')}
            <li class="nav-item ms-2">
              <button class="btn btn-sm btn-outline-secondary chege-theme-btn" id="chege-theme"
                      type="button" data-chege-theme-toggle title="Toggle theme"><i class="fas fa-sun"></i></button>
            </li>
            <li class="nav-item ms-2"><a class="btn btn-sm btn-primary" href="/app">
              <i class="fas fa-play"></i> Open Playground</a></li>
          </ul>
        </div>`;
    }

    if (side) {
      side.className = 'app-sidebar bg-dark';
      side.setAttribute('data-bs-theme', 'dark');
      side.innerHTML = `
        <div class="sidebar-brand">
          <a href="/" class="brand-link">
            <span class="chege-brand-mark"><i class="fas fa-robot"></i></span>
            <span class="brand-text chege-brand">Chege Agent</span>
          </a>
        </div>
        <div class="sidebar-wrapper">
          <nav class="mt-2">
            <ul class="nav nav-pills flex-column chege-sidebar-nav" role="menu">
              ${navItem('/', 'fas fa-house', 'Overview', active)}
              ${navItem('/guide', 'fas fa-book', 'How it works', active)}
              ${navItem('/app', 'fas fa-terminal', 'Playground', active)}
              ${navItem('/api', 'fas fa-plug', 'API reference', active)}
              ${navItem('/settings', 'fas fa-sliders', 'Settings console', active)}
              ${navItem('/models', 'fas fa-brain', 'Models', active)}
              ${navItem('/status', 'fas fa-heart-pulse', 'System status', active)}
              ${navItem('/security', 'fas fa-shield-halved', 'Safety model', active)}
              <li class="nav-header">REFERENCE</li>
              ${navItem('/setup', 'fas fa-download', 'Setup guide', active)}
              ${navItem('/docs', 'fas fa-code', 'Swagger UI', active, true)}
            </ul>
          </nav>
          <div class="mt-auto p-3 small chege-sidebar-note">Personal, local-only agent.<br>No login. Loopback only.</div>
        </div>`;
    }

    if (foot) {
      foot.className = 'app-footer chege-footer';
      foot.innerHTML = `
        <div class="container-fluid d-flex flex-wrap justify-content-between align-items-center gap-2">
          <span><strong>Chege Agent</strong> · personal, local-only · no login, no telemetry</span>
          <span class="chege-footer-links">
            <a href="/guide">Guide</a> · <a href="/setup">Setup</a> · <a href="/settings">Settings</a> ·
            <a href="/models">Models</a> · <a href="/api">API</a> · <a href="/security">Safety</a> · <a href="/status">Status</a> ·
            <a href="/docs" target="_blank" rel="noopener">Swagger</a> · <a href="/healthz">Health</a>
          </span>
        </div>`;
    }

    syncTheme(themePreference());
  }

  function alertBox(message, kind) {
    const host = document.getElementById('chege-alerts');
    if (!host) return;
    host.innerHTML = `<div class="alert alert-${kind || 'info'} alert-dismissible fade show" role="alert">
      ${escapeHtml(message)}<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button></div>`;
  }

  function setHostLabels() {
    const host = window.location.host || '127.0.0.1';
    document.querySelectorAll('.chege-host').forEach(function (el) { el.textContent = host; });
  }
  setHostLabels();

  window.Chege = {
    API, api, escapeHtml, markdown, highlight, shell, alertBox, setHostLabels,
    setTheme, cycleTheme, themePreference, syncTheme
  };
})();
