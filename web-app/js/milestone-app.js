// milestone-app.js — bootstraps the milestone gaps page.
(() => {
  const state = { migrationRows: null, defenderRows: null, migrationName: '', defenderName: '', model: null };

  document.addEventListener('DOMContentLoaded', init);

  function init() {
    document.getElementById('migration-input').addEventListener('change', e => handleFile(e, 'migration'));
    document.getElementById('defender-input').addEventListener('change', e => handleFile(e, 'defender'));
    document.getElementById('migration-btn').addEventListener('click', () => document.getElementById('migration-input').click());
    document.getElementById('defender-btn').addEventListener('click', () => document.getElementById('defender-input').click());
    document.getElementById('csv-btn').addEventListener('click', exportCsv);
    document.getElementById('pptx-btn').addEventListener('click', exportPptx);
    document.getElementById('near-term').addEventListener('change', rebuildIfReady);
    AppNav.onReload(() => {
      state.migrationRows = state.defenderRows = state.model = null;
      state.migrationName = state.defenderName = '';
      document.getElementById('migration-status').textContent = 'No file loaded';
      document.getElementById('defender-status').textContent = 'No file loaded';
      document.getElementById('milestone-shell').hidden = true;
      document.getElementById('milestone-empty').hidden = false;
      AppNav.setSource('');
    });
  }

  async function handleFile(event, kind) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    const statusEl = document.getElementById(kind + '-status');
    statusEl.textContent = 'Reading "' + file.name + '"…';
    try {
      const rows = await ExcelLoader.loadMilestoneWorkbook(file);
      state[kind + 'Rows'] = rows;
      state[kind + 'Name'] = file.name;
      statusEl.textContent = '✓ ' + file.name + ' — ' + (rows.length - 1) + ' rows';
      statusEl.className = 'file-status success';
      rebuildIfReady();
    } catch (err) {
      console.error(err);
      statusEl.textContent = 'Failed: ' + err.message;
      statusEl.className = 'file-status error';
    } finally {
      event.target.value = '';
    }
  }

  function rebuildIfReady() {
    if (!state.migrationRows || !state.defenderRows) return;
    try {
      const nearTerm = parseInt(document.getElementById('near-term').value, 10);
      const model = MilestoneModel.build(state.migrationRows, state.defenderRows, {
        near_term_days: nearTerm,
        migration_name: state.migrationName,
        defender_name: state.defenderName,
      });
      state.model = model;
      AppNav.setSource(`Migration: ${state.migrationName} · Defender: ${state.defenderName}`);
      MilestoneView.render(model);
      document.getElementById('csv-btn').disabled = false;
      document.getElementById('pptx-btn').disabled = false;
    } catch (err) {
      console.error(err);
      const empty = document.getElementById('milestone-empty');
      empty.hidden = false;
      empty.querySelector('.error-msg').textContent = 'Could not build the gap model: ' + err.message;
    }
  }

  function exportCsv() {
    if (!state.model) return;
    const columns = [
      { key: 'account',        label: 'account' },
      { key: 'opportunity_id', label: 'opportunity_id' },
      { key: 'gap_type',       label: 'gap_type' },
      { key: 'workload',       label: 'workload' },
      { key: 'estimated_date', label: 'estimated_date' },
      { key: 'priority',       label: 'priority' },
      { key: 'commitment',     label: 'commitment' },
      { key: 'status',         label: 'status' },
      { key: 'acr_pipeline',   label: 'acr_pipeline' },
      { key: 'owner_role',     label: 'owner_role' },
      { key: 'owner',          label: 'owner' },
      { key: 'milestone_count', label: 'milestone_count' },
      { key: 'priority_reason', label: 'priority_reason' },
    ];
    const today = new Date().toISOString().slice(0, 10);
    CsvExport.download(`milestone-gaps-${today}.csv`, columns, state.model.gaps || []);
  }

  async function exportPptx() {
    if (!state.model) return;
    const btn = document.getElementById('pptx-btn');
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = 'Building deck…';
    try {
      await PptxMilestones.exportDeck(state.model);
    } catch (err) {
      console.error(err);
      alert('PPT export failed: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  }
})();
