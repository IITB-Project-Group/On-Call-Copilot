"""HTML for the on-call console."""

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Incidents</title>
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
      font-size: 1rem;
      line-height: 1.45;
    }
    main {
      display: grid;
      grid-template-columns: 16.5rem minmax(0, 1fr);
      min-height: 100vh;
    }
    main.has-incident {
      grid-template-columns: 16.5rem minmax(0, 1fr) minmax(17.5rem, 22rem);
    }
    aside {
      padding: 1.35rem 1rem 2rem 1.25rem;
      border-right: 1px solid var(--line);
    }
    .decision {
      border-right: 0;
      border-left: 1px solid var(--line);
      padding: 1.35rem 1.15rem 2rem;
    }
    #detail { padding: 1.45rem 1.6rem 2.6rem; max-width: 44rem; }
    h1 {
      font-family: Newsreader, Georgia, serif;
      font-weight: 560;
      font-size: 1.85rem;
      line-height: 1.15;
      letter-spacing: -0.02em;
      margin: 0.2rem 0 0;
    }
    h2 { font-size: 1rem; font-weight: 600; margin: 1.35rem 0 0.55rem; }
    .desk { margin: 0 0 0.75rem; font-weight: 600; }
    .views { display: flex; gap: 0.4rem; margin: 0 0 0.85rem; }
    .views button, .actions button {
      font: inherit;
      cursor: pointer;
    }
    .views button {
      background: transparent;
      color: var(--ink);
      border: 1px solid var(--line);
      padding: 0.22rem 0.6rem;
    }
    .views button[aria-pressed="true"] { background: var(--ink); color: var(--panel); border-color: var(--ink); }
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
      padding: 0.65rem 0.6rem;
      cursor: pointer;
    }
    #list button[aria-current="true"] { border-left-color: var(--ink); background: var(--panel); }
    #list button:focus-visible, .views button:focus-visible, .actions button:focus-visible, textarea:focus-visible {
      outline: 2px solid var(--ink);
      outline-offset: 2px;
    }
    .service { display: block; font-weight: 600; }
    .when { display: block; color: var(--muted); font-size: 0.92rem; }
    .meta { color: var(--muted); margin: 0 0 0.35rem; }
    .firing { color: var(--firing); }
    .approved { color: var(--approved); }
    .rejected { color: var(--rejected); }
    .events { list-style: none; margin: 0; padding: 0; }
    .events li {
      display: grid;
      grid-template-columns: 8.6rem minmax(0, 1fr);
      gap: 0.75rem;
      padding: 0.5rem 0;
      border-top: 1px solid var(--line);
    }
    .events time { color: var(--muted); }
    #issue {
      margin: 0.85rem 0 0;
      font-size: 1.15rem;
      line-height: 1.4;
    }
    .kicker { margin: 1.35rem 0 0.4rem; font-weight: 600; }
    pre {
      white-space: pre-wrap;
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 0.75rem 0.8rem;
      margin: 0;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.82rem;
      line-height: 1.45;
    }
    .command {
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 0.95rem 1rem 1.05rem;
    }
    .command h2 { margin: 0 0 0.45rem; }
    .command p { margin: 0 0 0.75rem; }
    .payload {
      margin: 0 0 0.75rem;
      padding: 0.55rem 0.7rem;
      background: var(--bg);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.84rem;
      line-height: 1.55;
    }
    .effect { color: var(--muted); }
    label { display: block; margin-bottom: 0.35rem; font-weight: 600; }
    textarea {
      width: 100%;
      min-height: 6.5rem;
      padding: 0.7rem 0.75rem;
      border: 1px solid var(--line);
      background: var(--bg);
      color: inherit;
      font: inherit;
      line-height: 1.4;
      resize: vertical;
    }
    .actions { display: flex; flex-wrap: wrap; gap: 0.45rem; margin-top: 0.75rem; }
    .actions button {
      background: var(--ink);
      color: var(--panel);
      border: 0;
      padding: 0.42rem 0.75rem;
    }
    .actions button.quiet { background: transparent; color: var(--ink); border: 1px solid var(--line); }
    .hint { color: var(--muted); margin: 0.75rem 0 0; }
    #message:empty { display: none; }
    #stream[hidden], #decision[hidden], #payload[hidden], #effect[hidden], #controls[hidden] { display: none; }
    @media (max-width: 900px) {
      main, main.has-incident { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .decision { border-left: 0; }
    }
  </style>
</head>
<body>
  <main>
    <aside aria-label="Incidents">
      <p class="desk">Incidents</p>
      <div class="views">
        <button id="show-open" type="button" aria-pressed="true">Open</button>
        <button id="show-closed" type="button" aria-pressed="false">Closed</button>
      </div>
      <ul id="list"></ul>
    </aside>
    <section id="detail">
      <p id="message" class="hint" aria-live="polite"></p>
      <p id="state" class="meta">Approved and rejected incidents stay on Closed.</p>
      <h1 id="title">No open incidents</h1>
      <div id="stream" hidden>
        <h2>Issue</h2>
        <p id="issue"></p>
        <p id="alert" class="meta"></p>
        <p class="kicker">What was checked</p>
        <ol id="events" class="events"></ol>
        <p class="kicker">Query checked</p>
        <pre id="expression"></pre>
      </div>
    </section>
    <aside id="decision" class="decision" aria-label="Possible solution" hidden>
      <div class="command">
        <h2>Possible solution</h2>
        <p id="lead"></p>
        <div id="payload" class="payload" hidden></div>
        <p id="effect" class="effect" hidden></p>
        <form id="decision-form">
          <label for="command">Note</label>
          <textarea id="command" placeholder="Add a note. The issue stays above."></textarea>
          <div id="controls">
            <div class="actions">
              <button id="approve" type="button">Approve this command</button>
              <button id="edit" class="quiet" type="button">Save note</button>
              <button id="reject" class="quiet" type="button">Reject</button>
            </div>
            <p class="hint">Save note keeps this incident open and clears an earlier approval. Reject closes it and leaves the shop unchanged.</p>
          </div>
        </form>
      </div>
    </aside>
  </main>
  <script>
    const list = document.querySelector("#list");
    const title = document.querySelector("#title");
    const state = document.querySelector("#state");
    const lead = document.querySelector("#lead");
    const command = document.querySelector("#command");
    const issue = document.querySelector("#issue");
    const alertName = document.querySelector("#alert");
    const expression = document.querySelector("#expression");
    const message = document.querySelector("#message");
    const stream = document.querySelector("#stream");
    const decision = document.querySelector("#decision");
    const payload = document.querySelector("#payload");
    const effect = document.querySelector("#effect");
    const controls = document.querySelector("#controls");
    const events = document.querySelector("#events");
    const approve = document.querySelector("#approve");
    const shell = document.querySelector("main");
    const flagPolicy = "A checkout or payment incident also sets paymentFailure to off.";
    let current = null;
    let source = null;
    let incidents = [];
    let view = "open";
    let sending = false;
    let listed = "";

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

    function age(iso) {
      const date = new Date(iso);
      const minutes = Math.round((Date.now() - date.getTime()) / 60000);
      if (Number.isNaN(minutes) || minutes < 0) return when(iso);
      if (minutes < 1) return "under a minute";
      if (minutes < 60) return minutes + " min";
      const hours = Math.round(minutes / 60);
      if (hours < 48) return hours + " hr";
      return when(iso);
    }

    function decisionLabel(incident) {
      if (incident.decision === "approve") return "Approved";
      if (incident.decision === "edit") return "Edited";
      if (incident.decision === "reject") return "Rejected";
      return "Waiting";
    }

    function isOpen(incident) {
      return incident.decision !== "approve" && incident.decision !== "reject";
    }

    function firing(incident) {
      return (payloadOf(incident).status || "firing") === "firing";
    }

    function writesFlag(incident) {
      return incident.service === "checkout" || incident.service === "payment";
    }

    function severityOf(incident) {
      const severity = (payloadOf(incident).labels || {}).severity;
      if (typeof severity !== "string" || !severity.trim()) return "";
      const text = severity.trim();
      return text.charAt(0).toUpperCase() + text.slice(1);
    }

    function noteFor(incident) {
      if (!incident.decision) return "";
      return incident.command_text;
    }

    function statusLine(incident) {
      const parts = [];
      const severity = severityOf(incident);
      if (severity) parts.push(severity);
      parts.push(isOpen(incident) ? (firing(incident) ? "Firing" : "Not firing") : decisionLabel(incident));
      if (isOpen(incident)) parts.push("open " + age(incident.starts_at));
      parts.push("started " + when(incident.starts_at));
      if (!isOpen(incident)) parts.push("closed " + when(incident.updated_at));
      return parts.join(" · ");
    }

    function leadFor(incident) {
      const open = isOpen(incident);
      if (!open && incident.decision === "approve" && writesFlag(incident)) {
        return "Approved. " + flagPolicy + " This view does not run that change again.";
      }
      if (!open && incident.decision === "approve") return "Approved. The shop was left unchanged.";
      if (!open) return "Rejected. The shop was left unchanged.";
      if (writesFlag(incident)) return "Approving closes this incident. " + flagPolicy;
      return "No allow-listed action was proposed for this service. Approving stores the note and closes this incident.";
    }

    function renderPayload(incident) {
      const flag = writesFlag(incident);
      payload.hidden = !flag;
      effect.hidden = !flag;
      if (!flag) return;
      payload.replaceChildren();
      for (const line of ["set_flag", "flag: paymentFailure", "value: off"]) {
        const row = document.createElement("div");
        row.textContent = line;
        payload.appendChild(row);
      }
      effect.textContent = "Expected effect: payment errors decrease and the checkout error rate returns below the alert threshold.";
    }

    function renderEvents(incident) {
      const items = [[when(incident.starts_at), "Alert received."]];
      if (incident.decision === "edit") {
        items.push([when(incident.updated_at), "Note saved. Earlier approval cleared."]);
      } else if (incident.decision === "approve") {
        items.push([when(incident.updated_at), "Approved. The note below is what was stored."]);
      } else if (incident.decision === "reject") {
        items.push([when(incident.updated_at), "Rejected. The shop was left unchanged."]);
      }
      events.replaceChildren();
      for (const [time, text] of items) {
        const item = document.createElement("li");
        const stamp = document.createElement("time");
        stamp.textContent = time;
        const body = document.createElement("span");
        body.textContent = text;
        item.append(stamp, body);
        events.appendChild(item);
      }
    }

    function show(incident) {
      const open = isOpen(incident);
      shell.classList.add("has-incident");
      stream.hidden = false;
      decision.hidden = false;
      title.textContent = readableName(incident.service);
      issue.textContent = summaryOf(incident);
      alertName.textContent = readableName(incident.alert_name);
      state.textContent = statusLine(incident);
      state.className = "meta " + (
        incident.decision === "approve" ? "approved" :
        incident.decision === "reject" ? "rejected" :
        firing(incident) ? "firing" : ""
      );
      lead.textContent = leadFor(incident);
      renderPayload(incident);
      renderEvents(incident);
      if (document.activeElement !== command) command.value = noteFor(incident);
      expression.textContent = incident.expression || "No query was stored with this alert.";
      command.readOnly = !open;
      controls.hidden = !open;
      approve.textContent = writesFlag(incident) ? "Approve this command" : "Approve and close";
    }

    function showEmpty() {
      const closedView = view === "closed";
      shell.classList.remove("has-incident");
      title.textContent = closedView ? "No closed incidents" : "No open incidents";
      state.textContent = closedView
        ? "Approved and rejected incidents show up here."
        : "Approved and rejected incidents stay on Closed.";
      state.className = "meta";
      stream.hidden = true;
      decision.hidden = true;
      command.value = "";
      issue.textContent = "";
      alertName.textContent = "";
      expression.textContent = "";
    }

    function queueDetail(incident) {
      const severity = severityOf(incident);
      const prefix = severity ? severity + " · " : "";
      if (!isOpen(incident)) return prefix + decisionLabel(incident) + " · " + when(incident.updated_at);
      const label = incident.decision === "edit" ? "Edited" : (firing(incident) ? "Firing" : "Not firing");
      return prefix + label + " · " + age(incident.starts_at);
    }

    function listSignature(shown) {
      return shown.map((incident) => [
        incident.id, incident.decision, incident.updated_at, queueDetail(incident), incident.id === current
      ].join("|")).join(String.fromCharCode(10));
    }

    function renderList() {
      const shown = shownIncidents();
      listed = listSignature(shown);
      list.replaceChildren();
      for (const incident of shown) {
        const item = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.title = readableName(incident.alert_name);
        if (incident.id === current) button.setAttribute("aria-current", "true");
        const name = document.createElement("span");
        name.className = "service";
        name.textContent = readableName(incident.service);
        const whenLine = document.createElement("span");
        whenLine.className = "when";
        if (incident.decision === "approve") whenLine.classList.add("approved");
        else if (incident.decision === "reject") whenLine.classList.add("rejected");
        else if (isOpen(incident) && firing(incident) && incident.decision !== "edit") whenLine.classList.add("firing");
        whenLine.textContent = queueDetail(incident);
        button.append(name, whenLine);
        button.addEventListener("click", () => watch(incident.id));
        item.appendChild(button);
        list.appendChild(item);
      }
    }

    function shownIncidents() {
      const shown = incidents.filter(view === "open" ? isOpen : (incident) => !isOpen(incident));
      if (view === "open") shown.sort((a, b) => Number(firing(b)) - Number(firing(a)));
      return shown;
    }

    async function loadList() {
      try {
        const response = await fetch("/incidents?state=" + view);
        if (!response.ok) {
          message.textContent = "The incident list could not be loaded.";
          return;
        }
        incidents = await response.json();
        const shown = shownIncidents();
        if (current && !shown.some((incident) => incident.id === current)) {
          current = null;
          if (source) source.close();
        }
        if (!current && shown.length) watch(shown[0].id);
        else if (current) {
          const selected = incidents.find((incident) => incident.id === current);
          if (selected && document.activeElement !== command) state.textContent = statusLine(selected);
        }
        const nextList = listSignature(shownIncidents());
        if (nextList !== listed) renderList();
        if (!shown.length) showEmpty();
      } catch (error) {
        message.textContent = "The incident list could not be loaded.";
      }
    }

    function setView(next) {
      view = next;
      document.querySelector("#show-open").setAttribute("aria-pressed", String(view === "open"));
      document.querySelector("#show-closed").setAttribute("aria-pressed", String(view === "closed"));
      current = null;
      if (source) source.close();
      message.textContent = "";
      loadList();
    }

    function watch(id) {
      current = id;
      message.textContent = "";
      if (source) source.close();
      source = new EventSource("/incidents/" + id + "/stream");
      source.onmessage = (event) => show(JSON.parse(event.data));
      renderList();
    }

    async function send(decisionName) {
      if (!current || sending) return;
      sending = true;
      message.textContent = "";
      try {
        const response = await fetch("/incidents/" + current + "/decision", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ decision: decisionName, text: command.value })
        });
        if (!response.ok) {
          message.textContent = await response.text();
          return;
        }
        const body = await response.json();
        const service = readableName(body.service);
        if (decisionName === "approve" || decisionName === "reject") {
          current = null;
          if (source) source.close();
          await loadList();
          message.textContent = decisionName === "approve"
            ? (body.flag_result ? service + " closed. " + body.flag_result + "." : service + " closed.")
            : service + " closed. The shop was left unchanged.";
          return;
        }
        show(body);
        message.textContent = "Saved. The earlier approval was cleared.";
        loadList();
      } finally {
        sending = false;
      }
    }

    document.querySelector("#decision-form").addEventListener("submit", (event) => event.preventDefault());
    document.querySelector("#show-open").addEventListener("click", () => setView("open"));
    document.querySelector("#show-closed").addEventListener("click", () => setView("closed"));
    approve.addEventListener("click", () => send("approve"));
    document.querySelector("#edit").addEventListener("click", () => send("edit"));
    document.querySelector("#reject").addEventListener("click", () => send("reject"));
    loadList();
    setInterval(loadList, 5000);
  </script>
</body>
</html>
"""
