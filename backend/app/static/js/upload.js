/**
 * upload.js — handles file selection, drag-and-drop, and upload submission.
 */

(function () {
  "use strict";

  const dropZone   = document.getElementById("dropZone");
  const fileInput  = document.getElementById("fileInput");
  const fileInfo   = document.getElementById("fileInfo");
  const fileName   = document.getElementById("fileName");
  const errorAlert = document.getElementById("errorAlert");
  const uploadBtn  = document.getElementById("uploadBtn");
  const btnText    = document.getElementById("btnText");
  const btnSpinner = document.getElementById("btnSpinner");
  const uploadForm = document.getElementById("uploadForm");

  let selectedFile = null;

  // ── Click on drop zone opens file picker ──────────────────────────────────
  dropZone.addEventListener("click", () => fileInput.click());

  // ── Drag & Drop events ────────────────────────────────────────────────────
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  ["dragleave", "dragend"].forEach((evt) =>
    dropZone.addEventListener(evt, () => dropZone.classList.remove("dragover"))
  );

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file) setFile(file);
  });

  // ── File input change ─────────────────────────────────────────────────────
  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) setFile(fileInput.files[0]);
  });

  // ── Set selected file and update UI ──────────────────────────────────────
  function setFile(file) {
    hideError();
    const allowed = [".xlsx", ".csv"];
    const ext = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();

    if (!allowed.includes(ext)) {
      showError("Unsupported file type. Please upload a .xlsx or .csv file.");
      return;
    }

    selectedFile = file;
    fileName.textContent = file.name;
    fileInfo.classList.remove("d-none");
    uploadBtn.disabled = false;
  }

  // ── Form submit → POST /api/upload ────────────────────────────────────────
  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!selectedFile) return;

    setLoading(true);
    hideError();

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      const res = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        showError(data.detail || "Upload failed. Please try again.");
        return;
      }

      // Redirect to preview page on success
      window.location.href = `/preview/${data.dataset_id}`;

    } catch (err) {
      showError("Network error. Please check your connection and try again.");
    } finally {
      setLoading(false);
    }
  });

  // ── Helpers ───────────────────────────────────────────────────────────────
  function setLoading(loading) {
    uploadBtn.disabled = loading;
    btnText.classList.toggle("d-none", loading);
    btnSpinner.classList.toggle("d-none", !loading);
  }

  function showError(message) {
    errorAlert.textContent = message;
    errorAlert.classList.remove("d-none");
  }

  function hideError() {
    errorAlert.classList.add("d-none");
    errorAlert.textContent = "";
  }
})();
