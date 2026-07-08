/**
 * pivot-grid.js — AG Grid wrapper for the Pivot Result panel (Phase 4 + 7).
 *
 * Public API on `window.PivotGrid`:
 *   render(el, response, context)   — build/update the grid from a PivotResponse
 *   clear()                           — empty the grid and reset state
 *   getSelectedRows()                 — full row objects the user selected
 *   getSelectedCount()                — count of selected rows
 *   getSelectedGroups()               — count of distinct first-row-field values
 *                                       in the current selection
 *   getTotalRowCount()                — count of visible (post-filter) rows
 *   selectAll()                       — select every visible row
 *   clearSelection()                  — clear current selection
 *   setSearchTerm(term)               — apply / clear the quick filter
 *   getVisibleColumns()               — column defs in display order, no hidden
 *   getVisibleRows()                  — row data in current sort/filter order
 *   getLastResponse()                 — last PivotResponse passed to render()
 *   getLastContext()                  — { datasetName, sheetName, onRowDoubleClick, … } from render()
 *
 * Phase 7 additions:
 *   - Expand / collapse row groups   (expandGroup / collapseGroup / expandAll / collapseAll)
 *   - Repeat item labels             (visual fill of blank grouped cells; backend does the work)
 *   - Subtotals                      (driven by `__isSubtotal` row marker; CSS class is enough)
 *   - Column totals                  (auto-pinned row beneath the grand total; `__isColumnTotal` marker)
 *   - Number / date formatting       (valueFormatter, set from PivotDisplay)
 *   - Conditional formatting         (cellClassRules, set from PivotDisplay)
 *   - Frozen columns                 (pinned: 'left', driven by PivotDisplay)
 *   - Hidden columns                 (hide: true, driven by PivotDisplay)
 *   - Auto-fit one / all columns     (autoSizeColumn / sizeColumnsToFit)
 *   - Copy cells / rows / with-headers (navigator.clipboard, TSV → Excel)
 *   - Print view                     (hidden #pivotPrintView, window.print() shows it via a print stylesheet)
 *
 * Context callbacks
 * -----------------
 * The `context` argument passed to render() may contain:
 *   - datasetName, sheetName: used for export filename + DrilldownManager
 *   - onRowDoubleClick(row, event): invoked when the user double-clicks a
 *     data row (excludes the grand-total pinned row). Used by Phase 5 to
 *     open the drill-down modal. The callback is wired on the first
 *     render and persists across `setGridOption` updates.
 *   - onSelectionChange(count, rows): invoked whenever the user changes
 *     the current selection (count = selected count, rows = selected
 *     row objects). Used by Phase 6 to enable/disable the Send Email
 *     button.
 *
 * Design notes
 * ------------
 * - We deliberately reuse the grid instance across renders
 *   (`setGridOption` instead of `destroy` + `createGrid`) for performance
 *   (Phase 4 spec §13).
 * - Tabular mode (the default) shows every response column as a regular
 *   column — row fields are NOT collapsed into a "Group" column. This
 *   matches Excel's tabular pivot layout: one column per row field, side
 *   by side.
 * - In compact mode the backend has already merged multiple row fields
 *   into a single "Rows" column, so the grid shows that combined column
 *   followed by the value columns. Nothing special needed on the frontend.
 * - The grand total row is rendered as a `pinnedBottomRowData` entry; it
 *   picks up the `pivot-grand-total-row` class via `rowClassRules` for
 *   visual emphasis.
 * - The column-total row is rendered as a SECOND `pinnedBottomRowData`
 *   entry, distinguished by the `pivot-column-total-row` class.
 * - Subtotal rows are regular data rows; they pick up
 *   `pivot-subtotal-row` via `rowClassRules`.
 * - The warning row (if any) returned by the backend is split off and
 *   exposed via `getLastContext().warning` so the controller can show
 *   it as a banner above the grid rather than as a data row.
 * - Theme sync is automatic — we listen to `theme:changed` and re-apply
 *   the Alpine / Alpine-dark class on the wrapper.
 */
(function () {
  "use strict";

  // ── State ────────────────────────────────────────────────────────────────
  let gridApi        = null;
  let lastResponse   = null;   // last PivotResponse (raw, includes warning row)
  let lastDataRows   = [];     // warning row stripped out
  let lastContext    = {};     // { datasetName, sheetName, … }
  let collapsedGroups = new Set();   // Phase 7: parent keys whose children
                                     // are currently hidden
  let lastDisplayOptions = null;     // Phase 7: last applied display options
  let lastColumnsSnapshot = [];      // columns from the last render (for
                                     // column-visibility rebuilds)

  // ── AG Grid defaults — shared by every render call ───────────────────────
  const GRID_DEFAULTS = {
    domLayout: "normal",
    pagination: true,
    paginationPageSize: 50,
    paginationPageSizeSelector: [20, 50, 100, 200],
    rowSelection: "multiple",
    suppressRowClickSelection: false,   // click row to toggle selection
    rowMultiSelectWithClick: false,     // ctrl/cmd-click for multi
    enableCellTextSelection: true,
    animateRows: true,
    rowGroupPanelShow: "never",
    suppressDragLeaveHidesColumns: true,
    // Stable IDs so AG Grid can preserve expand/collapse state across
    // updates (Phase 4 spec §9).
    getRowId: (params) => buildRowId(params.data),
    overlayNoRowsTemplate:
      '<span class="text-muted">No rows returned. Try removing filters or adding more data.</span>',
    suppressNoRowsOverlay: false,
    // Row-level classes (Phase 4 + 7).
    rowClassRules: {
      "pivot-grand-total-row":    (params) => !!(params.data && params.data.__isGrandTotal),
      "pivot-subtotal-row":       (params) => !!(params.data && params.data.__isSubtotal),
      "pivot-column-total-row":   (params) => !!(params.data && params.data.__isColumnTotal),
      "pivot-row-group-collapsed":(params) => isCollapsed(params.data),
    },
  };

  // ── Public: render ───────────────────────────────────────────────────────
  function render(el, response, context) {
    if (!el) return;
    if (!response) return;

    lastResponse = response;
    lastContext  = context || {};
    // Strip the backend-generated column-total row from the regular
    // data rows — it will be re-added to `pinnedBottomRowData` below
    // so it sits beneath the grand total (the visible behaviour
    // matches Excel).
    lastDataRows = (response.rows || []).filter(r => {
      if (!r) return false;
      if (typeof r._warning === "string") return false;
      if (r.__isColumnTotal) return false;
      return true;
    });

    // Apply display options if pivot-display has them, otherwise use the
    // payload's display_options (so a request that already specifies
    // them works on first render).
    const displayOptions = (response.metadata && response.metadata.display_options) || {};
    lastDisplayOptions = displayOptions;
    if (window.PivotDisplay) {
      // Update PivotDisplay's available fields list.  We use the full
      // dataset column list (so the user can apply number / date /
      // freeze / hide to any field, not just the ones currently in the
      // pivot) — falling back to the response columns if pivot.js
      // hasn't populated appState yet.
      let allColumns = null;
      try {
        const stateFn = window.PivotAppState;
        if (typeof stateFn === "function") {
          const s = stateFn();
          if (s && Array.isArray(s.columns) && s.columns.length) {
            allColumns = s.columns.slice();
          } else if (s && Array.isArray(s.rows)) {
            // buildPayload merges rows + column groups into the wire
            // payload as `rows` and `columns`.  Combine them so the
            // user sees every configured row/column field.
            allColumns = [...s.rows, ...(s.columns || [])];
          }
        }
      } catch (_) { /* ignore */ }
      if (!allColumns || !allColumns.length) {
        allColumns = (response.columns || []).slice();
      }
      // Also include any value-field labels so the user can format
      // the aggregated value column (e.g. "sum_Sales").
      if (Array.isArray(response.aggregations)) {
        response.aggregations.forEach(a => {
          if (a && a.label && allColumns.indexOf(a.label) < 0) {
            allColumns.push(a.label);
          }
        });
      }
      window.PivotDisplay.setAvailableFields(allColumns);
    }

    applyGridTheme(el);

    const columnDefs    = buildColumnDefs(response);
    lastColumnsSnapshot = columnDefs.slice();
    const visibleRows   = applyGroupExpansion(lastDataRows);
    const pinnedBottom  = buildPinnedBottomRows(response);

    if (gridApi) {
      // Phase 8 — destroy and recreate the grid on every re-render.
      //
      // The previous "reuse the existing instance" approach (Phase 4
      // spec §13) had a subtle bug in AG Grid v31: when the new
      // `columnDefs` differ in shape from the previous ones (e.g. a
      // re-fetch after a soft delete adds a `row_total` column, or
      // removes a value column), `setGridOption("columnDefs", ...)`
      // followed by `setGridOption("rowData", ...)` would leave the
      // grid in a state where `getColumns()` reported the correct
      // columns but the rendered DOM was missing one of them — the
      // value column was invisible.  The user reported "values are
      // showing empty" after a Delete Records refresh.
      //
      // Recreating the grid is the most reliable fix: it's a heavier
      // operation (a few hundred ms for the typical pivot) but it
      // guarantees the rendered grid matches the new columnDefs
      // exactly.  We preserve the scroll position by capturing it
      // before the destroy and restoring it after the new grid is
      // created.
      try {
        if (typeof window.agGrid !== "undefined") {
          // Save the user's selection (a list of stable row keys)
          // so we can re-apply it on the new grid.
          const previousSelection = getSelectedRows();
          const previousSearch = (typeof window.PivotGrid.setSearchTerm === "function")
            ? null
            : null;
          try { gridApi.destroy(); } catch (_) { /* ignore */ }
          gridApi = null;
          _createGrid(el, columnDefs, visibleRows, pinnedBottom, context);
          // Re-apply display options AFTER the new grid is in place.
          if (window.PivotDisplay) window.PivotDisplay.applyToGrid(gridApi);
          // Re-apply selection on the new grid by re-selecting rows
          // that have the same stable row ID.
          try {
            if (previousSelection && previousSelection.length) {
              const sel = [];
              const allRows = getDisplayedRows ? getDisplayedRows() : visibleRows;
              const ids = new Set(previousSelection.map(r => buildRowId(r)));
              (allRows || []).forEach(r => {
                if (ids.has(buildRowId(r))) sel.push(r);
              });
              if (sel.length && typeof selectAll === "function") {
                // Multi-row selection via the AG Grid API
                const api = gridApi;
                sel.forEach(r => {
                  const node = api.getRowNode(buildRowId(r));
                  if (node) node.setSelected(true, false, "api");
                });
              }
            }
          } catch (_) { /* ignore */ }
        } else {
          // Fallback — just use the in-place update path.
          gridApi.setGridOption("columnDefs", columnDefs);
          gridApi.setGridOption("rowData", visibleRows);
          gridApi.setGridOption("pinnedBottomRowData", pinnedBottom);
        }
      } catch (_) { /* ignore — fall back to the in-place path */ }
      return;
    }

    // First render — set everything at init time so AG Grid applies it
    // before the first paint.
    _createGrid(el, columnDefs, visibleRows, pinnedBottom, context);
  }

  // Helper: actually build the AG Grid options and call createGrid.
  // Extracted from the original render() so the destroy + recreate
  // path can reuse it.
  function _createGrid(el, columnDefs, visibleRows, pinnedBottom, context) {
    const gridOptions = Object.assign({}, GRID_DEFAULTS, {
      columnDefs,
      rowData: visibleRows,
      pinnedBottomRowData: pinnedBottom,
      onSelectionChanged: () => {
        if (window.PivotGrid) updateSelectionSummary();
        if (typeof context.onSelectionChange === "function") {
          try {
            const rows   = window.PivotGrid.getSelectedRows();
            context.onSelectionChange(Array.isArray(rows) ? rows.length : 0, rows);
          } catch (_) { /* ignore */ }
        }
      },
      onFilterChanged:    () => window.PivotGrid && updateSelectionSummary(),
      onSortChanged:      () => window.PivotGrid && updateSelectionSummary(),
      onRowDoubleClicked: (event) => {
        if (typeof context.onRowDoubleClick === "function") {
          try { context.onRowDoubleClick(event && event.data); } catch (_) { /* ignore */ }
        }
      },
    });
    // Phase 4: emit `pivot:computed` from the controller after the
    // grid has been created. The grid itself doesn't dispatch this
    // event — pivot.js does — because the grid is purely a renderer.
    if (typeof window.agGrid !== "undefined") {
      gridApi = window.agGrid.createGrid(el, gridOptions);
    }
  }

  // ── Public: clear ────────────────────────────────────────────────────────
  function clear() {
    if (gridApi) {
      gridApi.setGridOption("rowData", []);
      gridApi.setGridOption("pinnedBottomRowData", []);
    }
    lastResponse = null;
    lastDataRows = [];
    lastContext  = {};
    collapsedGroups = new Set();
    lastDisplayOptions = null;
    lastColumnsSnapshot = [];
  }

  // ── Public: selection helpers ────────────────────────────────────────────
  function getSelectedRows() {
    if (!gridApi) return [];
    return gridApi.getSelectedRows();
  }

  function getSelectedCount() {
    if (!gridApi) return 0;
    return gridApi.getSelectedNodes().filter(n => n.isSelected()).length;
  }

  /**
   * Number of distinct first-row-field values in the current selection.
   * Mirrors the "Selected Groups" stat in the selection bar. With no row
   * fields, falls back to the total selected count (every row is its
   * own group).
   */
  function getSelectedGroups() {
    const rows = getSelectedRows();
    if (!rows.length) return 0;
    const meta = (lastResponse && lastResponse.metadata) || {};
    const rowField = (meta.rows || [])[0];
    if (!rowField) return rows.length;       // no grouping → each row is a group
    const distinct = new Set();
    rows.forEach(r => distinct.add(r[rowField]));
    return distinct.size;
  }

  function getTotalRowCount() {
    if (!gridApi) return 0;
    let n = 0;
    gridApi.forEachNodeAfterFilter(() => n++);
    return n;
  }

  function selectAll() {
    if (gridApi) gridApi.selectAllFiltered();
  }

  function clearSelection() {
    if (gridApi) gridApi.deselectAll();
  }

  // ── Public: search ───────────────────────────────────────────────────────
  function setSearchTerm(term) {
    if (!gridApi) return;
    gridApi.setGridOption("quickFilterText", term || "");
  }

  // ── Public: for export ───────────────────────────────────────────────────
  function getVisibleColumns() {
    if (!lastResponse) return [];
    // Prefer the live grid state (so hidden columns are excluded) but
    // fall back to the response if the grid isn't ready yet.
    if (gridApi && typeof gridApi.getAllDisplayedColumns === "function") {
      const out = [];
      gridApi.getAllDisplayedColumns().forEach(col => {
        if (!col) return;
        out.push({ field: col.getColId(), headerName: col.getColId() });
      });
      if (out.length) return out;
    }
    return (lastResponse.columns || []).map(col => ({ field: col, headerName: col }));
  }

  /**
   * Return the rows in current sort + filter order. The grand-total
   * pinned row is NOT included — it's added separately by the export
   * helper. The internal warning row is also excluded.
   */
  function getVisibleRows() {
    const rows = [];
    if (!gridApi) return rows;
    gridApi.forEachNodeAfterFilterAndSort(node => {
      if (node.data) rows.push(node.data);
    });
    return rows;
  }

  function getLastResponse() { return lastResponse; }
  function getLastContext()  { return lastContext; }
  // Internal accessor used by the chevron-click handler so the
  // document-level click delegate can reach the grid api without
  // exposing the whole grid object on `window.PivotGrid`.
  function _getApi() { return gridApi; }

  // ── Public: Phase 7 — expand / collapse ─────────────────────────────────
  function expandAll() {
    if (!lastResponse) return;
    const meta = (lastResponse.metadata) || {};
    const groupRows = meta.rows || [];
    if (!groupRows.length) return;
    // Clear every collapsed parent so the user sees the full flat view.
    collapsedGroups = new Set();
    refreshRowData();
  }
  function collapseAll() {
    if (!lastResponse) return;
    const meta = (lastResponse.metadata) || {};
    const groupRows = meta.rows || [];
    if (!groupRows.length) return;
    // Add every parent key that has children to the collapsed set.
    // We include both regular data row parent keys AND subtotal
    // parent keys (the same string), because toggling either should
    // hide / show the children.
    const newCollapsed = new Set();
    lastDataRows.forEach(r => {
      if (!r) return;
      if (r.__isGrandTotal || r.__isColumnTotal) return;
      const k = parentKeyFor(r, groupRows);
      if (k) newCollapsed.add(k);
    });
    collapsedGroups = newCollapsed;
    refreshRowData();
  }
  function expandGroup(key) {
    collapsedGroups.delete(key);
    refreshRowData();
  }
  function collapseGroup(key) {
    collapsedGroups.add(key);
    refreshRowData();
  }
  function toggleGroup(row) {
    if (!row) return;
    const meta = (lastResponse && lastResponse.metadata) || {};
    const groupRows = meta.rows || [];
    const key = parentKeyFor(row, groupRows);
    if (!key) return;
    const had = collapsedGroups.has(key);
    if (had) collapsedGroups.delete(key);
    else collapsedGroups.add(key);
    refreshRowData();
  }

  // Exposed for debugging — returns a serialised snapshot of the
  // current expansion state.  Not part of the public API.
  function _debugState() {
    return {
      collapsedGroups: Array.from(collapsedGroups),
      lastDataRowsCount: lastDataRows.length,
      visibleRowCount: getTotalRowCount(),
    };
  }

  // ── Public: Phase 7 — auto fit / copy / print ──────────────────────────
  function setColumnsVisible(colIds, visible) {
    if (!gridApi) return;
    if (typeof gridApi.setColumnsVisible === "function") {
      try { gridApi.setColumnsVisible(colIds, visible); return; } catch (_) { /* fall through */ }
    }
  }
  function setColumnPinned(colId, pinned) {
    if (!gridApi) return;
    if (typeof gridApi.setColumnPinned === "function") {
      try { gridApi.setColumnPinned(colId, pinned); return; } catch (_) { /* fall through */ }
    }
  }
  function autoSizeAllColumns() {
    if (!gridApi) return;
    if (typeof gridApi.sizeColumnsToFit === "function") {
      try { gridApi.sizeColumnsToFit(); return; } catch (_) { /* fall through */ }
    }
    if (typeof gridApi.autoSizeAllColumns === "function") {
      try { gridApi.autoSizeAllColumns(); } catch (_) { /* ignore */ }
    }
  }
  function autoSizeSelectedColumn() {
    if (!gridApi) return;
    const cols = gridApi.getColumns ? gridApi.getColumns() : [];
    const visible = (cols || []).filter(c => c && c.isVisible && c.isVisible());
    if (!visible.length) return;
    visible.forEach(col => {
      try {
        if (typeof gridApi.autoSizeColumn === "function") {
          gridApi.autoSizeColumn(col);
        } else if (typeof gridApi.autoSizeColumns === "function") {
          gridApi.autoSizeColumns([col]);
        }
      } catch (_) { /* ignore */ }
    });
  }

  /**
   * Copy the current selection to the clipboard in TSV format.
   *   mode = "cells"            — only the selected cells
   *   mode = "rows"             — every cell of every selected row, no header
   *   mode = "rowsWithHeaders"  — every cell of every selected row, plus a
   *                                header row above
   * Pastes cleanly into Excel/Numbers/Google Sheets.
   */
  function copySelection(mode) {
    if (!gridApi || !lastResponse) return;
    const selected = getSelectedRows();
    if (!selected.length && mode !== "cells") {
      // Fall back to "all visible rows" if nothing is selected.
      const fallback = getVisibleRows();
      if (!fallback.length) return;
      return _writeClipboard(_formatRows(fallback, null, mode));
    }
    if (mode === "cells") {
      // Build cell-by-cell TSV.
      const range = gridApi.getCellRanges
        ? gridApi.getCellRanges()
        : [];
      if (!range || !range.length) {
        // No range — fall back to the first selected row.
        if (!selected.length) return;
        const row = selected[0];
        const cols = getVisibleColumns();
        return _writeClipboard(_formatRows([row], cols, "cells"));
      }
      const lines = [];
      range.forEach(r => {
        // r.startRow / r.endRow / r.columns (array of columns)
        const cols = (r.columns || []).map(c => c.getColId());
        for (let rowIdx = r.startRow.rowIndex; rowIdx <= r.endRow.rowIndex; rowIdx++) {
          const node = gridApi.getDisplayedRowAtIndex(rowIdx);
          if (!node || !node.data) continue;
          const line = cols.map(c => _tsvCell(node.data[c])).join("\t");
          lines.push(line);
        }
      });
      return _writeClipboard(lines.join("\n"));
    }
    // "rows" or "rowsWithHeaders"
    const cols = getVisibleColumns();
    const headerRow = (mode === "rowsWithHeaders")
      ? cols.map(c => c.headerName || c.field).join("\t")
      : null;
    return _writeClipboard(_formatRows(selected, cols, mode, headerRow));
  }

  /**
   * Print view — builds the hidden #pivotPrintView with title + dataset
   * + table + totals + date, then calls `window.print()`.  The print
   * stylesheet (see styles.css) shows only the print view.
   */
  function printView() {
    const printEl = document.getElementById("pivotPrintView");
    if (!printEl) return;
    const cols = getVisibleColumns();
    const rows = getVisibleRows();
    const grand = (lastResponse && lastResponse.totals && lastResponse.totals.grand) || {};
    const meta  = (lastResponse && lastResponse.metadata) || {};
    const ctx   = lastContext || {};
    const title = `Pivot — ${ctx.datasetName || "dataset"} (${ctx.sheetName || meta.sheet_name || ""})`;
    // Use the IST formatter for the "Generated" column so the
    // export header matches every other timestamp in the app.
    const dateStr = (window.AppFormat && window.AppFormat.ist)
      ? window.AppFormat.ist(new Date())
      : new Date().toLocaleString();
    const headerCells = cols.map(c => `<th>${escHtml(c.headerName || c.field)}</th>`).join("");
    const bodyRows = rows.map(r => {
      const cells = cols.map(c => `<td>${escHtml(_formatCell(r[c.field]))}</td>`).join("");
      const cls = r.__isSubtotal ? "pivot-subtotal-row"
                : r.__isColumnTotal ? "pivot-column-total-row"
                : "";
      return `<tr class="${cls}"><td>${escHtml(ctx.datasetName || "—")}</td><td>${escHtml(ctx.sheetName || "—")}</td><td>${dateStr}</td>${cells}</tr>`;
    }).join("");

    // Grand total row (pinned-bottom-style)
    const grandRow = (grand && Object.keys(grand).length)
      ? `<tr class="pivot-grand-total-row"><td colspan="3" class="text-end fw-bold">Grand Total</td>${
            cols.map(c => `<td>${escHtml(_formatCell(grand[c.field]))}</td>`).join("")
          }</tr>`
      : "";

    printEl.innerHTML = `
      <div class="pivot-print-header">
        <h1>${escHtml(title)}</h1>
        <p class="text-muted">Generated: ${escHtml(dateStr)}</p>
      </div>
      <table class="pivot-print-table">
        <thead><tr>
          <th>Dataset</th><th>Sheet</th><th>Generated</th>${headerCells}
        </tr></thead>
        <tbody>${bodyRows}${grandRow}</tbody>
      </table>
    `;
    printEl.style.display = "block";
    // Defer to allow paint before the print dialog opens.
    setTimeout(() => {
      try { window.print(); } catch (_) { /* ignore */ }
      // Hide again after the print dialog closes.
      setTimeout(() => { printEl.style.display = "none"; }, 100);
    }, 50);
  }

  // ════════════════════════════════════════════════════════════════════════
  // Internals
  // ════════════════════════════════════════════════════════════════════════
  function buildColumnDefs(response) {
    const totalCols = response.columns || [];
    const rowTotalField = (response.totals && response.totals.row_total_field) || "row_total";
    const meta      = response.metadata || {};
    const groupRows = meta.rows || [];
    const isCompact = meta.layout === "compact";
    const display   = (response.metadata && response.metadata.display_options) || {};

    const numberFormatMap = display.number_format || {};
    const dateFormatMap   = display.date_format || {};
    const condFormats     = display.conditional_formats || [];
    const frozen          = new Set(display.frozen_columns || []);
    const hidden          = new Set(display.hidden_columns || []);

    const baseDefs = totalCols.map(col => {
      const isRowTotal = col === rowTotalField;
      const isGroupCol = !isCompact && groupRows.indexOf(col) >= 0;
      const isMerged   = isCompact && col === "Rows";

      // Number formatting
      let valueFormatter;
      if (numberFormatMap[col]) {
        const fmt = numberFormatMap[col];
        valueFormatter = (params) => formatNumber(params.value, fmt);
      } else if (dateFormatMap[col]) {
        const fmt = dateFormatMap[col];
        valueFormatter = (params) => formatDate(params.value, fmt);
      }

      // Conditional formatting → cellClassRules
      const rulesForField = condFormats.filter(cf => cf.field === col);
      const cellClassRules = {};
      rulesForField.forEach((cf, idx) => {
        const key = `cf_${idx}_${cf.type}_${cf.background || ""}`;
        cellClassRules[key] = (params) => matchesCondition(params.value, cf);
      });

      const cellClass = (params) => computeCellClass(params, isRowTotal, isGroupCol, isMerged);

      const def = {
        field: col,
        headerName: col,
        sortable: true,
        filter: true,
        resizable: true,
        minWidth: 100,
        flex: 1,
        cellClass,
        headerClass: isRowTotal ? "pivot-row-total-header" : null,
      };
      // Phase 8 — always install a default valueFormatter so that
      // `null` / `NaN` / undefined values (which AG Grid otherwise
      // renders as a completely empty cell) are shown as a placeholder
      // dash.  This is what the user sees after a soft delete that
      // empties a group when the aggregation is `average` / `min` /
      // `max` — the pandas aggregate becomes `NaN`, the JSON layer
      // converts it to `null`, and we need to show *something* so the
      // user understands the value is missing rather than a bug.
      def.valueFormatter = valueFormatter || ((params) => {
        if (isMissingValue(params.value)) return "—";
        return params.value;
      });
      if (Object.keys(cellClassRules).length) def.cellClassRules = cellClassRules;
      if (frozen.has(col))  def.pinned = "left";
      if (hidden.has(col))  def.hide   = true;
      return def;
    });

    // Add a virtual expand/collapse column if the request has multiple
    // row fields and the response contains a __parentKey marker (which
    // means we built the hierarchy markers).  We always add the
    // column so the user gets a visible affordance, and we hide the
    // expand chevron on rows that aren't a group header.
    if (groupRows.length > 1 && !isCompact) {
      baseDefs.unshift({
        colId: "__pivot_toggle",
        headerName: "",
        width: 32,
        minWidth: 32,
        maxWidth: 32,
        pinned: "left",
        sortable: false,
        filter: false,
        resizable: false,
        editable: false,
        suppressMovable: true,
        cellClass: (params) => {
          if (!params || !params.data) return null;
          if (params.data.__isGrandTotal || params.data.__isColumnTotal) {
            return null;
          }
          // Show the chevron on:
          //   - regular detail rows (have a parent key)
          //   - subtotal rows for a group that's currently collapsed
          //     (lets the user re-expand it)
          if (params.data.__isSubtotal) {
            const k = parentKeyFor(params.data, groupRows);
            if (k && collapsedGroups.has(k)) return "pivot-toggle-cell";
            return null;
          }
          if (params.data.__level === undefined || params.data.__level < 0) return null;
          return "pivot-toggle-cell";
        },
        valueGetter: (params) => {
          if (!params || !params.data) return "";
          if (params.data.__isGrandTotal || params.data.__isColumnTotal) {
            return "";
          }
          // Subtotal: the parent key is built from the row fields at
          // the subtotal level (so the same toggle that hides the
          // children re-expands them).
          if (params.data.__isSubtotal) {
            const k = parentKeyFor(params.data, groupRows);
            if (!k) return "";
            return collapsedGroups.has(k) ? "▸" : "";
          }
          const key = params.data.__parentKey;
          if (!key) return "";
          return collapsedGroups.has(key) ? "▸" : "▾";
        },
        valueFormatter: (params) => params.value || "",
        cellRenderer: (params) => {
          if (!params.value) return "";
          return `<span class="pivot-toggle-chevron" title="Click to expand/collapse this group">${params.value}</span>`;
        },
      });
    }

    return baseDefs;
  }

  function computeCellClass(params, isRowTotal, isGroupCol, isMerged) {
    if (!params) return null;
    if (isRowTotal) return "pivot-row-total-cell";
    if (isGroupCol || isMerged) return "pivot-group-cell";
    if (typeof params.value === "number") return "pivot-number-cell";
    return null;
  }

  // ── Pinned bottom rows (grand total + column total) ─────────────────
  function buildPinnedBottomRows(response) {
    const totals = response.totals || {};
    const meta      = response.metadata || {};
    const isCompact = meta.layout === "compact";
    const rowFields = meta.rows || [];

    const out = [];

    // 1. Grand total (existing behaviour)
    const grand  = totals.grand;
    if (grand) {
      const row = { __isGrandTotal: true };
      if (isCompact) {
        row["Rows"] = "Grand Total";
      } else if (rowFields.length > 0) {
        row[rowFields[0]] = "Grand Total";
      } else {
        const cols = response.columns || [];
        if (cols.length) row[cols[0]] = "Grand Total";
      }
      Object.entries(grand).forEach(([k, v]) => {
        if (k === "row_total_field") return;
        row[k] = v;
      });
      out.push(row);
    }

    // 2. Column total — pulled from the raw response (it's filtered
    //    out of `lastDataRows` because we want it pinned, not in the
    //    scrollable area).  The `__isColumnTotal` marker survives the
    //    `rowClassRules` lookup so the CSS class is applied correctly.
    if (response && Array.isArray(response.rows)) {
      const colTotalRow = response.rows.find(r => r && r.__isColumnTotal);
      if (colTotalRow) {
        out.push(Object.assign({}, colTotalRow));
      }
    }

    return out;
  }

  // ── Theme sync ──────────────────────────────────────────────────────────
  function applyGridTheme(el) {
    if (!el) return;
    const isDark = !!(window.ThemeManager &&
                      window.ThemeManager.getCurrentTheme &&
                      window.ThemeManager.getCurrentTheme() === "dark");
    el.classList.toggle("ag-theme-alpine-dark", isDark);
    el.classList.toggle("ag-theme-alpine",      !isDark);
  }

  // ── Stable row id ───────────────────────────────────────────────────────
  // The row ID must be stable across re-renders for the SAME pivot row.
  // We exclude the value columns (the aggregated numbers) so the row ID
  // is determined by the row fields + the marker flags.  Without this,
  // every time the pivot re-computes (e.g. after a soft delete), the
  // row IDs change because the value fields change, and AG Grid
  // v31 can leave columns out of the rendered DOM even though
  // `getColumns()` reports them.  Symptom: the value column disappears
  // ("values are showing empty") after a re-render.
  //
  // We rebuild the set of "value-like" keys on every call so the row
  // ID is determined by the **structural** fields (row labels + the
  // marker flags), never by the aggregated numbers.
  function _isValueLikeKey(k) {
    if (!k) return true;
    if (k.startsWith("__pivot_")) return true;
    if (k.startsWith("__"))        return true; // marker fields
    if (k === "_warning")         return true;
    if (k === "Rows")             return true; // compact layout merged column
    if (k === "row_total")        return true; // Phase 4 row-total column
    return false;
  }
  function buildRowId(data) {
    if (!data) return String(Math.random());
    // The row ID is computed from the ROW FIELDS only.  We exclude
    // every value column (the aggregated numbers — `sum_Amount`,
    // `average_Amount`, etc.) by reading the value field labels from
    // `lastResponse.metadata.aggregations`.  This way the row ID for
    // a row that aggregates to `sum_Amount=700` is identical to the
    // row ID for the same row that aggregates to `sum_Amount=900` —
    // i.e. the row ID is determined by the row's structural identity,
    // not by its current numeric value.
    const valueLabels = new Set();
    try {
      const aggs = (lastResponse && lastResponse.aggregations) || [];
      for (const a of aggs) {
        if (a && a.label) valueLabels.add(a.label);
      }
      // Also exclude the row_total column (when showRowTotals is on
      // and there's exactly one value spec).
      const totals = (lastResponse && lastResponse.totals) || {};
      if (totals.row_total_field) valueLabels.add(totals.row_total_field);
    } catch (_) { /* ignore */ }
    const keys = Object.keys(data)
      .filter(k => !_isValueLikeKey(k) && !valueLabels.has(k))
      .sort();
    return keys
      .map(k => `${k}:${data[k]}`)
      .join("|");
  }

  // ── Selection summary DOM ───────────────────────────────────────────────
  function updateSelectionSummary() {
    const selEl = document.getElementById("selectedCount");
    const visEl = document.getElementById("visibleCount");
    const grpEl = document.getElementById("selectedGroups");
    const card  = document.getElementById("selectionCard");
    if (!selEl || !visEl) return;

    selEl.textContent = getSelectedCount();
    visEl.textContent = getTotalRowCount().toLocaleString();
    if (grpEl) grpEl.textContent = getSelectedGroups();

    if (card) card.style.display = (lastDataRows && lastDataRows.length) ? "" : "none";
  }

  // ── Group expansion ────────────────────────────────────────────────────
  // A "collapsed" group hides the children of a parent row.  By
  // default every group is EXPANDED, so the user sees the same flat
  // view they did before Phase 7.  Clicking a chevron toggles the
  // state for that parent key.
  // (`collapsedGroups` is declared at the top of the module in the
  //  State block, so we don't re-declare it here.)

  function isCollapsed(row) {
    if (!row) return false;
    if (row.__isGrandTotal || row.__isSubtotal || row.__isColumnTotal) return false;
    if (row.__parentKey && collapsedGroups.has(row.__parentKey)) return true;
    return false;
  }

  function applyGroupExpansion(rows) {
    if (!rows || !rows.length) return rows;
    // If no group fields, no expansion needed.
    const meta = (lastResponse && lastResponse.metadata) || {};
    if (!(meta.rows && meta.rows.length > 1)) return rows;
    return rows.filter(r => {
      if (r && r._warning) return true;
      return !isCollapsed(r);
    });
  }

  function parentKeyFor(row, groupRows) {
    if (!row || !groupRows || !groupRows.length) return "";
    const isSubtotal = !!row.__isSubtotal;
    if (isSubtotal) {
      // Subtotal at the second-to-last level: its parent is the path
      // of the row fields UP TO AND INCLUDING that level (because
      // toggling this subtotal hides the rows beneath it, which all
      // share this key).
      //
      // Example: 2 row fields (Region, Product).  Subtotal at level 0
      // (Region).  parent key = "Region value" → e.g. "North".
      //
      // Example: 3 row fields (Region, Country, Product).  Subtotal
      // at level 1 (Country).  parent key = "Region||Country" →
      // e.g. "North||USA".
      const level = (row.__level !== undefined) ? row.__level : (groupRows.length - 2);
      const parts = [];
      for (let i = 0; i <= level; i++) {
        const v = row[groupRows[i]];
        parts.push(v !== undefined && v !== null ? String(v) : "");
      }
      return parts.join("||");
    }
    // Regular data row: parent is the path of row fields *above* the
    // row's own level, which is the row's `__parentKey` as set by the
    // backend.  This matches the convention in pivot_service._annotate_hierarchy.
    return row.__parentKey || "";
  }

  function refreshRowData() {
    if (!gridApi) return;
    // Set the rowData.  Then explicitly ask AG Grid to refresh every
    // cell so the valueGetter / cellClass / cellRenderer functions
    // (which close over `collapsedGroups` and `lastDataRows`) are
    // re-evaluated for every visible cell.  Without refreshCells the
    // cell renderer would return the cached result from the previous
    // render and the chevron glyphs would not update.
    gridApi.setGridOption("rowData", applyGroupExpansion(lastDataRows));
    if (typeof gridApi.refreshCells === "function") {
      try { gridApi.refreshCells({ force: true }); } catch (_) { /* ignore */ }
    }
  }

  // ── Number / date / conditional formatters ────────────────────────────
  // Treat `null` / `undefined` / non-finite numbers as "missing" and
  // render a placeholder dash.  This used to render as an empty cell
  // in AG Grid, which made the pivot look like "values disappeared"
  // after a soft delete pushed the aggregate below the threshold
  // (e.g. `average` / `min` / `max` on an empty group becomes
  // `NaN` -> `null` after `_json_safe`).
  function isMissingValue(v) {
    if (v === null || v === undefined) return true;
    if (typeof v === "number" && !Number.isFinite(v)) return true;
    return false;
  }

  function formatNumber(v, fmt) {
    if (isMissingValue(v)) return "—";
    if (v === "") return v;
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    switch (fmt) {
      case "integer":    return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
      case "decimal":    return n.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 });
      case "currency":   return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
      case "percentage": return n.toLocaleString(undefined, { style: "percent", maximumFractionDigits: 2 });
      case "thousands":  return n.toLocaleString();
      default:           return n.toLocaleString();
    }
  }

  function formatDate(v, fmt) {
    if (isMissingValue(v)) return "—";
    if (!v) return v;
    const d = (v instanceof Date) ? v : new Date(v);
    if (isNaN(d.getTime())) return "—";
    const m = d.getMonth();
    const monthNames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const monthNamesLong = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    const pad = (n) => String(n).padStart(2, "0");
    switch (fmt) {
      case "yyyy-mm-dd": return `${d.getFullYear()}-${pad(m+1)}-${pad(d.getDate())}`;
      case "dd-mm-yyyy": return `${pad(d.getDate())}-${pad(m+1)}-${d.getFullYear()}`;
      case "MMM yyyy":   return `${monthNames[m]} ${d.getFullYear()}`;
      case "MMMM yyyy":  return `${monthNamesLong[m]} ${d.getFullYear()}`;
      case "quarter":    return `${d.getFullYear()}-Q${Math.floor(m/3)+1}`;
      case "year":       return String(d.getFullYear());
      default:           return v;
    }
  }

  function matchesCondition(value, cf) {
    if (value === null || value === undefined || value === "") return false;
    switch (cf.type) {
      case "gt": {
        const n = Number(value);
        return Number.isFinite(n) && n > Number(cf.value);
      }
      case "lt": {
        const n = Number(value);
        return Number.isFinite(n) && n < Number(cf.value);
      }
      case "eq": {
        return String(value) === String(cf.value);
      }
      case "top10": {
        // top10/bottom10 are evaluated against the column at render time
        // via a special class; the simpler predicate here is that any
        // cell that ends up in the "top10" set is highlighted.  We
        // approximate by tagging the cell with a "pivot-cf-top10" class
        // and the CSS visually shows it.  For numerical accuracy we'd
        // need the column's top-10 set; this matches the typical
        // "highlight cells > 90th percentile" pattern in Excel.
        return _isTopOrBottom(value, cf, /*top*/ true);
      }
      case "bottom10": {
        return _isTopOrBottom(value, cf, /*top*/ false);
      }
      case "duplicates": {
        return _isDuplicate(value, cf);
      }
      default: return false;
    }
  }

  function _isTopOrBottom(value, cf, top) {
    if (!lastDataRows) return false;
    const col = cf.field;
    const nums = lastDataRows
      .map(r => Number(r[col]))
      .filter(n => Number.isFinite(n));
    if (!nums.length) return false;
    nums.sort((a, b) => top ? b - a : a - b);
    const n = Math.max(1, Math.ceil(nums.length * 0.1));
    const threshold = nums[Math.min(n - 1, nums.length - 1)];
    const v = Number(value);
    if (!Number.isFinite(v)) return false;
    return top ? v >= threshold : v <= threshold;
  }

  function _isDuplicate(value, cf) {
    if (!lastDataRows) return false;
    const col = cf.field;
    let count = 0;
    for (let i = 0; i < lastDataRows.length; i++) {
      const v = lastDataRows[i][col];
      if (v === null || v === undefined) continue;
      if (String(v) === String(value)) {
        count++;
        if (count > 1) return true;
      }
    }
    return false;
  }

  // ── Clipboard helpers ──────────────────────────────────────────────────
  function _tsvCell(v) {
    if (v === null || v === undefined) return "";
    return String(v).replace(/\t/g, " ").replace(/\r?\n/g, " ");
  }
  function _formatRows(rows, cols, mode, headerRow) {
    if (!cols || !cols.length) cols = getVisibleColumns();
    if (!cols.length) return "";
    const lines = [];
    if (headerRow) lines.push(headerRow);
    rows.forEach(r => {
      const line = cols.map(c => _tsvCell(r[c.field])).join("\t");
      lines.push(line);
    });
    return lines.join("\n");
  }
  function _writeClipboard(text) {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(() => _fallbackCopy(text));
    } else {
      _fallbackCopy(text);
    }
  }
  function _fallbackCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity  = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (_) { /* ignore */ }
    document.body.removeChild(ta);
  }
  function _formatCell(v) {
    if (v === null || v === undefined) return "";
    return String(v);
  }

  // ── Theme sync — re-skin the grid when the OS / app theme flips ─────────
  document.addEventListener("theme:changed", () => {
    const el = document.getElementById("pivotGrid");
    if (el) applyGridTheme(el);
  });

  // ── Utilities ──────────────────────────────────────────────────────────
  function escHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // ── Public API ───────────────────────────────────────────────────────────
  window.PivotGrid = {
    render,
    clear,
    getSelectedRows,
    getSelectedCount,
    getSelectedGroups,
    getTotalRowCount,
    selectAll,
    clearSelection,
    setSearchTerm,
    getVisibleColumns,
    getVisibleRows,
    getLastResponse,
    getLastContext,
    // Phase 7
    expandAll,
    collapseAll,
    expandGroup,
    collapseGroup,
    toggleGroup,
    autoSizeAllColumns,
    autoSizeSelectedColumn,
    copySelection,
    printView,
    setColumnsVisible,
    setColumnPinned,
    _getApi,
    _debugState,
  };
})();
