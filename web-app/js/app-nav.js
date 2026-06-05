// app-nav.js - shared app shell rendered into <div id="app-nav"></div> on each page.
// Pass the active key ("home", "acr", or "milestones") via data-active on the container.
(() => {
  const root = document.getElementById('app-nav');
  if (!root) return;
  const active = root.dataset.active || 'acr';
  const linkClass = key => key === active ? 'active' : '';
  const title = active === 'milestones'
    ? 'Defender for Cloud - Milestone Gaps'
    : 'Defender for Cloud - Customer Opportunity Dashboard';
  const salesPlanButton = active === 'acr'
    ? '<button type="button" class="menu-action sales-plan-action" id="build-sales-plan-btn" disabled title="Coming soon">Build sales plan</button>'
    : '';
  document.body.classList.add('shell-ready', `shell-${active}`);
  root.innerHTML = `
    <div class="app-shell" aria-label="Defender Attach shell">
      <header class="app-topbar">
        <div class="topbar-title">${title}</div>
        <div class="topbar-actions">
          <span class="source-pill" id="source-pill" title="">No data loaded yet</span>
          ${salesPlanButton}
          <button type="button" class="menu-action" id="reload-btn" title="Pick a new file">Load data</button>
        </div>
      </header>
      <aside class="app-sidebar" aria-label="Main">
        <nav class="app-menu">
          <a href="index.html" class="${linkClass('home')}"><span aria-hidden="true">HM</span> Home</a>
          <a href="acr.html" class="${linkClass('acr')}"><span aria-hidden="true">ACR</span> ACR opportunities</a>
          <a href="milestones.html" class="${linkClass('milestones')}"><span aria-hidden="true">MS</span> Milestone gaps</a>
        </nav>
        <div class="sidebar-meta">
          <span>Local-first analytics</span>
          <strong>Excel data stays on this machine</strong>
        </div>
      </aside>
    </div>
  `;
})();

// Helpers used by both pages.
window.AppNav = {
  setSource(label) {
    const pill = document.getElementById('source-pill');
    if (!pill) return;
    pill.textContent = label || 'No data loaded yet';
    pill.title = label || '';
  },
  onReload(handler) {
    const btn = document.getElementById('reload-btn');
    if (btn) btn.addEventListener('click', handler);
  },
};
