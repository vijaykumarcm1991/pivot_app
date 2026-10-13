/**
 * dataset-actions.js — "Delete dataset" buttons on the Datasets and
 * Preview pages. Any element with `data-delete-dataset-id` (and an
 * optional `data-delete-dataset-name` / `data-after-delete` URL) opens a
 * confirm dialog and calls DELETE /api/dataset/{id}.
 */
(function () {
  "use strict";

  document.querySelectorAll("[data-delete-dataset-id]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-delete-dataset-id");
      const name = btn.getAttribute("data-delete-dataset-name") || "this dataset";
      const after = btn.getAttribute("data-after-delete");
      const ok = await window.AppUI.confirm({
        title: "Delete dataset?",
        body: `“${name}” will be removed together with its uploaded file, metadata and soft-deleted records. This cannot be undone.`,
        confirmText: "Delete dataset",
        danger: true,
      });
      if (!ok) return;
      btn.disabled = true;
      try {
        await window.AppUI.fetchJSON(`/api/dataset/${encodeURIComponent(id)}`, { method: "DELETE" });
        window.AppUI.toast(`Deleted “${name}”.`, { type: "success" });
        if (after) {
          setTimeout(() => { window.location.href = after; }, 500);
        } else {
          const row = btn.closest("tr");
          if (row) row.remove();
          else setTimeout(() => window.location.reload(), 500);
        }
      } catch (err) {
        btn.disabled = false;
        window.AppUI.toast(`Delete failed: ${err.message}`, { type: "error", timeout: 8000 });
      }
    });
  });
})();

/**
 * "Refresh data" — replace a dataset's file with a new export while
 * keeping the same dataset (saved pivots, schedules and deleted records
 * stay attached). Elements: data-refresh-dataset-id, data-refresh-dataset-name.
 */
(function () {
  "use strict";

  // Messages from a refresh that just reloaded this page.
  try {
    const raw = sessionStorage.getItem("pivot-refresh-result");
    if (raw) {
      sessionStorage.removeItem("pivot-refresh-result");
      const r = JSON.parse(raw);
      window.AppUI.toast(r.message, { type: "success" });
      (r.warnings || []).forEach(w => window.AppUI.toast(w, { type: "warning", timeout: 0 }));
    }
  } catch (_) { /* ignore */ }

  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".xlsx,.csv";
  input.className = "d-none";
  document.body.appendChild(input);
  let target = null;

  document.querySelectorAll("[data-refresh-dataset-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      target = btn;
      input.value = "";
      input.click();
    });
  });

  input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file || !target) return;
    const id = target.getAttribute("data-refresh-dataset-id");
    const name = target.getAttribute("data-refresh-dataset-name") || "this dataset";
    const ok = await window.AppUI.confirm({
      title: "Replace the data?",
      body: `“${name}” will use “${file.name}” from now on. Saved pivots, schedules and deleted records stay attached to the dataset; records you deleted before stay hidden if they appear in the new file.`,
      confirmText: "Replace data",
    });
    if (!ok) return;
    const original = target.innerHTML;
    target.disabled = true;
    target.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Uploading…';
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await window.AppUI.fetchJSON(`/api/dataset/${encodeURIComponent(id)}/refresh`, { method: "POST", body: form });
      // Show the result after the reload (so the page shows the new data).
      try {
        sessionStorage.setItem("pivot-refresh-result", JSON.stringify({
          message: `Data refreshed: ${res.totalRows.toLocaleString()} rows from “${res.filename}”.`,
          warnings: res.warnings || [],
        }));
      } catch (_) { /* storage unavailable — the reload still shows the data */ }
      window.location.reload();
    } catch (err) {
      window.AppUI.toast(`Refresh failed: ${err.message}`, { type: "error", timeout: 10000 });
      target.disabled = false;
      target.innerHTML = original;
    }
  });
})();
