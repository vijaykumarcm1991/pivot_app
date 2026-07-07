/**
 * upload.js — file selection, drag-and-drop, and upload submission.
 *
 * Phase 8 enhancements:
 *   - client-side size check (against /api/settings)
 *   - full-card loading overlay
 *   - better error display (multi-line friendly messages)
 */
(function () {
  "use strict";

  const dropZone   = document.getElementById("dropZone");
  const fileInput  = document.getElementById("fileInput");
  const fileInfo   = document.getElementById("fileInfo");
  const fileName   = document.getElementById("fileName");
  const fileSize   = document.getElementById("fileSize");
  const errorAlert = document.getElementById("errorAlert");
  const uploadBtn  = document.getElementById("uploadBtn");
  const btnText    = document.getElementById("btnText");
  const btnSpinner = document.getElementById("btnSpinner");
  const uploadForm = document.getElementById("uploadForm");
  const overlay    = document.getElementById("uploadLoadingOverlay");
  const overlayTxt = document.getElementById("uploadLoadingText");
  const maxLabel   = document.getElementById("maxUploadLabel");

  let selectedFile = null;
  let maxUploadBytes = 50 * 1024 * 1024;

  // ── Load configured max upload size ──────────────────────────────────
  fetch("/api/settings").then(r => r.json()).then(s => {
    if (s && s.maxUploadBytes) {
      maxUploadBytes = s.maxUploadBytes;
      maxLabel.textContent = formatBytes(s.maxUploadBytes);
    }
  }).catch(() => {});

  // ── Click on drop zone opens file picker ─────────────────────────────
  dropZone.addEventListener("click", () => fileInput.click());

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

  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) setFile(fileInput.files[0]);
  });

  function setFile(file) {
    hideError();
    const allowed = [".xlsx", ".csv"];
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    if (!allowed.includes("." + ext)) {
      showError("Unsupported file type. Please upload a .xlsx or .csv file.");
      return;
    }
    if (file.size > maxUploadBytes) {
      showError(`File is too large (${formatBytes(file.size)}). ` +
                `Maximum allowed is ${formatBytes(maxUploadBytes)}.`);
      return;
    }
    selectedFile = file;
    fileName.textContent = file.name;
    fileSize.textContent = `(${formatBytes(file.size)})`;
    fileInfo.classList.remove("d-none");
    uploadBtn.disabled = false;
  }

  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!selectedFile) return;
    setLoading(true);
    hideError();
    const formData = new FormData();
    formData.append("file", selectedFile);
    try {
      const res = await fetch("/api/upload", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) {
        showError(data.detail || "Upload failed. Please try again.");
        return;
      }
      window.location.href = `/preview/${data.dataset_id}`;
    } catch (err) {
      showError("Network error. Please check your connection and try again.");
    } finally {
      setLoading(false);
    }
  });

  function setLoading(loading) {
    uploadBtn.disabled = loading;
    btnText.classList.toggle("d-none", loading);
    btnSpinner.classList.toggle("d-none", !loading);
    overlay.classList.toggle("d-none", !loading);
    if (loading) {
      overlayTxt.textContent = "Uploading & analysing…";
    }
  }

  function showError(message) {
    errorAlert.textContent = message;
    errorAlert.classList.remove("d-none");
  }
  function hideError() {
    errorAlert.classList.add("d-none");
    errorAlert.textContent = "";
  }
  function formatBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
    return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }
})();
