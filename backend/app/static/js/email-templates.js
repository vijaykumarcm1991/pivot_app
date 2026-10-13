/**
 * email-templates.js — template picker in the email composer (#7).
 *
 * Choosing a template fills Subject / Message and any recipients the
 * template has. "Save as template" stores the current form. Placeholders
 * ({date}, {dataset}, …) are rendered by the server at preview / send.
 */
(function () {
  "use strict";

  const modal   = document.getElementById("emailModal");
  const select  = document.getElementById("emailTemplateSelect");
  const saveBtn = document.getElementById("emailTemplateSaveBtn");
  const delBtn  = document.getElementById("emailTemplateDeleteBtn");
  if (!modal || !select) return;

  const field = id => document.getElementById(id);
  let templates = [];

  async function load(selectId) {
    try {
      templates = await window.AppUI.fetchJSON("/api/email/templates");
    } catch (err) {
      templates = [];
    }
    const current = selectId != null ? String(selectId) : select.value;
    select.innerHTML = '<option value="">— none —</option>' + templates
      .map(t => `<option value="${t.id}">${window.AppUI.escape(t.name)}</option>`).join("");
    if (templates.some(t => String(t.id) === current)) select.value = current;
    delBtn.disabled = !select.value;
  }

  function apply(t) {
    field("emailSubject").value = t.subject || "";
    field("emailMessage").value = t.message || "";
    // Only overwrite recipient fields the template actually sets.
    if (t.to)  field("emailTo").value  = t.to;
    if (t.cc)  field("emailCc").value  = t.cc;
    if (t.bcc) field("emailBcc").value = t.bcc;
  }

  select.addEventListener("change", () => {
    delBtn.disabled = !select.value;
    const t = templates.find(x => String(x.id) === select.value);
    if (t) apply(t);
  });

  saveBtn.addEventListener("click", async () => {
    const existing = templates.find(x => String(x.id) === select.value);
    const name = await window.AppUI.prompt({
      title: "Save as template", label: "Template name",
      value: existing ? existing.name : "", placeholder: "e.g. Daily ops alerts",
    });
    if (!name) return;
    const body = {
      name: name.trim(),
      subject: field("emailSubject").value,
      message: field("emailMessage").value,
      to: field("emailTo").value,
      cc: field("emailCc").value,
      bcc: field("emailBcc").value,
    };
    const same = templates.find(x => x.name.toLowerCase() === body.name.toLowerCase());
    try {
      if (same) {
        const ok = await window.AppUI.confirm({
          title: "Overwrite template?",
          body: `“${same.name}” will be replaced with the current subject, message and recipients.`,
          confirmText: "Overwrite",
        });
        if (!ok) return;
      }
      const saved = await window.AppUI.fetchJSON(
        same ? `/api/email/templates/${same.id}` : "/api/email/templates",
        { method: same ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      await load(saved.id);
      window.AppUI.toast(`Template “${saved.name}” saved.`, { type: "success" });
    } catch (err) {
      window.AppUI.toast(`Could not save template: ${err.message}`, { type: "error" });
    }
  });

  delBtn.addEventListener("click", async () => {
    const t = templates.find(x => String(x.id) === select.value);
    if (!t) return;
    const ok = await window.AppUI.confirm({
      title: "Delete template?", body: `“${t.name}” will be deleted.`, confirmText: "Delete", danger: true,
    });
    if (!ok) return;
    try {
      await window.AppUI.fetchJSON(`/api/email/templates/${t.id}`, { method: "DELETE" });
      await load("");
      window.AppUI.toast("Template deleted.", { type: "success" });
    } catch (err) {
      window.AppUI.toast(`Could not delete template: ${err.message}`, { type: "error" });
    }
  });

  modal.addEventListener("show.bs.modal", () => load());
  window.EmailTemplates = { reload: load, list: () => templates.slice() };
})();
