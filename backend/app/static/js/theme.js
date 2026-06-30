/**
 * theme.js — Light / Dark / System theme switcher.
 *
 * - Reads preference from localStorage (key: "pivot-theme", default "system").
 * - Sets `data-bs-theme` on <html>; Bootstrap 5.3 uses it to drive its
 *   light/dark token set.
 * - Reacts to OS theme changes when the user is on "system".
 * - Exposes window.ThemeManager for the AG Grid code in pivot.js / manage.js
 *   so the grid can swap its CSS theme class without a full re-render.
 */
(function () {
  "use strict";

  const STORAGE_KEY = "pivot-theme";
  const VALID_MODES = ["system", "light", "dark"];

  function readStoredMode() {
    try {
      const m = localStorage.getItem(STORAGE_KEY);
      return VALID_MODES.includes(m) ? m : "system";
    } catch (_) {
      return "system";
    }
  }

  function systemPrefersDark() {
    return window.matchMedia &&
           window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function resolveTheme(mode) {
    if (mode === "system") return systemPrefersDark() ? "dark" : "light";
    return mode;
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-bs-theme", theme);
    // Notify listeners (e.g. AG Grid) so they can react.
    document.dispatchEvent(new CustomEvent("theme:changed", { detail: { theme } }));
  }

  function persistMode(mode) {
    try { localStorage.setItem(STORAGE_KEY, mode); } catch (_) { /* ignore */ }
  }

  function getStoredMode()    { return readStoredMode(); }
  function getCurrentTheme()  {
    return document.documentElement.getAttribute("data-bs-theme") || "light";
  }
  function setMode(mode) {
    if (!VALID_MODES.includes(mode)) return;
    persistMode(mode);
    applyTheme(resolveTheme(mode));
    syncToggleUI();
  }

  // ── Toggle dropdown UI ───────────────────────────────────────────────────
  function syncToggleUI() {
    const mode = readStoredMode();
    document.querySelectorAll("[data-theme-mode]").forEach(el => {
      const active = el.getAttribute("data-theme-mode") === mode;
      el.classList.toggle("active", active);
      el.setAttribute("aria-pressed", active ? "true" : "false");
    });
    const label = document.getElementById("themeModeLabel");
    if (label) label.textContent = mode.charAt(0).toUpperCase() + mode.slice(1);
    const icon = document.getElementById("themeModeIcon");
    if (icon) {
      const map = { system: "bi-circle-half", light: "bi-sun-fill", dark: "bi-moon-stars-fill" };
      icon.className = "bi " + (map[mode] || "bi-circle-half");
    }
  }

  function wireToggle() {
    document.querySelectorAll("[data-theme-mode]").forEach(el => {
      el.addEventListener("click", e => {
        e.preventDefault();
        setMode(el.getAttribute("data-theme-mode"));
      });
    });
  }

  // ── React to OS theme changes when user is on "system" ───────────────────
  function wireSystemListener() {
    if (!window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => { if (readStoredMode() === "system") applyTheme(resolveTheme("system")); };
    if (mq.addEventListener) mq.addEventListener("change", handler);
    else if (mq.addListener) mq.addListener(handler);
  }

  // ── Public API ───────────────────────────────────────────────────────────
  window.ThemeManager = {
    setMode, getStoredMode, getCurrentTheme, syncToggleUI, applyTheme,
  };

  // ── Init ─────────────────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    wireToggle();
    syncToggleUI();
    wireSystemListener();
  });
})();
