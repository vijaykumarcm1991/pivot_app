/**
 * pivot.js — Pivot Builder UI logic (Phase 3).
 *
 * API endpoints:
 *   POST /api/pivot/validate   → validate a pivot config (no compute)
 *   POST /api/pivot            → compute the pivot
 *   POST /api/pivot/drilldown  → get raw rows matching a pivot selection
 *
 * Flow:
 *   1. Load datasets → populate dataset dropdown
 *   2. Select dataset → load sheet dropdown, auto-pick first sheet
 *   3. Sheet change  → reload columns for that sheet
 *   4. User adds rows/columns/values/filters/sorts
 *   5. Click "Validate" → POST /api/pivot/validate → show errors/warnings
 *   6. Click "Compute"  → POST /api/pivot → render AG Grid
 */
(function () {
  "use strict";

  // ── State ─────────────────────────────────────────────────────────────────
  const appState = {
    datasetId:    null,
    sheetName:    null,
    columns:      [],          // [{name, type, nullable}] for the current sheet
    rows:         [],          // selected row grouping fields
    columnsGroup: [],          // selected column grouping fields
    values:       [],          // [{field, aggregation, label}]
    filters:      {},          // {field: ["v1","v2"] | "v" | null}
    dateGrouping: {},          // {field: "month"}
    sorting:      {},          // {field: "asc" | "desc"}
    totals: {
      showGrandTotals:  true,
      showRowTotals:    true,
      showColumnTotals: false,
      showSubtotals:    false,
    },
    layout:       "tabular",
    gridApi:      null,
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
    count:   "Count",
    sum:     "Sum",
    average: "Average",
    min:     "Min",
    max:     "Max",
  };
  const TYPE_ICON = {
    datetime: "📅", integer: "🔢", float: "📊", decimal: "📊",
    boolean:  "✅", string:  "📝", text: "📝", date: "📅",
  };

  // ── DOM refs ──────────────────────────────────────────────────────────────
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
  const computeBtn        = document.getElementById("computeBtn");
  const validateBtn       = document.getElementById("validateBtn");
  const resultsTitle      = document.getElementById("resultsTitle");
  const loadingSpinner    = document.getElementById("loadingSpinner");
  const metaStats         = document.getElementById("metaStats");
  const errorAlert        = document.getElementById("errorAlert");
  const validationPanel   = document.getElementById("validationPanel");
  const validationBadge   = document.getElementById("validationBadge");
  const validationBody    = document.getElementById("validationBody");
  const pivotCard         = document.getElementById("pivotCard");
  const debugCard         = document.getElementById("debugCard");
  const requestJson       = document.getElementById("requestJson");
  const responseJson      = document.getElementById("responseJson");
  const drilldownBtn      = document.getElementById("drilldownBtn");
  const exportBtn         = document.getElementById("exportBtn");
  const saveBtn           = document.getElementById("saveBtn");
  const pivotGrid         = document.getElementById("pivotGrid");

  // Filter modal
  const filterModalEl     = document.getElementById("filterModal");
  const filterModal       = filterModalEl ? new bootstrap.Modal(filterModalEl) : null;
  const filterSearch      = document.getElementById("filterSearch");
  const filterValueList   = document.getElementById("filterValueList");
  const filterSelectAll   = document.getElementById("filterSelectAll");
  const filterSelectNone  = document.getElementById("filterSelectNone");
  const filterApplyBtn    = document.getElementById("filterApplyBtn");
  let filterModalField    = null;   // field being edited in the modal
  let filterModalSelected = new Set();

  // ── Init: load datasets ───────────────────────────────────────────────────
  loadDatasets();

  // ── API: fetch datasets ───────────────────────────────────────────────────
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

  // ── Dataset select → load sheets + first sheet columns ──────────────────
  datasetSelect.addEventListener("change", async () => {
    const id = datasetSelect.value;
    appState.datasetId = id || null;
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

      // Auto-pick first sheet and load its columns
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

  // ── Sheet select → reload columns for the new sheet ───────────────────────
  sheetSelect.addEventListener("change", async () => {
    const sheet = sheetSelect.value;
    appState.sheetName = sheet || null;
    if (!sheet || !appState.datasetId) return;
    clearColumnSelects();
    await loadColumnsForSheet(appState.datasetId, sheet);
  });

  // ── Load columns for a specific sheet ────────────────────────────────────
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

  // ── Populate dropdowns with available columns ─────────────────────────────
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

    // Show / hide date-grouping card
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

  // ── Update aggregations dropdown based on the selected value field type ──
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

  // ── Manage selections ─────────────────────────────────────────────────────
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
    saveBtn.disabled     = !canSubmit;
    exportBtn.disabled   = !canSubmit;

    // Show sorting card only if at least one row field is selected
    sortingCard.style.display = appState.rows.length ? "" : "none";
    renderSortList();
    renderDateGroupingList();
    renderValueList();
    renderFilterList();
  }

  // ── Add / remove row and column fields ───────────────────────────────────
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

  // ── Date grouping (using the proper UI card — no prompt()) ───────────────
  addDateGroupBtn.addEventListener("click", () => {
    const field    = dateFieldSelect.value;
    const grouping = dateGroupSelect.value;
    if (!field) return;
    appState.dateGrouping[field] = grouping;
    // Auto-add to rows if neither rows nor columns contain it
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

  // ── Per-row sorting ──────────────────────────────────────────────────────
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

  // ── Values (with type-aware aggregation) ─────────────────────────────────
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

  // ── Filters (multi-value via Bootstrap modal — no more prompt()) ─────────
  addFilterBtn.addEventListener("click", () => {
    const field = filterFieldSelect.value;
    if (!field) return;
    openFilterModal(field);
  });

  async function openFilterModal(field) {
    filterModalField    = field;
    filterModalSelected = new Set();

    // Existing selection
    const existing = appState.filters[field];
    if (Array.isArray(existing))     existing.forEach(v => filterModalSelected.add(String(v)));
    else if (existing !== undefined) filterModalSelected.add(String(existing));

    // Load distinct values from the current sheet
    filterValueList.innerHTML = '<div class="text-muted small p-2">Loading values…</div>';
    if (filterModal) filterModal.show();

    try {
      // We don't have a dedicated "distinct values" endpoint, so re-use the
      // preview endpoint and derive unique values client-side. For very large
      // sheets this loads only the first 100 rows — for filter selection on
      // small-to-medium datasets that's an acceptable trade-off.
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
      if (filterModal) filterModal.hide();
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

  // ── Layout / Totals options ──────────────────────────────────────────────
  layoutRadios.forEach(r => r.addEventListener("change", e => {
    appState.layout = e.target.value;
  }));
  optGrandTotals .addEventListener("change", () => appState.totals.showGrandTotals  = optGrandTotals.checked);
  optRowTotals   .addEventListener("change", () => appState.totals.showRowTotals    = optRowTotals.checked);
  optColumnTotals.addEventListener("change", () => appState.totals.showColumnTotals = optColumnTotals.checked);
  optSubtotals   .addEventListener("change", () => appState.totals.showSubtotals    = optSubtotals.checked);

  // ── Build payload (single source of truth) ───────────────────────────────
  function buildPayload() {
    return {
      datasetId:    appState.datasetId,
      sheetName:    appState.sheetName,
      rows:         [...appState.rows],
      columns:      [...appState.columnsGroup],
      values:       appState.values.map(v => ({ ...v })),
      filters:      { ...appState.filters },
      dateGrouping: { ...appState.dateGrouping },
      sorting:      { ...appState.sorting },
      totals:       { ...appState.totals },
      layout:       appState.layout,
    };
  }

  // ── Validate ─────────────────────────────────────────────────────────────
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

  // ── Compute ──────────────────────────────────────────────────────────────
  computeBtn.addEventListener("click", computePivot);
  async function computePivot() {
    if (!appState.datasetId || !appState.sheetName) return;
    hideError();
    validationPanel.style.display = "none";

    loadingSpinner.classList.remove("d-none");
    pivotCard.style.display = "none";
    debugCard.style.display = "none";
    resultsTitle.textContent = "Computing pivot…";

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

      renderPivotGrid(data);
      resultsTitle.textContent = "Pivot Table";
      metaStats.innerHTML = `
        <span class="text-primary">${data.metadata.filtered_rows.toLocaleString()} rows filtered</span>,
        <span class="text-success">${data.rows.length} pivot rows</span>,
        <span class="text-info">${data.columns.length} columns</span>
      `;
      pivotCard.style.display = "";
      debugCard.style.display = "";
    } catch (err) {
      showError("Pivot computation failed: " + err.message);
      clearResults();
    } finally {
      loadingSpinner.classList.add("d-none");
    }
  }

  // ── Render AG Grid from pivot response ────────────────────────────────────
  function renderPivotGrid(data) {
    const colDefs = data.columns.map(col => ({
      field:      col,
      headerName: col,
      sortable:   true,
      filter:     true,
      resizable:  true,
      minWidth:   100,
    }));

    const gridOptions = {
      columnDefs,
      rowData: data.rows,
      defaultColDef: { sortable: true, filter: true, resizable: true, minWidth: 100 },
      pagination: true,
      paginationPageSize: 20,
      enableCellTextSelection: true,
    };

    // Pick the AG Grid theme class to match the current app theme.
    if (pivotGrid) {
      const isDark = (window.ThemeManager && window.ThemeManager.getCurrentTheme() === "dark");
      pivotGrid.classList.toggle("ag-theme-alpine-dark", isDark);
      pivotGrid.classList.toggle("ag-theme-alpine",      !isDark);
    }

    if (appState.gridApi) {
      appState.gridApi.setGridOption("columnDefs", colDefs);
      appState.gridApi.setGridOption("rowData", data.rows);
      // Re-apply the theme class — setGridOption won't change the wrapper
      // class, but AG Grid reads it on init only, so we destroy + recreate
      // when the theme flips. Theme changes are rare, so this is fine.
      applyGridTheme(pivotGrid);
    } else {
      appState.gridApi = agGrid.createGrid(pivotGrid, gridOptions);
    }
  }

  // ── AG Grid: swap theme class & re-create the grid when the OS theme ────
  // ── changes (AG Grid's Alpine theme is a CSS class set at init time).   ──
  function applyGridTheme(el) {
    if (!el || !appState.gridApi) return;
    const isDark = (window.ThemeManager && window.ThemeManager.getCurrentTheme() === "dark");
    el.classList.toggle("ag-theme-alpine-dark", isDark);
    el.classList.toggle("ag-theme-alpine",      !isDark);
  }

  document.addEventListener("theme:changed", () => {
    if (pivotGrid) applyGridTheme(pivotGrid);
  });

  // ── Clear results / errors ───────────────────────────────────────────────
  function clearResults() {
    resultsTitle.textContent = "Pivot results will appear here";
    metaStats.textContent = "";
    pivotCard.style.display = "none";
    if (appState.gridApi) appState.gridApi.setGridOption("rowData", []);
  }

  // ── Stubs (Phase 4/5) ────────────────────────────────────────────────────
  exportBtn.addEventListener("click", () => showError("Export to Excel is not yet implemented (planned for Phase 4)."));
  saveBtn  .addEventListener("click", () => showError("Save pivot configuration is not yet implemented (planned for a later phase)."));

  // ── Utilities ────────────────────────────────────────────────────────────
  function showError(msg) {
    errorAlert.textContent = msg;
    errorAlert.classList.remove("d-none");
  }
  function hideError() {
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
})();
