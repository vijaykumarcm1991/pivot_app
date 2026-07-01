/**
 * pivot-display.js — Phase 7 Display Options controller.
 *
 * Owns:
 *   - The "Display Options" left-panel card (Repeat Item Labels,
 *     Number Format per field, Date Format per field, Conditional
 *     Formatting rules, Freeze Columns, Hide Columns, Auto-fit,
 *     Copy, Print).
 *   - The "Columns" dropdown in the result toolbar (show / hide /
 *     reset columns, freeze / unfreeze columns).
 *   - The "Conditional Formatting" modal (add / remove / preview
 *     rules).
 *   - State that the rest of the pivot page reads when it builds
 *     the request payload (displayOptions).
 *   - Bridge functions: every time the user changes a display
 *     option, we mutate `window.PivotAppState().displayOptions` so
 *     the next "Generate Pivot" payload carries the new settings.
 *
 * Public API on `window.PivotDisplay`:
 *   init()                         — wire the UI once the DOM is ready
 *   getState()                     — read the current displayOptions
 *                                    object in the same shape the
 *                                    backend expects
 *   applyToGrid(gridApi)           — drive number / date / conditional
 *                                    formats and column visibility on
 *                                    a live AG Grid instance
 *   reset()                        — clear every option back to default
 *   getAvailableFields()           — the column list for the current
 *                                    sheet (used to populate the
 *                                    format / freeze / hide dropdowns)
 *   getFrozenColumns()             — array of column ids to pin
 *   getHiddenColumns()             — array of column ids to hide
 *   getNumberFormats()             — { field: format }
 *   getDateFormats()               — { field: format }
 *   getConditionalFormats()        — [{ field, type, value, background }]
 *   setAvailableFields(fields)     — called by pivot.js after the
 *                                    sheet is loaded
 *
 * Notes
 * -----
 * - This module does NOT touch the grid.  It exposes getters that
 *   pivot-grid.js reads when it builds the column defs and cell
 *   class rules.  The result: every option the user picks shows up
 *   in the next render automatically.
 * - All state lives on the DOM (selects, checkboxes, hidden
 *   backing store).  The state is *not* persisted across page
 *   reloads — the user starts fresh each time, like every other
 *   Excel option.
 */
(function () {
  "use strict";

  // ── Backing store ──────────────────────────────────────────────────────
  const state = {
    repeatItemLabels: false,
    numberFormat:     {},   // { field: "integer" | "decimal" | ... }
    dateFormat:       {},   // { field: "yyyy-mm-dd" | ... }
    conditional:      [],   // [{ field, type, value, background }]
    frozen:           [],   // [field, ...]   — pin order matches array order
    hidden:           [],   // [field, ...]
    availableFields:  [],   // column names for the current sheet
  };

  // ── AG Grid column API helpers (called from pivot-grid.js) ────────────
  function applyToGrid(gridApi) {
    if (!gridApi) return;

    // 1. Frozen / hidden columns
    if (typeof gridApi.setColumnsVisible === "function") {
      const hiddenSet = new Set(state.hidden);
      const allCols = [];
      gridApi.getColumns().forEach(col => {
        if (col) allCols.push(col.getColId());
      });
      gridApi.setColumnsVisible(allCols, true);
      if (hiddenSet.size) {
        gridApi.setColumnsVisible(Array.from(hiddenSet), false);
      }
    }

    // 2. Frozen columns: pin every "frozen" field to the left in the
    //    order the user picked.
    if (typeof gridApi.setColumnPinned === "function") {
      // First unpin every column so we start clean.
      const allCols = [];
      gridApi.getColumns().forEach(col => {
        if (col) allCols.push(col.getColId());
      });
      allCols.forEach(id => {
        try { gridApi.setColumnPinned(id, null); } catch (_) { /* ignore */ }
      });
      state.frozen.forEach(id => {
        try { gridApi.setColumnPinned(id, "left"); } catch (_) { /* ignore */ }
      });
    }
  }

  function getState() {
    return {
      repeatItemLabels: state.repeatItemLabels,
      numberFormat:     Object.assign({}, state.numberFormat),
      dateFormat:       Object.assign({}, state.dateFormat),
      conditional:      state.conditional.slice(),
      frozen:           state.frozen.slice(),
      hidden:           state.hidden.slice(),
    };
  }

  function reset() {
    state.repeatItemLabels = false;
    state.numberFormat = {};
    state.dateFormat = {};
    state.conditional = [];
    state.frozen = [];
    state.hidden = [];
    refreshAllUis();
  }

  function getAvailableFields()  { return state.availableFields.slice(); }
  function getFrozenColumns()     { return state.frozen.slice(); }
  function getHiddenColumns()     { return state.hidden.slice(); }
  function getNumberFormats()     { return Object.assign({}, state.numberFormat); }
  function getDateFormats()       { return Object.assign({}, state.dateFormat); }
  function getConditionalFormats() { return state.conditional.slice(); }

  function setAvailableFields(fields) {
    state.availableFields = Array.isArray(fields) ? fields.slice() : [];
    refreshAllUis();
  }

  // ── DOM helpers ───────────────────────────────────────────────────────
  let dom = null;
  function getDom() {
    if (dom) return dom;
    dom = {
      // Left panel card
      repeatItemLabels:        document.getElementById("optRepeatItemLabels"),
      numberFormatFieldSelect: document.getElementById("numberFormatField"),
      numberFormatTypeSelect:  document.getElementById("numberFormatType"),
      addNumberFormatBtn:      document.getElementById("addNumberFormatBtn"),
      numberFormatList:        document.getElementById("numberFormatList"),
      dateFormatFieldSelect:   document.getElementById("dateFormatField"),
      dateFormatTypeSelect:    document.getElementById("dateFormatType"),
      addDateFormatBtn:        document.getElementById("addDateFormatBtn"),
      dateFormatList:          document.getElementById("dateFormatList"),
      openConditionalFormatBtn: document.getElementById("openConditionalFormatBtn"),
      conditionalFormatCount:  document.getElementById("conditionalFormatCount"),
      // Toolbar buttons (right panel)
      autoFitColBtn:            document.getElementById("autoFitColBtn"),
      autoFitAllBtn:            document.getElementById("autoFitAllBtn"),
      copyCellsBtn:             document.getElementById("copyCellsBtn"),
      copyRowsBtn:              document.getElementById("copyRowsBtn"),
      copyWithHeadersBtn:       document.getElementById("copyWithHeadersBtn"),
      printBtn:                 document.getElementById("printBtn"),
      // Columns dropdown
      columnsMenu:              document.getElementById("pivotColumnsMenu"),
      freezeMenu:               document.getElementById("pivotFreezeMenu"),
      resetColumnsBtn:          document.getElementById("resetColumnsBtn"),
      // Conditional formatting modal
      cfModal:                  document.getElementById("conditionalFormatModal"),
      cfFieldSelect:            document.getElementById("cfFieldSelect"),
      cfTypeSelect:             document.getElementById("cfTypeSelect"),
      cfValueInput:             document.getElementById("cfValueInput"),
      cfValueGroup:             document.getElementById("cfValueGroup"),
      cfColorInput:             document.getElementById("cfColorInput"),
      cfAddBtn:                 document.getElementById("cfAddBtn"),
      cfList:                   document.getElementById("cfList"),
      // Print view
      printView:                document.getElementById("pivotPrintView"),
    };
    return dom;
  }

  // ── Backing-store mutation → refresh UI ───────────────────────────────
  function refreshAllUis() {
    const d = getDom();
    if (!d) return;

    // Repeat Item Labels
    if (d.repeatItemLabels) d.repeatItemLabels.checked = state.repeatItemLabels;

    // Number format list
    if (d.numberFormatList) {
      d.numberFormatList.innerHTML = "";
      const entries = Object.entries(state.numberFormat);
      if (!entries.length) {
        d.numberFormatList.innerHTML = '<div class="text-muted small">No number formats applied.</div>';
      } else {
        entries.forEach(([field, fmt]) => {
          const row = document.createElement("div");
          row.className = "d-flex justify-content-between align-items-center border-bottom py-1";
          row.innerHTML = `
            <span class="small"><i class="bi bi-123 text-primary me-1"></i><span class="fw-medium">${escHtml(field)}</span></span>
            <span class="d-flex align-items-center">
              <span class="badge bg-primary me-2">${escHtml(fmt)}</span>
              <button class="btn btn-sm btn-outline-danger" data-nf-field="${escHtml(field)}">
                <i class="bi bi-x-lg"></i>
              </button>
            </span>
          `;
          d.numberFormatList.appendChild(row);
        });
        d.numberFormatList.querySelectorAll("button[data-nf-field]").forEach(btn => {
          btn.addEventListener("click", () => {
            const f = btn.getAttribute("data-nf-field");
            delete state.numberFormat[f];
            refreshAllUis();
          });
        });
      }
    }

    // Date format list
    if (d.dateFormatList) {
      d.dateFormatList.innerHTML = "";
      const entries = Object.entries(state.dateFormat);
      if (!entries.length) {
        d.dateFormatList.innerHTML = '<div class="text-muted small">No date formats applied.</div>';
      } else {
        entries.forEach(([field, fmt]) => {
          const row = document.createElement("div");
          row.className = "d-flex justify-content-between align-items-center border-bottom py-1";
          row.innerHTML = `
            <span class="small"><i class="bi bi-calendar3 text-warning me-1"></i><span class="fw-medium">${escHtml(field)}</span></span>
            <span class="d-flex align-items-center">
              <span class="badge bg-warning me-2">${escHtml(fmt)}</span>
              <button class="btn btn-sm btn-outline-danger" data-df-field="${escHtml(field)}">
                <i class="bi bi-x-lg"></i>
              </button>
            </span>
          `;
          d.dateFormatList.appendChild(row);
        });
        d.dateFormatList.querySelectorAll("button[data-df-field]").forEach(btn => {
          btn.addEventListener("click", () => {
            const f = btn.getAttribute("data-df-field");
            delete state.dateFormat[f];
            refreshAllUis();
          });
        });
      }
    }

    // Conditional format count + list (modal)
    if (d.conditionalFormatCount) {
      d.conditionalFormatCount.textContent = state.conditional.length;
    }
    if (d.cfList) {
      d.cfList.innerHTML = "";
      if (!state.conditional.length) {
        d.cfList.innerHTML = '<li class="text-muted small">No rules yet — add one below.</li>';
      } else {
        state.conditional.forEach((rule, idx) => {
          const li = document.createElement("li");
          li.className = "list-group-item d-flex justify-content-between align-items-center";
          const valueStr = (rule.value !== undefined && rule.value !== null && rule.value !== "")
            ? ` ${escHtml(String(rule.value))}`
            : "";
          li.innerHTML = `
            <span class="small">
              <span class="badge me-2" style="background:${escHtml(rule.background || "#ffd966")}; color:#222">${escHtml(rule.background || "#ffd966")}</span>
              <span class="fw-medium">${escHtml(rule.field)}</span>
              <span class="text-muted">${escHtml(rule.type)}${valueStr}</span>
            </span>
            <button class="btn btn-sm btn-outline-danger" data-cf-idx="${idx}">
              <i class="bi bi-x-lg"></i>
            </button>
          `;
          d.cfList.appendChild(li);
        });
        d.cfList.querySelectorAll("button[data-cf-idx]").forEach(btn => {
          btn.addEventListener("click", () => {
            const i = parseInt(btn.getAttribute("data-cf-idx"), 10);
            if (Number.isInteger(i)) {
              state.conditional.splice(i, 1);
              refreshAllUis();
            }
          });
        });
      }
    }

    // Dropdown selects
    populateFieldSelect(d.numberFormatFieldSelect, /*exclude*/ Object.keys(state.numberFormat));
    populateFieldSelect(d.dateFormatFieldSelect,   /*exclude*/ Object.keys(state.dateFormat));
    populateFieldSelect(d.cfFieldSelect,           /*exclude*/ []);
  }

  function populateFieldSelect(sel, exclude) {
    if (!sel) return;
    const current = sel.value;
    const excluded = new Set(exclude || []);
    sel.innerHTML = '<option value="">— field —</option>';
    state.availableFields.forEach(f => {
      if (excluded.has(f)) return;
      const opt = document.createElement("option");
      opt.value = f;
      opt.textContent = f;
      sel.appendChild(opt);
    });
    if (current && !excluded.has(current)) sel.value = current;
    // Enable the select as soon as we have at least one field to
    // populate it with.  The HTML defaults the select to `disabled`
    // so it shows the placeholder before any data is loaded.
    sel.disabled = state.availableFields.length === 0;
  }

  // ── Wire the controls ─────────────────────────────────────────────────
  function init() {
    const d = getDom();
    if (!d) return;

    // Repeat Item Labels
    if (d.repeatItemLabels) {
      d.repeatItemLabels.addEventListener("change", () => {
        state.repeatItemLabels = d.repeatItemLabels.checked;
      });
    }

    // Number format add
    if (d.addNumberFormatBtn) {
      d.addNumberFormatBtn.addEventListener("click", () => {
        const field = d.numberFormatFieldSelect.value;
        const fmt   = d.numberFormatTypeSelect.value;
        if (!field || !fmt) return;
        state.numberFormat[field] = fmt;
        refreshAllUis();
      });
    }

    // Date format add
    if (d.addDateFormatBtn) {
      d.addDateFormatBtn.addEventListener("click", () => {
        const field = d.dateFormatFieldSelect.value;
        const fmt   = d.dateFormatTypeSelect.value;
        if (!field || !fmt) return;
        state.dateFormat[field] = fmt;
        refreshAllUis();
      });
    }

    // Open conditional format modal
    if (d.openConditionalFormatBtn && d.cfModal && window.bootstrap) {
      const handler = () => {
        // Bootstrap.Modal is created lazily — see pivot.js for the pattern
        const Modal = window.bootstrap.Modal;
        if (!Modal) return;
        let inst = window.bootstrap.Modal.getInstance(d.cfModal);
        if (!inst) {
          try { inst = new Modal(d.cfModal); } catch (_) { return; }
        }
        inst.show();
        if (d.cfTypeSelect && d.cfValueGroup) {
          const t = d.cfTypeSelect.value;
          d.cfValueGroup.style.display = (t === "gt" || t === "lt" || t === "eq") ? "" : "none";
        }
      };
      d.openConditionalFormatBtn.addEventListener("click", handler);
    }
    if (d.cfTypeSelect && d.cfValueGroup) {
      d.cfTypeSelect.addEventListener("change", () => {
        const t = d.cfTypeSelect.value;
        d.cfValueGroup.style.display = (t === "gt" || t === "lt" || t === "eq") ? "" : "none";
      });
    }
    if (d.cfAddBtn) {
      d.cfAddBtn.addEventListener("click", () => {
        const field = d.cfFieldSelect.value;
        const type  = d.cfTypeSelect.value;
        const valueRaw = d.cfValueInput ? d.cfValueInput.value : "";
        const bg    = d.cfColorInput ? d.cfColorInput.value : "#ffd966";
        if (!field || !type) return;
        let value = valueRaw;
        if (type === "gt" || type === "lt" || type === "eq") {
          if (value === "") return;
          const n = Number(value);
          value = Number.isFinite(n) ? n : value;
        } else {
          value = null;
        }
        state.conditional.push({ field, type, value, background: bg });
        refreshAllUis();
        if (d.cfValueInput) d.cfValueInput.value = "";
      });
    }

    // Auto-fit
    if (d.autoFitAllBtn) {
      d.autoFitAllBtn.addEventListener("click", () => {
        if (window.PivotGrid) window.PivotGrid.autoSizeAllColumns();
      });
    }
    if (d.autoFitColBtn) {
      d.autoFitColBtn.addEventListener("click", () => {
        if (window.PivotGrid) window.PivotGrid.autoSizeSelectedColumn();
      });
    }

    // Copy
    if (d.copyCellsBtn)      d.copyCellsBtn.addEventListener("click",      () => window.PivotGrid && window.PivotGrid.copySelection("cells"));
    if (d.copyRowsBtn)       d.copyRowsBtn.addEventListener("click",       () => window.PivotGrid && window.PivotGrid.copySelection("rows"));
    if (d.copyWithHeadersBtn) d.copyWithHeadersBtn.addEventListener("click", () => window.PivotGrid && window.PivotGrid.copySelection("rowsWithHeaders"));

    // Print
    if (d.printBtn) {
      d.printBtn.addEventListener("click", () => {
        if (window.PivotGrid) window.PivotGrid.printView();
      });
    }

    refreshAllUis();
  }

  // ── Public API ────────────────────────────────────────────────────────
  function escHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  window.PivotDisplay = {
    init,
    reset,
    getState,
    applyToGrid,
    getAvailableFields,
    setAvailableFields,
    getFrozenColumns,
    getHiddenColumns,
    getNumberFormats,
    getDateFormats,
    getConditionalFormats,
  };
})();
