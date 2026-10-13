/**
 * saved-pivots.js — Save / Save as / Open saved pivot on the Pivot
 * Builder (#1). Uses window.PivotController from pivot.js.
 *
 *   ?saved=<id> in the URL opens that saved pivot and generates it.
 */
(function () {
  "use strict";

  const PC = () => window.PivotController;
  const saveBtn   = document.getElementById("savePivotBtn");
  const saveAsBtn = document.getElementById("saveAsPivotBtn");
  const openBtn   = document.getElementById("openSavedBtn");
  const tag       = document.getElementById("savedPivotTag");
  const tagName   = document.getElementById("savedPivotName");
  const modalEl   = document.getElementById("openSavedModal");
  const listEl    = document.getElementById("savedList");
  const searchEl  = document.getElementById("savedSearch");
  if (!saveBtn || !modalEl) return;

  const esc = s => window.AppUI.escape(s);
  let current = null;   // { id, name, datasetId } of the loaded saved pivot
  let all = [];

  function setCurrent(sp) {
    current = sp ? { id: sp.id, name: sp.name, datasetId: sp.datasetId } : null;
    tag.classList.toggle("d-none", !current);
    tagName.textContent = current ? current.name : "";
    saveBtn.querySelector("span").textContent = current ? "Save" : "Save…";
    saveBtn.title = current ? `Update “${current.name}”` : "Save this pivot configuration";
  }

  // Save needs a dataset + sheet. Choosing another dataset detaches the
  // loaded saved pivot (Save would otherwise overwrite it with an
  // unrelated configuration).
  document.addEventListener("pivot:source-changed", (e) => {
    const { datasetId, sheetName } = e.detail || {};
    saveBtn.disabled = !(datasetId && sheetName);
    if (current && String(datasetId) !== String(current.datasetId)) setCurrent(null);
  });

  async function saveAsNew() {
    const cfg = PC().getConfig();
    if (!cfg) return;
    const res = await window.AppUI.prompt({
      title: "Save pivot", label: "Name",
      value: current ? `${current.name} (copy)` : "",
      placeholder: "e.g. Daily disk-space alerts by unit",
      secondLabel: "Description (optional)",
      confirmText: "Save",
    });
    if (!res) return;
    try {
      const sp = await window.AppUI.fetchJSON("/api/saved-pivots", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: res.value, description: res.second || "", config: cfg }),
      });
      setCurrent(sp);
      window.AppUI.toast(`Saved “${sp.name}”.`, { type: "success" });
    } catch (err) {
      window.AppUI.toast(`Could not save: ${err.message}`, { type: "error", timeout: 7000 });
    }
  }

  async function saveCurrent() {
    if (!current) return saveAsNew();
    const cfg = PC().getConfig();
    if (!cfg) return;
    try {
      const sp = await window.AppUI.fetchJSON(`/api/saved-pivots/${current.id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: cfg }),
      });
      setCurrent(sp);
      window.AppUI.toast(`Updated “${sp.name}”.`, { type: "success" });
    } catch (err) {
      window.AppUI.toast(`Could not save: ${err.message}`, { type: "error", timeout: 7000 });
    }
  }

  async function openSaved(id) {
    try {
      const sp = await window.AppUI.fetchJSON(`/api/saved-pivots/${encodeURIComponent(id)}`);
      await PC().datasetsReady();
      const ok = await PC().applyConfig(sp.config);
      if (!ok) return;
      setCurrent(sp);
      const m = window.bootstrap && bootstrap.Modal.getInstance(modalEl);
      if (m) m.hide();
      await PC().compute();
    } catch (err) {
      window.AppUI.toast(`Could not open saved pivot: ${err.message}`, { type: "error", timeout: 7000 });
    }
  }

  function renderList() {
    const q = (searchEl.value || "").trim().toLowerCase();
    const items = all.filter(sp => !q || `${sp.name} ${sp.datasetName} ${sp.description}`.toLowerCase().includes(q));
    if (!items.length) {
      listEl.innerHTML = `<div class="empty-state py-4"><p class="mb-0">${all.length ? "No saved pivots match." : "No saved pivots yet. Configure a pivot and click <strong>Save</strong>."}</p></div>`;
      return;
    }
    listEl.innerHTML = items.map(sp => `
      <div class="list-group-item d-flex align-items-center gap-3">
        <div class="flex-grow-1 min-w-0">
          <div class="fw-semibold text-truncate">${esc(sp.name)}</div>
          <div class="small text-muted text-truncate">
            ${esc(sp.datasetName || "(dataset deleted)")} · ${esc(sp.sheetName)}
            ${sp.scheduleCount ? ` · <i class="bi bi-calendar-check"></i> ${sp.scheduleCount} schedule(s)` : ""}
            ${sp.description ? ` · ${esc(sp.description)}` : ""}
          </div>
        </div>
        <button class="btn btn-sm btn-primary" type="button" data-open="${sp.id}">Open</button>
      </div>`).join("");
    listEl.querySelectorAll("[data-open]").forEach(b =>
      b.addEventListener("click", () => openSaved(b.getAttribute("data-open"))));
  }

  async function showOpenDialog() {
    listEl.innerHTML = '<div class="text-muted small p-2"><span class="spinner-border spinner-border-sm me-2"></span>Loading…</div>';
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
    try {
      all = await window.AppUI.fetchJSON("/api/saved-pivots");
    } catch (err) {
      all = [];
      window.AppUI.toast(`Could not load saved pivots: ${err.message}`, { type: "error" });
    }
    renderList();
  }

  saveBtn.addEventListener("click", saveCurrent);
  saveAsBtn.addEventListener("click", saveAsNew);
  openBtn.addEventListener("click", showOpenDialog);
  searchEl.addEventListener("input", renderList);

  const savedParam = new URLSearchParams(window.location.search).get("saved");
  if (savedParam) {
    const start = () => (PC() ? openSaved(savedParam) : setTimeout(start, 100));
    start();
  }
})();
