/**
 * diagnostics.js — System diagnostics page controller.
 */
(function () {
  "use strict";
  try { main(); } catch (err) { console.error("[diagnostics] init error:", err); }

  function main() {
    const $ = (id) => document.getElementById(id);
    const cardsEl = $("diagCards");
    $("refreshBtn").addEventListener("click", load);
    load();

    async function load() {
      cardsEl.innerHTML = `<div class="col-12 text-muted py-3">
        <span class="spinner-border spinner-border-sm me-2"></span>Loading…
      </div>`;
      try {
        const res = await fetch("/api/diagnostics");
        const data = await res.json();
        if (!res.ok) throw new Error("Failed to load diagnostics.");
        render(data);
      } catch (err) {
        cardsEl.innerHTML = `<div class="col-12"><div class="alert alert-danger">${escHtml(err.message)}</div></div>`;
      }
    }

    function render(d) {
      const health = d.health || {};
      const app    = d.application || {};
      const db     = d.database || {};
      const storage= d.storage || {};
      const smtp   = d.smtp || {};
      const folders= d.folders || {};

      cardsEl.innerHTML = `
        ${section("Health", `
          ${row("Status", healthBadge(health.status), health.status === "ok" ? "OK" : "Issues detected")}
          ${row("Checked At", formatDate(health.checkedAt))}
        `)}
        ${section("Application", `
          ${row("Version", escHtml(app.version || ""))}
          ${row("Python", escHtml(app.python || ""))}
          ${row("SQLite", escHtml(db.sqliteVersion || "—"))}
          ${row("OS", escHtml(app.os || ""))}
          ${row("Hostname", escHtml(app.hostname || ""))}
        `)}
        ${section("Database", `
          ${row("Path", escHtml(db.path || "—"))}
          ${row("Size", escHtml((db.sizeMb ?? "—") + " MB"))}
          ${row("Dataset Count", escHtml(String(db.datasetCount ?? storage.datasetCount ?? 0)))}
          ${row("Status", db.ok ? okBadge("OK") : errBadge(db.error || "Unavailable"))}
        `)}
        ${section("Storage", `
          ${row("Datasets", escHtml(String(storage.datasetCount ?? 0)))}
          ${row("Uploads", escHtml((storage.uploadsMb ?? "—") + " MB"))}
          ${row("Reports", escHtml((storage.reportsMb ?? "—") + " MB"))}
        `)}
        ${section("Folders", `
          ${folderRow("Uploads", folders.uploads)}
          ${folderRow("Reports", folders.reports)}
          ${folderRow("Logs",    folders.logs)}
        `)}
        ${section("SMTP", `
          ${row("Configured", smtp.configured ? okBadge("Yes") : warnBadge("No"))}
          ${row("Host", escHtml(smtp.host || "—"))}
          ${row("Username", escHtml(smtp.username || "—"))}
          ${row("Sender", escHtml(smtp.sender || "—"))}
        `)}
      `;
    }

    function section(title, body) {
      return `
        <div class="col-md-6 col-xl-4">
          <div class="card border-0 shadow-sm h-100">
            <div class="card-header fw-semibold">${escHtml(title)}</div>
            <div class="card-body p-0">
              <table class="table table-sm mb-0">
                <tbody>${body}</tbody>
              </table>
            </div>
          </div>
        </div>`;
    }

    function row(label, value, hint) {
      return `<tr>
        <th class="text-muted small fw-normal" style="width:40%;">${escHtml(label)}</th>
        <td class="small">${value || ""}${hint ? ` <span class="text-muted">— ${escHtml(hint)}</span>` : ""}</td>
      </tr>`;
    }

    function folderRow(label, info) {
      if (!info) return row(label, "—");
      const badge = (!info.exists) ? errBadge("Missing")
                   : (!info.writable) ? warnBadge("Read-only")
                   : okBadge("OK");
      return row(label, `${badge} <span class="text-muted small">${escHtml(info.path || "")}</span>
        <div class="small text-muted">${escHtml((info.freeGb ?? "—") + " GB free of " + (info.totalGb ?? "—") + " GB")}</div>`);
    }

    function okBadge(t)   { return `<span class="badge bg-success-subtle text-success border"><i class="bi bi-check-circle me-1"></i>${escHtml(t)}</span>`; }
    function warnBadge(t) { return `<span class="badge bg-warning-subtle text-warning border"><i class="bi bi-exclamation-triangle me-1"></i>${escHtml(t)}</span>`; }
    function errBadge(t)  { return `<span class="badge bg-danger-subtle text-danger border"><i class="bi bi-x-circle me-1"></i>${escHtml(t)}</span>`; }
    function healthBadge(t) {
      const v = (t || "down").toLowerCase();
      if (v === "ok") return okBadge("OK");
      if (v === "degraded") return warnBadge("Degraded");
      return errBadge("Down");
    }

    function formatDate(iso) {
      const f = (window.AppFormat && window.AppFormat.ist) || (s => s || "");
      return f(iso);
    }
    function escHtml(s) {
      return String(s == null ? "" : s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }
  }
})();
