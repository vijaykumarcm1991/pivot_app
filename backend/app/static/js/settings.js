/**
 * settings.js — Application Settings page controller (Phase 8).
 *
 * - Loads the current settings from /api/settings
 * - Saves on submit (POST /api/settings)
 * - Shows a "last saved" timestamp and inline alerts
 *
 * The SMTP block on this page is read-only — editing is on /email/settings.
 */
(function () {
  "use strict";
  try { main(); } catch (err) { console.error("[settings] init error:", err); }

  function main() {
    const $ = (id) => document.getElementById(id);

    const applicationNameEl = $("applicationName");
    const companyNameEl     = $("companyName");
    const timezoneEl        = $("timezone");
    const maxUploadMbEl     = $("maxUploadMb");
    const defaultExportDirEl= $("defaultExportDir");
    const saveBtn           = $("saveBtn");
    const resetBtn          = $("resetBtn");
    const lastSavedAtEl     = $("lastSavedAt");
    const alertArea         = $("alertArea");
    const form              = $("settingsForm");

    load();

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      await save();
    });
    resetBtn.addEventListener("click", async () => {
      if (confirm("Discard unsaved changes and reload from the server?")) {
        load();
      }
    });

    async function load() {
      try {
        const res = await fetch("/api/settings");
        if (!res.ok) throw new Error("Failed to load settings.");
        const s = await res.json();
        applicationNameEl.value  = s.applicationName || "";
        companyNameEl.value      = s.companyName || "";
        timezoneEl.value         = s.timezone || "UTC";
        maxUploadMbEl.value      = Math.round((s.maxUploadBytes || 0) / (1024 * 1024));
        defaultExportDirEl.value = s.defaultExportDir || "";
        lastSavedAtEl.textContent = s.updatedAt
          ? `Last saved: ${formatDate(s.updatedAt)}`
          : "Not saved yet";
      } catch (err) {
        showAlert("danger", "Could not load settings: " + err.message);
      }
    }

    async function save() {
      saveBtn.disabled = true;
      const originalHtml = saveBtn.innerHTML;
      saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Saving…';
      try {
        const body = {
          applicationName: (applicationNameEl.value || "").trim(),
          companyName:     (companyNameEl.value || "").trim(),
          timezone:        (timezoneEl.value || "UTC").trim(),
          maxUploadBytes:  parseInt(maxUploadMbEl.value, 10) * 1024 * 1024,
          defaultExportDir:(defaultExportDirEl.value || "").trim(),
        };
        const res = await fetch("/api/settings", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) throw new Error((data && data.detail) || "Save failed.");
        lastSavedAtEl.textContent = `Last saved: ${formatDate(data.updatedAt || new Date().toISOString())}`;
        showAlert("success", "Settings saved.");
        // Reload to reflect any server-side normalisation.
        await load();
      } catch (err) {
        showAlert("danger", "Save failed: " + err.message);
      } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = originalHtml;
      }
    }

    function showAlert(kind, message) {
      alertArea.innerHTML = `
        <div class="alert alert-${kind} alert-dismissible fade show" role="alert">
          ${escHtml(message)}
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>`;
    }

    // ── User Directory card ────────────────────────────────────────
    // Show the live status of the directory cache + a manual
    // reload button.  Kept in the same module because the user is
    // most likely to look at the settings page whenever they're
    // thinking about "who can I email".  The directory is backed
    // by two CSVs (Users.csv + DistributionLists.csv); the card
    // shows a separate count + size for each.
    const userDirStatusEl  = document.getElementById("userDirStatus");
    const userDirReloadBtn = document.getElementById("userDirReloadBtn");
    if (userDirStatusEl) {
      loadUserDirectoryStatus();
    }
    if (userDirReloadBtn) {
      userDirReloadBtn.addEventListener("click", async () => {
        userDirReloadBtn.disabled = true;
        const orig = userDirReloadBtn.innerHTML;
        userDirReloadBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Reloading…';
        try {
          const res = await fetch("/api/users/reload", { method: "POST" });
          const data = await res.json();
          if (!res.ok) throw new Error((data && data.detail) || "Reload failed.");
          showAlert(data.skipped ? "info" : "success", data.message || "Reloaded.");
          await loadUserDirectoryStatus();
        } catch (err) {
          showAlert("danger", "Reload failed: " + err.message);
        } finally {
          userDirReloadBtn.disabled = false;
          userDirReloadBtn.innerHTML = orig;
        }
      });
    }

    async function loadUserDirectoryStatus() {
      if (!userDirStatusEl) return;
      try {
        const res = await fetch("/api/users/status");
        if (!res.ok) throw new Error("Failed to load status.");
        const s = await res.json();
        renderUserDirectoryStatus(s);
      } catch (err) {
        userDirStatusEl.innerHTML = `<div class="alert alert-warning small mb-0">${escHtml(err.message)}</div>`;
      }
    }

    function formatBytes(n) {
      if (!n || n < 1024) return `${n || 0} B`;
      if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
      return `${(n / (1024 * 1024)).toFixed(2)} MB`;
    }

    function renderUserDirectoryStatus(s) {
      if (!userDirStatusEl) return;
      const totalEntries = (s.totalUsers || 0) + (s.totalDls || 0);
      if (totalEntries === 0) {
        userDirStatusEl.innerHTML = `
          <div class="alert alert-warning small mb-0">
            <i class="bi bi-exclamation-triangle me-1"></i>
            <strong>No directory data loaded.</strong>
            Drop <code>Users.csv</code> and/or <code>DistributionLists.csv</code>
            at the project root (or
            <code>${escHtml(s && s.usersPath ? s.usersPath : "/app/Users.csv")}</code>
            /
            <code>${escHtml(s && s.dlsPath ? s.dlsPath : "/app/DistributionLists.csv")}</code>
            in the container), then click <em>Reload now</em>.
          </div>`;
        return;
      }
      const lastRel = s.loadedAtIst
        ? (window.AppFormat ? window.AppFormat.ist(s.loadedAtIst) : s.loadedAtIst)
        : "—";
      userDirStatusEl.innerHTML = `
        <ul class="list-unstyled small mb-3">
          <li class="d-flex justify-content-between align-items-center">
            <span>
              <i class="bi bi-person me-1 text-primary"></i>
              <strong>Users</strong>
              <code class="ms-1" title="${escHtml(s.usersPath || "")}">${escHtml(shortPath(s.usersPath))}</code>
            </span>
            <span>
              <span class="badge bg-primary-subtle text-primary-emphasis">${(s.totalUsers || 0).toLocaleString()}</span>
              <span class="text-muted ms-1">(${formatBytes(s.usersFileSize)})</span>
            </span>
          </li>
          <li class="d-flex justify-content-between align-items-center">
            <span>
              <i class="bi bi-people-fill me-1 text-info"></i>
              <strong>Distribution lists</strong>
              <code class="ms-1" title="${escHtml(s.dlsPath || "")}">${escHtml(shortPath(s.dlsPath))}</code>
            </span>
            <span>
              <span class="badge bg-info-subtle text-info-emphasis">${(s.totalDls || 0).toLocaleString()}</span>
              <span class="text-muted ms-1">(${formatBytes(s.dlsFileSize)})</span>
            </span>
          </li>
          <li class="mt-2">
            <strong>Last loaded:</strong> ${escHtml(lastRel)}
          </li>
          ${s.lastError
            ? `<li class="mt-1 text-danger"><i class="bi bi-exclamation-triangle me-1"></i>${escHtml(s.lastError)}</li>`
            : ""}
        </ul>
        <p class="small text-muted mb-0">
          <i class="bi bi-info-circle me-1"></i>
          Type any part of a name, email or alias into the email
          composer's To / CC / BCC field and the typeahead will show
          matching individuals and groups.
        </p>`;
    }

    // Show just the filename when the path is the default container
    // mount — the long /app/... path is noise on the Settings page.
    function shortPath(p) {
      if (!p) return "—";
      if (p.startsWith("/app/")) return p.slice(5);
      return p;
    }

    function escHtml(s) {
      return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function formatDate(iso) {
      const f = (window.AppFormat && window.AppFormat.ist) || (s => s || "");
      return f(iso);
    }
  }
})();
