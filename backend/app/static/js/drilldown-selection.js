/**
 * drilldown-selection.js — Build drill-down selection criteria from pivot rows.
 *
 * The drilldown endpoint `POST /api/pivot/drilldown` accepts the same payload
 * as `/api/pivot` plus a `selection: { field: value }` object. The values in
 * that object identify which pivot row the user clicked on. This module
 * builds that object from a pivot result row, and exposes the helpers used
 * by drilldown-manager.js and by the toolbar button in pivot.js.
 *
 * Public API on `window.DrilldownSelection`:
 *   buildSelectionForRow(pivotRow, response)
 *       — produce a { field: value } map for a single pivot row
 *   buildSelectionList(pivotRows, response)
 *       — produce [{ pivotRow, selection }] for an array of pivot rows
 *   getSelectedPivotRows()
 *       — read the current selection from window.PivotGrid
 *   getCurrentPivotResponse()
 *       — read the last PivotResponse from window.PivotGrid
 *
 * Selection rules
 * ---------------
 * The pivot result row has the following categories of keys (Phase 4
 * engine):
 *   1. Row field names (or their date-grouped display names like
 *      "OrderDate_month") — these ARE the selection.
 *   2. Value field labels (e.g. "sum_Amount", "count_Amount") — exclude.
 *   3. row_total (when `showRowTotals` is on) — exclude.
 *   4. Internal markers (`__isGrandTotal`, `__pivot_*`) — exclude.
 *   5. Column-group value cells when the pivot has column fields
 *      (e.g. rows=["Region"], columns=["Status"] → cells named "Open"
 *      and "Closed") — these are not row field names, so we leave them
 *      out of the selection. The backend's `_apply_selection` already
 *      ignores unknown keys, so we don't have to be perfect here.
 *
 * In tabular mode the date-grouped row field appears under its display
 * name `<Field>_<grouping>` (e.g. "OrderDate_month"). The backend's
 * `_selection_field_name` accepts that display name directly, so we can
 * just pass the key as it appears in the pivot row.
 */
(function () {
  "use strict";

  /**
   * Build the selection map for a single pivot row.
   *
   * @param {Object} pivotRow - a row from `PivotResponse.rows` (or any
   *                            equivalent object).
   * @param {Object} response - the full PivotResponse (used to know which
   *                            keys are value labels / row_total, etc.).
   * @returns {Object} a flat `{ field: value }` map ready to send as
   *                    `selection` in the drilldown request.
   */
  function buildSelectionForRow(pivotRow, response) {
    if (!pivotRow || typeof pivotRow !== "object") return {};
    if (!response || !response.metadata) return {};

    const meta   = response.metadata || {};
    const aggs   = response.aggregations || [];
    const totals = response.totals || {};
    const rowTotalField = totals.row_total_field || "row_total";

    // Build a set of "do not include" keys.
    const valueLabels = new Set();
    aggs.forEach(a => {
      if (a && a.label) valueLabels.add(a.label);
    });

    const selection = {};
    Object.keys(pivotRow).forEach(key => {
      // Skip internal markers + well-known non-row keys.
      if (key === rowTotalField)      return;
      if (key === "__isGrandTotal")   return;
      if (key === "_warning")         return;
      if (key.indexOf("__pivot_") === 0) return;
      if (valueLabels.has(key))       return;

      const value = pivotRow[key];
      // Drop null / empty values — they would never match anyway.
      if (value === null || value === undefined || value === "") return;
      selection[key] = value;
    });

    // Touch the meta so the linter doesn't complain — we read it above
    // to ensure the response has a pivot result shape.
    void meta;

    return selection;
  }

  /**
   * Build a list of selection entries for multiple pivot rows.
   *
   * @param {Array<Object>} pivotRows
   * @param {Object}        response
   * @returns {Array<{ pivotRow: Object, selection: Object }>}
   */
  function buildSelectionList(pivotRows, response) {
    if (!Array.isArray(pivotRows) || !pivotRows.length) return [];
    return pivotRows.map(row => ({
      pivotRow: row,
      selection: buildSelectionForRow(row, response),
    }));
  }

  /**
   * Read the currently selected rows from the pivot AG Grid.
   * Returns an empty array if PivotGrid is not loaded or nothing is selected.
   */
  function getSelectedPivotRows() {
    if (!window.PivotGrid) return [];
    try {
      const rows = window.PivotGrid.getSelectedRows();
      return Array.isArray(rows) ? rows : [];
    } catch (_) {
      return [];
    }
  }

  /**
   * Read the last PivotResponse from the pivot grid (so we know which
   * columns are value labels, which are row fields, etc.).
   */
  function getCurrentPivotResponse() {
    if (!window.PivotGrid) return null;
    try {
      return window.PivotGrid.getLastResponse() || null;
    } catch (_) {
      return null;
    }
  }

  /**
   * Build a deduplication key for a raw record returned by the drilldown
   * API. Two records that share every value (column-for-column) are
   * considered duplicates and merged into one row in the multi-row
   * drilldown view.
   *
   * Strategy: stable JSON serialisation. Columns are sorted alphabetically
   * so the key is independent of the order in which the backend returned
   * them. This works for the "matching records" use case; if a sheet has
   * truly identical rows (no primary key) they will collapse together.
   *
   * @param {Object} record - one record from the drilldown response
   * @returns {string} a stable, dedup-friendly key
   */
  function dedupKey(record) {
    if (!record || typeof record !== "object") return "";
    const keys = Object.keys(record).sort();
    const parts = keys.map(k => k + "=" + JSON.stringify(record[k]));
    return parts.join("|");
  }

  // ── Public API ───────────────────────────────────────────────────────────
  window.DrilldownSelection = {
    buildSelectionForRow,
    buildSelectionList,
    getSelectedPivotRows,
    getCurrentPivotResponse,
    dedupKey,
  };
})();
