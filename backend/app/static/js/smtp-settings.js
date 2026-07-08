/**
 * smtp-settings.js — SMTP configuration page controller (Phase 6).
 *
 * Renders the SMTP settings form at /email/settings:
 *   - Loads the current settings on page load
 *   - Saves on submit (POST /api/email/smtp-settings)
 *   - Sends a one-off test email (POST /api/email/test)
 *
 * The password field is always empty in the form (the server never
 * returns the password; it returns `password_set: true/false` so we
 * can show a hint). Leaving the field empty on save means "keep the
 * existing password" — the server handles that case.
 */
(function () {
  "use strict";

  // Wrap in try/catch so a missing Bootstrap doesn't break the page.
  try {
    main();
  } catch (err) {
    console.error("[smtp-settings] init error:", err);
  }

  function main() {
    const $ = (id) => document.getElementById(id);

    const hostEl       = $("smtpHost");
    const portEl       = $("smtpPort");
    const usernameEl   = $("smtpUsername");
    const passwordEl   = $("smtpPassword");
    const useTlsEl     = $("smtpUseTls");
    const senderNameEl = $("smtpSenderName");
    const senderEmailEl= $("smtpSenderEmail");
    const passwordHint = $("passwordHint");
    const saveBtn      = $("saveBtn");
    const testBtn      = $("testBtn");
    const testInlineBtn= $("sendTestInlineBtn");
    const testRecipientEl = $("testRecipient");
    const lastSavedAtEl = $("lastSavedAt");
    const alertArea    = $("alertArea");
    const form         = $("smtpForm");

    // ── Load on page entry ──────────────────────────────────────────
    loadSettings();

    // ── Form submit ─────────────────────────────────────────────────
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      await saveSettings();
    });

    // ── Test buttons ───────────────────────────────────────────────
    testBtn.addEventListener("click", async () => {
      const recipient = (senderEmailEl.value || "").trim();
      if (!recipient) {
        showAlert("warning", "Enter a sender email first, then click Send Test Email.");
        return;
      }
      await sendTest(recipient);
    });
    testInlineBtn.addEventListener("click", async () => {
      const recipient = (testRecipientEl.value || "").trim();
      if (!recipient) {
        showAlert("warning", "Enter a recipient address.");
        return;
      }
      await sendTest(recipient);
    });

    // ── Helpers ─────────────────────────────────────────────────────
    async function loadSettings() {
      try {
        const res = await fetch("/api/email/smtp-settings");
        if (!res.ok) throw new Error("Failed to load SMTP settings.");
        const s = await res.json();
        hostEl.value        = s.host || "";
        portEl.value        = s.port || 587;
        usernameEl.value    = s.username || "";
        useTlsEl.checked    = !!s.useTls;
        senderNameEl.value  = s.senderName || "";
        senderEmailEl.value = s.senderEmail || "";
        if (s.passwordSet) {
          passwordHint.style.display = "";
          passwordEl.placeholder = "•••••••• (saved)";
        } else {
          passwordHint.style.display = "none";
          passwordEl.placeholder = "Password";
        }
        if (s.updatedAt) {
          lastSavedAtEl.textContent = `Last saved: ${formatDate(s.updatedAt)}`;
        } else {
          lastSavedAtEl.textContent = "Not saved yet";
        }
      } catch (err) {
        showAlert("danger", "Could not load SMTP settings: " + err.message);
      }
    }

    async function saveSettings() {
      saveBtn.disabled = true;
      saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Saving…';
      try {
        const body = {
          host:        (hostEl.value || "").trim(),
          port:        parseInt(portEl.value, 10) || 587,
          username:    (usernameEl.value || "").trim(),
          password:    passwordEl.value,  // empty = keep existing
          useTls:      useTlsEl.checked,
          senderName:  (senderNameEl.value || "").trim(),
          senderEmail: (senderEmailEl.value || "").trim(),
        };
        const res = await fetch("/api/email/smtp-settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error((data && data.detail) || "Save failed.");
        }
        // Clear the password field so the placeholder reappears
        passwordEl.value = "";
        if (data.passwordSet) {
          passwordHint.style.display = "";
          passwordEl.placeholder = "•••••••• (saved)";
        }
        lastSavedAtEl.textContent = `Last saved: ${formatDate(data.updatedAt || new Date().toISOString())}`;
        showAlert("success", "SMTP settings saved.");
      } catch (err) {
        showAlert("danger", "Save failed: " + err.message);
      } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="bi bi-save me-1"></i>Save Settings';
      }
    }

    async function sendTest(recipient) {
      testBtn.disabled = true;
      testInlineBtn.disabled = true;
      testBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Sending…';
      try {
        const res = await fetch("/api/email/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ to: recipient }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error((data && data.detail) || "Test send failed.");
        }
        showAlert("success", `Test email sent to ${data.sent_to}.`);
      } catch (err) {
        showAlert("danger", "Test send failed: " + err.message);
      } finally {
        testBtn.disabled = false;
        testInlineBtn.disabled = false;
        testBtn.innerHTML = '<i class="bi bi-send me-1"></i>Send Test Email';
      }
    }

    function showAlert(kind, message) {
      alertArea.innerHTML = `
        <div class="alert alert-${kind} alert-dismissible fade show" role="alert">
          ${escHtml(message)}
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
      `;
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
      if (!iso) return "—";
      const f = (window.AppFormat && window.AppFormat.ist) || (s => s || "");
      return f(iso);
    }
  }
})();
