/**
 * email-manager.js — Email Composer orchestrator (Phase 6).
 *
 * The Composer is a Bootstrap modal that opens when the user
 * clicks the Send Email button on the Pivot page. It collects:
 *   - To / CC / BCC (with typeahead suggestions from
 *     /api/email/recent-recipients)
 *   - Subject
 *   - User message
 *
 * The user can:
 *   - Click Preview → POST /api/email/preview → render the HTML +
 *     attachment download
 *   - Click Send    → POST /api/email/send → record history and
 *     dispatch via SMTP
 *
 * The Composer reuses:
 *   - window.DrilldownSelection  — to turn the user's selected
 *     pivot rows into the `selections` list the server needs
 *   - window.DrilldownManager    — to detect whether the user has
 *     any selected rows (the button is only enabled when there are)
 *   - window.PivotAppState       — for the current payload
 *   - window.PivotGrid           — for the current PivotResponse
 *     (so we can render the same column / totals the user saw)
 *
 * Public API on `window.EmailManager`:
 *   open()         — open the modal
 *   close()        — close the modal
 *   getState()     — current composer state (mostly for tests)
 */
(function () {
  "use strict";

  let modalInstance = null;
  let dom = null;
  let lastPreview = null; // last EmailPreviewResponse from the server

  function init() {
    if (init._done) return;
    init._done = true;
    dom = {
      modal:           document.getElementById("emailModal"),
      toInput:         document.getElementById("emailTo"),
      ccInput:         document.getElementById("emailCc"),
      bccInput:        document.getElementById("emailBcc"),
      subjectInput:    document.getElementById("emailSubject"),
      messageInput:    document.getElementById("emailMessage"),
      previewBtn:      document.getElementById("emailPreviewBtn"),
      sendBtn:         document.getElementById("emailSendBtn"),
      resetBtn:        document.getElementById("emailResetBtn"),
      alertArea:       document.getElementById("emailAlertArea"),
      pivotRowsCount:  document.getElementById("emailPivotRowsCount"),
      recordsCount:    document.getElementById("emailRecordsCount"),
      datasetBadge:    document.getElementById("emailDatasetBadge"),
      sheetBadge:      document.getElementById("emailSheetBadge"),
      toSuggestions:   document.getElementById("emailToSuggestions"),
      ccSuggestions:   document.getElementById("emailCcSuggestions"),
      bccSuggestions:  document.getElementById("emailBccSuggestions"),
    };
    if (dom.modal && window.bootstrap && window.bootstrap.Modal) {
      modalInstance = new window.bootstrap.Modal(dom.modal, { backdrop: "static" });
    }
    if (dom.previewBtn)  dom.previewBtn.addEventListener("click", onPreview);
    if (dom.sendBtn)     dom.sendBtn.addEventListener("click", onSend);
    if (dom.resetBtn)    dom.resetBtn.addEventListener("click", onReset);
  }

  function open() {
    init();
    if (!dom.modal) {
      console.warn("[email-manager] emailModal not present in the page");
      return;
    }
    if (!hasSelection()) {
      notify("Select one or more pivot rows first (or double-click a row).");
      return;
    }
    resetForm();
    if (modalInstance) modalInstance.show();
    setBusy(false);
    refreshRecipientSuggestions();
  }

  function close() {
    if (modalInstance) modalInstance.hide();
  }

  function resetForm() {
    if (dom.toInput)      dom.toInput.value = "";
    if (dom.ccInput)      dom.ccInput.value = "";
    if (dom.bccInput)     dom.bccInput.value = "";
    if (dom.subjectInput) dom.subjectInput.value = defaultSubject();
    if (dom.messageInput) dom.messageInput.value = defaultMessage();
    lastPreview = null;
    if (dom.alertArea)    dom.alertArea.innerHTML = "";
    if (window.PreviewManager) window.PreviewManager.clear();
    setBusy(false);
    if (dom.previewBtn) dom.previewBtn.disabled = false;
    if (dom.sendBtn)    dom.sendBtn.disabled    = true;
    updateContextBadges();
  }

  function onReset() {
    resetForm();
  }

  async function onPreview() {
    if (!hasSelection()) {
      showAlert("warning", "Select one or more pivot rows first.");
      return;
    }
    setBusy(true, "Building preview…");
    try {
      const payload = buildEmailPayload();
      const res = await fetch("/api/email/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error((data && data.detail) || "Preview failed.");
      }
      lastPreview = data;
      if (window.PreviewManager) {
        window.PreviewManager.setHtml(data.html || "", data.datasetName || "");
        window.PreviewManager.setAttachment(
          data.attachmentFilename,
          data.attachmentDownloadUrl,
        );
      }
      // Update the "Records" badge with the server's count
      if (dom.recordsCount) {
        dom.recordsCount.textContent = (data.attachmentRecordCount || 0).toLocaleString();
      }
      if (dom.sendBtn) dom.sendBtn.disabled = false;
      showAlert("success",
        `Preview ready — ${data.attachmentRecordCount} record${data.attachmentRecordCount === 1 ? "" : "s"} ` +
        `from ${data.pivotRowsCount} pivot row${data.pivotRowsCount === 1 ? "" : "s"}.`,
      );
    } catch (err) {
      showAlert("danger", "Preview failed: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  async function onSend() {
    if (!lastPreview) {
      showAlert("warning", "Click Preview first to build the email.");
      return;
    }
    setBusy(true, "Sending email…");
    try {
      const payload = buildEmailPayload();
      const res = await fetch("/api/email/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error((data && data.detail) || "Send failed.");
      }
      showAlert("success",
        `Email sent successfully (history #${data.historyId}).`,
      );
      // Refresh suggestions so the autocomplete picks up the new
      // addresses immediately.
      refreshRecipientSuggestions();
      // Disable the Send button — the user has to click Preview again
      // to send another email.
      if (dom.sendBtn) dom.sendBtn.disabled = true;
    } catch (err) {
      showAlert("danger", "Send failed: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  // ── Payload construction ────────────────────────────────────────────
  function buildEmailPayload() {
    if (!window.DrilldownSelection) {
      throw new Error("Drill-down selection helper not loaded.");
    }
    const pivotResponse = window.PivotGrid ? window.PivotGrid.getLastResponse() : null;
    if (!pivotResponse) {
      throw new Error("No pivot result — generate a pivot first.");
    }
    const pivotRows = window.DrilldownSelection.getSelectedPivotRows();
    if (!pivotRows.length) {
      throw new Error("Select at least one pivot row.");
    }
    const basePayload = (window.PivotAppState && window.PivotAppState())
      || pivotResponse.metadata
      || {};
    if (!basePayload.datasetId || !basePayload.sheetName) {
      throw new Error("Pivot configuration is missing datasetId or sheetName.");
    }

    // Each selected pivot row becomes a `{ selection: {field:value} }`.
    const selections = pivotRows.map((row) => ({
      selection: window.DrilldownSelection.buildSelectionForRow(row, pivotResponse),
    }));

    return {
      to:       dom.toInput.value || "",
      cc:       dom.ccInput.value || "",
      bcc:      dom.bccInput.value || "",
      subject:  dom.subjectInput.value || "",
      message:  dom.messageInput.value || "",
      datasetId:    basePayload.datasetId,
      sheetName:    basePayload.sheetName,
      rows:         basePayload.rows || [],
      columns:      basePayload.columns || [],
      values:       basePayload.values || [],
      filters:      basePayload.filters || {},
      dateGrouping: basePayload.dateGrouping || {},
      sorting:      basePayload.sorting || {},
      totals:       basePayload.totals || {},
      layout:       basePayload.layout || "tabular",
      selections,
      pivot_rows:   pivotRows,
      pivot_response: {
        columns: pivotResponse.columns || [],
        totals:  pivotResponse.totals  || {},
      },
      dataset_name: basePayload.datasetName || basePayload.dataset_name || "",
    };
  }

  function hasSelection() {
    if (!window.DrilldownSelection) return false;
    return window.DrilldownSelection.getSelectedPivotRows().length > 0;
  }

  function defaultSubject() {
    const pivotResponse = window.PivotGrid ? window.PivotGrid.getLastResponse() : null;
    const meta = (pivotResponse && pivotResponse.metadata) || {};
    const dataset = (window.PivotAppState && window.PivotAppState() || {}).datasetName || "dataset";
    return `Pivot report — ${dataset} / ${meta.sheet_name || ""}`.trim();
  }
  function defaultMessage() {
    return "Hello team,\n\nPlease find the pivot summary below.\n\nThe detailed drill-down report is attached.\n\nRegards,";
  }

  // ── UI helpers ─────────────────────────────────────────────────────
  function updateContextBadges() {
    if (!dom.pivotRowsCount || !dom.recordsCount) return;
    const n = window.DrilldownSelection ? window.DrilldownSelection.getSelectedPivotRows().length : 0;
    dom.pivotRowsCount.textContent = n.toLocaleString();
    // "Records" is updated when the preview comes back.
    dom.recordsCount.textContent = "—";

    const appState = (window.PivotAppState && window.PivotAppState()) || {};
    if (dom.datasetBadge) dom.datasetBadge.textContent = appState.datasetName || "—";
    const meta = ((window.PivotGrid && window.PivotGrid.getLastResponse()) || {}).metadata || {};
    if (dom.sheetBadge) dom.sheetBadge.textContent = meta.sheet_name || "—";
  }

  function setBusy(busy, message) {
    if (dom.previewBtn) dom.previewBtn.disabled = !!busy;
    if (dom.sendBtn)    dom.sendBtn.disabled    = busy || !lastPreview;
    if (busy && window.PreviewManager) {
      window.PreviewManager.setBusy(true, message);
    } else if (!busy && window.PreviewManager && lastPreview) {
      // Re-render the preview so the busy overlay disappears.
      window.PreviewManager.setHtml(lastPreview.html || "", lastPreview.datasetName || "");
      window.PreviewManager.setAttachment(
        lastPreview.attachmentFilename, lastPreview.attachmentDownloadUrl,
      );
    } else if (!busy && window.PreviewManager) {
      window.PreviewManager.clear();
    }
  }

  function showAlert(kind, message) {
    if (!dom.alertArea) return;
    dom.alertArea.innerHTML = `
      <div class="alert alert-${kind} alert-dismissible fade show" role="alert">
        ${escHtml(message)}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
      </div>
    `;
  }

  // ── Recipient suggestions (typeahead) ──────────────────────────────
  // Simple: when the user focuses the To/CC/BCC field, show a
  // dropdown of recent addresses. Clicking one fills the field.
  async function refreshRecipientSuggestions() {
    for (const which of ["to", "cc", "bcc"]) {
      const list = await fetchRecent(which);
      renderSuggestions(which, list);
    }
  }

  async function fetchRecent(type) {
    try {
      const res = await fetch(`/api/email/recent-recipients?type=${type}&limit=8`);
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data) ? data : [];
    } catch (_) {
      return [];
    }
  }

  function renderSuggestions(type, list) {
    const menuId = type === "to" ? "emailToSuggestions"
                 : type === "cc" ? "emailCcSuggestions"
                 : "emailBccSuggestions";
    const menu = document.getElementById(menuId);
    if (!menu) return;
    if (!list.length) {
      menu.innerHTML = '<li><span class="dropdown-item text-muted small">No suggestions yet</span></li>';
      return;
    }
    menu.innerHTML = list.map((r) => `
      <li>
        <button class="dropdown-item small" type="button" data-fill-type="${escAttr(type)}" data-fill-address="${escAttr(r.address)}">
          <i class="bi bi-clock-history me-2 text-muted"></i>${escHtml(r.address)}
          <span class="text-muted ms-1">· ${r.useCount}×</span>
        </button>
      </li>
    `).join("");
    // Wire click → fill the input
    menu.querySelectorAll("button[data-fill-address]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const addr = btn.getAttribute("data-fill-address");
        const inputId = type === "to" ? "emailTo"
                      : type === "cc" ? "emailCc"
                      : "emailBcc";
        const input = document.getElementById(inputId);
        if (input) {
          // Append the address to the existing value (or set it if empty).
          const existing = (input.value || "").trim();
          input.value = existing ? `${existing}, ${addr}` : addr;
          input.focus();
        }
      });
    });
  }

  // ── Misc helpers ───────────────────────────────────────────────────
  function notify(msg) {
    if (window.DrilldownExport && window.DrilldownExport._notify) {
      window.DrilldownExport._notify(msg);
    } else {
      console.warn("[email]", msg);
    }
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
  function escAttr(s) {
    return escHtml(s);
  }

  function getState() {
    return {
      hasSelection: hasSelection(),
      lastPreview,
    };
  }

  window.EmailManager = { open, close, getState };
})();
