/* Tool governance console — reads and patches /api/v1/tools. */
(function () {
  const $ = (id) => document.getElementById(id);
  let tools = [];
  let riskFilter = 'all';

  const RISK_LABEL = {
    read: { text: 'Read', cls: 'bg-info' },
    write: { text: 'Write', cls: 'bg-primary' },
    exec: { text: 'Exec', cls: 'bg-warning' },
  };

  function badge(risk) {
    const meta = RISK_LABEL[risk] || { text: risk || 'read', cls: 'bg-secondary' };
    return `<span class="badge ${meta.cls}">${Chege.escapeHtml(meta.text)}</span>`;
  }

  function render() {
    const grid = $('tool-grid');
    const query = ($('tool-search').value || '').toLowerCase().trim();
    const visible = tools.filter((t) => {
      const riskOk = riskFilter === 'all' || t.risk === riskFilter;
      const text = (t.name + ' ' + (t.purpose || '') + ' ' + (t.description || '')).toLowerCase();
      return riskOk && (!query || text.includes(query));
    });

    if (!visible.length) {
      grid.innerHTML = '<div class="col-12"><div class="empty-state"><i class="fas fa-magnifying-glass fa-3x mb-3"></i><p>No tools match this filter.</p></div></div>';
      return;
    }

    grid.innerHTML = visible.map((t) => `
      <div class="col-md-6 col-xl-4">
        <div class="chege-tool-card${t.enabled ? '' : ' is-disabled'}" data-tool="${Chege.escapeHtml(t.name)}">
          <div class="chege-tool-head">
            <span class="chege-tool-name"><i class="fas fa-wrench"></i> ${Chege.escapeHtml(t.name)}</span>
            ${badge(t.risk)}
          </div>
          <div class="chege-tool-purpose">${Chege.escapeHtml(t.purpose || t.description || '')}</div>
          <div class="chege-tool-desc">${Chege.escapeHtml(t.description || '')}</div>
          <div class="chege-tool-controls">
            <label title="Activate or deactivate this tool">
              <input type="checkbox" class="tool-enabled" ${t.enabled ? 'checked' : ''}> Enabled
            </label>
            <label title="Ask for permission before the agent uses this tool in a run">
              Grant
              <select class="form-select form-select-sm tool-grant">
                <option value="none"${t.grant_mode === 'none' ? ' selected' : ''}>No grant</option>
                <option value="prompt_once"${t.grant_mode === 'prompt_once' ? ' selected' : ''}>Prompt once</option>
              </select>
            </label>
            <button type="button" class="btn btn-sm btn-outline-primary chege-tool-save">
              <i class="fas fa-floppy-disk"></i> Save
            </button>
          </div>
        </div>
      </div>`).join('');

    grid.querySelectorAll('.chege-tool-card').forEach((card) => {
      const name = card.dataset.tool;
      const enabled = card.querySelector('.tool-enabled');
      const grant = card.querySelector('.tool-grant');
      const save = card.querySelector('.chege-tool-save');
      [enabled, grant].forEach((el) => el.addEventListener('change', () => card.classList.add('is-dirty')));
      save.addEventListener('click', () => saveTool(card, name, enabled.checked, grant.value));
    });
  }

  async function saveTool(card, name, enabled, grantMode) {
    const original = tools.find((t) => t.name === name);
    if (!original) return;
    const btn = card.querySelector('.chege-tool-save');
    btn.disabled = true;
    try {
      const result = await Chege.api('/tools/' + encodeURIComponent(name), {
        method: 'PATCH',
        body: { enabled: enabled, grant_mode: grantMode },
      });
      const index = tools.findIndex((t) => t.name === name);
      tools[index] = result.tool;
      card.classList.remove('is-dirty');
      card.classList.add('is-saved');
      card.classList.toggle('is-disabled', !result.tool.enabled);
      setTimeout(() => card.classList.remove('is-saved'), 1200);
      updateSummary();
      Chege.alertBox(`${name} updated.`, 'success');
    } catch (e) {
      card.querySelector('.tool-enabled').checked = original.enabled;
      card.querySelector('.tool-grant').value = original.grant_mode;
      Chege.alertBox('Could not update ' + name + ': ' + e.message, 'danger');
    } finally {
      btn.disabled = false;
    }
  }

  function updateSummary() {
    const enabled = tools.filter((t) => t.enabled).length;
    const gated = tools.filter((t) => t.enabled && t.grant_mode === 'prompt_once').length;
    $('tools-summary').textContent =
      `${enabled} of ${tools.length} tools active · ${gated} require a grant prompt · restarts not needed`;
  }

  function formatTime(value) {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }

  function formatDuration(ms) {
    if (ms == null) return '';
    if (ms < 1000) return `${ms} ms`;
    return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
  }

  function statusBadge(status) {
    const meta = status === 'completed'
      ? { cls: 'bg-success', label: 'Completed' }
      : status === 'error'
        ? { cls: 'bg-danger', label: 'Error' }
        : { cls: 'bg-secondary', label: status || 'Running' };
    return `<span class="badge ${meta.cls}">${Chege.escapeHtml(meta.label)}</span>`;
  }

  function renderActivity(data) {
    const rows = data.activity || [];
    const body = $('tool-activity-body');
    const summary = $('activity-summary');
    if (!rows.length) {
      summary.textContent = 'No tool calls recorded yet.';
      body.innerHTML = '<tr><td colspan="5" class="text-muted small">Run the agent and its tool calls will appear here automatically.</td></tr>';
      return;
    }
    summary.textContent = `${rows.length} recent tool call${rows.length === 1 ? '' : 's'} · newest first`;
    body.innerHTML = rows.map((row) => {
      const project = `${Chege.escapeHtml(row.project_name || row.project_slug || '—')} / ${Chege.escapeHtml(row.session_title || '—')}`;
      const result = row.result_preview
        ? `<div class="small text-muted mt-1">${Chege.escapeHtml(row.result_preview)}</div>`
        : '';
      return `<tr>
        <td class="text-nowrap"><div>${Chege.escapeHtml(formatTime(row.started_at))}</div>
          <div class="small text-muted">${Chege.escapeHtml(formatDuration(row.duration_ms))}</div></td>
        <td class="small">${project}</td>
        <td><code>${Chege.escapeHtml(row.tool || '—')}</code></td>
        <td>${Chege.escapeHtml(row.summary || '—')}</td>
        <td>${statusBadge(row.status)}${result}</td>
      </tr>`;
    }).join('');
  }

  async function loadActivity() {
    try {
      const data = await Chege.api('/activity/tools?limit=80');
      renderActivity(data);
    } catch (e) {
      $('activity-summary').textContent = 'Could not load tool activity: ' + e.message;
      $('tool-activity-body').innerHTML = '<tr><td colspan="5" class="text-danger small">Activity unavailable.</td></tr>';
    }
  }

  async function load() {
    try {
      const data = await Chege.api('/tools');
      tools = data.tools || [];
      updateSummary();
      render();
    } catch (e) {
      Chege.alertBox('Could not load tools: ' + e.message, 'danger');
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    Chege.shell('/tools');
    $('tool-search').addEventListener('input', render);
    $('risk-filter').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-risk]');
      if (!btn) return;
      riskFilter = btn.dataset.risk;
      $('risk-filter').querySelectorAll('[data-risk]').forEach((b) => b.classList.toggle('active', b === btn));
      render();
    });
    $('refresh-activity').addEventListener('click', loadActivity);
    load();
    loadActivity();
  });
})();
