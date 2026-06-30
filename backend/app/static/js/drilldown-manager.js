/**
 * drilldown-manager.js — Drill-down modal orchestrator (Phase 5).
 *
 * Responsibilities
 * ----------------
 *  - Open / close the Bootstrap modal that shows raw records matching
 *    a pivot row (or several selected pivot rows).
 *  - Fetch the raw records from `POST /api/pivot/drilldown` (one call
 *    per selected pivot row) and merge the results, deduplicating
 *    identical raw records so the same source row never appears twice
 *    in a multi-row drilldown.
 *  - Render the records in a dedicated AG Grid (independent from the
 *    pivot grid) with sorting, filtering, searching, column resizing,
 *    pagination, and built-in copy (Ctrl+C).
 *  - Drive the toolbar:
 *      - record counter
 *      - search box
 *      - column visibility menu (hide / show / reset)
 *      - Export to .xlsx
 *  - Render the selection summary card (Dataset / Sheet / Selected
 *    Pivot Rows / Matching Records / Returned Records).
 *  - Render the matching-criteria card (the row-field values that
 *    produced the drilldown).
 *  - Keep the most recently displayed drill-down dataset cached on
 *    `getCurrentDataset()` for the email phase (Phase 6).
 *  - Show a friendly empty state when no records are found.
 *  - Show a loading overlay while the API calls are in flight.
 *  - Handle thousands of rows without unnecessary re-renders.
 *
 * Public API on `window.DrilldownManager`:
 *   open(pivotRows, payload, response)
 *       — Open the modal for the given pivot row(s) using the
 *         current pivot payload + response.
 *   openForCurrentSelection()
 *       — Convenience: open using the current pivot grid selection
 *         (uses `DrilldownSelection.getSelectedPivotRows()`). If
 *         nothing is selected, open for the row the user just
 *         double-clicked (passed in via `_lastDoubleClickedRow`).
 *   openForRow(pivotRow)
 *       — Convenience: open for a single pivot row (called from the
 *         grid's double-click handler).
 *   close()
 *       — Close the modal if it is open.
 *   hasData()
 *       — True when a drilldown has finished loading and is on screen.
 *   getCurrentDataset()
 *       — The merged, deduplicated drilldown response (the same one
 *         the user is looking at). This is what the email phase
 *         will use to build the attachment.
 *   getCurrentContext()
 *       — { datasetName, sheetName, payload, pivotRows } for the
 *         current drilldown.
 *   getVisibleColumns()
 *       — Column defs the user currently sees (display order, hidden
 *         columns excluded). Used by the export module.
 *   getVisibleRows()
 *       — Row data in the current sort + filter order. Used by the
 *         export module.
 *
 * Note: this module is the *only* piece that talks to the grid
 * instance for the drilldown. The export module reads from it via
 * the `getVisibleColumns()` / `getVisibleRows()` helpers.
 */
(function () {
  "use strict";

  // ════════════════════════════════════════════════════════════════════════
  // Module state
  // ════════════════════════════════════════════════════════════════════════
  let modalInstance   = null;     // Bootstrap Modal handle
  let gridApi         = null;     // AG Grid instance for the drilldown
  let lastDataset     = null;     // Cached drilldown response (for email)
  let lastContext     = null;     // { datasetName, sheetName, payload, pivotRows }
  let lastVisibleCols = [];       // Cached "currently visible" columns
  let lastVisibleRows = [];       // Cached "currently visible" rows
  let lastPivotRow    = null;     // Most-recently double-clicked row (fallback
                                  // when the user double-clicks but hasn't
                                  // selected anything else first).
  let isLoading       = false;
  let inflightToken   = 0;        // Monotonic counter to avoid stale renders.

  // AG Grid defaults for the drilldown grid. Kept separate from the
  // pivot grid's defaults so the two grids evolve independently.
  const GRID_DEFAULTS = {
    domLayout: "normal",
    pagination: true,
    paginationPageSize: 50,
    paginationPageSizeSelector: [20, 50, 100, 200],
    rowSelection: "multiple",
    suppressRowClickSelection: false,
    rowMultiSelectWithClick: false,
    enableCellTextSelection: true,   // let users drag-select cell text
    animateRows: true,
    rowGroupPanelShow: "never",
    suppressDragLeaveHidesColumns: true,
    // Quick filter is set via setGridOption("quickFilterText", ...).
    overlayNoRowsTemplate:
      '<span class="text-muted">No matching records. Try widening the search or selecting fewer pivot rows.</span>',
    // Stable row IDs so AG Grid can preserve UI state across re-renders.
    getRowId: (params) => buildRowId(params.data),
  };

  // ════════════════════════════════════════════════════════════════════════
  // DOM refs (resolved lazily on first open)
  // ════════════════════════════════════════════════════════════════════════
  let dom = null;
  function getDom() {
    if (dom) return dom;
    dom = {
      modal:           document.getElementById("drilldownModal"),
      grid:            document.getElementById("drilldownGrid"),
      loadingOverlay:  document.getElementById("drilldownLoadingOverlay"),
      searchInput:     document.getElementById("drilldownSearch"),
      exportBtn:       document.getElementById("drilldownExportBtn"),
      columnsMenu:     document.getElementById("drilldownColumnsMenu"),
      resetColumnsBtn: document.getElementById("drilldownResetColumnsBtn"),
      summaryCard:     document.getElementById("drilldownSummaryCard"),
      criteriaCard:    document.getElementById("drilldownCriteriaCard"),
      criteriaBody:    document.getElementById("drilldownCriteria"),
      recordCount:     document.getElementById("drilldownRecordCount"),
      emptyState:      document.getElementById("drilldownEmptyState"),
      gridContainer:   document.getElementById("drilldownGridContainer"),
      // Summary fields
      sumDataset:      document.getElementById("ddSumDataset"),
      sumSheet:        document.getElementById("ddSumSheet"),
      sumPivotRows:    document.getElementById("ddSumPivotRows"),
      sumMatched:      document.getElementById("ddSumMatched"),
      sumReturned:     document.getElementById("ddSumReturned"),
    };
    return dom;
  }

  // ════════════════════════════════════════════════════════════════════════
  // Public: open / close
  // ════════════════════════════════════════════════════════════════════════
  /**
   * Open the drill-down modal for one or more pivot rows.
   *
   * @param {Array<Object>} pivotRows  - selected pivot rows (1+ entries)
   * @param {Object}        payload    - the same payload sent to /api/pivot
   * @param {Object}        response   - the last PivotResponse (for criteria)
   * @param {Object}        [opts]     - { datasetName, sheetName }
   */
  function open(pivotRows, payload, response, opts) {
    if (!Array.isArray(pivotRows) || !pivotRows.length) {
      notify("Select one or more pivot rows first (or double-click a row).");
      return;
    }
    if (!payload || !payload.datasetId || !payload.sheetName) {
      notify("Cannot drill down — pivot configuration is missing.");
      return;
    }
    if (!response) {
      notify("Cannot drill down — no pivot response available.");
      return;
    }

    const o = opts || {};
    lastContext = {
      datasetName: o.datasetName || (window.PivotGrid ? window.PivotGrid.getLastContext()?.datasetName : "") || "dataset",
      sheetName:   o.sheetName   || (window.PivotGrid ? window.PivotGrid.getLastContext()?.sheetName   : "") || payload.sheetName,
      payload:     payload,
      pivotRows:   pivotRows,
    };
    lastDataset = null;
    lastVisibleCols = [];
    lastVisibleRows = [];

    const d = getDom();
    if (!d.modal) {
      notify("Drill-down modal is not present in the page.");
      return;
    }
    if (!modalInstance && window.bootstrap && window.bootstrap.Modal) {
      try {
        modalInstance = new window.bootstrap.Modal(d.modal, { backdrop: "static" });
      } catch (_) {
        modalInstance = null;
      }
    }
    if (modalInstance) {
      modalInstance.show();
    }

    showLoadingState();
    fetchAndRender(pivotRows, payload, response);
  }

  /** Open for the current pivot grid selection (multi-row drilldown). */
  function openForCurrentSelection() {
    if (!window.DrilldownSelection) {
      notify("Drill-down selection helper not loaded.");
      return;
    }
    const rows = window.DrilldownSelection.getSelectedPivotRows();
    if (!rows.length && lastPivotRow) {
      // Fall back to the row the user just double-clicked.
      open([lastPivotRow],
           buildPayloadFromAppState(),
           window.DrilldownSelection.getCurrentPivotResponse());
      return;
    }
    if (!rows.length) {
      notify("Select one or more pivot rows first (or double-click a row).");
      return;
    }
    open(rows,
         buildPayloadFromAppState(),
         window.DrilldownSelection.getCurrentPivotResponse());
  }

  /** Open for a single pivot row (called from the grid's double-click). */
  function openForRow(pivotRow) {
    if (!pivotRow) return;
    lastPivotRow = pivotRow;
    const response = window.DrilldownSelection
      ? window.DrilldownSelection.getCurrentPivotResponse()
      : null;
    open([pivotRow], buildPayloadFromAppState(), response);
  }

  function close() {
    if (modalInstance) modalInstance.hide();
  }

  // ════════════════════════════════════════════════════════════════════════
  // Data fetch + merge + dedup
  // ════════════════════════════════════════════════════════════════════════
  async function fetchAndRender(pivotRows, payload, response) {
    const myToken = ++inflightToken;
    isLoading = true;

    const merged = {
      rows: [],
      columns: [],
      metadata: {
        dataset_id:    payload.datasetId,
        sheet_name:    payload.sheetName,
        matched_rows:  0,
        returned_rows: 0,
        limit:         5000,
        selection:     {},
      },
    };

    const seen = new Set();
    let totalMatched = 0;
    let anyError     = null;

    try {
      for (let i = 0; i < pivotRows.length; i++) {
        const pivotRow = pivotRows[i];
        const selection = window.DrilldownSelection
          ? window.DrilldownSelection.buildSelectionForRow(pivotRow, response)
          : {};

        // Update the loading overlay with progress.
        updateLoadingProgress(i + 1, pivotRows.length, pivotRow);

        const res = await fetch("/api/pivot/drilldown", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...payload, selection, limit: 5000 }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error((data && data.detail) || "Drilldown request failed");
        }

        totalMatched += Number((data.metadata && data.metadata.matched_rows) || 0);

        // Capture columns from the first successful response. The backend
        // guarantees the same column set for all calls (same payload).
        if (!merged.columns.length && Array.isArray(data.columns)) {
          merged.columns = data.columns.slice();
        }

        // Merge rows, dedup by stable JSON key.
        if (Array.isArray(data.rows)) {
          data.rows.forEach(row => {
            const key = window.DrilldownSelection
              ? window.DrilldownSelection.dedupKey(row)
              : JSON.stringify(row);
            if (!seen.has(key)) {
              seen.add(key);
              merged.rows.push(row);
            }
          });
        }
      }

      if (myToken !== inflightToken) return;   // a newer call superseded us

      merged.metadata.matched_rows  = totalMatched;
      merged.metadata.returned_rows = merged.rows.length;
      merged.metadata.selection     = buildMergedSelection(pivotRows, response);

      lastDataset     = merged;
      lastVisibleCols = [];
      lastVisibleRows = [];

      renderDataset(merged, pivotRows, response);
    } catch (err) {
      if (myToken !== inflightToken) return;
      anyError = err;
      showError("Drill-down failed: " + (err && err.message ? err.message : err));
      hideLoadingState();
    } finally {
      if (myToken === inflightToken) {
        isLoading = false;
        if (!anyError) hideLoadingState();
      }
    }
  }

  function buildMergedSelection(pivotRows, response) {
    if (!pivotRows || !pivotRows.length) return {};
    if (pivotRows.length === 1) {
      return window.DrilldownSelection
        ? window.DrilldownSelection.buildSelectionForRow(pivotRows[0], response)
        : {};
    }
    // For multiple rows we surface the union so the user sees the
    // combined "any of these" intent.
    const all = {};
    pivotRows.forEach(row => {
      const sel = window.DrilldownSelection
        ? window.DrilldownSelection.buildSelectionForRow(row, response)
        : {};
      Object.keys(sel).forEach(k => {
        if (!(k in all)) all[k] = sel[k];
      });
    });
    return all;
  }

  // ════════════════════════════════════════════════════════════════════════
  // Render
  // ════════════════════════════════════════════════════════════════════════
  function renderDataset(merged, pivotRows, response) {
    const d = getDom();
    if (!d.grid) return;

    renderSummary(merged, pivotRows, response);
    renderCriteria(pivotRows, response);

    if (!merged.rows.length) {
      // Hide the grid, show the friendly empty state.
      if (d.gridContainer) d.gridContainer.style.display = "none";
      if (d.emptyState)    d.emptyState.style.display    = "";
      updateRecordCount(0);
      setExportEnabled(false);
      hideLoadingState();
      return;
    }

    if (d.emptyState)      d.emptyState.style.display    = "none";
    if (d.gridContainer)   d.gridContainer.style.display = "";

    const colDefs = buildColumnDefs(merged.columns);
    applyGridTheme(d.grid);

    if (gridApi) {
      // Reuse the existing instance — cheaper for large result sets.
      gridApi.setGridOption("columnDefs", colDefs);
      gridApi.setGridOption("rowData",    merged.rows);
    } else {
      const options = Object.assign({}, GRID_DEFAULTS, {
        columnDefs: colDefs,
        rowData:    merged.rows,
        onFilterChanged: () => { cacheVisible(); updateRecordCount(merged.rows.length); },
        onSortChanged:   () => { cacheVisible(); },
        onGridReady:     () => { cacheVisible(); updateRecordCount(merged.rows.length); },
      });
      gridApi = agGrid.createGrid(d.grid, options);
    }

    // Wire the column-visibility menu + reset now that we know the columns.
    rebuildColumnsMenu(merged.columns);
    updateRecordCount(merged.rows.length);
    setExportEnabled(true);

    // Defer one frame so the grid finishes its first paint before we
    // hide the loading overlay.
    requestAnimationFrame(() => {
      cacheVisible();
      hideLoadingState();
    });
  }

  // ── Summary card ────────────────────────────────────────────────────────
  function renderSummary(merged, pivotRows, response) {
    const d = getDom();
    if (!d.summaryCard) return;
    if (d.sumDataset)   d.sumDataset.textContent   = lastContext.datasetName || "—";
    if (d.sumSheet)     d.sumSheet.textContent     = (merged.metadata && merged.metadata.sheet_name) || "—";
    if (d.sumPivotRows) d.sumPivotRows.textContent = pivotRows.length.toLocaleString();
    if (d.sumMatched)   d.sumMatched.textContent   = (merged.metadata.matched_rows  || 0).toLocaleString();
    if (d.sumReturned)  d.sumReturned.textContent  = (merged.metadata.returned_rows || 0).toLocaleString();
    void response;
  }

  // ── Matching-criteria card ──────────────────────────────────────────────
  function renderCriteria(pivotRows, response) {
    const d = getDom();
    if (!d.criteriaCard || !d.criteriaBody) return;

    if (!pivotRows || !pivotRows.length) {
      d.criteriaCard.style.display = "none";
      return;
    }

    // Combine all unique criteria across the selected rows.
    const allCriteria = [];
    pivotRows.forEach((row, idx) => {
      const sel = window.DrilldownSelection
        ? window.DrilldownSelection.buildSelectionForRow(row, response)
        : {};
      const entries = Object.entries(sel);
      if (!entries.length) return;
      allCriteria.push({ idx: idx + 1, entries });
    });

    if (!allCriteria.length) {
      d.criteriaCard.style.display = "none";
      return;
    }

    const html = allCriteria.map(group => {
      const pills = group.entries
        .map(([k, v]) => `<span class="drilldown-criteria-pill">
                            <span class="key">${escHtml(k)}</span>
                            <span class="op">=</span>
                            <span class="val">${escHtml(String(v))}</span>
                          </span>`)
        .join("");
      const label = pivotRows.length > 1
        ? `<span class="text-muted small me-2">Row ${group.idx}:</span>`
        : "";
      return `<div class="d-flex flex-wrap align-items-center gap-1 mb-1">${label}${pills}</div>`;
    }).join("");

    d.criteriaBody.innerHTML = html;
    d.criteriaCard.style.display = "";
  }

  // ── Column defs (no special row-group logic; every column is plain) ───
  function buildColumnDefs(columns) {
    return (columns || []).map(col => ({
      field: col,
      headerName: col,
      sortable: true,
      filter: true,
      resizable: true,
      minWidth: 100,
      flex: 1,
    }));
  }

  // ════════════════════════════════════════════════════════════════════════
  // Toolbar
  // ════════════════════════════════════════════════════════════════════════
  function wireToolbarOnce() {
    if (wireToolbarOnce._done) return;
    wireToolbarOnce._done = true;

    const d = getDom();
    if (d.searchInput) {
      let timer = null;
      d.searchInput.addEventListener("input", () => {
        clearTimeout(timer);
        const term = d.searchInput.value;
        timer = setTimeout(() => {
          if (gridApi) gridApi.setGridOption("quickFilterText", term || "");
          // Update visible rows + counter so the export sees the filter.
          requestAnimationFrame(cacheVisible);
        }, 120);
      });
    }
    if (d.exportBtn) {
      d.exportBtn.addEventListener("click", () => {
        if (!window.DrilldownExport) {
          notify("Export module not loaded.");
          return;
        }
        const filename = window.DrilldownExport.exportCurrentView();
        if (filename) {
          flashExportButton(d.exportBtn);
        }
      });
    }
    if (d.resetColumnsBtn) {
      d.resetColumnsBtn.addEventListener("click", () => {
        if (!gridApi || !lastDataset) return;
        const allIds = (lastDataset.columns || []).map(c => c);
        gridApi.setColumnsVisible(allIds, true);
        rebuildColumnsMenu(lastDataset.columns, /*recheckAll*/ true);
        cacheVisible();
      });
    }
  }

  function rebuildColumnsMenu(columns, recheckAll) {
    const d = getDom();
    if (!d.columnsMenu) return;
    d.columnsMenu.innerHTML = "";

    if (!columns || !columns.length) {
      d.columnsMenu.innerHTML = '<li><span class="dropdown-item text-muted small">No columns</span></li>';
      return;
    }

    // Header + Select all / Clear shortcuts
    d.columnsMenu.insertAdjacentHTML("beforeend", `
      <li>
        <div class="dropdown-header d-flex justify-content-between align-items-center">
          <span>Show / hide columns</span>
          <span>
            <button type="button" class="btn btn-link btn-sm p-0 me-2" data-dd-cols-action="all">All</button>
            <button type="button" class="btn btn-link btn-sm p-0"    data-dd-cols-action="none">None</button>
          </span>
        </div>
      </li>
      <li><hr class="dropdown-divider"></li>
    `);

    columns.forEach(col => {
      const li = document.createElement("li");
      li.innerHTML = `
        <label class="dropdown-item d-flex align-items-center" style="cursor: pointer">
          <input class="form-check-input me-2" type="checkbox" data-dd-col-id="${escHtml(col)}" checked>
          <span class="text-truncate" title="${escHtml(col)}">${escHtml(col)}</span>
        </label>
      `;
      d.columnsMenu.appendChild(li);
    });

    // Wire checkboxes → grid column visibility.
    d.columnsMenu.querySelectorAll("input[type=checkbox][data-dd-col-id]").forEach(cb => {
      cb.addEventListener("change", () => {
        if (!gridApi) return;
        const colId = cb.getAttribute("data-dd-col-id");
        gridApi.setColumnsVisible([colId], cb.checked);
        cacheVisible();
      });
    });

    // Wire "All" / "None" shortcuts.
    d.columnsMenu.querySelectorAll("[data-dd-cols-action]").forEach(btn => {
      btn.addEventListener("click", e => {
        e.preventDefault();
        e.stopPropagation();
        const action = btn.getAttribute("data-dd-cols-action");
        if (!gridApi || !lastDataset) return;
        const allIds = lastDataset.columns || [];
        const visible = action === "all";
        gridApi.setColumnsVisible(allIds, visible);
        d.columnsMenu.querySelectorAll("input[type=checkbox][data-dd-col-id]")
          .forEach(cb => { cb.checked = visible; });
        cacheVisible();
      });
    });

    // If the user reset columns, re-check everything in the menu.
    if (recheckAll) {
      d.columnsMenu.querySelectorAll("input[type=checkbox][data-dd-col-id]")
        .forEach(cb => { cb.checked = true; });
    }
  }

  function updateRecordCount(total) {
    const d = getDom();
    if (!d.recordCount) return;
    if (!gridApi) {
      d.recordCount.textContent = (total || 0).toLocaleString();
      return;
    }
    const visible = gridApi.getDisplayedRowCount
      ? gridApi.getDisplayedRowCount()
      : (window.PivotGrid ? 0 : 0);
    // Prefer the grid's post-filter count (the user-facing number).
    let shown = visible;
    if (!shown && typeof gridApi.forEachNodeAfterFilter === "function") {
      let n = 0;
      gridApi.forEachNodeAfterFilter(() => n++);
      shown = n;
    }
    if (shown === 0 && gridApi.paginationGetTotalPages) {
      // Older AG Grid API fallback
      shown = (gridApi.paginationGetTotalPages() || 0) *
              (gridApi.paginationGetPageSize ? gridApi.paginationGetPageSize() : 0);
    }
    d.recordCount.textContent = `${shown.toLocaleString()} of ${(total || 0).toLocaleString()} records`;
  }

  function setExportEnabled(enabled) {
    const d = getDom();
    if (d.exportBtn) d.exportBtn.disabled = !enabled;
  }

  function flashExportButton(btn) {
    if (!btn) return;
    const original = btn.innerHTML;
    btn.classList.remove("btn-outline-success");
    btn.classList.add("btn-success");
    btn.innerHTML = '<i class="bi bi-check2 me-1"></i>Exported';
    setTimeout(() => {
      btn.classList.add("btn-outline-success");
      btn.classList.remove("btn-success");
      btn.innerHTML = original;
    }, 1500);
  }

  // ════════════════════════════════════════════════════════════════════════
  // Loading + error states
  // ════════════════════════════════════════════════════════════════════════
  function showLoadingState() {
    const d = getDom();
    if (d.loadingOverlay) {
      d.loadingOverlay.classList.remove("d-none");
      const label = d.loadingOverlay.querySelector("[data-dd-loading-label]");
      if (label) label.textContent = "Loading drill-down…";
    }
    setExportEnabled(false);
  }
  function hideLoadingState() {
    const d = getDom();
    if (d.loadingOverlay) d.loadingOverlay.classList.add("d-none");
  }
  function updateLoadingProgress(done, total, currentRow) {
    const d = getDom();
    if (!d.loadingOverlay) return;
    const label = d.loadingOverlay.querySelector("[data-dd-loading-label]");
    if (!label) return;
    if (total <= 1) {
      label.textContent = "Loading drill-down…";
    } else {
      const criteriaSummary = summariseRow(currentRow);
      label.textContent = `Loading drill-down… (${done} / ${total} group${total === 1 ? "" : "s"}${criteriaSummary ? " · " + criteriaSummary : ""})`;
    }
  }
  function summariseRow(row) {
    if (!row) return "";
    const parts = Object.entries(row)
      .filter(([k, v]) => v !== null && v !== undefined && v !== "" && typeof v !== "number" && k !== "__isGrandTotal")
      .slice(0, 2)
      .map(([k, v]) => `${k}=${String(v).slice(0, 20)}`);
    return parts.join(", ");
  }
  function showError(msg) {
    notify(msg);
  }

  // ════════════════════════════════════════════════════════════════════════
  // Cache the currently visible view (columns + rows) for the export
  // module and for the email phase. Called whenever the grid state
  // (filter / sort / column visibility) changes.
  // ════════════════════════════════════════════════════════════════════════
  function cacheVisible() {
    if (!gridApi) {
      lastVisibleCols = [];
      lastVisibleRows = [];
      return;
    }
    // Visible column defs in display order.
    const visibleColDefs = [];
    if (typeof gridApi.getAllDisplayedColumns === "function") {
      gridApi.getAllDisplayedColumns().forEach(col => {
        if (!col) return;
        visibleColDefs.push({ field: col.getColId(), headerName: col.getColId() });
      });
    } else if (typeof gridApi.getColumns === "function") {
      gridApi.getColumns().forEach(col => {
        if (!col || !col.isVisible || !col.isVisible()) return;
        visibleColDefs.push({ field: col.getColId(), headerName: col.getColId() });
      });
    }
    lastVisibleCols = visibleColDefs;

    // Visible rows in current sort + filter order.
    const rows = [];
    if (typeof gridApi.forEachNodeAfterFilterAndSort === "function") {
      gridApi.forEachNodeAfterFilterAndSort(node => {
        if (node && node.data) rows.push(node.data);
      });
    } else if (typeof gridApi.forEachNode === "function") {
      gridApi.forEachNode(node => { if (node && node.data) rows.push(node.data); });
    }
    lastVisibleRows = rows;

    // Keep the record counter in sync (this runs after every search hit).
    if (lastDataset) updateRecordCount(lastDataset.rows.length);
  }

  // ════════════════════════════════════════════════════════════════════════
  // Theme sync — re-skin the drilldown grid when the OS / app theme flips
  // ════════════════════════════════════════════════════════════════════════
  function applyGridTheme(el) {
    if (!el) return;
    const isDark = !!(window.ThemeManager &&
                      window.ThemeManager.getCurrentTheme &&
                      window.ThemeManager.getCurrentTheme() === "dark");
    el.classList.toggle("ag-theme-alpine-dark", isDark);
    el.classList.toggle("ag-theme-alpine",      !isDark);
  }
  document.addEventListener("theme:changed", () => {
    const d = getDom();
    if (d && d.grid) applyGridTheme(d.grid);
  });

  // ════════════════════════════════════════════════════════════════════════
  // Public getters (used by the export module + the email phase)
  // ════════════════════════════════════════════════════════════════════════
  function hasData() {
    return !!(lastDataset && lastDataset.rows);
  }
  function getCurrentDataset()   { return lastDataset; }
  function getCurrentContext()   { return lastContext; }
  function getVisibleColumns()   { return lastVisibleCols.slice(); }
  function getVisibleRows()      { return lastVisibleRows.slice(); }

  // ════════════════════════════════════════════════════════════════════════
  // Misc helpers
  // ════════════════════════════════════════════════════════════════════════
  function buildRowId(data) {
    if (!data) return String(Math.random());
    return Object.keys(data).sort()
      .map(k => `${k}:${data[k]}`)
      .join("|");
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function notify(msg) {
    // Hook for the controller to display in the page's error alert.
    if (window.DrilldownExport && window.DrilldownExport._notify) {
      window.DrilldownExport._notify(msg);
    } else {
      console.warn("[drilldown]", msg);
    }
  }

  /**
   * Read the current pivot request payload from pivot.js's appState. We
   * rely on a tiny global (`window.PivotAppState`) that pivot.js sets
   * after every successful compute. The fallback reads from the cached
   * `lastContext` so the modal still works if PivotAppState is missing.
   */
  function buildPayloadFromAppState() {
    const fromGlobal = (typeof window.PivotAppState === "function")
      ? window.PivotAppState()
      : (window.PivotAppState || null);
    if (fromGlobal) return fromGlobal;
    if (lastContext && lastContext.payload) return lastContext.payload;
    return null;
  }

  // ════════════════════════════════════════════════════════════════════════
  // Init
  // ════════════════════════════════════════════════════════════════════════
  // Wire the toolbar once the DOM is parsed. The modal is created lazily
  // on the first `open()` call.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireToolbarOnce);
  } else {
    wireToolbarOnce();
  }

  // Reset the cached dataset on every successful pivot recompute, so the
  // drilldown modal can't show stale records from the previous run.
  document.addEventListener("pivot:computed", () => {
    lastDataset = null;
    lastContext = null;
    lastVisibleCols = [];
    lastVisibleRows = [];
  });

  // ════════════════════════════════════════════════════════════════════════
  // Public API
  // ════════════════════════════════════════════════════════════════════════
  window.DrilldownManager = {
    open,
    openForCurrentSelection,
    openForRow,
    close,
    hasData,
    getCurrentDataset,
    getCurrentContext,
    getVisibleColumns,
    getVisibleRows,
  };
})();
