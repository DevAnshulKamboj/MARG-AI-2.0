(function () {
  "use strict";

  // ================= EDIT YOUR CONTENT HERE =================
  var FAQ_ITEMS = [
    { q: "How long will it take for prototype to be completed?", a: "Our team is working really hard on this project. We are constantly releasing new versions of this software. It is expcted to be completed positively before SIH Grand Finale" },
    { q: "How secure is this softaware?", a: "Right now, both the front-end and the back-end of our website is running on our own local servers, instead of running it on google servers. That means none of the data is being sent to google or any other website. Simultaneously the login page stores password of users in 256-bit encryption, so even in case of a database leak, users login credentials won't be exposed." },
    { q: "Will this software be actually usefull for Indian Railways or it's just another dummy wesite", a: "Our software will be very usefull to Indian railways, and there is no limit on increasing efficieny of it, as we are using MCDM technique to make algorithms, which can be optimised unlimited times to get better and better results each time. This will ultimately solve the delay of trains due to delayed or poor Scheduling of Blocks " }
  ];

  var HELP_ITEMS = [
    { q: "How to use software", a: "Complete Manual will be provided on how to use our software." },
    { q: "I have issues regarding software", a: "You can raise a complaint by clicking on report button." },
    { q: "Some features are broken", a: "Yes we are aware of that, we are constantly fixing bugs and making our software better." }
  ];

  // Where the report form is sent (the backend endpoint must exist)
  var REPORT_PATH = "/api/reports";
  var BASE = window.location.hostname.endsWith("github.io")
    ? "https://genre-workflow-minneapolis-examination.trycloudflare.com"
    : (window.location.port === "8000" ? "" : "http://127.0.0.1:8000");
  var TOKEN_KEY = "marg_access_token";
  // ==========================================================

  var PAGES = ["Dashboard", "Block Requests", "Priority List", "Scheduler", "Live Tracker", "Live Map"];
  var REPORT_TYPES = ["Wrong block information", "Data issue", "Bug / Error", "Feature request", "Other"];
  var PRIORITIES = ["Low", "Medium", "High", "Urgent"];

  // ---------- styles ----------
  var css = "" +
    ".ht-overlay{position:fixed;inset:0;background:rgba(20,30,50,.45);display:flex;align-items:center;justify-content:center;z-index:9999;padding:16px}" +
    ".ht-box{width:520px;max-width:100%;max-height:85vh;display:flex;flex-direction:column;background:#fff;border:1px solid #7fa6d8;border-radius:8px;box-shadow:0 12px 40px rgba(0,0,0,.3);font-family:Arial,Helvetica,sans-serif;color:#222}" +
    ".ht-box.ht-wide{width:640px}" +
    ".ht-head{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:#dfe8f5;border-bottom:1px solid #b8cbe6;border-radius:8px 8px 0 0}" +
    ".ht-title{font-size:16px;font-weight:700;color:#263e69}" +
    ".ht-close{border:none;background:transparent;font-size:26px;line-height:20px;color:#31517e;cursor:pointer;padding:0 4px}" +
    ".ht-close:hover{color:#c0392b}" +
    ".ht-body{padding:14px 16px;overflow:auto}" +
    ".ht-item{border:1px solid #d5deea;border-radius:6px;margin-bottom:8px;overflow:hidden}" +
    ".ht-q{width:100%;display:flex;align-items:center;justify-content:space-between;gap:10px;text-align:left;padding:11px 12px;border:none;background:#f7f9fc;font-size:14px;font-weight:700;color:#263e69;cursor:pointer}" +
    ".ht-q:hover{background:#eaf1fb}" +
    ".ht-arrow{transition:transform .15s;color:#3f78bd}" +
    ".ht-item.open .ht-arrow{transform:rotate(90deg)}" +
    ".ht-a{display:none;padding:11px 12px;font-size:14px;line-height:1.5;white-space:pre-line;border-top:1px solid #d5deea;background:#fff}" +
    ".ht-item.open .ht-a{display:block}" +
    ".ht-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}" +
    ".ht-field{display:flex;flex-direction:column;gap:4px}" +
    ".ht-full{grid-column:1/-1}" +
    ".ht-label{font-size:12px;font-weight:700;color:#31517e}" +
    ".ht-input{width:100%;padding:8px 10px;font-size:14px;font-family:inherit;color:#222;background:#fff;border:1px solid #cfd6df;border-radius:5px;outline:none}" +
    ".ht-input:focus{border-color:#3f78bd}" +
    ".ht-input[readonly]{background:#f2f4f7;color:#555}" +
    "textarea.ht-input{min-height:100px;resize:vertical}" +
    ".ht-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}" +
    ".ht-btn{padding:8px 18px;font-size:14px;font-weight:700;border-radius:5px;cursor:pointer;border:1px solid #3f78bd}" +
    ".ht-btn.primary{background:#3f78bd;color:#fff}" +
    ".ht-btn.primary:disabled{opacity:.6;cursor:default}" +
    ".ht-btn.secondary{background:#fff;color:#3f78bd}" +
    ".ht-msg{margin-top:10px;font-size:13px;min-height:16px}" +
    ".ht-msg.error{color:#c0392b}" +
    ".ht-done{text-align:center;padding:24px 8px;font-size:15px;color:#2e7d32;font-weight:700}";
  var styleTag = document.createElement("style");
  styleTag.textContent = css;
  document.head.appendChild(styleTag);

  // ---------- helpers ----------
  function el(tag, className, text) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  var current = null;

  function onKey(e) { if (e.key === "Escape") closeModal(); }

  function closeModal() {
    if (current) { current.remove(); current = null; }
    document.removeEventListener("keydown", onKey);
  }

  function openModal(title, bodyNode, wide) {
    closeModal();
    var overlay = el("div", "ht-overlay");
    var box = el("div", "ht-box" + (wide ? " ht-wide" : ""));
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-label", title);

    var head = el("div", "ht-head");
    head.appendChild(el("span", "ht-title", title));
    var x = el("button", "ht-close", "\u00D7");
    x.type = "button";
    x.setAttribute("aria-label", "Close");
    x.addEventListener("click", closeModal);
    head.appendChild(x);

    var body = el("div", "ht-body");
    body.appendChild(bodyNode);

    box.appendChild(head);
    box.appendChild(body);
    overlay.appendChild(box);
    overlay.addEventListener("mousedown", function (e) { if (e.target === overlay) closeModal(); });
    document.body.appendChild(overlay);
    current = overlay;
    document.addEventListener("keydown", onKey);
  }

  // ---------- FAQ / Help (click a question to see its answer) ----------
  function buildAccordion(items) {
    var wrap = el("div");
    items.forEach(function (item) {
      var box = el("div", "ht-item");
      var btn = el("button", "ht-q");
      btn.type = "button";
      btn.appendChild(el("span", "", item.q));
      btn.appendChild(el("span", "ht-arrow", "\u25B8"));
      var ans = el("div", "ht-a", item.a);
      btn.addEventListener("click", function () {
        var wasOpen = box.classList.contains("open");
        var all = wrap.querySelectorAll(".ht-item");
        for (var i = 0; i < all.length; i++) all[i].classList.remove("open");
        if (!wasOpen) box.classList.add("open");
      });
      box.appendChild(btn);
      box.appendChild(ans);
      wrap.appendChild(box);
    });
    return wrap;
  }

  // ---------- Report form ----------
  function field(labelText, input, required, full) {
    var wrap = el("label", "ht-field" + (full ? " ht-full" : ""));
    wrap.appendChild(el("span", "ht-label", labelText + (required ? " *" : "")));
    wrap.appendChild(input);
    return wrap;
  }

  function makeSelect(options, selected) {
    var s = el("select", "ht-input");
    options.forEach(function (o) {
      var op = document.createElement("option");
      op.value = o;
      op.textContent = o;
      if (o === selected) op.selected = true;
      s.appendChild(op);
    });
    return s;
  }

  function makeInput(type, placeholder) {
    var i = el("input", "ht-input");
    i.type = type;
    if (placeholder) i.placeholder = placeholder;
    return i;
  }

  function currentPageName() {
    var p = window.location.pathname.toLowerCase();
    if (p.indexOf("block-request") !== -1) return "Block Requests";
    if (p.indexOf("priority") !== -1) return "Priority List";
    if (p.indexOf("scheduler") !== -1) return "Scheduler";
    if (p.indexOf("live-tracker") !== -1) return "Live Tracker";
    if (p.indexOf("live-map") !== -1) return "Live Map";
    return "Dashboard";
  }

  function reporterName() {
    var w = document.querySelector(".welcome");
    return w ? w.textContent.replace(/^\s*Welcome,?\s*/i, "").trim() : "";
  }

  function buildReportForm() {
    var form = el("div");
    var grid = el("div", "ht-grid");

    var typeSel = makeSelect(REPORT_TYPES, REPORT_TYPES[0]);
    var pageSel = makeSelect(PAGES, currentPageName());
    var blockId = makeInput("text", "e.g. NR-BLK-2026-001");
    var prioSel = makeSelect(PRIORITIES, "Medium");
    var subject = makeInput("text", "Short summary of the problem");
    var desc = el("textarea", "ht-input");
    desc.placeholder = "Describe what is wrong, and what you expected to see";
    var email = makeInput("email", "optional");
    var by = makeInput("text");
    by.value = reporterName();
    by.readOnly = true;
    var when = makeInput("text");
    when.value = new Date().toLocaleString();
    when.readOnly = true;

    grid.appendChild(field("Report type", typeSel, true));
    grid.appendChild(field("Related page", pageSel, true));
    grid.appendChild(field("Block ID (if any)", blockId, false));
    grid.appendChild(field("Priority", prioSel, true));
    grid.appendChild(field("Subject", subject, true, true));
    grid.appendChild(field("Description", desc, true, true));
    grid.appendChild(field("Contact email", email, false));
    grid.appendChild(field("Reported by", by, false));
    grid.appendChild(field("Date and time", when, false, true));
    form.appendChild(grid);

    var msg = el("div", "ht-msg");
    form.appendChild(msg);

    var actions = el("div", "ht-actions");
    var cancel = el("button", "ht-btn secondary", "Cancel");
    cancel.type = "button";
    cancel.addEventListener("click", closeModal);
    var send = el("button", "ht-btn primary", "Submit report");
    send.type = "button";
    actions.appendChild(cancel);
    actions.appendChild(send);
    form.appendChild(actions);

    send.addEventListener("click", async function () {
      msg.className = "ht-msg";
      msg.textContent = "";
      if (!subject.value.trim() || !desc.value.trim()) {
        msg.className = "ht-msg error";
        msg.textContent = "Please fill in the subject and description.";
        return;
      }
      var data = {
        report_type: typeSel.value,
        page: pageSel.value,
        block_id: blockId.value.trim() || null,
        priority: prioSel.value,
        subject: subject.value.trim(),
        description: desc.value.trim(),
        contact_email: email.value.trim() || null,
        reported_by: by.value,
        reported_at: new Date().toISOString()
      };
      var headers = { "Content-Type": "application/json" };
      var token = sessionStorage.getItem(TOKEN_KEY);
      if (token) headers["Authorization"] = "Bearer " + token;

      send.disabled = true;
      send.textContent = "Sending...";
      try {
        var res = await fetch(BASE.trim() + REPORT_PATH, {
          method: "POST",
          headers: headers,
          body: JSON.stringify(data)
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        form.innerHTML = "";
        form.appendChild(el("div", "ht-done", "Report submitted. Thank you."));
        var okRow = el("div", "ht-actions");
        var closeBtn = el("button", "ht-btn primary", "Close");
        closeBtn.type = "button";
        closeBtn.addEventListener("click", closeModal);
        okRow.appendChild(closeBtn);
        form.appendChild(okRow);
      } catch (e) {
        console.warn("Report not sent:", e);
        msg.className = "ht-msg error";
        msg.textContent = "Could not send the report. Please try again later.";
        send.disabled = false;
        send.textContent = "Submit report";
      }
    });

    return form;
  }

  // ---------- connect the header links ----------
  function bind(id, fn) {
    var a = document.getElementById(id);
    if (a) a.addEventListener("click", function (e) { e.preventDefault(); fn(); });
  }

  bind("faqLink", function () { openModal("Frequently Asked Questions", buildAccordion(FAQ_ITEMS)); });
  bind("helpLink", function () { openModal("Help", buildAccordion(HELP_ITEMS)); });
  bind("reportLink", function () { openModal("Report an Issue", buildReportForm(), true); });
})();