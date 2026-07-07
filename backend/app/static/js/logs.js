/**
 * logs.js — Log Viewer controller (Phase 8).
 */
(function () {
  "use strict";
  try { main(); } catch (err) { console.error("[logs] init error:", err); }

  function main() {
    const $ = (id) => document.getElementById(id);
    const queryEl     = $("logQuery");
    const levelEl     = $("logLevel");
    const categoryEl  = $("logCategory");
    const dateFromEl  = $("logDateFrom");
    const dateToEl    = $("logDateTo");
    const applyBtn    = $("applyBtn");
    const clearBtn    = $("clearBtn");
    const resultCount = $("resultCount");
    const rowsEl      = $("logRows");

    $("logFilterForm").addEventListener("submit", (e) => { e.preventDefault(); load(); });
    clearBtn.addEventListener("click", () => {
      queryEl.value = ""; levelEl.value = ""; categoryEl.value = "";
      dateFromEl.value = ""; dateToEl.value = "";
      load();
    });

    load();

    async function load() {
      rowsEl.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-3">
        <span class="spinner-border spinner-border-sm me-2"></span>Loading…
      </td></tr>`;
      const params = new URLSearchParams();
      if (queryEl.value)     params.set("q", queryEl.value);
      if (levelEl.value)     params.set("level", levelEl.value);
      if (categoryEl.value)  params.set("category", categoryEl.value);
      if (dateFromEl.value)  params.set("date_from", dateFromEl.value);
      if (dateToEl.value)    params.set("date_to", dateToEl.value);
      try {
        const res = await fetch("/api/logs?" + params.toString());
        const data = await res.json();
        if (!res.ok) throw new Error("Failed to load logs.");
        render(data.rows || []);
        resultCount.textContent = `${data.count || 0} record(s)`;
      } catch (err) {
        rowsEl.innerHTML = `<tr><td colspan="5" class="text-center text-danger py-3">${escHtml(err.message)}</td></tr>`;
      }
    }

    function render(rows) {
      if (!rows.length) {
        rowsEl.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">No log records match the current filters.</td></tr>`;
        return;
      }
      rowsEl.innerHTML = rows.map(r => `
        <tr>
          <td class="text-muted small">${formatDate(r.timestamp)}</td>
          <td>${levelBadge(r.level)}</td>
          <td><span class="badge bg-body-tertiary border text-body">${escHtml(r.category || "")}</span></td>
          <td>${escHtml(r.message || "")}${r.details ? `<div class="small text-muted mt-1">${escHtml(r.details)}</div>` : ""}</td>
          <td class="small text-muted text-truncate" style="max-width:220px;" title="${escHtml(r.source || "")}">${escHtml(r.source || "")}</td>
        </tr>
      `).join("");
    }

    function levelBadge(level) {
      const map = { debug: "secondary", info: "primary", warning: "warning", error: "danger", critical: "danger" };
      const cls = map[(level || "info").toLowerCase()] || "secondary";
      return `<span class="badge bg-${cls}-subtle text-${cls} border">${escHtml(level || "")}</span>`;
    }

    function escHtml(s) {
      return String(s == null ? "" : s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function formatDate(iso) {
      try { return new Date(iso).toLocaleString(); } catch (_) { return iso || ""; }
    }
  }
})();
