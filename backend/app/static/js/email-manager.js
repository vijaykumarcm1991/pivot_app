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
      // The server may return an HTML error page (e.g. from the
      // 500 / 400 exception handler) when the request body fails
      // validation.  res.json() on an HTML body throws
      // "JSON.parse: unexpected character at line 1 column 1" which
      // is confusing to the user — instead, surface the HTTP status
      // and a snippet of the response text so the error is actionable.
      const contentType = res.headers.get("content-type") || "";
      let data;
      if (contentType.includes("application/json")) {
        data = await res.json();
      } else {
        const text = await res.text();
        const snippet = (text || "").slice(0, 200).replace(/\s+/g, " ").trim();
        throw new Error(`Server returned ${res.status} (non-JSON): ${snippet || "<empty body>"}`);
      }
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
    if (!dom.sendBtn) {
      showAlert("danger", "Send button not initialised — reload the page and try again.");
      return;
    }
    // The original button label (with the bootstrap icon) is captured
    // BEFORE we replace innerHTML so we can restore it on every exit
    // path — success, error, and exception. The previous implementation
    // only restored it on error, so a successful send left the button
    // stuck on "Sending…" forever (with the spinner spinning).
    const origHtml = dom.sendBtn.innerHTML;
    setBusy(true, "Sending email…");
    dom.sendBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Sending…';
    try {
      const payload = buildEmailPayload();
      const res = await fetch("/api/email/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const contentType = res.headers.get("content-type") || "";
      let data;
      if (contentType.includes("application/json")) {
        data = await res.json();
      } else {
        const text = await res.text();
        const snippet = (text || "").slice(0, 200).replace(/\s+/g, " ").trim();
        throw new Error(`Server returned ${res.status} (non-JSON): ${snippet || "<empty body>"}`);
      }
      if (!res.ok) {
        throw new Error((data && data.detail) || "Send failed.");
      }
      showAlert("success",
        `Email sent successfully (history #${data.historyId}).`,
      );
      // Refresh suggestions so the autocomplete picks up the new
      // addresses immediately.
      refreshRecipientSuggestions();
      // Invalidate lastPreview so the user must click Preview again
      // before they can send another email.  This prevents a second
      // send of the same preview if the user re-clicks Send before
      // changing anything.
      lastPreview = null;
    } catch (err) {
      showAlert("danger", "Send failed: " + err.message);
    } finally {
      // ALWAYS restore the button label so the user is never stuck
      // on the "Sending…" spinner.
      dom.sendBtn.innerHTML = origHtml;
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
    // The user has explicitly asked for this template — don't change
    // it without their say-so.  The opening and closing quotes
    // are curly (’— U+2019) to match the user's spec exactly.
    // Newlines are preserved in the rendered email body
    // (see _message_to_html in the backend).
    return "Hello Team,\n\nWe\u2019ve been consistently receiving alerts related to the following issue types on a daily basis. Kindly investigate the root cause and take necessary action to resolve them permanently.\n\nRegards,";
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

  // ── Recipient typeahead (Phase — new) ──────────────────────────────────
  // Real-time suggestions as the user types in To / CC / BCC.
  // The suggestions come from two sources:
  //   1. /api/users/suggest  — the company directory (users.json)
  //   2. /api/email/recent-recipients  — addresses the user has
  //      actually sent to before
  // We merge them so the most relevant rows are at the top:
  // directory matches first (richer info: name + department),
  // then recent recipients (so a typed address that's not in
  // the directory still gets a clickable suggestion).
  //
  // The dropdown is shown on the input (not on focus) so the user
  // gets instant feedback as they type.  Each suggestion shows
  // the display name in bold, the email address underneath, and
  // the department in muted text.  Clicking a suggestion inserts
  // the email at the cursor position and re-opens the dropdown
  // for multi-recipient entry.
  const _suggAbort = { to: null, cc: null, bcc: null };
  const _suggCache = new Map();  // key = `${type}:${q}` -> results[]

  function menuFor(type) {
    const id = type === "to"   ? "emailToSuggestions"   :
                type === "cc"   ? "emailCcSuggestions"   :
                                  "emailBccSuggestions";
    return document.getElementById(id);
  }

  function attachTypeahead(inputEl, type) {
    if (!inputEl) return;
    let timer = null;
    let lastQuery = null;

    const hide = () => {
      const menu = menuFor(type);
      if (menu) menu.classList.remove("show");
    };

    const showMenu = (menu, html) => {
      if (!menu) return;
      menu.innerHTML = html;
      menu.classList.add("show");
      // Wire click handlers (re-built every render)
      menu.querySelectorAll("button[data-fill-address]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.preventDefault();
          const addr = btn.getAttribute("data-fill-address");
          insertAtCursor(inputEl, addr);
          hide();
          // Re-render with the new state — the just-inserted
          // address may now be present in the suggestions list.
          scheduleSearch();
        });
      });
    };

    const renderEmpty = (menu, msg) => {
      showMenu(menu,
        `<li><span class="dropdown-item text-muted small">${escHtml(msg)}</span></li>`
      );
    };

    const renderResults = (menu, items) => {
      if (!items.length) {
        renderEmpty(menu, "No matches");
        return;
      }
      const html = items.slice(0, 8).map(u => `
        <li>
          <button class="dropdown-item small d-flex align-items-start py-2"
                  type="button"
                  data-fill-address="${escAttr(u.email)}"
                  style="white-space: normal; max-width: 100%;">
            <i class="bi bi-person me-2 mt-1 text-primary"></i>
            <div class="flex-grow-1">
              <div class="fw-semibold">${escHtml(u.name || u.email)}</div>
              <div class="small text-muted">${escHtml(u.email)}</div>
              ${u.department || u.jobTitle
                ? `<div class="small text-muted mt-1">
                     <i class="bi bi-building me-1"></i>${escHtml(u.department || u.jobTitle)}
                   </div>`
                : ""}
            </div>
          </button>
        </li>`).join("");
      showMenu(menu, html);
    };

    const renderSectioned = (menu, sections) => {
      // sections: [{title, icon, items}, ...] — each rendered as
      // a labelled group.  Used when both directory + recent are
      // non-empty.
      const blocks = [];
      let hasAny = false;
      for (const s of sections) {
        if (!s.items || !s.items.length) continue;
        hasAny = true;
        blocks.push(`
          <li><h6 class="dropdown-header d-flex align-items-center">
            <i class="bi ${s.icon} me-2"></i>${escHtml(s.title)}
            <span class="badge bg-secondary ms-2">${s.items.length}</span>
          </h6></li>
          <li><hr class="dropdown-divider my-0"></li>`);
        s.items.slice(0, 6).forEach(u => {
          blocks.push(`
            <li>
              <button class="dropdown-item small d-flex align-items-start py-2"
                      type="button"
                      data-fill-address="${escAttr(u.email)}"
                      style="white-space: normal; max-width: 100%;">
                <i class="bi bi-person me-2 mt-1 text-primary"></i>
                <div class="flex-grow-1">
                  <div class="fw-semibold">${escHtml(u.name || u.email)}</div>
                  <div class="small text-muted">${escHtml(u.email)}</div>
                  ${u.department || u.jobTitle
                    ? `<div class="small text-muted mt-1">
                         <i class="bi bi-building me-1"></i>${escHtml(u.department || u.jobTitle)}
                       </div>`
                    : ""}
                </div>
              </button>
            </li>`);
        });
      }
      if (!hasAny) {
        renderEmpty(menu, "No matches");
        return;
      }
      showMenu(menu, blocks.join(""));
    };

    const fetchDirectory = async (q) => {
      try {
        if (_suggAbort[type]) _suggAbort[type].abort();
        const ctrl = new AbortController();
        _suggAbort[type] = ctrl;
        const res = await fetch(
          `/api/users/suggest?q=${encodeURIComponent(q)}&limit=8`,
          { signal: ctrl.signal }
        );
        if (!res.ok) return [];
        const data = await res.json();
        return Array.isArray(data.results) ? data.results : [];
      } catch (_) {
        return [];
      }
    };

    const fetchRecent = async (q) => {
      // Recent recipients are only useful as a fallback when the
      // directory has no match for the typed query.
      try {
        const res = await fetch(`/api/email/recent-recipients?limit=8`);
        if (!res.ok) return [];
        const data = await res.json();
        return (Array.isArray(data) ? data : []).map(r => ({
          email: r.address,
          name:  r.address,
          department: "",
          jobTitle: `${r.useCount || 0}× used (${r.recipientType || "to"})`,
        })).filter(r => !q || r.email.toLowerCase().includes(q.toLowerCase()));
      } catch (_) {
        return [];
      }
    };

    const scheduleSearch = () => {
      clearTimeout(timer);
      timer = setTimeout(doSearch, 120);  // debounce
    };

    const doSearch = async () => {
      const menu = menuFor(type);
      if (!menu) return;
      // Extract the "current" part of the input — everything
      // after the last comma (or semicolon) so multi-recipient
      // entry still works.
      const raw = (inputEl.value || "");
      const tokens = raw.split(/[,;]\s*/);
      const q = (tokens[tokens.length - 1] || "").trim();
      if (q === lastQuery && menu.classList.contains("show")) return;
      lastQuery = q;
      if (!q) {
        renderEmpty(menu, "Type a name or email to search the directory");
        return;
      }
      // Cache hit?
      const cacheKey = `${type}:${q}`;
      if (_suggCache.has(cacheKey)) {
        renderResults(menu, _suggCache.get(cacheKey));
        return;
      }
      renderEmpty(menu, "Searching…");
      // Try directory first; fall back to recent if empty.
      const directory = await fetchDirectory(q);
      if (directory.length > 0) {
        _suggCache.set(cacheKey, directory);
        renderResults(menu, directory);
      } else {
        // Directory empty — try recent recipients as fallback.
        const recent = await fetchRecent(q);
        if (recent.length > 0) {
          renderSectioned(menu, [
            { title: "Recent recipients", icon: "bi-clock-history", items: recent },
          ]);
        } else {
          renderEmpty(menu,
            "No matches in the directory or recent recipients. " +
            "Press Enter to use the typed address as-is."
          );
        }
      }
    };

    // Show the dropdown on focus and on every keystroke.
    inputEl.addEventListener("focus", doSearch);
    inputEl.addEventListener("input", scheduleSearch);
    // Hide when the user clicks outside the input + dropdown.
    document.addEventListener("click", (e) => {
      if (e.target === inputEl) return;
      const menu = menuFor(type);
      if (menu && !menu.contains(e.target)) hide();
    });
    // Hide on Escape.
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Escape") hide();
    });
  }

  // Insert text into an input that already has a comma-separated
  // list.  We always REPLACE the partial token after the last
  // comma/semicolon so the user doesn't end up with
  // "alice@, bob@example.com" — they get "alice@example.com, bob@example.com".
  function insertAtCursor(inputEl, addr) {
    if (!inputEl || !addr) return;
    const cur = inputEl.value || "";
    const trimmed = cur.replace(/\s+$/, "");
    if (!trimmed) {
      inputEl.value = addr;
    } else if (/[,;]\s*[^,;]*$/.test(trimmed)) {
      // There's a partial token after the last comma — replace
      // it with the new address.
      inputEl.value = trimmed.replace(/[,;]\s*[^,;]*$/, ", " + addr);
    } else {
      inputEl.value = trimmed + ", " + addr;
    }
    inputEl.dispatchEvent(new Event("input", { bubbles: true }));
    inputEl.focus();
  }

  // Attach the typeahead to all three recipient inputs.
  attachTypeahead(dom.toInput,  "to");
  attachTypeahead(dom.ccInput,  "cc");
  attachTypeahead(dom.bccInput, "bcc");

  // ── Public API ────────────────────────────────────────────────────
  window.EmailManager = {
    open, close, getState,
    // Exposed for tests / debugging.
    _insertAtCursor: insertAtCursor,
  };
})();
