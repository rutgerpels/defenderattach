// sl-app.js — bootstraps the service-attach (SL2/SL4) page.
// Single workbook in, parsed entirely client-side, scored, and rendered.
// Mirrors the milestone-app.js lifecycle (file load, sessionStorage cache,
// reload, exports) but for the per-service attach motion.
(() => {
  'use strict';

  const state = { rows: null, sourceName: '', model: null };
  const CACHE_KEY = 'defenderattach:service:v1';

  document.addEventListener('DOMContentLoaded', init);

  function errorEl() {
    return document.querySelector('#sa-empty .error-msg');
  }

  function setError(message) {
    const el = errorEl();
    if (el) el.textContent = message || '';
  }

  function init() {
    document.getElementById('sl-btn').addEventListener('click', () => document.getElementById('sl-input').click());
    document.getElementById('sl-input').addEventListener('change', handleFile);

    document.getElementById('sa-apply-btn').addEventListener('click', () => { rebuildIfReady(); persist(); });
    document.getElementById('sa-json-btn').addEventListener('click', exportJson);
    document.getElementById('sa-md-btn').addEventListener('click', exportMarkdown);
    document.getElementById('sa-csv-btn').addEventListener('click', exportCsv);
    document.getElementById('sa-pptx-btn').addEventListener('click', exportPptx);

    seedControls(SLMapping.defaultConfig());

    AppNav.onReload(() => {
      state.rows = state.model = null;
      state.sourceName = '';
      if (window.SLView) SLView.reset();
      document.getElementById('sl-status').textContent = 'No file loaded';
      document.getElementById('sl-status').className = 'file-status';
      document.getElementById('sa-shell').hidden = true;
      document.getElementById('sa-empty').hidden = false;
      setError('');
      AppNav.setSource('');
      try { sessionStorage.removeItem(CACHE_KEY); } catch (_) {}
    });

    restoreFromSession();
  }

  function seedControls(config) {
    document.getElementById('sa-target-ratio').value = (config.targetRatio * 100).toString();
    document.getElementById('sa-w-gap').value = config.weightGap.toString();
    document.getElementById('sa-w-mom').value = config.weightMomentum.toString();
    document.getElementById('sa-w-breadth').value = config.weightBreadth.toString();
  }

  function readConfig() {
    const config = SLMapping.defaultConfig();
    const ratio = parseFloat(document.getElementById('sa-target-ratio').value);
    const wGap = parseFloat(document.getElementById('sa-w-gap').value);
    const wMom = parseFloat(document.getElementById('sa-w-mom').value);
    const wBreadth = parseFloat(document.getElementById('sa-w-breadth').value);
    if (Number.isFinite(ratio) && ratio >= 0) config.targetRatio = ratio / 100;
    if (Number.isFinite(wGap) && wGap >= 0) config.weightGap = wGap;
    if (Number.isFinite(wMom) && wMom >= 0) config.weightMomentum = wMom;
    if (Number.isFinite(wBreadth) && wBreadth >= 0) config.weightBreadth = wBreadth;
    return config;
  }

  function persist() {
    if (!state.rows) return;
    try {
      const payload = JSON.stringify({
        rows: state.rows,
        sourceName: state.sourceName,
        config: readConfig(),
      });
      // 4.5 MB ceiling — leaves headroom under the 5 MB sessionStorage quota.
      if (payload.length < 4500000) sessionStorage.setItem(CACHE_KEY, payload);
      else console.warn('Service-attach data too large to cache in sessionStorage.');
    } catch (err) {
      console.warn('Could not cache service-attach data:', err);
    }
  }

  function restoreFromSession() {
    let cached;
    try { cached = sessionStorage.getItem(CACHE_KEY); }
    catch (_) { return; }
    if (!cached) return;
    try {
      const parsed = JSON.parse(cached);
      if (!parsed || !Array.isArray(parsed.rows)) return;
      state.rows = parsed.rows;
      state.sourceName = parsed.sourceName || '';
      if (parsed.config) seedControls(parsed.config);
      const status = document.getElementById('sl-status');
      status.textContent = '✓ ' + state.sourceName + ' — restored from session';
      status.className = 'file-status success';
      rebuildIfReady();
    } catch (err) {
      console.warn('Could not restore cached service-attach data:', err);
      try { sessionStorage.removeItem(CACHE_KEY); } catch (_) {}
    }
  }

  async function handleFile(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    const status = document.getElementById('sl-status');
    setError('');
    status.textContent = 'Reading "' + file.name + '"…';
    status.className = 'file-status';
    try {
      const rows = await ExcelLoader.loadAcrWorkbook(file);
      state.rows = rows;
      state.sourceName = file.name;
      status.textContent = '✓ ' + file.name + ' — ' + Math.max(0, rows.length - 2) + ' data rows';
      status.className = 'file-status success';
      rebuildIfReady();
      persist();
    } catch (err) {
      console.error(err);
      status.textContent = 'Failed: ' + err.message;
      status.className = 'file-status error';
      setError('Could not read the workbook: ' + err.message);
    } finally {
      event.target.value = '';
    }
  }

  function rebuildIfReady() {
    if (!state.rows) return;
    try {
      const parsed = SLParser.parseSl2Sl4(state.rows, state.sourceName);
      const model = SLEngine.buildModel(parsed, readConfig());
      state.model = model;
      AppNav.setSource('Source: ' + state.sourceName + ' · ' + model.latestMonth);
      SLView.render(model);
      ['sa-json-btn', 'sa-md-btn', 'sa-csv-btn', 'sa-pptx-btn'].forEach((id) => {
        document.getElementById(id).disabled = false;
      });
      setError('');
    } catch (err) {
      console.error(err);
      state.model = null;
      document.getElementById('sa-shell').hidden = true;
      document.getElementById('sa-empty').hidden = false;
      setError('Could not build the attach model: ' + err.message);
    }
  }

  function downloadText(filename, text, mime) {
    const blob = new Blob([text], { type: (mime || 'text/plain') + ';charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  function today() { return new Date().toISOString().slice(0, 10); }

  function exportJson() {
    if (!state.model) return;
    downloadText(`defender-attach-data-${today()}.json`, SLExport.buildJsonText(state.model), 'application/json');
  }

  function exportMarkdown() {
    if (!state.model) return;
    const jsonName = `defender-attach-data-${today()}.json`;
    downloadText(`defender-attach-brief-${today()}.md`, SLExport.buildMarkdown(state.model, jsonName, 15), 'text/markdown');
  }

  function exportCsv() {
    if (!state.model) return;
    // One row per opportunity — the unit a seller acts on.
    const rows = [];
    for (const d of state.model.dossiers) {
      for (const o of d.opportunities) {
        rows.push({
          customer: d.customer,
          customer_score: Math.round(d.customerScore),
          plan: o.planLabel,
          signal: o.signal,
          confidence: o.confidence,
          workload_acr: Math.round(o.workloadAcr),
          defender_acr: Math.round(o.defenderActual),
          benchmark_acr: o.hasDollarGap ? Math.round(o.expected) : '',
          gap_dollars: o.hasDollarGap ? Math.round(o.gapDollars) : '',
          coverage_pct: o.hasDollarGap && Number.isFinite(o.coveragePct) ? (o.coveragePct * 100).toFixed(1) : '',
          workload_growth_3m: Number.isFinite(o.workloadGrowth) ? (o.workloadGrowth * 100).toFixed(0) : '',
          defender_growth_3m: Number.isFinite(o.defenderGrowth) ? (o.defenderGrowth * 100).toFixed(0) : '',
          blended_score: Math.round(o.blendedScore),
          opener: o.opener,
        });
      }
    }
    const columns = [
      'customer', 'customer_score', 'plan', 'signal', 'confidence',
      'workload_acr', 'defender_acr', 'benchmark_acr', 'gap_dollars', 'coverage_pct',
      'workload_growth_3m', 'defender_growth_3m', 'blended_score', 'opener',
    ].map((key) => ({ key, label: key }));
    CsvExport.download(`defender-attach-opportunities-${today()}.csv`, columns, rows);
  }

  async function exportPptx() {
    if (!state.model) return;
    const btn = document.getElementById('sa-pptx-btn');
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = 'Building deck…';
    try {
      await PptxSl.exportDeck(state.model);
    } catch (err) {
      console.error(err);
      alert('PowerPoint export failed: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  }
})();
