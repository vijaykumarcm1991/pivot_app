/**
 * cleanup.js — Admin cleanup page controller.
 */
(function () {
  "use strict";
  try { main(); } catch (err) { console.error("[cleanup] init error:", err); }

  function main() {
    const $ = (id) => document.getElementById(id);
    const cardsEl      = $("cleanupCards");
    const runCard      = $("runCard");
    const selectedKeys = new Set();
    const selectedSum  = $("selectedSummary");
    const selectedBytes= $("selectedBytes");
    const olderEl      = $("olderThanDays");
    const refreshBtn   = $("refreshBtn");
    const runBtn       = $("runBtn");
    const clearBtn     = $("clearSelectionBtn");
    const confirmBtn   = $("confirmRunBtn");

    olderEl.addEventListener("change", load);
    refreshBtn.addEventListener("click", load);
    clearBtn.addEventListener("click", () => {
      selectedKeys.clear();
      update();
    });
    runBtn.addEventListener("click", showConfirm);
    confirmBtn.addEventListener("click", runCleanup);

    load();

    async function load() {
      cardsEl.innerHTML = `<div class="col-12 text-muted py-3">
        <span class="spinner-border spinner-border-sm me-2"></span>Loading…
      </div>`;
      const days = Math.max(0, parseInt(olderEl.value, 10) || 7);
      try {
        const res = await fetch(`/api/admin/cleanup/preview?older_than_days=${days}`);
        const data = await res.json();
        if (!res.ok) throw new Error("Failed to load cleanup preview.");
        render(data.targets || []);
      } catch (err) {
        cardsEl.innerHTML = `<div class="col-12"><div class="alert alert-danger">${escHtml(err.message)}</div></div>`;
      }
    }

    function render(targets) {
      if (!targets.length) {
        cardsEl.innerHTML = `<div class="col-12 text-muted py-3">Nothing to clean.</div>`;
        runCard.classList.add("d-none");
        return;
      }
      cardsEl.innerHTML = targets.map(t => `
        <div class="col-md-6 col-xl-4">
          <div class="card border-0 shadow-sm h-100">
            <div class="card-body">
              <div class="form-check mb-2">
                <input class="form-check-input" type="checkbox" id="ck-${escAttr(t.key)}" data-key="${escAttr(t.key)}" ${t.fileCount === 0 ? "disabled" : ""} ${selectedKeys.has(t.key) ? "checked" : ""}>
                <label class="form-check-label fw-semibold" for="ck-${escAttr(t.key)}">${escHtml(t.label)}</label>
              </div>
              <p class="small text-muted mb-2">${escHtml(t.description)}</p>
              <div class="d-flex align-items-center gap-2">
                <span class="badge bg-body-tertiary border text-body">${t.fileCount} file(s)</span>
                <span class="badge bg-body-tertiary border text-body">${t.totalMb} MB</span>
                ${t.fileCount === 0 ? '<span class="badge bg-success-subtle text-success border">empty</span>' : ""}
              </div>
            </div>
          </div>
        </div>
      `).join("");
      cardsEl.querySelectorAll("input[type=checkbox][data-key]").forEach(cb => {
        cb.addEventListener("change", () => {
          if (cb.checked) selectedKeys.add(cb.dataset.key);
          else selectedKeys.delete(cb.dataset.key);
          update();
        });
      });
      update();
    }

    function update() {
      const days = Math.max(0, parseInt(olderEl.value, 10) || 7);
      const all  = Array.from(cardsEl.querySelectorAll("input[type=checkbox][data-key]"));
      let totalFiles = 0, totalBytes = 0;
      selectedKeys.forEach(k => {
        const cb = all.find(c => c.dataset.key === k);
        if (!cb) return;
        const card = cb.closest(".card");
        const txt = card ? card.textContent : "";
        // Best-effort: re-derive from rendered text (we don't have the JSON)
        const fileMatch = txt.match(/(\d+)\s*file/);
        const mbMatch   = txt.match(/([\d.]+)\s*MB/);
        if (fileMatch) totalFiles += parseInt(fileMatch[1], 10) || 0;
        if (mbMatch)   totalBytes += (parseFloat(mbMatch[1]) || 0) * 1024 * 1024;
      });
      selectedSum.textContent  = `${totalFiles} file(s) selected`;
      selectedBytes.textContent= `${(totalBytes / 1024 / 1024).toFixed(2)} MB`;
      runCard.classList.toggle("d-none", selectedKeys.size === 0);
    }

    function showConfirm() {
      const listEl = $("confirmList");
      const items = Array.from(selectedKeys).map(k => `<li>${escHtml(prettyKey(k))}</li>`).join("");
      listEl.innerHTML = items || "<li>(nothing selected)</li>";
      const modal = bootstrap.Modal.getOrCreateInstance($("confirmModal"));
      modal.show();
    }

    async function runCleanup() {
      const days = Math.max(0, parseInt(olderEl.value, 10) || 7);
      const keys = Array.from(selectedKeys);
      const modal = bootstrap.Modal.getOrCreateInstance($("confirmModal"));
      modal.hide();
      confirmBtn.disabled = true;
      const originalHtml = confirmBtn.innerHTML;
      confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Cleaning…';
      try {
        const res = await fetch("/api/admin/cleanup/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ keys, olderThanDays: days }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error("Cleanup failed.");
        const freed = data.freedMb || 0;
        const files = Object.values(data.deleted || {}).reduce((s, d) => s + (d.filesDeleted || 0), 0);
        showToast("success", `Cleanup complete. ${files} file(s) removed, ${freed} MB freed.`);
        selectedKeys.clear();
        load();
      } catch (err) {
        showToast("danger", "Cleanup failed: " + err.message);
      } finally {
        confirmBtn.disabled = false;
        confirmBtn.innerHTML = originalHtml;
      }
    }

    function prettyKey(k) {
      return ({
        temp_exports: "Temporary email previews",
        drilldown_files: "Temporary drill-down files",
        old_uploads: "Orphaned uploaded files",
        old_logs: "Old log files",
        cached_files: "Cached files",
      })[k] || k;
    }

    function showToast(kind, message) {
      const area = document.createElement("div");
      area.className = `alert alert-${kind} position-fixed top-0 start-50 translate-middle-x mt-3 shadow`;
      area.style.zIndex = "2000";
      area.textContent = message;
      document.body.appendChild(area);
      setTimeout(() => area.remove(), 4000);
    }

    function escHtml(s) {
      return String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }
    function escAttr(s) { return escHtml(s); }
  }
})();
