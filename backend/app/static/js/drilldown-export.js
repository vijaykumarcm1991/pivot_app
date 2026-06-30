/**
 * drilldown-export.js — Export the current drill-down view to .xlsx.
 *
 * Public API on `window.DrilldownExport`:
 *   exportCurrentView()
 *       — Build a workbook from the current drill-down grid view and
 *         trigger a browser download. Returns the chosen filename
 *         (or null when there's nothing to export or the library
 *         failed to load).
 *   buildWorkbookFromView(visibleColumns, visibleRows, options)
 *       — Pure helper: build a SheetJS workbook object from already-
 *         filtered column defs and row data, without touching the grid
 *         or the DOM. This is the reusable form for the email phase
 *         (Phase 6) — the mail module can call it with the same
 *         dataset that the user sees, without re-querying the backend.
 *
 * Scope (from Phase 5 spec §8):
 *   - Headers: yes
 *   - Visible rows: yes (post filter + sort)
 *   - Hidden columns: excluded
 *   - Sort order: respected
 *   - Filter (search): respected
 *   - Output format: .xlsx
 *
 * The exported workbook always matches what the user sees in the grid:
 * every column the user can still see, in the user's current sort +
 * filter order.
 *
 * Phase 6 (email) reuse plan
 * --------------------------
 * The email phase will attach a drill-down to an email. The
 * `buildWorkbookFromView()` helper accepts any `(columns, rows)` pair
 * so the mail module can:
 *   1. call `DrilldownManager.getCurrentDataset()` to get the cached
 *      records (no backend round-trip needed),
 *   2. re-apply the user's current column visibility / sort / search
 *      by reading them from the grid (the same call DrilldownManager
 *      uses to render the export button),
 *   3. pass the resulting (columns, rows) to `buildWorkbookFromView()`
 *      and ship the returned workbook as the email attachment.
 */
(function () {
  "use strict";

  // ── Public: exportCurrentView ───────────────────────────────────────────
  function exportCurrentView() {
    if (!window.DrilldownManager) {
      notify("Drill-down module not loaded.");
      return null;
    }
    const dm = window.DrilldownManager;
    if (!dm.hasData()) {
      notify("No drill-down data to export — open a drill-down first.");
      return null;
    }
    if (typeof window.XLSX === "undefined") {
      notify("Excel export library failed to load.");
      return null;
    }

    // Read the columns the user actually sees (in display order) and the
    // rows in their current sort + filter order from the AG Grid inside
    // the drilldown modal.
    const visibleColumns = dm.getVisibleColumns();
    const visibleRows    = dm.getVisibleRows();
    if (!visibleColumns.length) {
      notify("Drill-down has no columns to export.");
      return null;
    }

    const ctx = dm.getCurrentContext() || {};
    const options = {
      sheetName: "Drilldown",
      filename:  buildFilename(ctx),
    };

    const wb = buildWorkbookFromView(visibleColumns, visibleRows, options);
    XLSX.writeFile(wb, options.filename);
    return options.filename;
  }

  /**
   * Build a SheetJS workbook from a (columns, rows) pair.
   *
   * @param {Array<{field:string,headerName?:string}>} visibleColumns
   *        Column descriptors in display order. `headerName` is used
   *        for the header row; if missing, `field` is used.
   * @param {Array<Object>} visibleRows
   *        Row data in the desired order.
   * @param {Object} [options]
   * @param {string} [options.sheetName="Drilldown"]  Worksheet name.
   * @param {string} [options.filename]              Only used by the
   *        download helper, NOT by this function. The workbook is
   *        returned for the caller to use (download, attach to email,
   *        etc.).
   * @returns {Object} a SheetJS workbook (`XLSX.utils.book_new()`-
   *        shaped, ready to be passed to `XLSX.writeFile` or to be
   *        serialised with `XLSX.write` for an email attachment).
   */
  function buildWorkbookFromView(visibleColumns, visibleRows, options) {
    const opts = options || {};
    const sheetName = opts.sheetName || "Drilldown";

    // Defensive copies — never mutate the caller's data.
    const cols  = Array.isArray(visibleColumns) ? visibleColumns.slice() : [];
    const rows  = Array.isArray(visibleRows)    ? visibleRows.slice()    : [];

    // 1. Header row.
    const headerRow = cols.map(c => (c && (c.headerName || c.field)) || "");

    // 2. Data rows (already in the desired order from the grid).
    const dataAOA = rows.map(row => cols.map(c => cellValue(c, row)));

    // 3. Compose worksheet.
    const aoa = [headerRow].concat(dataAOA);
    const ws  = XLSX.utils.aoa_to_sheet(aoa);

    // 4. Best-effort column widths.
    setColumnWidths(ws, aoa);

    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, sheetName.slice(0, 31));
    return wb;
  }

  // ── Cell value helpers ──────────────────────────────────────────────────
  function cellValue(col, row) {
    if (!col || !row) return "";
    return formatScalar(row[col.field]);
  }

  function formatScalar(v) {
    if (v === undefined || v === null) return "";
    return v;
  }

  // ── Worksheet cosmetics ────────────────────────────────────────────────
  function setColumnWidths(ws, aoa) {
    if (!aoa.length) return;
    const colCount = aoa[0].length;
    const widths   = new Array(colCount).fill(0);
    aoa.forEach(row => {
      row.forEach((cell, i) => {
        const len = cell === null || cell === undefined ? 0 : String(cell).length;
        if (len > widths[i]) widths[i] = len;
      });
    });
    ws["!cols"] = widths.map(w => ({ wch: Math.min(Math.max(w + 2, 10), 50) }));
  }

  function buildFilename(ctx) {
    const datasetRaw = ((ctx && ctx.datasetName) || "dataset").replace(/\.[^.]+$/, "");
    const sheetRaw   = ((ctx && ctx.sheetName)   || "sheet").replace(/[^\w.-]+/g, "_");
    const stamp      = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    return `drilldown_${datasetRaw}_${sheetRaw}_${stamp}.xlsx`;
  }

  // ── Notification hook (the controller wires this to the page error
  //    alert; defaults to console so the module is self-contained). ────
  function notify(msg) { /* set by the controller */ }
  function setNotifier(fn) { notify = typeof fn === "function" ? fn : () => {}; }

  // ── Public API ──────────────────────────────────────────────────────────
  window.DrilldownExport = {
    exportCurrentView,
    buildWorkbookFromView,
    setNotifier,
  };
})();
