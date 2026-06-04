// csv-export.js — produces a UTF-8-BOM CSV download from rows + columns spec.
// Exposes window.CsvExport.download(filename, columns, rows)
(() => {
  // Per OWASP CSV-injection guidance: cells starting with =, +, -, @, tab, or CR
  // are interpreted as formulas by Excel/Sheets. Since cells originate from
  // untrusted workbooks (account names, notes, owner, ...), we prefix a single
  // quote so the consumer sees the literal value, not a formula.
  const FORMULA_PREFIX = /^[=+\-@\t\r]/;
  function escape(value) {
    if (value == null) return '';
    let s = String(value);
    if (FORMULA_PREFIX.test(s)) s = "'" + s;
    if (s.includes('"') || s.includes(',') || s.includes('\n') || s.includes('\r')) {
      s = '"' + s.replace(/"/g, '""') + '"';
    }
    return s;
  }
  function download(filename, columns, rows) {
    const lines = [columns.map(c => escape(c.label)).join(',')];
    for (const r of rows) {
      lines.push(columns.map(c => escape(typeof c.value === 'function' ? c.value(r) : r[c.key])).join(','));
    }
    const blob = new Blob(['\uFEFF' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }
  window.CsvExport = { download };
})();
