"""HTML for the on-call console."""

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>On-call</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600&family=Newsreader:opsz,wght@6..72,480;6..72,560&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #e7eef2;
      --ink: #17232c;
      --muted: #4d6270;
      --panel: #f8fbfc;
      --line: #c5d2da;
      --firing: #9a4d08;
      --approved: #1c6b45;
      --rejected: #8f2d2d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Figtree, "Segoe UI", sans-serif;
      font-size: 1.05rem;
      line-height: 1.45;
    }
    main {
      display: grid;
      grid-template-columns: 18rem 1fr;
      min-height: 100vh;
    }
    aside {
      padding: 1.5rem 1rem 2rem 1.4rem;
      border-right: 1px solid var(--line);
    }
    section { padding: 1.6rem 1.8rem 3rem; max-width: 42rem; }
    h1 {
      font-family: Newsreader, Georgia, serif;
      font-weight: 560;
      font-size: 2.15rem;
      line-height: 1.15;
      letter-spacing: -0.02em;
      margin: 0.35rem 0 0.8rem;
    }
    .desk { margin: 0 0 1rem; color: var(--muted); }
    #list { list-style: none; margin: 0; padding: 0; }
    #list button {
      display: block;
      width: 100%;
      text-align: left;
      background: transparent;
      border: 0;
      border-left: 3px solid transparent;
      color: inherit;
      font: inherit;
      padding: 0.7rem 0.6rem;
      cursor: pointer;
    }
    #list button[aria-current="true"] { border-left-color: var(--firing); background: var(--panel); }
    #list button:focus-visible, .actions button:focus-visible, textarea:focus-visible, summary:focus-visible {
      outline: 2px solid var(--ink);
      outline-offset: 2px;
    }
    .when { display: block; color: var(--muted); font-size: 0.92rem; }
    .meta { color: var(--muted); margin: 0 0 1.2rem; }
    .firing { color: var(--firing); }
    .approved { color: var(--approved); }
    .rejected { color: var(--rejected); }
    label { display: block; margin-bottom: 0.35rem; }
    textarea {
      width: 100%;
      min-height: 6.5rem;
      padding: 0.75rem 0.8rem;
      border: 1px solid var(--line);
      background: var(--panel);
      color: inherit;
      font: inherit;
      line-height: 1.4;
      resize: vertical;
    }
    .actions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.8rem; }
    .actions button {
      font: inherit;
      background: var(--ink);
      color: #f8fbfc;
      border: 0;
      padding: 0.45rem 0.8rem;
      cursor: pointer;
    }
    .actions button.quiet { background: transparent; color: var(--ink); border: 1px solid var(--line); }
    .hint { color: var(--muted); margin-top: 0.8rem; max-width: 38rem; }
    details { margin-top: 1.6rem; }
    summary { cursor: pointer; color: var(--muted); }
    pre {
      white-space: pre-wrap;
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 0.8rem;
      font-family: ui-monospace, monospace;
      font-size: 0.86rem;
    }
    #message:empty { display: none; }
    @media (max-width: 760px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <main>
    <aside>
      <p class="desk">On-call</p>
      <ul id="list"></ul>
    </aside>
    <section>
      <p id="state" class="meta">No incidents yet.</p>
      <h1 id="title">Waiting for a checkout alert</h1>
      <p id="lead">The shop keeps running. This page only records what you decide.</p>
      <form id="decision">
        <label for="command">Note</label>
        <textarea id="command"></textarea>
        <div class="actions">
          <button id="approve" type="button">Approve note</button>
          <button id="edit" class="quiet" type="button">Save edit</button>
          <button id="reject" class="quiet" type="button">Reject</button>
        </div>
      </form>
      <p id="message" class="hint"></p>
      <p class="hint">Approve records this note. Save edit replaces it and clears an earlier approval. Reject records a no. None of these change the shop.</p>
      <details>
        <summary>Query Prometheus used</summary>
        <pre id="expression"></pre>
      </details>
    </section>
  </main>
  <script>
    const list = document.querySelector("#list");
    const title = document.querySelector("#title");
    const state = document.querySelector("#state");
    const lead = document.querySelector("#lead");
    const command = document.querySelector("#command");
    const expression = document.querySelector("#expression");
    const message = document.querySelector("#message");
    const form = document.querySelector("#decision");
    let current = null;
    let source = null;
    let incidents = [];

    function payloadOf(incident) {
      try { return JSON.parse(incident.payload); }
      catch { return {}; }
    }

    function summaryOf(incident) {
      const summary = (payloadOf(incident).annotations || {}).summary;
      if (summary) return summary;
      return incident.alert_name + " on the " + incident.service + " service.";
    }

    function readableName(name) {
      const spaced = name.replace(/([a-z0-9])([A-Z])/g, "$1 $2");
      return spaced.charAt(0).toUpperCase() + spaced.slice(1);
    }

    function when(iso) {
      const date = new Date(iso);
      if (Number.isNaN(date.getTime())) return iso;
      return new Intl.DateTimeFormat(undefined, {
        month: "short", day: "numeric", hour: "numeric", minute: "2-digit"
      }).format(date);
    }

    function decisionLabel(incident) {
      if (incident.decision === "approve") return "Approved";
      if (incident.decision === "edit") return "Edited";
      if (incident.decision === "reject") return "Rejected";
      return "Waiting";
    }

    function generatedNote(incident) {
      return incident.command_text.includes("Expression:");
    }

    function noteFor(incident) {
      if (!incident.decision && generatedNote(incident)) return summaryOf(incident);
      return incident.command_text;
    }

    function show(incident) {
      const payload = payloadOf(incident);
      const firing = (payload.status || "firing") === "firing";
      const decision = decisionLabel(incident);
      title.textContent = summaryOf(incident);
      state.textContent = when(incident.starts_at) + ". " + readableName(incident.service) + " service.";
      state.className = "meta " + (incident.decision === "approve" ? "approved" : incident.decision === "reject" ? "rejected" : firing ? "firing" : "");
      lead.textContent = firing ? decision + ". The alert is still firing." : decision + ".";
      if (document.activeElement !== command) command.value = noteFor(incident);
      expression.textContent = incident.expression || "No query was stored with this alert.";
      form.hidden = false;
    }

    function showEmpty() {
      title.textContent = "Waiting for a checkout alert";
      state.textContent = "No incidents yet.";
      state.className = "meta";
      lead.textContent = "Set paymentFailure to 100% and leave the load generator running. This page updates after the error rate stays high for five minutes.";
      command.value = "";
      expression.textContent = "";
      form.hidden = true;
    }

    function renderList() {
      list.replaceChildren();
      for (const incident of incidents) {
        const item = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        if (incident.id === current) button.setAttribute("aria-current", "true");
        const whenLine = document.createElement("span");
        whenLine.className = "when";
        whenLine.textContent = when(incident.starts_at) + ", " + decisionLabel(incident).toLowerCase();
        button.append(whenLine, document.createTextNode(readableName(incident.alert_name)));
        button.addEventListener("click", () => watch(incident.id));
        item.appendChild(button);
        list.appendChild(item);
      }
    }

    async function loadList() {
      const response = await fetch("/incidents");
      incidents = await response.json();
      if (!current && incidents.length) watch(incidents[0].id);
      if (current && !incidents.some((incident) => incident.id === current)) {
        current = null;
        if (source) source.close();
      }
      renderList();
      if (!incidents.length) showEmpty();
    }

    function watch(id) {
      current = id;
      message.textContent = "";
      if (source) source.close();
      source = new EventSource("/incidents/" + id + "/stream");
      source.onmessage = (event) => show(JSON.parse(event.data));
      renderList();
    }

    async function send(decision) {
      if (!current) return;
      message.textContent = "";
      const response = await fetch("/incidents/" + current + "/decision", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ decision, text: command.value })
      });
      if (!response.ok) {
        message.textContent = await response.text();
        return;
      }
      show(await response.json());
      if (decision === "approve") message.textContent = "Approved. That note is the recorded text.";
      if (decision === "edit") message.textContent = "Saved. The earlier approval was cleared.";
      if (decision === "reject") message.textContent = "Rejected. No note is approved.";
      loadList();
    }

    document.querySelector("#approve").addEventListener("click", () => send("approve"));
    document.querySelector("#edit").addEventListener("click", () => send("edit"));
    document.querySelector("#reject").addEventListener("click", () => send("reject"));
    loadList();
    setInterval(loadList, 5000);
  </script>
</body>
</html>
"""
