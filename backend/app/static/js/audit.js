/**
 * audit.js — Delete audit page controller.
 */
(function () {
  "use strict";
  try { main(); } catch (err) { console.error("[audit] init error:", err); }

  function main() {
    const $ = (id) => document.getElementById(id);
    const queryEl  = $("auditQuery");
    const statusEl = $("auditStatus");
    const rowsEl   = $("auditRows");
    const form     = $("auditForm");
    const clearBtn = $("clearBtn");
    const detailPre= $("detailPre");
    const detailModal = new bootstrap.Modal($("detailModal"));

    form.addEventListener("submit", (e) => { e.preventDefault(); load(); });
    clearBtn.addEventListener("click", () => {
      queryEl.value = ""; statusEl.value = ""; load();
    });
    $("refreshBtn").addEventListener("click", load);

    load();

    async function load() {
      rowsEl.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-3">
        <span class="spinner-border spinner-border-sm me-2"></span>Loading…
      </td></tr>`;
      const params = new URLSearchParams();
      if (queryEl.value)  params.set("q", queryEl.value);
      if (statusEl.value) params.set("status", statusEl.value);
      try {
        const res = await fetch("/api/admin/audit?" + params.toString());
        const data = await res.json();
        if (!res.ok) throw new Error("Failed to load audit rows.");
        render(data.rows || []);
      } catch (err) {
        rowsEl.innerHTML = `<tr><td colspan="7" class="text-center text-danger py-3">${escHtml(err.message)}</td></tr>`;
      }
    }

    function render(rows) {
      if (!rows.length) {
        rowsEl.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">No delete operations recorded yet.</td></tr>`;
        return;
      }
      rowsEl.innerHTML = rows.map(r => `
        <tr>
          <td class="text-muted small">${formatDate(r.timestamp)}</td>
          <td>
            <div class="fw-semibold">${escHtml(r.datasetName || "")}</div>
            <div class="small text-muted">${escHtml(r.sheetName || "")}</div>
          </td>
          <td class="text-end">${r.pivotRowsCount}</td>
          <td class="text-end">${r.sourceRecordsFound}</td>
          <td class="text-end">${r.sourceRecordsDeleted}</td>
          <td>${statusBadge(r.status)}</td>
          <td class="text-end text-nowrap">
            ${r.restorable ? `<button class="btn btn-sm btn-outline-primary" data-restore="${r.id}" title="Undo this delete — the records reappear">
              <i class="bi bi-arrow-counterclockwise me-1"></i>Restore
            </button>` : ""}
            <button class="btn btn-sm btn-outline-secondary" data-detail='${escAttr(JSON.stringify(r))}' title="Details">
              <i class="bi bi-eye"></i>
            </button>
          </td>
        </tr>
      `).join("");
      rowsEl.querySelectorAll("button[data-restore]").forEach(btn => {
        btn.addEventListener("click", () => restore(rows.find(r => String(r.id) === btn.dataset.restore), btn));
      });
      rowsEl.querySelectorAll("button[data-detail]").forEach(btn => {
        btn.addEventListener("click", () => {
          const data = JSON.parse(btn.getAttribute("data-detail"));
          detailPre.textContent = JSON.stringify(data, null, 2);
          detailModal.show();
        });
      });
    }

    async function restore(r, btn) {
      const ok = await window.AppUI.confirm({
        title: "Restore deleted records?",
        body: `The ${r.sourceRecordsDeleted} record(s) deleted from “${r.datasetName}” at ${formatDate(r.timestamp)} will appear again in pivots, drill-downs, exports and emails.`,
        confirmText: "Restore",
      });
      if (!ok) return;
      btn.disabled = true;
      try {
        const res = await window.AppUI.fetchJSON(`/api/admin/audit/${r.id}/restore`, { method: "POST" });
        window.AppUI.toast(`Restored ${res.restored} record(s).`, { type: "success" });
      } catch (err) {
        window.AppUI.toast(`Restore failed: ${err.message}`, { type: "error", timeout: 8000 });
      }
      load();
    }

    function statusBadge(s) {
      const map = { success: "success", failed: "danger", in_progress: "warning", restored: "info" };
      const cls = map[(s || "").toLowerCase()] || "secondary";
      return `<span class="badge bg-${cls}-subtle text-${cls} border">${escHtml(s || "")}</span>`;
    }

    function escHtml(s) {
      return String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }
    function escAttr(s) { return escHtml(s); }
    // IST-formatted timestamp — the user asked for every visible
    // timestamp in the app to be in Indian Standard Time.
    function formatDate(iso) {
      const f = (window.AppFormat && window.AppFormat.ist) || (s => s || "");
      return f(iso);
    }
  }
})();
