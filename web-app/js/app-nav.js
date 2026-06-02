// app-nav.js — top navigation rendered into <div id="app-nav"></div> on each page.
// Pass the active key ("acr" or "milestones") via data-active on the container.
(() => {
  const root = document.getElementById('app-nav');
  if (!root) return;
  const active = root.dataset.active || 'acr';
  const linkClass = key => key === active ? 'active' : '';
  root.innerHTML = `
    <nav class="app-menu" aria-label="Main">
      <a href="index.html" class="${linkClass('acr')}">📊 ACR opportunities</a>
      <a href="service-attach.html" class="${linkClass('service')}">🛡️ Service attach</a>
      <a href="milestones.html" class="${linkClass('milestones')}">🎯 Milestone gaps</a>
      <span class="spacer"></span>
      <span class="source-pill" id="source-pill" title="">No data loaded yet</span>
      <button type="button" class="menu-action" id="reload-btn" title="Pick a new file">Load other file</button>
    </nav>
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
