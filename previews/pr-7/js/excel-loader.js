// excel-loader.js — SheetJS wrappers used by both ACR and milestone pages.
// Exposes window.ExcelLoader.

(() => {
  const EXPORT_SHEET = 'Export';

  function ensureSheetJs() {
    if (typeof XLSX === 'undefined') {
      throw new Error('Excel library (SheetJS) failed to load. Make sure the web-app folder is intact and try again.');
    }
  }

  // Read a File object and return the first matching sheet's raw 2D array of rows.
  async function readSheet(file, sheetName) {
    ensureSheetJs();
    const buf = await file.arrayBuffer();
    let wb;
    try {
      wb = XLSX.read(buf, { type: 'array', cellDates: true });
    } catch (err) {
      throw new Error(`Could not read "${file.name}". The file may be encrypted, corrupt, or in an unsupported format. Original error: ${err.message}`);
    }
    if (!wb.SheetNames.length) {
      throw new Error(`Workbook "${file.name}" contains no sheets.`);
    }
    let name = sheetName;
    if (name && !wb.Sheets[name]) {
      // Case-insensitive match against existing sheets.
      const found = wb.SheetNames.find(s => s.toLowerCase() === String(name).toLowerCase());
      if (found) name = found;
      else {
        // Fall back to the first sheet but report what we found so users can rename.
        console.warn(`Sheet "${sheetName}" not found in ${file.name}. Available sheets: ${wb.SheetNames.join(', ')}. Falling back to "${wb.SheetNames[0]}".`);
        name = wb.SheetNames[0];
      }
    } else if (!name) {
      name = wb.SheetNames[0];
    }
    const ws = wb.Sheets[name];
    return XLSX.utils.sheet_to_json(ws, { header: 1, defval: null, raw: true });
  }

  // ACR workbook: tries the "Export" sheet first. Returns the raw rows array; the parser in
  // acr-model.js handles the two-row header.
  async function loadAcrWorkbook(file) {
    return await readSheet(file, EXPORT_SHEET);
  }

  // Milestone workbook: tries "Export" then falls back to the first sheet. Returns rows and
  // the sheet name that was actually used.
  async function loadMilestoneWorkbook(file) {
    return await readSheet(file, EXPORT_SHEET);
  }

  window.ExcelLoader = { loadAcrWorkbook, loadMilestoneWorkbook };
})();
