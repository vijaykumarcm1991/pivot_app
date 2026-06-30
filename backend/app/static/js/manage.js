/**
 * manage.js — Dataset Management page logic.
 *
 * Flow:
 *  1. User picks a dataset  → fetch /api/dataset/{id}  → populate sheet selector + meta cards
 *  2. User picks a sheet    → fetch columns + preview  → render column table + AG Grid
 *  3. URL param ?dataset_id → auto-select on load
 */

(function () {
  "use strict";

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const datasetSelect     = document.getElementById("datasetSelect");
  const sheetCard         = document.getElementById("sheetCard");
  const sheetSelect       = document.getElementById("sheetSelect");
  const metaCards         = document.getElementById("metaCards");
  const metaRows          = document.getElementById("metaRows");
  const metaCols          = document.getElementById("metaCols");
  const metaSheets        = document.getElementById("metaSheets");
  const metaDateCols      = document.getElementById("metaDateCols");
  const metaNumericCols   = document.getElementById("metaNumericCols");
  const metaTextCols      = document.getElementById("metaTextCols");
  const errorAlert        = document.getElementById("errorAlert");
  const colCard           = document.getElementById("colCard");
  const colCount          = document.getElementById("colCount");
  const colTableBody      = document.getElementById("colTableBody");
  const previewCard       = document.getElementById("previewCard");
  const previewLabel      = document.getElementById("previewLabel");
  const gridSpinner       = document.getElementById("gridSpinner");
  const previewGrid       = document.getElementById("previewGrid");
  const deleteDatasetBtn  = document.getElementById("deleteDatasetBtn");
  const deleteAlert       = document.getElementById("deleteAlert");
  const deleteMessage     = document.getElementById("deleteMessage");
  const confirmDeleteBtn  = document.getElementById("confirmDeleteBtn");
  const cancelDeleteBtn   = document.getElementById("cancelDeleteBtn");

  let gridApi = null;   // AG Grid instance
  let currentDatasetName = "";

  // ── Type → Bootstrap badge colour (Phase 2 calls this "Decimal" in the UI) ─
  const TYPE_COLOURS = {
    integer:  "primary",
    float:    "info",
    decimal:  "info",
    boolean:  "warning",
    datetime: "success",
    date:     "success",
    string:   "secondary",
  };

  // ── Type display label (user-facing) ─────────────────────────────────────
  const TYPE_LABELS = {
    integer:  "Integer",
    float:    "Decimal",
    decimal:  "Decimal",
    boolean:  "Boolean",
    datetime: "Date",
    date:     "Date",
    string:   "Text",
  };

  // Helper: count column types across all sheets of a dataset
  function countColumnTypes(sheets) {
    let dateCount = 0, numericCount = 0, textCount = 0;
    sheets.forEach(sh => {
      (sh.columns || []).forEach(c => {
        if (c.data_type === "datetime" || c.data_type === "date") dateCount++;
        else if (c.data_type === "integer" || c.data_type === "float" || c.data_type === "decimal") numericCount++;
        else if (c.data_type === "string" || c.data_type === "text") textCount++;
      });
    });
    return { dateCount, numericCount, textCount };
  }

  // ── Dataset select ────────────────────────────────────────────────────────
  datasetSelect.addEventListener("change", () => {
    const id = datasetSelect.value;
    resetSheetPanel();
    resetPreviewPanel();
    deleteDatasetBtn.disabled = !id;
    if (!id) return;
    loadDataset(id);
  });

  // ── Sheet select ──────────────────────────────────────────────────────────
  sheetSelect.addEventListener("change", () => {
    const datasetId = datasetSelect.value;
    const sheetName = sheetSelect.value;
    resetPreviewPanel();
    if (!sheetName) return;
    loadSheetDetail(datasetId, sheetName);
  });

  // ── Load dataset metadata ─────────────────────────────────────────────────
  async function loadDataset(datasetId) {
    hideError();
    cancelDelete(); // hide any pending delete confirmation
    try {
      const res  = await fetch(`/api/dataset/${datasetId}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      // Store dataset name for delete confirmation
      currentDatasetName = data.filename;

      // Populate sheet selector
      sheetSelect.innerHTML = '<option value="">— select a sheet —</option>';
      data.sheets.forEach(s => {
        const opt = document.createElement("option");
        opt.value       = s.sheet_name;
        opt.textContent = `${s.sheet_name}  (${s.row_count.toLocaleString()} rows)`;
        sheetSelect.appendChild(opt);
      });

      // Show sheet card + meta
      sheetCard.style.display  = "";
      metaCards.style.display  = "";
      metaRows.textContent     = data.total_rows.toLocaleString();
      metaCols.textContent     = data.total_columns.toLocaleString();
      metaSheets.textContent   = data.sheets.length;

      // Compute and show column-type stats across all sheets
      const stats = countColumnTypes(data.sheets);
      metaDateCols.textContent    = stats.dateCount;
      metaNumericCols.textContent = stats.numericCount;
      metaTextCols.textContent    = stats.textCount;

      // Auto-select first sheet if only one
      if (data.sheets.length === 1) {
        sheetSelect.value = data.sheets[0].sheet_name;
        sheetSelect.dispatchEvent(new Event("change"));
      }

    } catch (err) {
      showError("Failed to load dataset: " + err.message);
    }
  }

  // ── Load sheet columns + preview ──────────────────────────────────────────
  async function loadSheetDetail(datasetId, sheetName) {
    hideError();
    gridSpinner.classList.remove("d-none");
    previewCard.style.display = "";

    try {
      const encoded = encodeURIComponent(sheetName);
      const res = await fetch(`/api/dataset/${datasetId}/sheet/${encoded}/preview`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      // Column type table
      renderColumnTable(data.columns);

      // AG Grid preview
      renderGrid(data.columns, data.rows);

      previewLabel.textContent = ` — first ${data.rows.length} rows`;

    } catch (err) {
      showError("Failed to load sheet: " + err.message);
      previewCard.style.display = "none";
    } finally {
      gridSpinner.classList.add("d-none");
    }
  }

  // ── Column type table ─────────────────────────────────────────────────────
  function renderColumnTable(columns) {
    colTableBody.innerHTML = "";
    columns.forEach(col => {
      const colour = TYPE_COLOURS[col.data_type] || "secondary";
      const label  = TYPE_LABELS[col.data_type]  || col.data_type;
      const row = document.createElement("tr");
      row.innerHTML = `
        <td class="fw-medium">${escHtml(col.column_name)}</td>
        <td><span class="badge bg-${colour}">${escHtml(label)}</span></td>
        <td>${col.is_nullable
              ? '<span class="text-warning"><i class="bi bi-check-circle-fill"></i></span>'
              : '<span class="text-muted"><i class="bi bi-dash-circle"></i></span>'}</td>`;
      colTableBody.appendChild(row);
    });
    colCount.textContent = columns.length;
    colCard.style.display = "";
  }

  // ── AG Grid ───────────────────────────────────────────────────────────────
  function renderGrid(columns, rows) {
    const colDefs = columns.map(col => ({
      field:           col.column_name,
      headerName:      col.column_name,
      sortable:        true,
      filter:          true,
      resizable:       true,
      minWidth:        100,
    }));

    if (gridApi) {
      // Update existing grid
      gridApi.setGridOption("columnDefs", colDefs);
      gridApi.setGridOption("rowData", rows);
      applyGridTheme(previewGrid);
    } else {
      // Apply theme class BEFORE creating the grid — AG Grid reads it
      // from the wrapper at init time.
      applyGridTheme(previewGrid);
      const gridOptions = {
        columnDefs:          colDefs,
        rowData:             rows,
        defaultColDef: {
          sortable:   true,
          filter:     true,
          resizable:  true,
          minWidth:   100,
        },
        pagination:          true,
        paginationPageSize:  20,
        suppressMovableColumns: false,
      };
      gridApi = agGrid.createGrid(previewGrid, gridOptions);
    }
  }

  // ── AG Grid theme sync — match the wrapper class to the active theme ─────
  function applyGridTheme(el) {
    if (!el) return;
    const isDark = (window.ThemeManager && window.ThemeManager.getCurrentTheme() === "dark");
    el.classList.toggle("ag-theme-alpine-dark", isDark);
    el.classList.toggle("ag-theme-alpine",      !isDark);
  }

  // ── React to theme:changed events so the grid follows the app theme ──────
  document.addEventListener("theme:changed", () => {
    // AG Grid's Alpine themes are pure CSS class selectors — toggling the
    // class on the wrapper is enough to re-skin the grid without a flicker.
    applyGridTheme(previewGrid);
  });

  // ── Reset helpers ─────────────────────────────────────────────────────────
  function resetSheetPanel() {
    sheetCard.style.display = "none";
    metaCards.style.display = "none";
    sheetSelect.innerHTML   = '<option value="">— select a sheet —</option>';
    metaRows.textContent    = "—";
    metaCols.textContent    = "—";
    metaSheets.textContent  = "—";
    metaDateCols.textContent = "—";
    metaNumericCols.textContent = "—";
    metaTextCols.textContent = "—";
  }

  function resetPreviewPanel() {
    colCard.style.display     = "none";
    previewCard.style.display = "none";
    colTableBody.innerHTML    = "";
    previewLabel.textContent  = "";
    if (gridApi) {
      gridApi.setGridOption("rowData", []);
    }
  }

  // ── Error helpers ─────────────────────────────────────────────────────────
  function showError(msg) {
    errorAlert.textContent = msg;
    errorAlert.classList.remove("d-none");
  }
  function hideError() {
    errorAlert.classList.add("d-none");
    errorAlert.textContent = "";
  }

  // ── XSS-safe text ─────────────────────────────────────────────────────────
  function escHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Delete dataset functionality ──────────────────────────────────────────
  deleteDatasetBtn.addEventListener("click", () => {
    const datasetId = datasetSelect.value;
    if (!datasetId) return;
    
    deleteAlert.classList.remove("d-none");
    deleteMessage.textContent = `Delete dataset "${currentDatasetName}"? This will also remove the uploaded file and all metadata.`;
    
    confirmDeleteBtn.onclick = () => performDelete(datasetId);
    cancelDeleteBtn.onclick = cancelDelete;
  });
  
  async function performDelete(datasetId) {
    try {
      const res = await fetch(`/api/dataset/${datasetId}`, { method: 'DELETE' });
      const data = await res.json();
      if (res.ok) {
        alert('Dataset deleted successfully!');
        window.location.href = '/datasets'; // Redirect to datasets list
      } else {
        showError(`Delete failed: ${data.detail || 'Unknown error'}`);
        cancelDelete();
      }
    } catch (err) {
      showError('Network error occurred while deleting dataset.');
      cancelDelete();
    }
  }
  
  function cancelDelete() {
    deleteAlert.classList.add("d-none");
    deleteMessage.textContent = "";
  }

  // ── Auto-select from URL param (?dataset_id=N) ────────────────────────────
  const params    = new URLSearchParams(window.location.search);
  const presetId  = params.get("dataset_id");
  if (presetId && datasetSelect) {
    datasetSelect.value = presetId;
    if (datasetSelect.value === presetId) {
      datasetSelect.dispatchEvent(new Event("change"));
    }
  }

})();
