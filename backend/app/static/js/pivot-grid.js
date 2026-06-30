/**
 * pivot-grid.js — AG Grid wrapper for the Pivot Result panel (Phase 4).
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
 * Context callbacks
 * -----------------
 * The `context` argument passed to render() may contain:
 *   - datasetName, sheetName: used for export filename + DrilldownManager
 *   - onRowDoubleClick(row, event): invoked when the user double-clicks a
 *     data row (excludes the grand-total pinned row). Used by Phase 5 to
 *     open the drill-down modal. The callback is wired on the first
 *     render and persists across `setGridOption` updates.
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
    // Grand total pinned row gets a distinct class (Phase 4 §5).
    rowClassRules: {
      "pivot-grand-total-row": (params) => !!(params.data && params.data.__isGrandTotal),
    },
  };

  // ── Public: render ───────────────────────────────────────────────────────
  function render(el, response, context) {
    if (!el) return;
    if (!response) return;

    lastResponse = response;
    lastContext  = context || {};
    lastDataRows = (response.rows || []).filter(r => !(r && typeof r._warning === "string"));

    applyGridTheme(el);

    const columnDefs    = buildColumnDefs(response);
    const pinnedBottom  = buildPinnedBottomRow(response);

    if (gridApi) {
      // Reuse the existing instance (Phase 4 spec §13).
      gridApi.setGridOption("columnDefs", columnDefs);
      gridApi.setGridOption("rowData", lastDataRows);
      gridApi.setGridOption("pinnedBottomRowData", pinnedBottom ? [pinnedBottom] : []);
      applyGridTheme(el);
      return;
    }

    // First render — set everything at init time so AG Grid applies it
    // before the first paint.
    const gridOptions = Object.assign({}, GRID_DEFAULTS, {
      columnDefs,
      rowData: lastDataRows,
      pinnedBottomRowData: pinnedBottom ? [pinnedBottom] : [],
      onSelectionChanged: () => window.PivotGrid && updateSelectionSummary(),
      onFilterChanged:    () => window.PivotGrid && updateSelectionSummary(),
      onSortChanged:      () => window.PivotGrid && updateSelectionSummary(),
      onRowDoubleClicked: (event) => {
        if (event && event.data && !event.data.__isGrandTotal &&
            typeof context.onRowDoubleClick === "function") {
          context.onRowDoubleClick(event.data, event);
        }
      },
      onGridReady:        () => {
        if (window.PivotGrid) updateSelectionSummary();
      },
    });

    gridApi = agGrid.createGrid(el, gridOptions);
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
  /**
   * Return the columns the user actually sees, in display order.
   *
   * In tabular mode every response column (including all row-field columns)
   * is shown as a regular column — we just return them in the order the
   * backend sent them.
   *
   * In compact mode the backend has already merged multiple row fields
   * into a single "Rows" column, so `response.columns` contains that one
   * merged column plus the value columns. Returning everything in order
   * matches what the user sees in the grid.
   */
  function getVisibleColumns() {
    if (!lastResponse) return [];
    const totalCols = lastResponse.columns || [];
    return totalCols.map(col => ({ field: col, headerName: col }));
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

  // ════════════════════════════════════════════════════════════════════════
  // Internals
  // ════════════════════════════════════════════════════════════════════════
  function buildColumnDefs(response) {
    const totalCols = response.columns || [];
    const rowTotalField = (response.totals && response.totals.row_total_field) || "row_total";

    // Tabular mode (the default) shows EVERY response column as a regular
    // column — each row field is its own column, side by side. This is the
    // expected Excel-like behaviour and the user-facing fix.
    //
    // In compact mode the backend already merges all row fields into a
    // single "Rows" column, so `totalCols` doesn't include the individual
    // row-field names and there's nothing special to do here either.
    return totalCols.map(col => {
      const isRowTotal = col === rowTotalField;
      return {
        field: col,
        headerName: col,
        sortable: true,
        filter: true,
        resizable: true,
        minWidth: 100,
        flex: 1,
        cellClass: (params) => computeCellClass(params, isRowTotal),
        headerClass: isRowTotal ? "pivot-row-total-header" : null,
      };
    });
  }

  function computeCellClass(params, isRowTotal) {
    if (!params) return null;
    if (isRowTotal) return "pivot-row-total-cell";
    if (typeof params.value === "number") return "pivot-number-cell";
    return null;
  }

  // ── Pinned bottom row (grand totals) ────────────────────────────────────
  function buildPinnedBottomRow(response) {
    const totals = response.totals || {};
    const grand  = totals.grand;
    if (!grand) return null;

    const meta      = response.metadata || {};
    const isCompact = meta.layout === "compact";
    const rowFields = meta.rows || [];

    const row = { __isGrandTotal: true };

    if (isCompact) {
      row["Rows"] = "Grand Total";
    } else if (rowFields.length > 0) {
      // The auto-generated group column will display this value.
      row[rowFields[0]] = "Grand Total";
    } else {
      const cols = response.columns || [];
      if (cols.length) row[cols[0]] = "Grand Total";
    }

    Object.entries(grand).forEach(([k, v]) => {
      if (k === "row_total_field") return;
      row[k] = v;
    });

    return row;
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
  function buildRowId(data) {
    if (!data) return String(Math.random());
    return Object.keys(data).sort()
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

  // ── Theme sync — re-skin the grid when the OS / app theme flips ─────────
  document.addEventListener("theme:changed", () => {
    const el = document.getElementById("pivotGrid");
    if (el) applyGridTheme(el);
  });

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
  };
})();
