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

    function escHtml(s) {
      return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function formatDate(iso) {
      try { return new Date(iso).toLocaleString(); } catch (_) { return iso; }
    }
  }
})();
