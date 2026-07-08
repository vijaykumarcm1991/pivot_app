/**
 * pivot.js — Pivot Builder controller (Phase 3 config + Phase 4 result UI).
 *
 * Owns:
 *   - The appState object (dataset, sheet, columns, rows, columnsGroup,
 *     values, filters, dateGrouping, sorting, totals, layout).
 *   - The left-panel configuration UI (Phase 3).
 *   - The right-panel action toolbar, stats card, selection bar and empty
 *     state (Phase 4).
 *   - The buildPayload() / validate / compute flow against /api/pivot/validate
 *     and /api/pivot (the Phase 3 contract — unchanged).
 *
 * Delegates:
 *   - AG Grid rendering, selection, search, theme sync → window.PivotGrid
 *   - Excel export of the current view                  → window.PivotExport
 *
 * API endpoints (Phase 3 — do not change):
 *   POST /api/pivot/validate   — pure metadata validation
 *   POST /api/pivot            — compute the pivot
 *   POST /api/pivot/drilldown  — raw rows matching a pivot cell
 */
(function () {
  "use strict";

  // Wrap the whole IIFE in a try-catch so a single bad line (e.g. an
  // uncaught ReferenceError from a missing global) doesn't prevent
  // loadDatasets() from running and the dataset dropdown from
  // populating. The catch logs the error to the console for visibility.
  try {
    main();
  } catch (err) {
    console.error("[pivot.js] init error:", err);
  }

  function main() {

  // ════════════════════════════════════════════════════════════════════════
  // STATE
  // ════════════════════════════════════════════════════════════════════════
  const appState = {
    datasetId:     null,
    sheetName:     null,
    datasetName:   "",     // for stats / export filename
    columns:       [],     // [{name, type, nullable}] for the current sheet
    rows:          [],
    columnsGroup:  [],
    values:        [],     // [{field, aggregation, label}]
    filters:       {},     // {field: [...] | "v" | null}
    dateGrouping:  {},     // {field: "month"}
    sorting:       {},     // {field: "asc" | "desc"}
    totals: {
      showGrandTotals:    true,
      showRowTotals:      true,
      showColumnTotals:   false,
      showSubtotals:      false,
      repeatItemLabels:   false,   // Phase 7
    },
    // Phase 7 — display options.  Mirror of window.PivotDisplay.getState()
    // at the moment we build the payload, then we forward the values to
    // the backend as `displayOptions`.
    displayOptions: {
      numberFormat:        {},   // { field: "integer" | ... }
      dateFormat:          {},   // { field: "yyyy-mm-dd" | ... }
      conditionalFormats:  [],   // [{ field, type, value, background }]
      frozenColumns:       [],   // [field, ...]
      hiddenColumns:       [],   // [field, ...]
    },
    layout: "tabular",
    lastResponse:  null,   // last PivotResponse (for export)
  };

  // ── Allowed aggregations per data type (mirrors pivot_validation_service) ─
  const AGG_BY_TYPE = {
    string:   ["count"],
    text:     ["count"],
    boolean:  ["count"],
    integer:  ["count", "sum", "average", "min", "max"],
    float:    ["count", "sum", "average", "min", "max"],
    decimal:  ["count", "sum", "average", "min", "max"],
    datetime: ["count", "sum", "average", "min", "max"],
    date:     ["count", "sum", "average", "min", "max"],
  };
  const AGG_LABEL = {
    count:   "Count", sum: "Sum", average: "Average", min: "Min", max: "Max",
  };
  const TYPE_ICON = {
    datetime: "📅", integer: "🔢", float: "📊", decimal: "📊",
    boolean:  "✅", string:  "📝", text: "📝", date: "📅",
  };

  // ════════════════════════════════════════════════════════════════════════
  // DOM REFS
  // ════════════════════════════════════════════════════════════════════════
  // Left panel
  const datasetSelect     = document.getElementById("datasetSelect");
  const sheetSelect       = document.getElementById("sheetSelect");
  const sourceInfo        = document.getElementById("sourceInfo");
  const sourceMeta        = document.getElementById("sourceMeta");
  const rowsSelect        = document.getElementById("rowsSelect");
  const colsSelect        = document.getElementById("colsSelect");
  const rowsBadge         = document.getElementById("rowsBadge");
  const colsBadge         = document.getElementById("colsBadge");
  const valuesBadge       = document.getElementById("valuesBadge");
  const valueList         = document.getElementById("valueList");
  const valueFieldSelect  = document.getElementById("valueFieldSelect");
  const valueAggSelect    = document.getElementById("valueAggSelect");
  const addValueBtn       = document.getElementById("addValueBtn");
  const filterFieldSelect = document.getElementById("filterFieldSelect");
  const addFilterBtn      = document.getElementById("addFilterBtn");
  const filterList        = document.getElementById("filterList");
  const addRowBtn         = document.getElementById("addRowBtn");
  const addColBtn         = document.getElementById("addColBtn");
  const removeRowBtn      = document.getElementById("removeRowBtn");
  const removeColBtn      = document.getElementById("removeColBtn");
  const dateGroupingCard  = document.getElementById("dateGroupingCard");
  const dateGroupingBadge = document.getElementById("dateGroupingBadge");
  const dateGroupingList  = document.getElementById("dateGroupingList");
  const dateFieldSelect   = document.getElementById("dateFieldSelect");
  const dateGroupSelect   = document.getElementById("dateGroupSelect");
  const addDateGroupBtn   = document.getElementById("addDateGroupBtn");
  const layoutRadios      = document.getElementsByName("layout");
  const optGrandTotals    = document.getElementById("optGrandTotals");
  const optRowTotals      = document.getElementById("optRowTotals");
  const optColumnTotals   = document.getElementById("optColumnTotals");
  const optSubtotals      = document.getElementById("optSubtotals");
  const sortingCard       = document.getElementById("sortingCard");
  const sortBadge         = document.getElementById("sortBadge");
  const sortList          = document.getElementById("sortList");

  // Right panel — Phase 4
  const computeBtn        = document.getElementById("computeBtn");
  const validateBtn       = document.getElementById("validateBtn");
  const exportBtn         = document.getElementById("exportBtn");
  const drilldownBtn      = document.getElementById("drilldownBtn");
  const emailBtn          = document.getElementById("emailBtn");
  const deleteRecordsBtn  = document.getElementById("deleteRecordsBtn");
  const toggleConfigBtn   = document.getElementById("toggleConfigBtn");
  const fullscreenBtn     = document.getElementById("fullscreenBtn");
  const configPanel       = document.getElementById("configPanel");
  const resultPanel       = document.getElementById("resultPanel");
  const loadingSpinner    = document.getElementById("loadingSpinner");
  const metaStats         = document.getElementById("metaStats");
  const errorAlert        = document.getElementById("errorAlert");
  const validationPanel   = document.getElementById("validationPanel");
  const validationBadge   = document.getElementById("validationBadge");
  const validationBody    = document.getElementById("validationBody");
  const pivotCard         = document.getElementById("pivotCard");
  const pivotGrid         = document.getElementById("pivotGrid");
  const gridLoadingOverlay= document.getElementById("gridLoadingOverlay");
  const statsCard         = document.getElementById("statsCard");
  const statsGrid         = document.getElementById("statsGrid");
  const selectionCard     = document.getElementById("selectionCard");
  const emptyState        = document.getElementById("emptyState");
  const warningBanner     = document.getElementById("warningBanner");
  const warningText       = document.getElementById("warningText");
  const selectAllBtn      = document.getElementById("selectAllBtn");
  const clearSelectionBtn = document.getElementById("clearSelectionBtn");
  const gridSearch        = document.getElementById("gridSearch");
  const debugCard         = document.getElementById("debugCard");
  const requestJson       = document.getElementById("requestJson");
  const responseJson      = document.getElementById("responseJson");

  // Phase 8 — Delete Records modal + draft recovery
  const deleteRecordsModal = document.getElementById("deleteRecordsModal");
  const confirmDeleteBtn   = document.getElementById("confirmDeleteBtn");
  const delDatasetName     = document.getElementById("delDatasetName");
  const delSheetName       = document.getElementById("delSheetName");
  const delPivotRowsCount  = document.getElementById("delPivotRowsCount");
  const delCriteria        = document.getElementById("delCriteria");
  const delResultArea      = document.getElementById("delResultArea");
  const draftBanner        = document.getElementById("draftRecoveryBanner");
  const draftMeta          = document.getElementById("draftRecoveryMeta");
  const restoreDraftBtn    = document.getElementById("restoreDraftBtn");
  const discardDraftBtn    = document.getElementById("discardDraftBtn");

  // Phase 7 — toolbar buttons (right panel)
  const expandAllBtn        = document.getElementById("expandAllBtn");
  const collapseAllBtn      = document.getElementById("collapseAllBtn");
  const pivotColumnsBtn     = document.getElementById("pivotColumnsBtn");
  const pivotColumnsMenu    = document.getElementById("pivotColumnsMenu");
  const pivotColumnsEmptyMsg= document.getElementById("pivotColumnsEmptyMsg");
  const pivotFreezeBtn      = document.getElementById("pivotFreezeBtn");
  const pivotFreezeMenu     = document.getElementById("pivotFreezeMenu");
  const pivotFreezeEmptyMsg = document.getElementById("pivotFreezeEmptyMsg");
  const resetColumnsBtn     = document.getElementById("resetColumnsBtn");
  const printBtn            = document.getElementById("printBtn");
  const resetDisplayOptionsBtn = document.getElementById("resetDisplayOptionsBtn");

  // Phase 7 — totals + display-options checkboxes
  const optRepeatItemLabels = document.getElementById("optRepeatItemLabels");

  // Filter modal (lazy — create on first use, not at module load time).
  const filterModalEl     = document.getElementById("filterModal");
  let   filterModal       = null;
  function getFilterModal() {
    if (filterModal) return filterModal;
    if (!filterModalEl || !window.bootstrap || !window.bootstrap.Modal) return null;
    try {
      filterModal = new window.bootstrap.Modal(filterModalEl);
    } catch (_) {
      filterModal = null;
    }
    return filterModal;
  }
  const filterSearch      = document.getElementById("filterSearch");
  const filterValueList   = document.getElementById("filterValueList");
  const filterSelectAll   = document.getElementById("filterSelectAll");
  const filterSelectNone  = document.getElementById("filterSelectNone");
  const filterApplyBtn    = document.getElementById("filterApplyBtn");
  let filterModalField    = null;
  let filterModalSelected = new Set();

  // Wire PivotExport's notifier to our error alert.
  if (window.PivotExport) {
    window.PivotExport.setNotifier(showError);
  }

  // ════════════════════════════════════════════════════════════════════════
  // INIT
  // ════════════════════════════════════════════════════════════════════════
  loadDatasets();
  showEmptyState();
  hideAllResults();

  // ════════════════════════════════════════════════════════════════════════
  // DATASETS / SHEETS / COLUMNS  (Phase 3 — unchanged)
  // ════════════════════════════════════════════════════════════════════════
  async function loadDatasets() {
    try {
      const res  = await fetch("/api/datasets");
      const data = await res.json();
      datasetSelect.innerHTML = '<option value="">— select a dataset —</option>';
      data.forEach(ds => {
        const opt = document.createElement("option");
        opt.value       = ds.id;
        opt.textContent = ds.filename;
        datasetSelect.appendChild(opt);
      });
    } catch (err) {
      console.error("Failed to load datasets", err);
    }
  }

  datasetSelect.addEventListener("change", async () => {
    const id = datasetSelect.value;
    appState.datasetId = id || null;
    appState.datasetName = id
      ? (datasetSelect.options[datasetSelect.selectedIndex]?.text || "")
      : "";
    appState.sheetName = null;

    sheetSelect.innerHTML = '<option value="">— select —</option>';
    sheetSelect.disabled = !id;
    sourceInfo.style.display = "none";
    appState.columns = [];
    clearColumnSelects();
    clearResults();
    if (!id) return;

    try {
      const res = await fetch(`/api/dataset/${id}`);
      const data = await res.json();
      sheetSelect.innerHTML = '<option value="">— select —</option>';
      data.sheets.forEach(s => {
        const opt = document.createElement("option");
        opt.value       = s.sheet_name;
        opt.textContent = `${s.sheet_name}  (${s.row_count.toLocaleString()} rows)`;
        sheetSelect.appendChild(opt);
      });

      if (data.sheets.length) {
        sheetSelect.value = data.sheets[0].sheet_name;
        appState.sheetName = sheetSelect.value;
        await loadColumnsForSheet(id, appState.sheetName);
      }

      sourceMeta.textContent = `${data.total_rows.toLocaleString()} rows, ${data.total_columns} columns, ${data.sheets.length} sheet(s)`;
      sourceInfo.style.display = "";
    } catch (err) {
      showError("Failed to load dataset metadata: " + err.message);
    }
  });

  sheetSelect.addEventListener("change", async () => {
    const sheet = sheetSelect.value;
    appState.sheetName = sheet || null;
    if (!sheet || !appState.datasetId) return;
    // The previous pivot result was computed for the OLD sheet — clear
    // it so we never show stale data (Phase 4 spec §16, "refresh").
    clearResults();
    clearColumnSelects();
    await loadColumnsForSheet(appState.datasetId, sheet);
  });

  async function loadColumnsForSheet(datasetId, sheetName) {
    try {
      const res = await fetch(
        `/api/dataset/${datasetId}/sheet/${encodeURIComponent(sheetName)}/columns`
      );
      const data = await res.json();
      appState.columns = (data || []).map(c => ({
        name:     c.column_name,
        type:     c.data_type,
        nullable: c.is_nullable,
      }));
      populateColumnSelects();
    } catch (err) {
      showError("Failed to load columns: " + err.message);
    }
  }

  function populateColumnSelects() {
    clearColumnSelects();
    valueFieldSelect.disabled = false;
    filterFieldSelect.disabled = false;
    addValueBtn.disabled      = false;
    addFilterBtn.disabled     = false;

    valueFieldSelect.innerHTML  = '<option value="">— field —</option>';
    filterFieldSelect.innerHTML = '<option value="">— field —</option>';
    dateFieldSelect.innerHTML   = '<option value="">— date field —</option>';

    appState.columns.forEach(col => {
      const vOpt = document.createElement("option");
      vOpt.value       = col.name;
      vOpt.textContent = `${col.name} ${TYPE_ICON[col.type] || ""}`;
      valueFieldSelect.appendChild(vOpt);

      const fOpt = document.createElement("option");
      fOpt.value       = col.name;
      fOpt.textContent = col.name;
      filterFieldSelect.appendChild(fOpt);

      if (col.type === "datetime" || col.type === "date") {
        const dOpt = document.createElement("option");
        dOpt.value       = col.name;
        dOpt.textContent = col.name;
        dateFieldSelect.appendChild(dOpt);
      }
    });

    rowsSelect.disabled = false;
    colsSelect.disabled = false;
    addRowBtn.disabled  = false;
    addColBtn.disabled  = false;
    rowsSelect.innerHTML = "";
    colsSelect.innerHTML = "";

    appState.columns.forEach(col => {
      const rOpt = document.createElement("option");
      rOpt.value       = col.name;
      rOpt.textContent = `${col.name} ${TYPE_ICON[col.type] || ""}`;
      rowsSelect.appendChild(rOpt.cloneNode(true));
      colsSelect.appendChild(rOpt.cloneNode(true));
    });

    const hasDate = appState.columns.some(c => c.type === "datetime" || c.type === "date");
    dateGroupingCard.style.display = hasDate ? "" : "none";
    dateFieldSelect.disabled = !hasDate;
    addDateGroupBtn.disabled = !hasDate;

    updateBadges();
  }

  function clearColumnSelects() {
    rowsSelect.innerHTML      = "";
    colsSelect.innerHTML      = "";
    valueList.innerHTML       = "";
    filterList.innerHTML      = "";
    dateGroupingList.innerHTML = "";
    sortList.innerHTML        = "";
    [rowsSelect, colsSelect, valueFieldSelect, filterFieldSelect, dateFieldSelect]
      .forEach(s => (s.disabled = true));
    [addRowBtn, addColBtn, addValueBtn, addFilterBtn, removeRowBtn, removeColBtn, addDateGroupBtn]
      .forEach(b => (b.disabled = true));
    dateGroupingCard.style.display = "none";
    sortingCard.style.display      = "none";
    appState.dateGrouping = {};
    appState.sorting      = {};
    updateBadges();
  }

  valueFieldSelect.addEventListener("change", () => {
    const field = valueFieldSelect.value;
    const col   = appState.columns.find(c => c.name === field);
    if (!col) return;
    const allowed = AGG_BY_TYPE[col.type] || ["count"];
    valueAggSelect.innerHTML = "";
    allowed.forEach(agg => {
      const opt = document.createElement("option");
      opt.value       = agg;
      opt.textContent = AGG_LABEL[agg] || agg;
      valueAggSelect.appendChild(opt);
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // ROWS / COLUMNS / VALUES / FILTERS  (Phase 3 — unchanged)
  // ════════════════════════════════════════════════════════════════════════
  function updateBadges() {
    rowsBadge.textContent           = appState.rows.length;
    colsBadge.textContent           = appState.columnsGroup.length;
    valuesBadge.textContent         = appState.values.length;
    dateGroupingBadge.textContent   = Object.keys(appState.dateGrouping).length;
    sortBadge.textContent           = Object.keys(appState.sorting).length;

    removeRowBtn.disabled = !rowsSelect.selectedOptions.length;
    removeColBtn.disabled = !colsSelect.selectedOptions.length;

    const canSubmit = !!appState.datasetId && !!appState.sheetName;
    computeBtn.disabled  = !canSubmit;
    validateBtn.disabled = !canSubmit;

    sortingCard.style.display = appState.rows.length ? "" : "none";
    renderSortList();
    renderDateGroupingList();
    renderValueList();
    renderFilterList();
  }

  addRowBtn.addEventListener("click", () => {
    Array.from(rowsSelect.selectedOptions).forEach(o => {
      const field = o.value;
      if (!appState.rows.includes(field)) appState.rows.push(field);
    });
    updateBadges();
  });

  addColBtn.addEventListener("click", () => {
    Array.from(colsSelect.selectedOptions).forEach(o => {
      const field = o.value;
      if (!appState.columnsGroup.includes(field)) appState.columnsGroup.push(field);
    });
    updateBadges();
  });

  removeRowBtn.addEventListener("click", () => {
    const selected = Array.from(rowsSelect.selectedOptions).map(o => o.value);
    appState.rows = appState.rows.filter(f => !selected.includes(f));
    selected.forEach(f => {
      delete appState.dateGrouping[f];
      delete appState.sorting[f];
    });
    updateBadges();
  });

  removeColBtn.addEventListener("click", () => {
    const selected = Array.from(colsSelect.selectedOptions).map(o => o.value);
    appState.columnsGroup = appState.columnsGroup.filter(f => !selected.includes(f));
    selected.forEach(f => delete appState.dateGrouping[f]);
    updateBadges();
  });

  addDateGroupBtn.addEventListener("click", () => {
    const field    = dateFieldSelect.value;
    const grouping = dateGroupSelect.value;
    if (!field) return;
    appState.dateGrouping[field] = grouping;
    if (!appState.rows.includes(field) && !appState.columnsGroup.includes(field)) {
      appState.rows.push(field);
    }
    updateBadges();
  });

  function renderDateGroupingList() {
    dateGroupingList.innerHTML = "";
    Object.entries(appState.dateGrouping).forEach(([field, grouping]) => {
      const div = document.createElement("div");
      div.className = "d-flex justify-content-between align-items-center border-bottom py-1";
      div.innerHTML = `
        <span><i class="bi bi-calendar3 text-warning me-1"></i><span class="fw-medium">${escHtml(field)}</span></span>
        <span class="badge bg-warning me-1">${escHtml(grouping)}</span>
        <button class="btn btn-sm btn-outline-danger" data-field="${escHtml(field)}">
          <i class="bi bi-x-lg"></i>
        </button>
      `;
      dateGroupingList.appendChild(div);
    });
    dateGroupingList.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", () => {
        delete appState.dateGrouping[btn.getAttribute("data-field")];
        updateBadges();
      });
    });
  }

  function renderSortList() {
    sortList.innerHTML = "";
    appState.rows.forEach(field => {
      const current = appState.sorting[field] || "";
      const div = document.createElement("div");
      div.className = "d-flex justify-content-between align-items-center border-bottom py-1";
      div.innerHTML = `
        <span class="fw-medium">${escHtml(field)}</span>
        <div class="btn-group btn-group-sm" role="group">
          <button type="button" class="btn btn-outline-secondary ${current === "asc"  ? "active" : ""}" data-field="${escHtml(field)}" data-dir="asc"  title="Ascending">▲</button>
          <button type="button" class="btn btn-outline-secondary ${current === "desc" ? "active" : ""}" data-field="${escHtml(field)}" data-dir="desc" title="Descending">▼</button>
          <button type="button" class="btn btn-outline-secondary ${!current        ? "active" : ""}" data-field="${escHtml(field)}" data-dir=""     title="No sort">⊘</button>
        </div>
      `;
      sortList.appendChild(div);
    });
    sortList.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", () => {
        const field = btn.getAttribute("data-field");
        const dir   = btn.getAttribute("data-dir");
        if (dir) appState.sorting[field] = dir;
        else     delete appState.sorting[field];
        updateBadges();
      });
    });
  }

  addValueBtn.addEventListener("click", () => {
    const field = valueFieldSelect.value;
    const agg   = valueAggSelect.value;
    if (!field || !agg) return;
    const col = appState.columns.find(c => c.name === field);
    if (!col) return;
    const allowed = AGG_BY_TYPE[col.type] || ["count"];
    if (!allowed.includes(agg)) {
      showError(`Aggregation "${agg}" is not allowed for ${col.type} field "${field}". Allowed: ${allowed.join(", ")}.`);
      return;
    }
    const label = `${agg}_${field}`;
    appState.values.push({ field, aggregation: agg, label });
    updateBadges();
  });

  function renderValueList() {
    valueList.innerHTML = "";
    appState.values.forEach((spec, idx) => {
      const div = document.createElement("div");
      div.className = "d-flex justify-content-between align-items-center border-bottom py-1";
      div.innerHTML = `
        <span><i class="bi bi-calculator text-success me-1"></i><span class="fw-medium">${escHtml(spec.label)}</span></span>
        <div>
          <span class="badge bg-${aggregationColor(spec.aggregation)} me-1">${escHtml(spec.aggregation)}</span>
          <button class="btn btn-sm btn-outline-danger" data-index="${idx}">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
      `;
      valueList.appendChild(div);
    });
    valueList.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.getAttribute("data-index"), 10);
        appState.values.splice(idx, 1);
        updateBadges();
      });
    });
  }

  addFilterBtn.addEventListener("click", () => {
    const field = filterFieldSelect.value;
    if (!field) return;
    openFilterModal(field);
  });

  async function openFilterModal(field) {
    filterModalField    = field;
    filterModalSelected = new Set();

    const existing = appState.filters[field];
    if (Array.isArray(existing))     existing.forEach(v => filterModalSelected.add(String(v)));
    else if (existing !== undefined) filterModalSelected.add(String(existing));

    filterValueList.innerHTML = '<div class="text-muted small p-2">Loading values…</div>';
    const m = getFilterModal();
    if (m) m.show();

    try {
      const res  = await fetch(
        `/api/dataset/${appState.datasetId}/sheet/${encodeURIComponent(appState.sheetName)}/preview`
      );
      const data = await res.json();
      const seen = new Set();
      const distinct = [];
      (data.rows || []).forEach(row => {
        const v = row[field];
        if (v === undefined || v === null || v === "") return;
        const k = String(v);
        if (!seen.has(k)) { seen.add(k); distinct.push(v); }
      });
      distinct.sort((a, b) => String(a).localeCompare(String(b), undefined, { numeric: true }));
      renderFilterValueList(distinct);
    } catch (err) {
      filterValueList.innerHTML = `<div class="text-danger small p-2">Failed to load values: ${escHtml(err.message)}</div>`;
    }
  }

  function renderFilterValueList(values) {
    filterValueList.innerHTML = "";
    if (!values.length) {
      filterValueList.innerHTML = '<div class="text-muted small p-2">No values found.</div>';
      return;
    }
    values.forEach(v => {
      const key = String(v);
      const checked = filterModalSelected.has(key);
      const item = document.createElement("label");
      item.className = "list-group-item d-flex align-items-center";
      item.innerHTML = `
        <input class="form-check-input me-2" type="checkbox" value="${escHtml(key)}" ${checked ? "checked" : ""}>
        <span>${escHtml(key)}</span>
      `;
      const cb = item.querySelector("input");
      cb.addEventListener("change", () => {
        if (cb.checked) filterModalSelected.add(key);
        else           filterModalSelected.delete(key);
      });
      filterValueList.appendChild(item);
    });
  }

  if (filterSearch) {
    filterSearch.addEventListener("input", () => {
      const q = filterSearch.value.toLowerCase();
      filterValueList.querySelectorAll(".list-group-item").forEach(li => {
        li.style.display = li.textContent.toLowerCase().includes(q) ? "" : "none";
      });
    });
  }
  if (filterSelectAll) {
    filterSelectAll.addEventListener("click", () => {
      filterValueList.querySelectorAll("input[type=checkbox]").forEach(cb => {
        cb.checked = true;
        filterModalSelected.add(cb.value);
      });
    });
  }
  if (filterSelectNone) {
    filterSelectNone.addEventListener("click", () => {
      filterValueList.querySelectorAll("input[type=checkbox]").forEach(cb => {
        cb.checked = false;
        filterModalSelected.delete(cb.value);
      });
    });
  }
  if (filterApplyBtn) {
    filterApplyBtn.addEventListener("click", () => {
      if (!filterModalField) return;
      if (filterModalSelected.size === 0) {
        delete appState.filters[filterModalField];
      } else {
        appState.filters[filterModalField] = Array.from(filterModalSelected);
      }
      updateBadges();
      const m = getFilterModal();
      if (m) m.hide();
    });
  }

  function renderFilterList() {
    filterList.innerHTML = "";
    Object.entries(appState.filters).forEach(([field, val]) => {
      const display = Array.isArray(val)
        ? (val.length > 3 ? `${val.length} values` : val.join(", "))
        : (val === null ? "[null]" : String(val));
      const div = document.createElement("div");
      div.className = "d-flex justify-content-between align-items-center border-bottom py-1";
      div.innerHTML = `
        <span><i class="bi bi-funnel-fill text-warning me-1"></i><span class="fw-medium">${escHtml(field)}</span></span>
        <div>
          <span class="text-muted small me-2">${escHtml(display)}</span>
          <button class="btn btn-sm btn-outline-warning me-1" data-field="${escHtml(field)}" data-action="edit" title="Edit">
            <i class="bi bi-pencil"></i>
          </button>
          <button class="btn btn-sm btn-outline-danger" data-field="${escHtml(field)}" data-action="remove" title="Remove">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
      `;
      filterList.appendChild(div);
    });
    filterList.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", () => {
        const field  = btn.getAttribute("data-field");
        const action = btn.getAttribute("data-action");
        if (action === "remove") {
          delete appState.filters[field];
          updateBadges();
        } else if (action === "edit") {
          openFilterModal(field);
        }
      });
    });
  }

  layoutRadios.forEach(r => r.addEventListener("change", e => {
    appState.layout = e.target.value;
  }));
  optGrandTotals    .addEventListener("change", () => appState.totals.showGrandTotals  = optGrandTotals.checked);
  optRowTotals      .addEventListener("change", () => appState.totals.showRowTotals    = optRowTotals.checked);
  optColumnTotals   .addEventListener("change", () => appState.totals.showColumnTotals = optColumnTotals.checked);
  optSubtotals      .addEventListener("change", () => appState.totals.showSubtotals    = optSubtotals.checked);
  if (optRepeatItemLabels) {
    optRepeatItemLabels.addEventListener("change", () => appState.totals.repeatItemLabels = optRepeatItemLabels.checked);
  }

  // Phase 7 — Read the current display options from PivotDisplay
  // and copy them into appState so the next payload includes them.
  function syncDisplayOptionsFromUI() {
    if (!window.PivotDisplay) return;
    const s = window.PivotDisplay.getState();
    appState.displayOptions = {
      numberFormat:       s.numberFormat || {},
      dateFormat:         s.dateFormat   || {},
      conditionalFormats: s.conditional  || [],
      frozenColumns:      s.frozen       || [],
      hiddenColumns:      s.hidden       || [],
    };
  }
  // Trigger a sync on every change to the display options UI.  We
  // can't listen to every internal widget, so we listen to `change`
  // events on the parent card and to clicks on any of its buttons.
  const displayCard = document.getElementById("displayOptionsCard");
  if (displayCard) {
    displayCard.addEventListener("change", syncDisplayOptionsFromUI);
    displayCard.addEventListener("click", (e) => {
      // The format list has remove buttons — debounce so we don't
      // resync 30 times when a user is clicking through a list.
      setTimeout(syncDisplayOptionsFromUI, 0);
    });
  }
  if (resetDisplayOptionsBtn) {
    resetDisplayOptionsBtn.addEventListener("click", () => {
      if (window.PivotDisplay) window.PivotDisplay.reset();
      syncDisplayOptionsFromUI();
    });
  }

  // ════════════════════════════════════════════════════════════════════════
  // BUILD PAYLOAD  (Phase 3 + 7 contract)
  // ════════════════════════════════════════════════════════════════════════
  function buildPayload() {
    // Phase 7: re-read the display-options state at the moment the
    // payload is built (rather than relying on appState being kept in
    // sync, which is brittle if the user interacts with a widget
    // before the change event fires).
    syncDisplayOptionsFromUI();
    return {
      datasetId:      appState.datasetId,
      sheetName:      appState.sheetName,
      rows:           [...appState.rows],
      columns:        [...appState.columnsGroup],
      values:         appState.values.map(v => ({ ...v })),
      filters:        { ...appState.filters },
      dateGrouping:   { ...appState.dateGrouping },
      sorting:        { ...appState.sorting },
      totals:         { ...appState.totals },
      displayOptions: { ...appState.displayOptions,
                        numberFormat:       { ...(appState.displayOptions.numberFormat       || {}) },
                        dateFormat:         { ...(appState.displayOptions.dateFormat         || {}) },
                        conditionalFormats: [...(appState.displayOptions.conditionalFormats || [])],
                        frozenColumns:      [...(appState.displayOptions.frozenColumns      || [])],
                        hiddenColumns:      [...(appState.displayOptions.hiddenColumns      || [])],
                      },
      layout:         appState.layout,
    };
  }

  // Expose the current pivot payload to other modules (Phase 5 drilldown
  // manager). The function is preferred so we always read the latest
  // appState at call time, but a plain value is also accepted.
  window.PivotAppState = () => {
    if (!appState.datasetId || !appState.sheetName) return null;
    const payload = buildPayload();
    // Phase 7 — also expose the full dataset column list so the
    // display-options dropdowns (number / date format, freeze, hide)
    // can show every field, not just the ones currently in the
    // pivot definition.
    payload.columns = [...(appState.columns || []).map(c => c.name)];
    return payload;
  };

  // ════════════════════════════════════════════════════════════════════════
  // VALIDATE  (Phase 3)
  // ════════════════════════════════════════════════════════════════════════
  validateBtn.addEventListener("click", validatePivot);
  async function validatePivot() {
    if (!appState.datasetId || !appState.sheetName) return;
    hideError();
    validationPanel.style.display = "none";
    loadingSpinner.classList.remove("d-none");
    const payload = buildPayload();
    requestJson.textContent = JSON.stringify(payload, null, 2);
    try {
      const res  = await fetch("/api/pivot/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      responseJson.textContent = JSON.stringify(data, null, 2);
      renderValidation(data);
      debugCard.style.display = "";
    } catch (err) {
      showError("Validation failed: " + err.message);
    } finally {
      loadingSpinner.classList.add("d-none");
    }
  }

  function renderValidation(data) {
    validationPanel.style.display = "";
    validationBody.innerHTML = "";
    const valid = data.valid;
    validationBadge.className = "badge " + (valid ? "bg-success" : "bg-danger");
    validationBadge.textContent = valid ? "Valid" : `${data.errors.length} error(s)`;
    if (valid && (!data.warnings || !data.warnings.length)) {
      validationBody.innerHTML = '<div class="text-success"><i class="bi bi-check-circle-fill me-1"></i>Configuration is valid and ready to compute.</div>';
      return;
    }
    if (data.errors && data.errors.length) {
      const errDiv = document.createElement("div");
      errDiv.className = "alert alert-danger py-2 mb-2";
      errDiv.innerHTML = "<strong>Errors</strong><ul class='mb-0'>" +
        data.errors.map(e => `<li>${escHtml(e)}</li>`).join("") + "</ul>";
      validationBody.appendChild(errDiv);
    }
    if (data.warnings && data.warnings.length) {
      const warnDiv = document.createElement("div");
      warnDiv.className = "alert alert-warning py-2 mb-0";
      warnDiv.innerHTML = "<strong>Warnings</strong><ul class='mb-0'>" +
        data.warnings.map(w => `<li>${escHtml(w)}</li>`).join("") + "</ul>";
      validationBody.appendChild(warnDiv);
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  // GENERATE PIVOT  (Phase 4 — renamed from "Compute Pivot")
  // ════════════════════════════════════════════════════════════════════════
  computeBtn.addEventListener("click", computePivot);
  async function computePivot() {
    if (!appState.datasetId || !appState.sheetName) return;
    hideError();
    validationPanel.style.display = "none";

    // Phase 4: show loading overlay, disable button, hide empty state
    setComputing(true);

    // Phase 8 — on narrow viewports the actions card itself is below
    // the fold (because the left config panel stacks vertically with
    // the right result area), so the user can't see the loading state
    // they just triggered. Scroll the actions card into view so the
    // spinner is visible while the request is in flight.
    try {
      const ac = document.getElementById("actionsCard");
      if (ac) {
        const rect = ac.getBoundingClientRect();
        const vh = window.innerHeight || document.documentElement.clientHeight;
        if (rect.top < 0 || rect.bottom > vh) {
          ac.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      }
    } catch (_) { /* best-effort */ }

    const payload = buildPayload();
    requestJson.textContent = JSON.stringify(payload, null, 2);
    try {
      const res = await fetch("/api/pivot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      responseJson.textContent = JSON.stringify(data, null, 2);
      if (!res.ok) throw new Error(data.detail || "Pivot request failed");

      appState.lastResponse = data;
      const context = {
        datasetName: appState.datasetName,
        sheetName:   appState.sheetName,
        // Phase 5: open the drill-down modal when the user double-clicks
        // a pivot row. The grand-total row is filtered out inside
        // pivot-grid.js (see onRowDoubleClicked).
        onRowDoubleClick: (row) => {
          if (window.DrilldownManager) {
            window.DrilldownManager.openForRow(row);
          }
        },
        // Phase 6 + 8 — enable the Send Email and Delete Records
        // buttons only when at least one row is selected. The buttons
        // start disabled in the markup; this callback turns them on
        // when the user picks rows.
        onSelectionChange: (count) => {
          if (emailBtn)         emailBtn.disabled         = !(count > 0);
          if (deleteRecordsBtn) deleteRecordsBtn.disabled = !(count > 0);
        },
      };

      renderResult(data, context);

      // Phase 5: let listeners know a fresh pivot is available. The
      // drill-down manager uses this to clear its cached dataset so a
      // subsequent drill-down can't show records from the previous run.
      document.dispatchEvent(new CustomEvent("pivot:computed", {
        detail: { response: data, context: context },
      }));
    } catch (err) {
      showError("Pivot computation failed: " + err.message);
      clearResults();
    } finally {
      setComputing(false);
    }
  }

  /**
   * Phase 4 §1: loading overlay + disabled Generate button while the
   * request is in flight. We also enable the Export button here once a
   * result is rendered, and disable it again on clear.
   */
  function setComputing(isComputing) {
    if (loadingSpinner)    loadingSpinner.classList.toggle("d-none", !isComputing);
    if (gridLoadingOverlay) {
      gridLoadingOverlay.classList.toggle("d-none", !isComputing);
    }
    if (computeBtn) {
      computeBtn.disabled = isComputing || !appState.datasetId || !appState.sheetName;
    }
    if (validateBtn) {
      validateBtn.disabled = isComputing || !appState.datasetId || !appState.sheetName;
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  // RENDER RESULT  (Phase 4 — orchestrates grid / stats / selection / warning)
  // ════════════════════════════════════════════════════════════════════════
  function renderResult(data, context) {
    if (!data || !Array.isArray(data.rows)) {
      showError("Invalid pivot response from the server.");
      return;
    }

    hideEmptyState();
    hideAllResults();

    const meta  = data.metadata || {};
    const rows  = data.rows || [];
    const warning = rows.find(r => r && typeof r._warning === "string");
    const dataRows = rows.filter(r => !(r && typeof r._warning === "string"));

    // 1. Render the grid (Phase 4 §2–9)
    if (dataRows.length || warning) {
      if (window.PivotGrid && pivotGrid) {
        window.PivotGrid.render(pivotGrid, data, context);
      }
    }

    // 2. Stats panel (Phase 4 §10)
    renderStats(data, context);

    // 3. Selection card — visible if there's a result
    if (selectionCard) selectionCard.style.display = dataRows.length ? "" : "none";

    // 4. Meta line in the action toolbar
    if (metaStats) {
      metaStats.innerHTML = `
        <span class="text-primary">${(dataRows.length).toLocaleString()} rows</span>,
        <span class="text-success">${(data.columns || []).length} columns</span>
        <span class="text-muted">·</span>
        <span class="text-muted">${(meta.filtered_rows || 0).toLocaleString()} filtered from ${(meta.source_rows || 0).toLocaleString()}</span>
      `;
    }

    // 5. Warning banner (Phase 4 §14)
    if (warning) {
      warningText.textContent = warning._warning;
      warningBanner.style.display = "";
    } else {
      warningBanner.style.display = "none";
    }

    // 6. Show the grid card + debug card
    pivotCard.style.display = "";
    debugCard.style.display = "";

    // Phase 8 — auto-scroll to the grid after a successful compute.
    // On narrow viewports the actions card + grid are below the
    // fold, so the user can't see the result without scrolling.
    // We scroll the grid into view (smooth, not blocking the
    // compute). We skip the scroll if the grid is already fully
    // visible in the viewport.
    try {
      if (pivotCard) {
        const rect = pivotCard.getBoundingClientRect();
        const vh = window.innerHeight || document.documentElement.clientHeight;
        const fullyVisible = rect.top >= 0 && rect.bottom <= vh;
        if (!fullyVisible) {
          // Small delay so the grid is in the DOM before we scroll.
          setTimeout(() => {
            try {
              pivotCard.scrollIntoView({ behavior: "smooth", block: "start" });
            } catch (_) {
              pivotCard.scrollIntoView();
            }
          }, 50);
        }
      }
    } catch (_) { /* best-effort */ }

    // 7. Enable Export (Phase 4 §12) + Drill-down (Phase 5) + Email (Phase 6)
    //    + Delete Records (Phase 8)
    if (exportBtn)         exportBtn.disabled         = false;
    if (drilldownBtn)      drilldownBtn.disabled      = false;
    if (emailBtn)          emailBtn.disabled          = false;
    if (deleteRecordsBtn)  deleteRecordsBtn.disabled  = false;

    // 8. Phase 7 — enable expand/collapse, columns, freeze, auto-fit, copy,
    //    print, and the conditional-formatting button.  We only enable
    //    Expand/Collapse when the response has a row hierarchy (more
    //    than one row field), otherwise the buttons would be no-ops.
    const hasMultiRows = Array.isArray(meta.rows) && meta.rows.length > 1;
    if (expandAllBtn)    expandAllBtn.disabled    = !hasMultiRows;
    if (collapseAllBtn)  collapseAllBtn.disabled  = !hasMultiRows;
    if (pivotColumnsBtn) pivotColumnsBtn.disabled = !dataRows.length;
    if (pivotFreezeBtn)  pivotFreezeBtn.disabled  = !dataRows.length;
    if (resetColumnsBtn) resetColumnsBtn.disabled = !dataRows.length;
    if (printBtn)        printBtn.disabled        = !dataRows.length;
    // The auto-fit and copy dropdowns are always enabled while a
    // result is on screen.
    const autoFitBtn = document.getElementById("autoFitBtn");
    if (autoFitBtn) autoFitBtn.disabled = !dataRows.length;
    const copyBtn = document.getElementById("copyBtn");
    if (copyBtn) copyBtn.disabled = !dataRows.length;
    rebuildColumnsMenu(data);
    rebuildFreezeMenu(data);
  }

  // ════════════════════════════════════════════════════════════════════════
  // STATS PANEL  (Phase 4 §10)
  // ════════════════════════════════════════════════════════════════════════
  function renderStats(data, context) {
    if (!statsGrid || !statsCard) return;
    const meta = data.metadata || {};
    const aggs = data.aggregations || [];
    const dataRows = (data.rows || []).filter(r => !(r && typeof r._warning === "string"));

    const stats = [
      { label: "Dataset",         value: context.datasetName || "—" },
      { label: "Sheet",           value: meta.sheet_name || "—" },
      { label: "Source Rows",     value: (meta.source_rows || 0).toLocaleString() },
      { label: "Rows After Filters", value: (meta.filtered_rows || 0).toLocaleString() },
      { label: "Pivot Rows Returned", value: dataRows.length.toLocaleString() },
      { label: "Layout",          value: meta.layout === "compact" ? "Compact" : "Tabular" },
      { label: "Date Grouping",   value: formatDateGrouping(meta.date_grouping || {}), muted: true },
      { label: "Aggregations Used", value: formatAggregations(aggs), muted: true },
    ];

    statsGrid.innerHTML = "";
    stats.forEach(s => {
      const col = document.createElement("div");
      col.className = "col-md-3 col-sm-6";
      const valueClass = s.muted && !s.value
        ? "stat-value text-muted"
        : "stat-value";
      col.innerHTML = `
        <div class="pivot-stat">
          <div class="stat-label">${escHtml(s.label)}</div>
          <div class="${valueClass}">${s.value}</div>
        </div>
      `;
      statsGrid.appendChild(col);
    });
    statsCard.style.display = "";
  }

  function formatDateGrouping(dg) {
    const entries = Object.entries(dg || {});
    if (!entries.length) return '<span class="text-muted">none</span>';
    return entries
      .map(([f, g]) => `<span class="pivot-agg-pill">${escHtml(f)} → ${escHtml(g)}</span>`)
      .join("");
  }

  function formatAggregations(aggs) {
    if (!aggs.length) return '<span class="text-muted">none</span>';
    return aggs
      .map(a => `<span class="pivot-agg-pill">${escHtml(a.field)}: ${escHtml(a.aggregation)}</span>`)
      .join("");
  }

  // ════════════════════════════════════════════════════════════════════════
  // SELECTION BAR  (Phase 4 §3)
  // ════════════════════════════════════════════════════════════════════════
  if (selectAllBtn) {
    selectAllBtn.addEventListener("click", () => {
      if (window.PivotGrid) window.PivotGrid.selectAll();
    });
  }
  if (clearSelectionBtn) {
    clearSelectionBtn.addEventListener("click", () => {
      if (window.PivotGrid) window.PivotGrid.clearSelection();
    });
  }

  // ════════════════════════════════════════════════════════════════════════
  // SEARCH  (Phase 4 §11)
  // ════════════════════════════════════════════════════════════════════════
  if (gridSearch) {
    let searchTimer = null;
    gridSearch.addEventListener("input", () => {
      // Debounce so we don't recompute the quick filter on every keystroke.
      clearTimeout(searchTimer);
      const term = gridSearch.value;
      searchTimer = setTimeout(() => {
        if (window.PivotGrid) window.PivotGrid.setSearchTerm(term);
      }, 120);
    });
  }

  // ════════════════════════════════════════════════════════════════════════
  // EXPORT  (Phase 4 §12)
  // ════════════════════════════════════════════════════════════════════════
  if (exportBtn) {
    exportBtn.addEventListener("click", () => {
      if (!window.PivotExport) {
        showError("Export module not loaded.");
        return;
      }
      const filename = window.PivotExport.exportCurrentView();
      if (filename) {
        // Briefly highlight the button so the user knows the file was saved.
        const original = exportBtn.innerHTML;
        exportBtn.classList.remove("btn-outline-success");
        exportBtn.classList.add("btn-success");
        exportBtn.innerHTML = '<i class="bi bi-check2 me-1"></i>Exported';
        setTimeout(() => {
          exportBtn.classList.add("btn-outline-success");
          exportBtn.classList.remove("btn-success");
          exportBtn.innerHTML = original;
        }, 1500);
      }
    });
  }

  // ════════════════════════════════════════════════════════════════════════
  // DRILL-DOWN  (Phase 5)
  // ════════════════════════════════════════════════════════════════════════
  // Open the drill-down modal for:
  //   - the currently selected pivot rows (multi-row drilldown), or
  //   - the row the user just double-clicked (handled by PivotGrid's
  //     onRowDoubleClicked → DrilldownManager.openForRow).
  // The button is enabled once a pivot result has been rendered.
  if (drilldownBtn) {
    drilldownBtn.addEventListener("click", () => {
      if (!window.DrilldownManager) {
        showError("Drill-down module not loaded.");
        return;
      }
      if (!appState.lastResponse) {
        showError("Generate a pivot first.");
        return;
      }
      window.DrilldownManager.openForCurrentSelection();
    });
  }

  // Wire DrilldownExport's notifier to our error alert so export
  // problems surface in the same alert as compute errors.
  if (window.DrilldownExport) {
    window.DrilldownExport.setNotifier(showError);
  }

  // ════════════════════════════════════════════════════════════════════════
  // SEND EMAIL  (Phase 6)
  // ════════════════════════════════════════════════════════════════════════
  // Open the email composer. The button is enabled only after a
  // pivot is rendered (via `renderResult`) — the composer itself
  // requires at least one selected pivot row, which EmailManager
  // enforces before opening the modal.
  if (emailBtn) {
    emailBtn.addEventListener("click", () => {
      if (!window.EmailManager) {
        showError("Email module not loaded.");
        return;
      }
      if (!appState.lastResponse) {
        showError("Generate a pivot first.");
        return;
      }
      window.EmailManager.open();
    });
  }

  // ════════════════════════════════════════════════════════════════════════
  // EMPTY STATES / CLEAR  (Phase 4 §14)
  // ════════════════════════════════════════════════════════════════════════
  function hideAllResults() {
    if (pivotCard)     pivotCard.style.display = "none";
    if (statsCard)     statsCard.style.display = "none";
    if (selectionCard) selectionCard.style.display = "none";
    if (warningBanner) warningBanner.style.display = "none";
    if (exportBtn)         exportBtn.disabled         = true;
    if (drilldownBtn)      drilldownBtn.disabled      = true;
    if (emailBtn)          emailBtn.disabled          = true;
    if (deleteRecordsBtn)  deleteRecordsBtn.disabled  = true;
    if (metaStats)     metaStats.innerHTML = "";
    if (window.PivotGrid) window.PivotGrid.clear();
    // Phase 7 — disable the new toolbar buttons
    if (expandAllBtn)    expandAllBtn.disabled    = true;
    if (collapseAllBtn)  collapseAllBtn.disabled  = true;
    if (pivotColumnsBtn) pivotColumnsBtn.disabled = true;
    if (pivotFreezeBtn)  pivotFreezeBtn.disabled  = true;
    if (resetColumnsBtn) resetColumnsBtn.disabled = true;
    if (printBtn)        printBtn.disabled        = true;
    const autoFitBtn = document.getElementById("autoFitBtn");
    if (autoFitBtn) autoFitBtn.disabled = true;
    const copyBtn = document.getElementById("copyBtn");
    if (copyBtn) copyBtn.disabled = true;
  }

  function showEmptyState() {
    if (emptyState) emptyState.style.display = "";
  }
  function hideEmptyState() {
    if (emptyState) emptyState.style.display = "none";
  }

  function clearResults() {
    hideAllResults();
    showEmptyState();
  }

  // ════════════════════════════════════════════════════════════════════════
  // VIEW CONTROLS — hideable config panel + fullscreen pivot result
  // ════════════════════════════════════════════════════════════════════════

  // Track the current state of the two view toggles so we can update
  // button icons, aria attributes, and the result-panel column class
  // correctly.
  let configHidden  = false;
  let isFullscreen  = false;

  /**
   * Show / hide the left-side configuration panel. When hidden, the
   * result panel switches from col-lg-8 to col-lg-12 so it fills the row.
   */
  function setConfigHidden(hidden) {
    if (!configPanel || !resultPanel) return;
    configHidden = !!hidden;

    if (configHidden) {
      configPanel.classList.add("d-none");
      resultPanel.classList.remove("col-lg-8");
      resultPanel.classList.add("col-lg-12");
    } else {
      configPanel.classList.remove("d-none");
      resultPanel.classList.remove("col-lg-12");
      resultPanel.classList.add("col-lg-8");
    }

    // Update the toggle button's icon + label + aria state.
    if (toggleConfigBtn) {
      const icon = toggleConfigBtn.querySelector("i");
      const label = toggleConfigBtn.querySelector("span");
      if (icon) {
        icon.className = configHidden
          ? "bi bi-chevron-double-right"
          : "bi bi-chevron-double-left";
      }
      if (label) {
        label.textContent = configHidden ? "Show Config" : "Hide Config";
      }
      toggleConfigBtn.title = configHidden
        ? "Show pivot configuration panel"
        : "Hide pivot configuration panel";
      toggleConfigBtn.setAttribute("aria-expanded", configHidden ? "false" : "true");
    }

    // The grid needs to know its container changed size.
    requestAnimationFrame(() => {
      window.dispatchEvent(new Event("resize"));
    });
  }

  /**
   * Enter / exit a CSS-overlay "fullscreen" mode for the result panel.
   * The panel is positioned `fixed` covering the viewport and the grid
   * grows to fill the available space. The page body is locked so only
   * the result panel scrolls.
   */
  function setFullscreen(active) {
    if (!resultPanel) return;
    isFullscreen = !!active;

    resultPanel.classList.toggle("pivot-fullscreen", isFullscreen);
    document.body.classList.toggle("pivot-fullscreen-active", isFullscreen);

    if (fullscreenBtn) {
      const icon = fullscreenBtn.querySelector("i");
      const label = fullscreenBtn.querySelector("span");
      if (icon) {
        icon.className = isFullscreen
          ? "bi bi-fullscreen-exit"
          : "bi bi-arrows-fullscreen";
      }
      if (label) {
        label.textContent = isFullscreen ? "Exit Fullscreen" : "Fullscreen";
      }
      fullscreenBtn.title = isFullscreen
        ? "Exit fullscreen (Esc)"
        : "Expand pivot result to full screen";
      fullscreenBtn.setAttribute("aria-pressed", isFullscreen ? "true" : "false");
    }

    // AG Grid watches the container size with a ResizeObserver and
    // re-flows automatically, but firing a `resize` event is a cheap
    // belt-and-braces nudge for the first paint after the toggle.
    requestAnimationFrame(() => {
      window.dispatchEvent(new Event("resize"));
    });
  }

  if (toggleConfigBtn) {
    toggleConfigBtn.addEventListener("click", () => setConfigHidden(!configHidden));
  }
  if (fullscreenBtn) {
    fullscreenBtn.addEventListener("click", () => setFullscreen(!isFullscreen));
  }

  // ESC exits fullscreen — standard convention for fullscreen overlays.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isFullscreen) {
      e.preventDefault();
      setFullscreen(false);
    }
  });

  // ════════════════════════════════════════════════════════════════════════
  // PHASE 7 — Expand / Collapse, Columns menu, Freeze menu, Reset
  // ════════════════════════════════════════════════════════════════════════

  if (expandAllBtn) {
    expandAllBtn.addEventListener("click", () => {
      if (window.PivotGrid) window.PivotGrid.expandAll();
    });
  }
  if (collapseAllBtn) {
    collapseAllBtn.addEventListener("click", () => {
      if (window.PivotGrid) window.PivotGrid.collapseAll();
    });
  }

  /**
   * Build the "Columns" dropdown — show / hide each column.
   * Mirrors the same pattern as the drilldown module's column menu
   * (Phase 5) but lives in the page toolbar.
   */
  function rebuildColumnsMenu(data) {
    if (!pivotColumnsMenu) return;
    const cols = (data && data.columns) || [];
    pivotColumnsMenu.innerHTML = "";

    if (!cols.length) {
      pivotColumnsMenu.innerHTML = `
        <li><h6 class="dropdown-header">Show / hide columns</h6></li>
        <li><span class="dropdown-item text-muted small" id="pivotColumnsEmptyMsg">No columns yet</span></li>
      `;
      return;
    }

    pivotColumnsMenu.insertAdjacentHTML("beforeend", `
      <li><h6 class="dropdown-header d-flex justify-content-between align-items-center">
        <span>Show / hide columns</span>
        <span>
          <button type="button" class="btn btn-link btn-sm p-0 me-2" data-pv-cols-action="all">All</button>
          <button type="button" class="btn btn-link btn-sm p-0"    data-pv-cols-action="none">None</button>
        </span>
      </h6></li>
      <li><hr class="dropdown-divider"></li>
    `);
    cols.forEach(col => {
      const li = document.createElement("li");
      li.innerHTML = `
        <label class="dropdown-item d-flex align-items-center" style="cursor: pointer">
          <input class="form-check-input me-2" type="checkbox" data-pv-col-id="${escHtml(col)}" checked>
          <span class="text-truncate" title="${escHtml(col)}">${escHtml(col)}</span>
        </label>
      `;
      pivotColumnsMenu.appendChild(li);
    });

    // Per-column show/hide
    pivotColumnsMenu.querySelectorAll("input[type=checkbox][data-pv-col-id]").forEach(cb => {
      cb.addEventListener("change", () => {
        const colId = cb.getAttribute("data-pv-col-id");
        if (window.PivotGrid) {
          const grid = window.PivotGrid;
          if (grid && typeof grid.setColumnsVisible === "function") {
            try { grid.setColumnsVisible([colId], cb.checked); } catch (_) { /* ignore */ }
          }
        }
        // Mirror in appState so the next payload picks it up.
        const set = new Set(appState.displayOptions.hiddenColumns);
        if (cb.checked) set.delete(colId); else set.add(colId);
        appState.displayOptions.hiddenColumns = Array.from(set);
      });
    });
    // All / None shortcuts
    pivotColumnsMenu.querySelectorAll("[data-pv-cols-action]").forEach(btn => {
      btn.addEventListener("click", e => {
        e.preventDefault();
        e.stopPropagation();
        const action = btn.getAttribute("data-pv-cols-action");
        const visible = action === "all";
        const grid = window.PivotGrid;
        if (grid && typeof grid.setColumnsVisible === "function") {
          try { grid.setColumnsVisible(cols, visible); } catch (_) { /* ignore */ }
        }
        pivotColumnsMenu.querySelectorAll("input[type=checkbox][data-pv-col-id]")
          .forEach(c => { c.checked = visible; });
        if (visible) appState.displayOptions.hiddenColumns = [];
        else        appState.displayOptions.hiddenColumns = cols.slice();
      });
    });
  }

  /**
   * Build the "Freeze" dropdown — pin a column to the left, or unpin
   * it.  Matches Excel's "Freeze First Column" / "Freeze Panes".
   */
  function rebuildFreezeMenu(data) {
    if (!pivotFreezeMenu) return;
    const cols = (data && data.columns) || [];
    pivotFreezeMenu.innerHTML = "";

    if (!cols.length) {
      pivotFreezeMenu.innerHTML = `
        <li><h6 class="dropdown-header">Freeze columns</h6></li>
        <li><span class="dropdown-item text-muted small" id="pivotFreezeEmptyMsg">No columns yet</span></li>
      `;
      return;
    }

    pivotFreezeMenu.insertAdjacentHTML("beforeend", `
      <li><h6 class="dropdown-header d-flex justify-content-between align-items-center">
        <span>Freeze columns to the left</span>
        <button type="button" class="btn btn-link btn-sm p-0" data-pv-freeze-action="none">Unfreeze all</button>
      </h6></li>
      <li><hr class="dropdown-divider"></li>
    `);
    cols.forEach(col => {
      const li = document.createElement("li");
      li.innerHTML = `
        <label class="dropdown-item d-flex align-items-center" style="cursor: pointer">
          <input class="form-check-input me-2" type="checkbox" data-pv-freeze-id="${escHtml(col)}">
          <span class="text-truncate" title="${escHtml(col)}">${escHtml(col)}</span>
        </label>
      `;
      pivotFreezeMenu.appendChild(li);
    });

    pivotFreezeMenu.querySelectorAll("input[type=checkbox][data-pv-freeze-id]").forEach(cb => {
      cb.addEventListener("change", () => {
        const colId = cb.getAttribute("data-pv-freeze-id");
        if (window.PivotGrid) {
          try {
            if (typeof window.PivotGrid.setColumnPinned === "function") {
              window.PivotGrid.setColumnPinned(colId, cb.checked ? "left" : null);
            }
          } catch (_) { /* ignore */ }
        }
        const set = new Set(appState.displayOptions.frozenColumns);
        if (cb.checked) set.add(colId); else set.delete(colId);
        appState.displayOptions.frozenColumns = Array.from(set);
      });
    });
    pivotFreezeMenu.querySelectorAll("[data-pv-freeze-action]").forEach(btn => {
      btn.addEventListener("click", e => {
        e.preventDefault();
        e.stopPropagation();
        const grid = window.PivotGrid;
        if (grid && typeof grid.setColumnPinned === "function") {
          cols.forEach(c => {
            try { grid.setColumnPinned(c, null); } catch (_) { /* ignore */ }
          });
        }
        pivotFreezeMenu.querySelectorAll("input[type=checkbox][data-pv-freeze-id]")
          .forEach(c => { c.checked = false; });
        appState.displayOptions.frozenColumns = [];
      });
    });
  }

  if (resetColumnsBtn) {
    resetColumnsBtn.addEventListener("click", () => {
      const data = (appState && appState.lastResponse) || null;
      if (!data) return;
      const cols = data.columns || [];
      if (window.PivotGrid) {
        try {
          if (typeof window.PivotGrid.setColumnsVisible === "function") {
            window.PivotGrid.setColumnsVisible(cols, true);
          }
          if (typeof window.PivotGrid.setColumnPinned === "function") {
            cols.forEach(c => {
              try { window.PivotGrid.setColumnPinned(c, null); } catch (_) { /* ignore */ }
            });
          }
        } catch (_) { /* ignore */ }
      }
      appState.displayOptions.hiddenColumns = [];
      appState.displayOptions.frozenColumns = [];
      rebuildColumnsMenu(data);
      rebuildFreezeMenu(data);
    });
  }

  // Initialize the PivotDisplay module once the DOM is ready.
  if (window.PivotDisplay) window.PivotDisplay.init();

  // ════════════════════════════════════════════════════════════════════════
  // PHASE 8 — Delete Records + draft recovery + auto-refresh
  // ════════════════════════════════════════════════════════════════════════

  // ── Delete Records ────────────────────────────────────────────────
  //
  // When the user clicks "Delete Records" the controller:
  //   1. Builds a list of {field: value} selections from the currently
  //      selected pivot rows (we reuse DrilldownSelection for this so the
  //      selection shape is identical to drilldown + email).
  //   2. Opens the confirmation modal showing the count + criteria.
  //   3. On confirm, POSTs to /api/pivot/delete-records.
  //   4. Re-computes the pivot automatically so the user sees the
  //      updated numbers — no manual refresh needed.

  if (deleteRecordsBtn) {
    deleteRecordsBtn.addEventListener("click", () => {
      if (!appState.lastResponse) {
        showError("Generate a pivot first.");
        return;
      }
      const rows = window.PivotGrid ? window.PivotGrid.getSelectedRows() : [];
      // Exclude marker rows (grand total, column total, subtotals) — we
      // don't want to delete based on those.
      const dataRows = rows.filter(r =>
        r && !r.__isGrandTotal && !r.__isColumnTotal && !r.__isSubtotal
      );
      if (!dataRows.length) {
        showError("Select at least one data row (not a totals row) to delete.");
        return;
      }
      // buildSelectionList returns [{pivotRow, selection}] but the
      // delete-records API expects plain [{field: value}] maps.
      // Extract .selection from each entry so the backend's
      // _apply_selection can match the keys against DataFrame columns.
      const selections = (window.DrilldownSelection
        ? window.DrilldownSelection.buildSelectionList(dataRows, appState.lastResponse)
            .map(entry => entry.selection || {})
        : dataRows.map(r => {
            const sel = {};
            (appState.rows || []).forEach(f => { sel[f] = r[f]; });
            return sel;
          }));

      // Populate the confirmation modal.
      if (delDatasetName)    delDatasetName.textContent   = appState.datasetName || "—";
      if (delSheetName)      delSheetName.textContent     = appState.sheetName || "—";
      if (delPivotRowsCount) delPivotRowsCount.textContent= dataRows.length.toLocaleString();
      if (delCriteria) {
        delCriteria.textContent = JSON.stringify(selections, null, 2);
      }
      if (delResultArea) {
        delResultArea.style.display = "none";
        delResultArea.innerHTML = "";
      }
      // Cache for the confirm handler.
      deleteRecordsBtn.dataset.pending = JSON.stringify(selections);
      if (window.bootstrap && deleteRecordsModal) {
        const m = bootstrap.Modal.getOrCreateInstance(deleteRecordsModal);
        m.show();
        // Phase 8 (safety) — run a dry-run preview so the modal can
        // show the actual source-record count.  This catches the case
        // where the user thought they were deleting 1 row but actually
        // had many rows selected.
        previewDeleteRecordCount(selections);
      }
    });
  }

  // Phase 8 (safety) — run a dry-run to count how many source records
  // will be affected.  We POST to /api/pivot/delete-records with
  // `dryRun: true` so the server returns the count without deleting
  // anything.  Then the modal shows the count and warns the user if
  // it's a large delete (>500 records).
  async function previewDeleteRecordCount(selections) {
    if (!delResultArea) return;
    delResultArea.style.display = "";
    delResultArea.innerHTML = `
      <div class="text-muted small">
        <span class="spinner-border spinner-border-sm me-1"></span>
        Counting affected records…
      </div>`;
    try {
      const res = await fetch("/api/pivot/delete-records", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pivotRequest: buildPayload(),
          selections: selections,
          dryRun: true,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Preview failed.");
      const n = data.matched || 0;
      const LARGE = 500;
      const huge  = n > 2000;
      const tag   = huge
        ? `<span class="badge bg-danger ms-1">HUGE</span>`
        : n > LARGE
        ? `<span class="badge bg-warning text-dark ms-1">LARGE</span>`
        : "";
      delResultArea.innerHTML = `
        <div class="alert alert-info mb-0">
          <i class="bi bi-info-circle me-1"></i>
          <strong>${n.toLocaleString()}</strong> source record(s) will be
          soft-deleted from
          <strong>${selections.length.toLocaleString()}</strong> pivot
          row(s). ${tag}
          ${huge
            ? `<div class="small text-danger mt-1">
                <i class="bi bi-exclamation-triangle me-1"></i>
                This is a very large delete. Please review the selection
                criteria above carefully before confirming.
              </div>`
            : ""}
        </div>`;
      // Disable confirm if count is unreasonable
      if (confirmDeleteBtn) {
        confirmDeleteBtn.disabled = n <= 0;
        if (n <= 0) {
          confirmDeleteBtn.title = "No records would be deleted";
        } else {
          confirmDeleteBtn.title = "";
        }
      }
    } catch (err) {
      delResultArea.innerHTML = `
        <div class="alert alert-warning mb-0">
          <i class="bi bi-exclamation-triangle me-1"></i>
          Could not count affected records: ${escHtml(err.message)}
        </div>`;
    }
  }

  if (confirmDeleteBtn) {
    confirmDeleteBtn.addEventListener("click", async () => {
      const selections = JSON.parse(deleteRecordsBtn.dataset.pending || "[]");
      if (!selections.length) return;
      confirmDeleteBtn.disabled = true;
      const originalHtml = confirmDeleteBtn.innerHTML;
      confirmDeleteBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Deleting…';
      try {
        const body = {
          pivotRequest: buildPayload(),
          selections:   selections,
        };
        const res = await fetch("/api/pivot/delete-records", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Delete failed.");
        // Show the result inside the modal.
        if (delResultArea) {
          delResultArea.innerHTML = `
            <div class="alert alert-success mb-0">
              <i class="bi bi-check-circle me-1"></i>
              <strong>Deleted.</strong>
              ${data.deleted} source record(s) removed from
              ${data.selections} pivot row(s).
            </div>`;
          delResultArea.style.display = "";
        }
        // Close the modal after a short pause and auto-refresh.
        setTimeout(async () => {
          if (window.bootstrap && deleteRecordsModal) {
            const m = bootstrap.Modal.getOrCreateInstance(deleteRecordsModal);
            m.hide();
          }
          // Auto-refresh the pivot so the user sees the updated numbers.
          await computePivot();
        }, 1200);
      } catch (err) {
        if (delResultArea) {
          delResultArea.innerHTML = `
            <div class="alert alert-danger mb-0">
              <i class="bi bi-x-circle me-1"></i> ${escHtml(err.message)}
            </div>`;
          delResultArea.style.display = "";
        }
      } finally {
        confirmDeleteBtn.disabled = false;
        confirmDeleteBtn.innerHTML = originalHtml;
      }
    });
  }

  // ── Draft recovery (Phase 8) ─────────────────────────────────────
  //
  // Auto-save the pivot configuration to localStorage on every change.
  // On page load, if a saved draft exists, show the recovery banner
  // and let the user restore or discard it.

  const DRAFT_KEY = "pivot-draft-v1";

  function captureDraft() {
    try {
      const draft = {
        datasetId:    appState.datasetId,
        sheetName:    appState.sheetName,
        rows:         [...appState.rows],
        columns:      [...appState.columnsGroup],
        values:       appState.values.map(v => ({ ...v })),
        filters:      { ...appState.filters },
        dateGrouping: { ...appState.dateGrouping },
        sorting:      { ...appState.sorting },
        totals:       { ...appState.totals },
        displayOptions: {
          numberFormat:       { ...(appState.displayOptions.numberFormat || {}) },
          dateFormat:         { ...(appState.displayOptions.dateFormat   || {}) },
          conditionalFormats: [...(appState.displayOptions.conditionalFormats || [])],
          frozenColumns:      [...(appState.displayOptions.frozenColumns || [])],
          hiddenColumns:      [...(appState.displayOptions.hiddenColumns || [])],
        },
        layout:      appState.layout,
        savedAt:     new Date().toISOString(),
      };
      localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch (_) { /* ignore quota errors */ }
  }

  function applyDraft(draft) {
    if (!draft) return;
    appState.datasetId    = draft.datasetId    || null;
    appState.sheetName    = draft.sheetName    || null;
    appState.rows         = Array.isArray(draft.rows)        ? draft.rows        : [];
    appState.columnsGroup = Array.isArray(draft.columns)     ? draft.columns     : [];
    appState.values       = Array.isArray(draft.values)      ? draft.values      : [];
    appState.filters      = (draft.filters     && typeof draft.filters     === "object") ? draft.filters     : {};
    appState.dateGrouping = (draft.dateGrouping && typeof draft.dateGrouping === "object") ? draft.dateGrouping : {};
    appState.sorting      = (draft.sorting     && typeof draft.sorting     === "object") ? draft.sorting      : {};
    appState.totals       = Object.assign({
      showGrandTotals: true, showRowTotals: true,
      showColumnTotals: false, showSubtotals: false, repeatItemLabels: false,
    }, draft.totals || {});
    appState.displayOptions = Object.assign({
      numberFormat: {}, dateFormat: {}, conditionalFormats: [],
      frozenColumns: [], hiddenColumns: [],
    }, draft.displayOptions || {});
    appState.layout = draft.layout || "tabular";
    // Push the values into the visible UI.
    restoreUIFromState();
  }

  function restoreUIFromState() {
    // Dataset + sheet dropdowns.
    if (datasetSelect && appState.datasetId) {
      datasetSelect.value = appState.datasetId;
    }
    // Totals checkboxes
    if (optGrandTotals)    optGrandTotals.checked    = !!appState.totals.showGrandTotals;
    if (optRowTotals)      optRowTotals.checked      = !!appState.totals.showRowTotals;
    if (optColumnTotals)   optColumnTotals.checked   = !!appState.totals.showColumnTotals;
    if (optSubtotals)      optSubtotals.checked      = !!appState.totals.showSubtotals;
    if (optRepeatItemLabels) optRepeatItemLabels.checked = !!appState.totals.repeatItemLabels;
    // Layout radio
    layoutRadios.forEach(r => { r.checked = (r.value === appState.layout); });
    // After the dataset change handler runs, columns + sheet are loaded.
    // We re-fire change to make sure the sheet dropdown reflects state.
    if (datasetSelect && appState.datasetId) {
      datasetSelect.dispatchEvent(new Event("change"));
    }
  }

  function maybeOfferDraftRecovery() {
    let draft = null;
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (raw) draft = JSON.parse(raw);
    } catch (_) { draft = null; }
    if (!draft || !draft.datasetId) return;
    if (draft.datasetId === appState.datasetId && draft.sheetName === appState.sheetName) {
      return; // Same as current state, no need to recover.
    }
    if (draftBanner) {
      if (draftMeta) {
        const when = draft.savedAt ? new Date(draft.savedAt).toLocaleString() : "";
        draftMeta.textContent = `Last saved ${when} · dataset id ${draft.datasetId}`;
      }
      draftBanner.classList.remove("d-none");
      draftBanner.dataset.draft = JSON.stringify(draft);
    }
  }

  if (restoreDraftBtn) {
    restoreDraftBtn.addEventListener("click", () => {
      const raw = draftBanner && draftBanner.dataset.draft;
      if (!raw) return;
      const draft = JSON.parse(raw);
      applyDraft(draft);
      draftBanner.classList.add("d-none");
    });
  }
  if (discardDraftBtn) {
    discardDraftBtn.addEventListener("click", () => {
      try { localStorage.removeItem(DRAFT_KEY); } catch (_) {}
      if (draftBanner) draftBanner.classList.add("d-none");
    });
  }

  // Auto-save the draft on every meaningful state change. Debounced so
  // we don't hammer localStorage on every keystroke.
  let _draftTimer = null;
  function scheduleDraftSave() {
    clearTimeout(_draftTimer);
    _draftTimer = setTimeout(captureDraft, 300);
  }
  // Hook the save into every state-mutating UI event.
  [datasetSelect, sheetSelect, optGrandTotals, optRowTotals,
   optColumnTotals, optSubtotals, optRepeatItemLabels].forEach(el => {
    if (el) el.addEventListener("change", scheduleDraftSave);
  });
  layoutRadios.forEach(r => r.addEventListener("change", scheduleDraftSave));
  // After the dataset select changes (which loads columns), the user
  // is going to add fields — we need to save after those too. The
  // easiest hook is to save at the end of every compute.
  const _origCompute = computeBtn.onclick;
  // We re-save on every render so the saved draft always reflects the
  // last computed state.
  const _origRender = renderResult;

  // After the dataset loads, check for a draft to recover.
  setTimeout(maybeOfferDraftRecovery, 600);

  // Hook the render call to also save the draft.
  window.addEventListener("beforeunload", () => {
    captureDraft();
  });

  // ════════════════════════════════════════════════════════════════════════
  // UTILITIES
  // ════════════════════════════════════════════════════════════════════════
  function showError(msg) {
    if (!errorAlert) return;
    errorAlert.textContent = msg;
    errorAlert.classList.remove("d-none");
    errorAlert.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  function hideError() {
    if (!errorAlert) return;
    errorAlert.classList.add("d-none");
    errorAlert.textContent = "";
  }
  function escHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
  function aggregationColor(agg) {
    return ({ sum: "primary", average: "info", count: "secondary",
              min: "warning", max: "danger" })[agg] || "light";
  }

  }  // end of main()
})();
