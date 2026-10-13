/**
 * ui.js — small shared UI helpers for every page.
 *
 *   AppUI.toast(message, { type: "success" | "error" | "warning" | "info", timeout })
 *   AppUI.confirm({ title, body, confirmText, danger }) → Promise<boolean>
 *   AppUI.fetchJSON(url, options) → Promise<data>  (throws Error(detail) on !ok,
 *       and copes with non-JSON error pages such as nginx's 413)
 *   AppUI.escape(str)
 *
 * Also wires the app-shell sidebar (mobile drawer + desktop collapse).
 */
(function () {
  "use strict";

  function escape(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // ── Toasts ──────────────────────────────────────────────────────────
  const ICONS = {
    success: "bi-check-circle-fill",
    error:   "bi-x-octagon-fill",
    warning: "bi-exclamation-triangle-fill",
    info:    "bi-info-circle-fill",
  };

  function toast(message, opts) {
    const o = Object.assign({ type: "info", timeout: 4500 }, opts || {});
    const stack = document.getElementById("toastStack");
    if (!stack) { console.log(message); return; }
    const el = document.createElement("div");
    el.className = `app-toast app-toast-${o.type}`;
    el.setAttribute("role", o.type === "error" ? "alert" : "status");
    el.innerHTML = `
      <i class="bi ${ICONS[o.type] || ICONS.info}"></i>
      <div class="app-toast-body">${escape(message)}</div>
      <button type="button" class="app-toast-close" aria-label="Dismiss"><i class="bi bi-x"></i></button>`;
    const remove = () => {
      el.classList.add("leaving");
      setTimeout(() => el.remove(), 180);
    };
    el.querySelector(".app-toast-close").addEventListener("click", remove);
    stack.appendChild(el);
    if (o.timeout > 0) setTimeout(remove, o.timeout);
    return el;
  }

  // ── Confirm dialog (Bootstrap modal, built on demand) ───────────────
  let confirmEl = null;
  function confirmDialog(opts) {
    const o = Object.assign({
      title: "Are you sure?", body: "", confirmText: "Confirm", danger: false,
    }, opts || {});
    if (!window.bootstrap) return Promise.resolve(window.confirm(o.body || o.title));
    if (!confirmEl) {
      confirmEl = document.createElement("div");
      confirmEl.className = "modal fade";
      confirmEl.tabIndex = -1;
      confirmEl.innerHTML = `
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header border-0 pb-0">
              <h5 class="modal-title" data-confirm-title></h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body text-secondary-emphasis" data-confirm-body></div>
            <div class="modal-footer border-0 pt-0">
              <button type="button" class="btn btn-light" data-bs-dismiss="modal">Cancel</button>
              <button type="button" class="btn" data-confirm-ok></button>
            </div>
          </div>
        </div>`;
      document.body.appendChild(confirmEl);
    }
    confirmEl.querySelector("[data-confirm-title]").textContent = o.title;
    confirmEl.querySelector("[data-confirm-body]").textContent = o.body;
    const ok = confirmEl.querySelector("[data-confirm-ok]");
    ok.textContent = o.confirmText;
    ok.className = "btn " + (o.danger ? "btn-danger" : "btn-primary");

    const modal = bootstrap.Modal.getOrCreateInstance(confirmEl);
    return new Promise(resolve => {
      let result = false;
      const onOk = () => { result = true; modal.hide(); };
      const onHidden = () => {
        ok.removeEventListener("click", onOk);
        confirmEl.removeEventListener("hidden.bs.modal", onHidden);
        resolve(result);
      };
      ok.addEventListener("click", onOk);
      confirmEl.addEventListener("hidden.bs.modal", onHidden);
      modal.show();
    });
  }

  // ── fetch helper ────────────────────────────────────────────────────
  async function fetchJSON(url, options) {
    const res = await fetch(url, options);
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (_) { data = null; }
    if (!res.ok) {
      let detail = data && (data.detail || data.message);
      if (Array.isArray(detail)) detail = detail.map(d => d.msg || JSON.stringify(d)).join("; ");
      if (!detail) {
        detail = res.status === 413
          ? "The file is larger than the server accepts."
          : `Request failed (HTTP ${res.status}).`;
      }
      const err = new Error(detail);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  // ── Sidebar ─────────────────────────────────────────────────────────
  function wireSidebar() {
    const root = document.documentElement;
    document.querySelectorAll("[data-sidebar-open]").forEach(b =>
      b.addEventListener("click", () => root.classList.add("sidebar-open")));
    document.querySelectorAll("[data-sidebar-close]").forEach(b =>
      b.addEventListener("click", () => root.classList.remove("sidebar-open")));
    document.addEventListener("keydown", e => {
      if (e.key === "Escape") root.classList.remove("sidebar-open");
    });
    document.querySelectorAll("[data-sidebar-collapse]").forEach(b =>
      b.addEventListener("click", () => {
        const collapsed = root.classList.toggle("sidebar-collapsed");
        try { localStorage.setItem("pivot-sidebar", collapsed ? "collapsed" : "open"); } catch (_) {}
        // Let grids re-measure their width after the transition.
        setTimeout(() => window.dispatchEvent(new Event("resize")), 220);
      }));
  }

  window.AppUI = { toast, confirm: confirmDialog, fetchJSON, escape };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireSidebar);
  } else {
    wireSidebar();
  }
})();
