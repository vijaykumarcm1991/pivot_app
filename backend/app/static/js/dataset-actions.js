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
