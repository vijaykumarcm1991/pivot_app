/**
 * pivot-export.js — Export the current Pivot Result view to .xlsx (Phase 4).
 *
 * Public API on `window.PivotExport`:
 *   exportCurrentView()  — build a workbook from the current grid view and
 *                           trigger a browser download. Returns the chosen
 *                           filename (or null when there's nothing to export).
 *
 * Scope (from Phase 4 spec §12):
 *   - Headers: yes
 *   - Visible rows: yes (post filter + sort)
 *   - Hidden columns: excluded
 *   - Grand total row: included (if the backend returned it)
 *   - Warning row from the backend: NOT exported (UI shows it as a banner)
 *
 * The exported workbook always matches what the user sees in the grid:
 * every response column (row-field + value + row_total) is written in
 * the same order, in the user's current sort + filter.
 */
(function () {
  "use strict";

  // ── Public: exportCurrentView ───────────────────────────────────────────
  function exportCurrentView() {
    if (!window.PivotGrid) return null;
    const grid = window.PivotGrid;
    const response = grid.getLastResponse();
    if (!response) {
      if (window.PivotExport && window.PivotExport._notify) {
        window.PivotExport._notify("Nothing to export — generate a pivot first.");
      }
      return null;
    }
    if (typeof window.XLSX === "undefined") {
      if (window.PivotExport && window.PivotExport._notify) {
        window.PivotExport._notify("Excel export library failed to load.");
      }
      return null;
    }

    const meta      = (response && response.metadata) || {};

    // 1. Get the columns the user actually sees. PivotGrid.getVisibleColumns()
    //    now returns every response column in order (row-field columns are
    //    shown as regular columns in tabular mode, and the backend already
    //    merges them into "Rows" in compact mode).
    const visibleCols = grid.getVisibleColumns();
    if (!visibleCols.length) {
      if (window.PivotExport._notify) {
        window.PivotExport._notify("Pivot has no columns to export.");
      }
      return null;
    }

    // 2. Build the header row.
    const headerRow = visibleCols.map(c => c.headerName || c.field || "");

    // 3. Build the data rows (current filter + sort).
    const dataRows = grid.getVisibleRows();
    const dataAOA = dataRows.map(row => visibleCols.map(c => cellValue(c, row)));

    // 4. Append the grand total row if the backend returned one.
    const grand = (response.totals && response.totals.grand) || null;
    if (grand) {
      const totalRow = visibleCols.map(c => grandCellValue(c, grand));
      dataAOA.push(totalRow);
    }

    // 5. Compose the worksheet.
    const aoa = [headerRow].concat(dataAOA);
    const ws  = XLSX.utils.aoa_to_sheet(aoa);

    // Best-effort column widths: header length + max cell length (capped).
    setColumnWidths(ws, aoa);

    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Pivot");

    // 6. Build a sensible filename: pivot_<dataset>_<sheet>_<timestamp>.xlsx
    const ctx        = grid.getLastContext() || {};
    const datasetRaw = (ctx.datasetName || "pivot").replace(/\.[^.]+$/, "");
    const sheetRaw   = (ctx.sheetName    || "sheet").replace(/[^\w.-]+/g, "_");
    const stamp      = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const filename   = `pivot_${datasetRaw}_${sheetRaw}_${stamp}.xlsx`;

    XLSX.writeFile(wb, filename);
    return filename;
  }

  // ── Cell value helpers ──────────────────────────────────────────────────
  function cellValue(col, row) {
    return formatScalar(row[col.field]);
  }

  function grandCellValue(col, grand) {
    const field = col.field;
    if (!field) return "";
    if (field in grand) return formatScalar(grand[field]);
    // The backend does not include `row_total` in `totals.grand`
    // (see pivot_service._compute_totals). Compute the sum of the
    // currently visible row_total values so the export stays consistent
    // with what the user sees in the grid.
    if (field === "row_total" && window.PivotGrid) {
      const dataRows = window.PivotGrid.getVisibleRows();
      return dataRows.reduce((sum, r) => sum + (Number(r[field]) || 0), 0);
    }
    return "";
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

  // ── Notification hook (the controller wires this to showError) ──────────
  function _notify(msg) { /* set by the controller */ }
  function setNotifier(fn) { _notify = typeof fn === "function" ? fn : () => {}; }

  // ── Public API ──────────────────────────────────────────────────────────
  window.PivotExport = {
    exportCurrentView,
    setNotifier,
  };
})();
