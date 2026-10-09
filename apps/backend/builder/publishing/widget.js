/* EnterpriseAI chat widget - one script tag, no dependencies.
 *
 *   <script src="https://YOUR-BACKEND/api/v1/public/widget.js" data-key="eai_pk_..."
 *           data-title="Ask us" data-color="#4f46e5" data-greeting="Hi! How can I help?"></script>
 *
 * Talks to the public API next to this file with the publishable key. Each
 * message is its own run (no memory between messages). Answers are shown as
 * plain text (never as HTML), inside a shadow root so the page's CSS can't
 * touch the widget or the widget the page.
 */
(function () {
  var script = document.currentScript;
  if (!script || !script.getAttribute("data-key")) {
    console.error("[EnterpriseAI widget] add data-key=\"eai_pk_...\" to the script tag");
    return;
  }
  var KEY = script.getAttribute("data-key");
  var API = script.src.replace(/\/widget\.js(\?.*)?$/, "");
  var COLOR = script.getAttribute("data-color") || "#4f46e5";
  var TITLE = script.getAttribute("data-title") || "";
  var GREETING = script.getAttribute("data-greeting") || "Hi! How can I help?";

  function call(method, path, body) {
    return fetch(API + path, {
      method: method,
      headers: { "Authorization": "Bearer " + KEY, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; });
    });
  }

  var host = document.createElement("div");
  host.setAttribute("data-enterpriseai-widget", "");
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });
  root.innerHTML =
    "<style>" +
    ":host{all:initial}*{box-sizing:border-box;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}" +
    ".bubble{display:flex;align-items:center;justify-content:center;position:fixed;right:20px;bottom:20px;width:56px;height:56px;border-radius:50%;border:0;cursor:pointer;color:#fff;box-shadow:0 6px 20px rgba(0,0,0,.2);font-size:24px;z-index:2147483646}" +
    ".panel{position:fixed;right:20px;bottom:88px;width:min(380px,calc(100vw - 40px));height:min(560px,calc(100vh - 120px));background:#fff;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.25);display:none;flex-direction:column;overflow:hidden;z-index:2147483647}" +
    ".panel.open{display:flex}.head{padding:14px 16px;color:#fff;font-weight:600;font-size:15px}" +
    ".log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:8px;background:#fafafa}" +
    ".msg{max-width:85%;padding:9px 12px;border-radius:12px;font-size:14px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}" +
    ".me{align-self:flex-end;color:#fff}.bot{align-self:flex-start;background:#fff;border:1px solid #e4e4e7;color:#18181b}" +
    ".note{align-self:center;font-size:12px;color:#71717a}.err{border-color:#fecaca;background:#fef2f2;color:#991b1b}" +
    "form{display:flex;gap:8px;padding:10px;border-top:1px solid #e4e4e7}" +
    "input{flex:1;border:1px solid #d4d4d8;border-radius:8px;padding:9px 10px;font-size:14px;outline:none}" +
    "button.send{border:0;border-radius:8px;padding:0 14px;color:#fff;font-size:14px;cursor:pointer}button:disabled{opacity:.5;cursor:default}" +
    "</style>" +
    '<div class="panel" part="panel"><div class="head"></div><div class="log" aria-live="polite"></div>' +
    '<form><input aria-label="Message" placeholder="Type a message\u2026" maxlength="4000"/><button class="send" type="submit">Send</button></form></div>' +
    '<button class="bubble" aria-label="Open chat"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></button>';

  var panel = root.querySelector(".panel"), log = root.querySelector(".log"), head = root.querySelector(".head");
  var form = root.querySelector("form"), input = root.querySelector("input"), send = root.querySelector(".send");
  var bubble = root.querySelector(".bubble");
  bubble.style.background = COLOR; head.style.background = COLOR; send.style.background = COLOR;
  head.textContent = TITLE || "Chat";

  function add(text, cls) {
    var el = document.createElement("div");
    el.className = "msg " + cls;
    if (cls === "me") el.style.background = COLOR;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  var started = false;
  bubble.addEventListener("click", function () {
    panel.classList.toggle("open");
    if (panel.classList.contains("open")) input.focus();
    if (started) return;
    started = true;
    add(GREETING, "bot");
    if (!TITLE) call("GET", "/info").then(function (r) { if (r.status === 200 && r.data.name) head.textContent = r.data.name; });
  });

  function show(view, pending) {
    if (view.status === "succeeded") {
      pending.textContent = view.output || "(no answer)";
      if (view.sources && view.sources.length) add("Sources: " + view.sources.join(", "), "note");
      return true;
    }
    if (view.status === "failed" || view.status === "cancelled") {
      pending.textContent = view.error || "Something went wrong.";
      pending.classList.add("err");
      return true;
    }
    pending.textContent = view.waiting_for === "approval" ? "Waiting for a team member to approve\u2026" : "Working on it\u2026";
    return false;
  }

  function poll(runId, pending, tries) {
    if (tries > 90) { pending.textContent = "This is taking a while \u2014 please try again later."; send.disabled = false; return; }
    setTimeout(function () {
      call("GET", "/runs/" + runId).then(function (r) {
        if (r.status !== 200) { pending.textContent = r.data.detail || "Something went wrong."; pending.classList.add("err"); send.disabled = false; return; }
        if (show(r.data, pending)) send.disabled = false; else poll(runId, pending, tries + 1);
      }, function () { poll(runId, pending, tries + 1); });
    }, 2000);
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || send.disabled) return;
    input.value = "";
    add(text, "me");
    var pending = add("\u2026", "bot");
    send.disabled = true;
    call("POST", "/runs", { input: text, wait_seconds: 25 }).then(function (r) {
      if (r.status !== 200 && r.status !== 202) {
        var why = (r.data.problems && r.data.problems.length) ? r.data.problems.join(" ") : r.data.detail;
        pending.textContent = why || "Something went wrong.";
        pending.classList.add("err");
        send.disabled = false;
        return;
      }
      if (show(r.data, pending)) send.disabled = false; else poll(r.data.run_id, pending, 0);
    }, function () {
      pending.textContent = "Couldn't reach the server.";
      pending.classList.add("err");
      send.disabled = false;
    });
  });
})();
