/**
 * email-history.js — Email history page controller (Phase 6).
 *
 * Renders the email history at /email/history:
 *   - Fetches GET /api/email/history
 *   - Renders rows with status badges + attachment re-download link
 *   - Search box (subject, recipients, dataset) + status filter
 *   - Click an attachment to re-download it from the server
 */
(function () {
  "use strict";

  try {
    main();
  } catch (err) {
    console.error("[email-history] init error:", err);
  }

  function main() {
    const $ = (id) => document.getElementById(id);

    const loadingEl     = $("historyLoading");
    const emptyEl       = $("historyEmpty");
    const tableWrapEl   = $("historyTableWrap");
    const tbodyEl       = $("historyTbody");
    const countEl       = $("historyCount");
    const searchEl      = $("historySearch");
    const statusFilterEl= $("historyStatusFilter");
    const errorModalEl  = $("historyErrorModal");
    const errorBodyEl   = $("historyErrorBody");
    const errorModal    = (window.bootstrap && window.bootstrap.Modal)
      ? new window.bootstrap.Modal(errorModalEl)
      : null;

    let allRows = [];
    let searchTerm = "";
    let statusFilter = "";

    loadHistory();

    // Debounced search
    let searchTimer = null;
    searchEl.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        searchTerm = (searchEl.value || "").trim().toLowerCase();
        render();
      }, 150);
    });
    statusFilterEl.addEventListener("change", () => {
      statusFilter = statusFilterEl.value || "";
      render();
    });

    async function loadHistory() {
      try {
        const res = await fetch("/api/email/history?limit=200");
        if (!res.ok) throw new Error("Failed to load history.");
        allRows = await res.json();
        render();
      } catch (err) {
        tbodyEl.innerHTML = `<tr><td colspan="8" class="text-center text-danger py-4">${escHtml(err.message)}</td></tr>`;
        tableWrapEl.style.display = "";
        loadingEl.style.display = "none";
        emptyEl.style.display = "none";
      }
    }

    function render() {
      loadingEl.style.display = "none";

      // Apply filters
      const filtered = allRows.filter((row) => {
        if (statusFilter && (row.status || "") !== statusFilter) return false;
        if (searchTerm) {
          const haystack = [
            row.subject,
            (row.toAddresses || []).join(" "),
            (row.ccAddresses || []).join(" "),
            (row.bccAddresses || []).join(" "),
            row.datasetName || "",
            row.sheetName || "",
          ].join(" ").toLowerCase();
          if (!haystack.includes(searchTerm)) return false;
        }
        return true;
      });

      countEl.textContent = `${filtered.length} of ${allRows.length} email${allRows.length === 1 ? "" : "s"}`;

      if (!allRows.length) {
        emptyEl.style.display = "";
        tableWrapEl.style.display = "none";
        return;
      }
      if (!filtered.length) {
        emptyEl.innerHTML = `
          <i class="bi bi-funnel display-3 text-muted opacity-50"></i>
          <h5 class="mt-3 mb-1">No matches</h5>
          <p class="text-muted mb-0">No emails match your filters.</p>
        `;
        emptyEl.style.display = "";
        tableWrapEl.style.display = "none";
        return;
      }

      emptyEl.style.display = "none";
      tableWrapEl.style.display = "";

      // Reset the "no matches" message for the next time it shows.
      emptyEl.innerHTML = `
        <i class="bi bi-inbox display-3 text-muted opacity-50"></i>
        <h5 class="mt-3 mb-1">No emails sent yet</h5>
        <p class="text-muted mb-0">
          Send a pivot report from the
          <a href="/pivot">Pivot Builder</a>
          to see entries here.
        </p>
      `;

      tbodyEl.innerHTML = filtered.map(rowHtml).join("");

      // Wire attachment buttons
      tbodyEl.querySelectorAll("[data-attachment-id]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.preventDefault();
          const id = btn.getAttribute("data-attachment-id");
          window.location.href = `/api/email/history/${id}/attachment`;
        });
      });
      // Wire error-message expanders
      tbodyEl.querySelectorAll("[data-show-error]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.preventDefault();
          const id = btn.getAttribute("data-show-error");
          const row = allRows.find((r) => String(r.id) === String(id));
          if (row && errorBodyEl && errorModal) {
            errorBodyEl.textContent = row.errorMessage || "Unknown error";
            errorModal.show();
          }
        });
      });
    }

    function rowHtml(row) {
      const date = formatDate(row.sentAt);
      const recipients = [
        ...(row.toAddresses || []).map((a) => `to: ${a}`),
        ...(row.ccAddresses || []).map((a) => `cc: ${a}`),
        ...(row.bccAddresses || []).map((a) => `bcc: ${a}`),
      ];
      const recipientSummary = recipients.length
        ? `<div class="small text-muted" title="${escHtml(recipients.join("\n"))}">${escHtml(recipients.slice(0, 2).join(", "))}${recipients.length > 2 ? ` <span class="text-muted">+${recipients.length - 2} more</span>` : ""}</div>`
        : '<span class="text-muted small">—</span>';

      const datasetSheet = row.datasetName
        ? `<div>${escHtml(row.datasetName)}</div><div class="small text-muted">${escHtml(row.sheetName || "—")}</div>`
        : '<span class="text-muted small">—</span>';

      const statusBadge = row.status === "success"
        ? '<span class="badge bg-success">Sent</span>'
        : `<span class="badge bg-danger" role="button" data-show-error="${row.id}" title="Click for details">Failed</span>`;

      const attachmentCell = row.hasAttachment && row.status === "success"
        ? `<a href="#" class="btn btn-sm btn-outline-success" data-attachment-id="${row.id}">
             <i class="bi bi-download me-1"></i>${escHtml(truncate(row.attachmentFilename || "xlsx", 20))}
           </a>`
        : row.hasAttachment
        ? `<span class="text-muted small" title="Attachment saved but the email was not sent"><i class="bi bi-paperclip"></i> saved</span>`
        : '<span class="text-muted small">—</span>';

      return `
        <tr>
          <td class="small text-nowrap">${escHtml(date)}</td>
          <td>
            <div class="fw-medium">${escHtml(row.subject || "(no subject)")}</div>
            ${row.errorMessage ? `<div class="small text-danger mt-1" role="button" data-show-error="${row.id}">${escHtml(truncate(row.errorMessage, 80))}</div>` : ""}
          </td>
          <td>${recipientSummary}</td>
          <td>${datasetSheet}</td>
          <td class="text-end">${row.pivotRowsCount || 0}</td>
          <td class="text-end">${row.attachedRecordsCount || 0}</td>
          <td>${statusBadge}</td>
          <td>${attachmentCell}</td>
        </tr>
      `;
    }

    function formatDate(iso) {
      if (!iso) return "—";
      // The backend exposes `sentAtIst` (an ISO-8601 string in
      // Asia/Kolkata with the +05:30 offset).  Pass it to
      // AppFormat.ist() so the user sees the same "08 Jul 2026,
      // 14:32 IST" format the rest of the app uses.
      const f = (window.AppFormat && window.AppFormat.ist) || (s => s || "");
      return f(iso);
    }

    function truncate(s, n) {
      if (!s) return "";
      return s.length > n ? s.slice(0, n - 1) + "…" : s;
    }

    function escHtml(s) {
      return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }
  }
})();
