/**
 * preview-manager.js — Email preview rendering (Phase 6).
 *
 * Owns the right-hand side of the Email Composer modal — the
 * rendered HTML preview + the attachment download button. The
 * preview HTML is built server-side by `email_service.build_email_html`
 * (so the HTML is identical to what the recipient will see); this
 * module just renders it inside the modal and exposes the
 * download link.
 *
 * Public API on `window.PreviewManager`:
 *   setHtml(html, datasetName)
 *       — replace the preview body with the given HTML
 *   setAttachment(filename, downloadUrl)
 *       — show / update the attachment card
 *   setBusy(busy, message)
 *       — show a spinner + "Building preview…" while the server
 *         is generating the attachment
 *   clear()
 *       — reset to the initial "click Preview" state
 */
(function () {
  "use strict";

  let bodyEl    = null;
  let attachEl  = null;
  let busyEl    = null;
  let initialEl = null;
  let linkEl    = null;

  function init() {
    if (init._done) return;
    init._done = true;
    bodyEl    = document.getElementById("ddPreviewBody");
    attachEl  = document.getElementById("ddPreviewAttachment");
    busyEl    = document.getElementById("ddPreviewBusy");
    initialEl = document.getElementById("ddPreviewInitial");
    linkEl    = document.getElementById("ddPreviewAttachmentLink");
  }

  function setHtml(html, datasetName) {
    init();
    if (!bodyEl) return;
    // Render the HTML inside a sandboxed iframe to keep the email's
    // inline styles contained. We DO NOT trust the server's HTML
    // here (it's our own service, not user input), so this is
    // purely cosmetic — the iframe is just a layout container.
    if (window.DOMPurify && typeof window.DOMPurify.sanitize === "function") {
      // Defensive: if the user later loads DOMPurify, the preview
      // is sanitised. Not enabled by default in Version 1.
      html = window.DOMPurify.sanitize(html);
    }
    bodyEl.innerHTML = `
      <iframe id="ddPreviewFrame"
              class="email-preview-frame"
              title="Email preview"
              sandbox="allow-same-origin"
              srcdoc="${escAttr(html)}"></iframe>
    `;
    if (initialEl) initialEl.style.display = "none";
    if (busyEl)    busyEl.style.display    = "none";
    bodyEl.style.display = "";
  }

  function setAttachment(filename, downloadUrl) {
    init();
    if (!attachEl) return;
    if (filename && downloadUrl) {
      if (linkEl) {
        linkEl.href = downloadUrl;
        linkEl.setAttribute("download", filename);
        linkEl.textContent = filename;
      }
      attachEl.style.display = "";
    } else {
      attachEl.style.display = "none";
    }
  }

  function setBusy(busy, message) {
    init();
    if (busy) {
      if (initialEl) initialEl.style.display = "none";
      if (bodyEl)    bodyEl.style.display    = "none";
      if (attachEl)  attachEl.style.display  = "none";
      if (busyEl) {
        busyEl.style.display = "";
        const label = busyEl.querySelector("[data-busy-label]");
        if (label) label.textContent = message || "Building preview…";
      }
    } else {
      if (busyEl) busyEl.style.display = "none";
      // Do NOT touch bodyEl/attachEl/initialEl here — the caller
      // will set them.
    }
  }

  function clear() {
    init();
    if (bodyEl)    bodyEl.innerHTML = "", bodyEl.style.display = "none";
    if (attachEl)  attachEl.style.display = "none";
    if (busyEl)    busyEl.style.display = "none";
    if (initialEl) initialEl.style.display = "";
  }

  function escAttr(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;");
  }

  window.PreviewManager = {
    setHtml,
    setAttachment,
    setBusy,
    clear,
  };
})();
