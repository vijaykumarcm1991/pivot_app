/**
 * reports.js — Scheduled reports page (#2): schedules + saved pivots.
 */
(function () {
  "use strict";

  const UI = window.AppUI;
  const esc = s => UI.escape(s);
  const $ = id => document.getElementById(id);
  const fmt = iso => (iso ? (window.AppFormat ? window.AppFormat.ist(iso) : iso) : "—");
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  let schedules = [];
  let saved = [];
  let templates = [];
  let editingId = null;

  const modalEl = $("scheduleModal");
  const modal = () => bootstrap.Modal.getOrCreateInstance(modalEl);

  // ── Load ──────────────────────────────────────────────────────────
  async function loadAll() {
    try {
      [schedules, saved, templates] = await Promise.all([
        UI.fetchJSON("/api/schedules"),
        UI.fetchJSON("/api/saved-pivots"),
        UI.fetchJSON("/api/email/templates"),
      ]);
    } catch (err) {
      UI.toast(`Could not load reports: ${err.message}`, { type: "error" });
      return;
    }
    if (schedules[0]) $("tzLabel").textContent = schedules[0].timezone;
    renderSchedules();
    renderSaved();
  }

  function describeWhen(s) {
    const t = s.runTime;
    if (s.frequency === "daily") return `Every day at ${t}`;
    if (s.frequency === "weekdays") return `Weekdays at ${t}`;
    if (s.frequency === "weekly") return `${s.weekdays.map(d => DAYS[d]).join(", ")} at ${t}`;
    return `Day ${s.dayOfMonth} of each month at ${t}`;
  }

  function statusBadge(s) {
    if (!s.lastStatus) return '<span class="text-muted small">Never</span>';
    const cls = { success: "bg-success", failed: "bg-danger", skipped: "bg-secondary" }[s.lastStatus] || "bg-secondary";
    const label = { success: "Sent", failed: "Failed", skipped: "Skipped" }[s.lastStatus] || s.lastStatus;
    const title = s.lastError ? ` title="${esc(s.lastError)}"` : "";
    return `<span class="badge ${cls}"${title}>${label}</span><div class="small text-muted">${esc(fmt(s.lastRunAtIst))}</div>`;
  }

  function renderSchedules() {
    $("scheduleCount").textContent = schedules.length;
    const body = $("scheduleRows");
    if (!schedules.length) {
      body.innerHTML = `<tr><td colspan="8"><div class="empty-state py-4">
        <div class="empty-icon"><i class="bi bi-calendar-check"></i></div>
        <h3>No schedules yet</h3>
        <p>${saved.length ? "Create one to email a saved pivot automatically." : "First save a pivot in the Pivot Builder, then schedule it here."}</p>
      </div></td></tr>`;
      return;
    }
    body.innerHTML = schedules.map(s => {
      const recips = [...s.to, ...s.cc, ...s.bcc];
      return `<tr>
        <td class="fw-semibold">${esc(s.name)}</td>
        <td><div>${esc(s.savedPivotName)}</div><div class="small text-muted">${esc(s.datasetName)}</div></td>
        <td class="small">${esc(describeWhen(s))}</td>
        <td class="small" title="${esc(recips.join(", "))}">${esc(recips[0] || "")}${recips.length > 1 ? ` <span class="text-muted">+${recips.length - 1}</span>` : ""}</td>
        <td class="small">${s.enabled ? esc(fmt(s.nextRunAtIst)) : '<span class="text-muted">Paused</span>'}</td>
        <td>${statusBadge(s)}</td>
        <td class="text-center">
          <div class="form-check form-switch d-inline-block mb-0">
            <input class="form-check-input" type="checkbox" role="switch" data-toggle="${s.id}" ${s.enabled ? "checked" : ""} aria-label="Enabled">
          </div>
        </td>
        <td class="text-end text-nowrap">
          <button class="btn btn-sm btn-outline-primary" data-run="${s.id}" title="Send now"><i class="bi bi-send"></i></button>
          <button class="btn btn-sm btn-outline-secondary" data-edit="${s.id}" title="Edit"><i class="bi bi-pencil"></i></button>
          <button class="btn btn-sm btn-outline-danger" data-del="${s.id}" title="Delete"><i class="bi bi-trash"></i></button>
        </td>
      </tr>`;
    }).join("");
    body.querySelectorAll("[data-run]").forEach(b => b.addEventListener("click", () => runNow(+b.dataset.run, b)));
    body.querySelectorAll("[data-edit]").forEach(b => b.addEventListener("click", () => openForm(schedules.find(s => s.id === +b.dataset.edit))));
    body.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", () => removeSchedule(+b.dataset.del)));
    body.querySelectorAll("[data-toggle]").forEach(cb => cb.addEventListener("change", () => toggle(+cb.dataset.toggle, cb.checked)));
  }

  function renderSaved() {
    $("savedCount").textContent = saved.length;
    const body = $("savedRows");
    if (!saved.length) {
      body.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">No saved pivots. In the Pivot Builder, configure a pivot and click <strong>Save</strong>.</td></tr>`;
      return;
    }
    body.innerHTML = saved.map(sp => `<tr>
      <td><div class="fw-semibold">${esc(sp.name)}</div>${sp.description ? `<div class="small text-muted">${esc(sp.description)}</div>` : ""}</td>
      <td class="small">${esc(sp.datasetName || "(dataset deleted)")}<div class="text-muted">${esc(sp.sheetName)}</div></td>
      <td class="small text-muted">${esc(fmt(sp.updatedAtIst))}</td>
      <td class="text-end tabular">${sp.scheduleCount}</td>
      <td class="text-end text-nowrap">
        <a class="btn btn-sm btn-outline-secondary" href="/pivot?saved=${sp.id}" title="Open in Pivot Builder"><i class="bi bi-box-arrow-up-right"></i></a>
        <button class="btn btn-sm btn-outline-primary" data-schedule="${sp.id}" title="Schedule"><i class="bi bi-calendar-plus"></i></button>
        <button class="btn btn-sm btn-outline-secondary" data-rename="${sp.id}" title="Rename"><i class="bi bi-pencil"></i></button>
        <button class="btn btn-sm btn-outline-danger" data-delsaved="${sp.id}" title="Delete"><i class="bi bi-trash"></i></button>
      </td>
    </tr>`).join("");
    body.querySelectorAll("[data-schedule]").forEach(b => b.addEventListener("click", () => openForm(null, +b.dataset.schedule)));
    body.querySelectorAll("[data-rename]").forEach(b => b.addEventListener("click", () => renameSaved(+b.dataset.rename)));
    body.querySelectorAll("[data-delsaved]").forEach(b => b.addEventListener("click", () => deleteSaved(+b.dataset.delsaved)));
  }

  // ── Schedule actions ──────────────────────────────────────────────
  async function runNow(id, btn) {
    const s = schedules.find(x => x.id === id);
    const ok = await UI.confirm({
      title: "Send now?", body: `“${s.name}” will be emailed to ${[...s.to, ...s.cc, ...s.bcc].length} recipient(s) right away.`,
      confirmText: "Send now",
    });
    if (!ok) return;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    try {
      const res = await UI.fetchJSON(`/api/schedules/${id}/run`, { method: "POST" });
      if (res.status === "success") UI.toast(`Sent “${s.name}” (${res.rowsSent} rows).`, { type: "success" });
      else if (res.status === "skipped") UI.toast(res.error || "Nothing to send.", { type: "warning" });
      else UI.toast(`Send failed: ${res.error}`, { type: "error", timeout: 10000 });
    } catch (err) {
      UI.toast(`Send failed: ${err.message}`, { type: "error", timeout: 10000 });
    }
    loadAll();
  }

  async function toggle(id, enabled) {
    const s = schedules.find(x => x.id === id);
    try {
      await UI.fetchJSON(`/api/schedules/${id}`, json("PUT", { ...toPayload(s), enabled }));
      UI.toast(enabled ? `“${s.name}” resumed.` : `“${s.name}” paused.`, { type: "success" });
    } catch (err) {
      UI.toast(err.message, { type: "error" });
    }
    loadAll();
  }

  async function removeSchedule(id) {
    const s = schedules.find(x => x.id === id);
    if (!await UI.confirm({ title: "Delete schedule?", body: `“${s.name}” will stop being sent.`, confirmText: "Delete", danger: true })) return;
    try {
      await UI.fetchJSON(`/api/schedules/${id}`, { method: "DELETE" });
      UI.toast("Schedule deleted.", { type: "success" });
    } catch (err) {
      UI.toast(err.message, { type: "error" });
    }
    loadAll();
  }

  // ── Saved pivot actions ───────────────────────────────────────────
  async function renameSaved(id) {
    const sp = saved.find(x => x.id === id);
    const res = await UI.prompt({
      title: "Rename saved pivot", label: "Name", value: sp.name,
      secondLabel: "Description (optional)", secondValue: sp.description, confirmText: "Save",
    });
    if (!res) return;
    try {
      await UI.fetchJSON(`/api/saved-pivots/${id}`, json("PUT", { name: res.value, description: res.second }));
      UI.toast("Saved pivot updated.", { type: "success" });
    } catch (err) {
      UI.toast(err.message, { type: "error" });
    }
    loadAll();
  }

  async function deleteSaved(id) {
    const sp = saved.find(x => x.id === id);
    const extra = sp.scheduleCount ? ` Its ${sp.scheduleCount} schedule(s) will be deleted too.` : "";
    if (!await UI.confirm({ title: "Delete saved pivot?", body: `“${sp.name}” will be deleted.${extra}`, confirmText: "Delete", danger: true })) return;
    try {
      await UI.fetchJSON(`/api/saved-pivots/${id}`, { method: "DELETE" });
      UI.toast("Saved pivot deleted.", { type: "success" });
    } catch (err) {
      UI.toast(err.message, { type: "error" });
    }
    loadAll();
  }

  // ── Form ──────────────────────────────────────────────────────────
  $("sWeekdays").innerHTML = DAYS.map((d, i) => `
    <input type="checkbox" class="btn-check" id="sDay${i}" value="${i}" autocomplete="off">
    <label class="btn btn-outline-secondary" for="sDay${i}">${d}</label>`).join("");

  function syncFrequency() {
    const f = $("sFrequency").value;
    $("sWeekdaysWrap").classList.toggle("d-none", f !== "weekly");
    $("sDayWrap").classList.toggle("d-none", f !== "monthly");
  }
  $("sFrequency").addEventListener("change", syncFrequency);

  $("sTemplate").addEventListener("change", () => {
    const t = templates.find(x => String(x.id) === $("sTemplate").value);
    if (!t) return;
    $("sSubject").value = t.subject || "";
    $("sMessage").value = t.message || "";
    if (t.to) $("sTo").value = t.to;
    if (t.cc) $("sCc").value = t.cc;
    if (t.bcc) $("sBcc").value = t.bcc;
  });

  function openForm(s, presetSavedId) {
    if (!saved.length) {
      UI.toast("Save a pivot in the Pivot Builder first, then schedule it here.", { type: "warning", timeout: 7000 });
      return;
    }
    editingId = s ? s.id : null;
    $("scheduleModalLabel").textContent = s ? "Edit schedule" : "New schedule";
    $("scheduleError").classList.add("d-none");
    $("sSaved").innerHTML = saved.map(sp =>
      `<option value="${sp.id}">${esc(sp.name)} — ${esc(sp.datasetName || "?")}</option>`).join("");
    $("sTemplate").innerHTML = '<option value="">— none —</option>' +
      templates.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join("");
    const preset = presetSavedId ? saved.find(x => x.id === presetSavedId) : null;

    $("sName").value = s ? s.name : (preset ? preset.name : "");
    $("sSaved").value = String(s ? s.savedPivotId : (presetSavedId || saved[0].id));
    $("sFrequency").value = s ? s.frequency : "weekdays";
    $("sTime").value = s ? s.runTime : "09:00";
    const days = s ? s.weekdays : [0];
    DAYS.forEach((_, i) => { $(`sDay${i}`).checked = days.includes(i); });
    $("sDay").value = s ? s.dayOfMonth : 1;
    $("sTo").value = s ? s.to.join(", ") : "";
    $("sCc").value = s ? s.cc.join(", ") : "";
    $("sBcc").value = s ? s.bcc.join(", ") : "";
    $("sSubject").value = s ? s.subject : "{dataset} — {date}";
    $("sMessage").value = s ? s.message : "Hello Team,\n\nPlease find today's report below.\n\nRegards,";
    $("sSkipEmpty").checked = s ? s.skipIfEmpty : true;
    $("sEnabled").checked = s ? s.enabled : true;
    syncFrequency();
    modal().show();
  }

  function toPayload(s) {
    return {
      name: s.name, savedPivotId: s.savedPivotId, frequency: s.frequency, runTime: s.runTime,
      weekdays: s.weekdays, dayOfMonth: s.dayOfMonth, to: s.to.join(", "), cc: s.cc.join(", "),
      bcc: s.bcc.join(", "), subject: s.subject, message: s.message, skipIfEmpty: s.skipIfEmpty,
      enabled: s.enabled,
    };
  }

  $("scheduleForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      name: $("sName").value,
      savedPivotId: +$("sSaved").value,
      frequency: $("sFrequency").value,
      runTime: $("sTime").value,
      weekdays: DAYS.map((_, i) => i).filter(i => $(`sDay${i}`).checked),
      dayOfMonth: +$("sDay").value,
      to: $("sTo").value, cc: $("sCc").value, bcc: $("sBcc").value,
      subject: $("sSubject").value, message: $("sMessage").value,
      skipIfEmpty: $("sSkipEmpty").checked, enabled: $("sEnabled").checked,
    };
    const btn = $("sSaveBtn");
    btn.disabled = true;
    try {
      await UI.fetchJSON(editingId ? `/api/schedules/${editingId}` : "/api/schedules",
                         json(editingId ? "PUT" : "POST", body));
      modal().hide();
      UI.toast("Schedule saved.", { type: "success" });
      loadAll();
    } catch (err) {
      const box = $("scheduleError");
      box.textContent = err.message;
      box.classList.remove("d-none");
    } finally {
      btn.disabled = false;
    }
  });

  $("newScheduleBtn").addEventListener("click", () => openForm(null));
  loadAll();
})();
