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
    aside {
      padding: 1.35rem 1rem 2rem 1.25rem;
      border-right: 1px solid var(--line);
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
    #list button:focus-visible, .views button:focus-visible, .actions button:focus-visible, textarea:focus-visible, input:focus-visible {
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
    #pending { margin: 0.45rem 0 0; font-size: 1.05rem; }
    #live-panel { margin: 0.35rem 0 1rem; max-width: 42rem; }
    #live, #live-activity {
      display: grid;
      grid-template-columns: 4.5rem 1fr;
      gap: 0.55rem 0.75rem;
      align-items: center;
      margin: 0.35rem 0 0;
      font-size: 1.02rem;
    }
    #live { grid-template-columns: 4.5rem auto 1fr; }
    #live[hidden], #live-activity[hidden] { display: none; }
    .live-label {
      color: var(--muted);
      font-size: 0.78rem;
      font-variant: all-small-caps;
      letter-spacing: 0.04em;
    }
    #activity-log {
      list-style: none;
      margin: 0.65rem 0 0;
      padding: 0.35rem 0 0;
      border-top: 1px solid var(--line);
      max-width: 42rem;
    }
    #activity-log[hidden] { display: none; }
    #activity-log .log-title {
      margin: 0 0 0.35rem;
      color: var(--muted);
      font-size: 0.78rem;
      font-variant: all-small-caps;
      letter-spacing: 0.04em;
    }
    #activity-log li {
      display: grid;
      grid-template-columns: 4.5rem 1fr;
      gap: 0.65rem;
      padding: 0.28rem 0;
      color: var(--muted);
      font-size: 0.92rem;
    }
    #activity-log li:first-of-type { color: var(--ink); font-weight: 560; }
    #activity-log .kind { color: var(--muted); font-variant: all-small-caps; letter-spacing: 0.04em; }
    #plan-block { margin-top: 1.1rem; }
    #plan-block h3 { margin: 0 0 0.35rem; font-size: 1rem; }
    #plan-focus { margin: 0 0 0.45rem; }
    #plan-why summary {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      cursor: pointer;
      color: var(--muted);
      list-style: none;
    }
    #plan-why summary::-webkit-details-marker { display: none; }
    #plan-why .chevron {
      width: 0.4rem;
      height: 0.4rem;
      border-right: 2px solid currentColor;
      border-bottom: 2px solid currentColor;
      transform: rotate(-45deg);
    }
    #plan-why[open] .chevron { transform: rotate(45deg); }
    .pulse { display: inline-flex; gap: 0.22rem; align-items: center; height: 1rem; }
    .pulse[hidden], #phase[hidden] { display: none; }
    .pulse i {
      width: 0.38rem;
      height: 0.38rem;
      border-radius: 50%;
      background: var(--ink);
      display: block;
      animation: blink 1.2s infinite ease-in-out;
    }
    .pulse i:nth-child(2) { animation-delay: 0.15s; }
    .pulse i:nth-child(3) { animation-delay: 0.3s; }
    @keyframes blink {
      0%, 80%, 100% { opacity: 0.2; }
      40% { opacity: 1; }
    }
    @media (prefers-reduced-motion: reduce) {
      .pulse i { animation: none; opacity: 0.7; }
    }
    #plan-why { margin: 0.7rem 0 0; }
    #plan-why summary { cursor: pointer; }
    #plan-why[hidden] { display: none; }
    #plan-reason { margin: 0.45rem 0 0; max-width: 38rem; }
    #plan, #hypotheses { list-style: none; margin: 0.55rem 0 0; padding: 0; }
    #plan li, #hypotheses li {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 1rem;
      padding: 0.4rem 0;
      border-top: 1px solid var(--line);
    }
    #plan li.running { font-weight: 600; }
    #plan li.failed .status { color: var(--reject, #a33); }
    #plan .status, #hypotheses .status { color: var(--muted); text-align: right; }
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
    .hitl-banner {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.75rem 1rem;
      margin: 1rem 0 0;
      padding: 0.85rem 1rem;
      background: var(--panel);
      border: 1px solid var(--line);
    }
    .hitl-banner[hidden] { display: none; }
    .hitl-banner p { margin: 0; flex: 1 1 12rem; }
    .hitl-banner button {
      font: inherit;
      cursor: pointer;
      background: var(--ink);
      color: var(--panel);
      border: 0;
      padding: 0.42rem 0.85rem;
    }
    .decision {
      position: fixed;
      inset: 0;
      z-index: 40;
      display: grid;
      place-items: center;
      padding: 1.25rem;
      background: rgba(23, 35, 44, 0.42);
    }
    .decision[hidden] { display: none; }
    .command {
      width: min(32rem, 100%);
      max-height: min(92vh, 44rem);
      overflow: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 1.15rem 1.2rem 1.25rem;
      box-shadow: 0 18px 48px rgba(23, 35, 44, 0.18);
    }
    .command-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 1rem;
      margin: 0 0 0.45rem;
    }
    .command h2 { margin: 0; }
    .command p { margin: 0 0 0.75rem; }
    .modal-close {
      font: inherit;
      cursor: pointer;
      background: transparent;
      border: 1px solid var(--line);
      color: var(--ink);
      padding: 0.2rem 0.55rem;
      line-height: 1.2;
    }
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
    textarea, input {
      width: 100%;
      padding: 0.7rem 0.75rem;
      border: 1px solid var(--line);
      background: var(--bg);
      color: inherit;
      font: inherit;
      line-height: 1.4;
    }
    textarea { min-height: 5.5rem; resize: vertical; }
    input { margin-bottom: 0.75rem; }
    .actions { display: flex; flex-wrap: wrap; gap: 0.45rem; margin-top: 0.75rem; }
    .actions button {
      background: var(--ink);
      color: var(--panel);
      border: 0;
      padding: 0.42rem 0.75rem;
    }
    .actions button.quiet { background: transparent; color: var(--ink); border: 1px solid var(--line); }
    .hint { color: var(--muted); margin: 0.75rem 0 0; }
    #now {
      margin: 0.9rem 0 0;
      padding: 0.75rem 0.85rem;
      background: var(--panel);
      border: 1px solid var(--line);
      font-size: 1.05rem;
    }
    #now.error { border-color: var(--rejected); }
    #stages { display: flex; flex-wrap: wrap; gap: 0.4rem; list-style: none; margin: 0.75rem 0 0; padding: 0; }
    #stages li {
      padding: 0.2rem 0.55rem;
      border: 1px solid var(--line);
      color: var(--muted);
    }
    #stages li.done { color: var(--approved); border-color: var(--approved); }
    #stages li.now { color: var(--panel); background: var(--ink); border-color: var(--ink); }
    #stages li.bad { color: var(--rejected); border-color: var(--rejected); }
    #shown-code { font-weight: 600; margin: 0 0 0.75rem; }
    #agent-error { color: var(--rejected); white-space: pre-wrap; }
    #message:empty { display: none; }
    #review-note {
      white-space: pre-wrap;
      margin: 0 0 0.75rem;
      padding: 0.65rem 0.75rem;
      background: var(--bg);
      border: 1px solid var(--line);
    }
    #stream[hidden], #decision[hidden], #payload[hidden], #effect[hidden], #controls[hidden], #decision-form[hidden], #code-fields[hidden], #review-note[hidden], #live[hidden], #hitl-banner[hidden] { display: none; }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
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
        <p id="now"></p>
        <ol id="stages" aria-label="Where this incident is"></ol>
        <h2>Issue</h2>
        <p id="issue"></p>
        <p id="alert" class="meta"></p>
        <div id="agent" hidden>
          <h2>What the agent is doing</h2>
          <div id="live-panel">
            <div id="live" hidden>
              <span class="live-label">Now</span>
              <span class="pulse" aria-hidden="true"><i></i><i></i><i></i></span>
              <span id="phase">Investigating</span>
            </div>
            <p id="live-activity" hidden>
              <span class="live-label">Current</span>
              <span id="live-activity-text"></span>
            </p>
            <div id="activity-log" hidden aria-label="Recent agent actions">
              <p class="log-title">Recent steps</p>
              <ol id="activity-log-items"></ol>
            </div>
            <p id="pending"></p>
            <p id="agent-error" hidden></p>
          </div>
          <div id="plan-block">
            <h3>Plan</h3>
            <p id="plan-focus" class="meta"></p>
            <ol id="plan"></ol>
            <details id="plan-why">
              <summary><span class="chevron" aria-hidden="true"></span> Why this plan</summary>
              <p id="plan-reason"></p>
            </details>
          </div>
          <h2>Likely causes</h2>
          <ol id="hypotheses"></ol>
        </div>
        <div id="hitl-banner" class="hitl-banner" hidden>
          <p id="hitl-banner-text">Human approval is needed before the agent continues.</p>
          <button id="open-hitl" type="button">Review approval</button>
        </div>
        <p class="kicker">What was checked</p>
        <ol id="events" class="events"></ol>
        <details>
          <summary>Query checked</summary>
          <pre id="expression"></pre>
        </details>
      </div>
    </section>
  </main>
  <div id="decision" class="decision" role="dialog" aria-modal="true" aria-labelledby="decision-title" hidden>
    <div class="command" role="document">
      <div class="command-head">
        <h2 id="decision-title">Your decision</h2>
        <button id="close-hitl" class="modal-close" type="button" aria-label="Close approval dialog">Close</button>
      </div>
      <p id="lead"></p>
      <div id="review-note" hidden></div>
      <div id="payload" class="payload" hidden></div>
      <p id="effect" class="effect" hidden></p>
      <form id="decision-form">
        <div id="code-fields">
          <p id="shown-code" hidden></p>
          <label for="confirmation">Confirmation code</label>
          <input id="confirmation" autocomplete="off" placeholder="Type the code shown with the command">
        </div>
        <label for="approver">Approver</label>
        <input id="approver" autocomplete="off" value="oncall" placeholder="Your on-call id">
        <label for="command">Note</label>
        <textarea id="command" placeholder="Add a note. The issue stays above."></textarea>
        <div id="controls">
          <div class="actions">
            <button id="approve" type="button">Approve this command</button>
            <button id="edit" class="quiet" type="button">Save note</button>
            <button id="reject" class="quiet" type="button">Reject</button>
          </div>
          <p id="decision-hint" class="hint">Save note keeps this incident open and clears an earlier approval. Reject closes it and leaves the shop unchanged.</p>
        </div>
      </form>
    </div>
  </div>
  <script>
    const list = document.querySelector("#list");
    const title = document.querySelector("#title");
    const state = document.querySelector("#state");
    const lead = document.querySelector("#lead");
    const command = document.querySelector("#command");
    const confirmation = document.querySelector("#confirmation");
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
    const hitlBanner = document.querySelector("#hitl-banner");
    const hitlBannerText = document.querySelector("#hitl-banner-text");
    const openHitl = document.querySelector("#open-hitl");
    const closeHitl = document.querySelector("#close-hitl");
    const flagPolicy = "A checkout or payment incident also sets paymentFailure to off.";
    let current = null;
    let source = null;
    let incidents = [];
    let view = "open";
    let sending = false;
    let listed = "";
    let hitlDismissed = false;
    let hitlKey = "";
    let hitlWasOpen = false;

    function payloadOf(incident) {
      try { return JSON.parse(incident.payload); }
      catch { return {}; }
    }

    function plainText(value) {
      let rest = String(value || "");
      let clean = "";
      while (rest) {
        const open = rest.toLowerCase().indexOf("<untrusted_telemetry");
        if (open < 0) { clean += rest; break; }
        clean += rest.slice(0, open) + " ";
        const close = rest.indexOf(">", open);
        rest = close < 0 ? "" : rest.slice(close + 1);
      }
      return clean.split("</untrusted_telemetry>").join(" ").replace(/\\s+/g, " ").trim();
    }

    function summaryOf(incident) {
      const summary = plainText((payloadOf(incident).annotations || {}).summary);
      if (summary) return summary;
      return readableName(incident.alert_name) + " on " + readableName(incident.service) + ".";
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
      if (incident.agent) return Boolean(incident.agent.proposal);
      return incident.service === "checkout" || incident.service === "payment";
    }

    function fillRows(node, rows) {
      node.replaceChildren();
      for (const row of rows) {
        const item = document.createElement("li");
        if (row.mark) item.className = row.mark;
        const name = document.createElement("span");
        name.textContent = row.name;
        const status = document.createElement("span");
        status.className = "status";
        status.textContent = row.status;
        item.append(name, status);
        node.appendChild(item);
      }
    }

    function storyOf(incident) {
      const view = incident.agent;
      if (!view) return isOpen(incident) ? "The agent just started. The plan shows up here." : decisionLabel(incident) + ".";
      if (view.error) return "The agent stopped before it could finish.";
      const pending = view.pending;
      if (pending && pending.kind === "action") return "The agent has a command. Type the code and approve it.";
      if (pending && pending.kind === "comms" && view.outcome === "escalated") return "No command was run. Review the status note.";
      if (pending && pending.kind === "comms") return "Review the status note before it is published.";
      if (pending) return "Review the lessons the agent wants to remember.";
      if (view.running) return "The agent is investigating. Nothing to approve yet.";
      if (view.outcome) return "Finished: " + view.outcome.replaceAll("_", " ") + ".";
      return "Waiting for the agent.";
    }

    function renderStages(incident) {
      const view = incident.agent || {};
      const finished = !isOpen(incident) || Boolean(view.outcome);
      const currentName = view.error ? (view.plan ? "Plan" : "Alert")
        : finished ? "Done"
        : view.pending ? "Your decision"
        : view.plan ? "Plan"
        : "Alert";
      const reached = {
        "Alert": true,
        "Plan": Boolean(view.plan) && currentName !== "Plan",
        "Your decision": Boolean(view.pending) && currentName !== "Your decision",
        "Done": finished && currentName !== "Done"
      };
      const node = document.querySelector("#stages");
      node.replaceChildren();
      for (const name of ["Alert", "Plan", "Your decision", "Done"]) {
        const item = document.createElement("li");
        item.textContent = name;
        item.className = view.error && name === currentName ? "bad" : name === currentName ? "now" : reached[name] ? "done" : "";
        node.appendChild(item);
      }
    }

    function phaseOf(view) {
      if (!view || !view.running || view.pending || view.error) return "";
      const steps = (view.plan && view.plan.steps) || [];
      let current = "";
      for (const step of steps) if (step.status === "running") current = step.name;
      const named = {
        triage: "Investigating",
        diagnose: "Investigating",
        runbook: "Reading runbooks",
        propose: "Planning the command",
        approve: "Waiting for approval",
        act: "Applying the command",
        verify: "Checking recovery",
        communicate: "Writing the note",
        learn: "Reviewing lessons"
      };
      return named[current] || "Investigating";
    }

    function plainActivity(text) {
      if (!text) return "";
      const named = text.match(/service="([^"]+)"/);
      if (named) {
        const service = readableName(named[1]);
        return text
          .replace(/service="[^"]+"/, service)
          .replace("Checking metrics:", "Checking metrics for")
          .replace("Reading logs:", "Reading logs for")
          .replace("Looking at traces:", "Looking at traces for");
      }
      return text;
    }

    function activityKind(text) {
      const match = String(text || "").match(/^([A-Za-z]+) · /);
      return match ? match[1] : "Step";
    }

    function activityBody(text) {
      return String(text || "").replace(/^[A-Za-z]+ · /, "");
    }

    function renderActivityLog(view) {
      const wrap = document.querySelector("#activity-log");
      const node = document.querySelector("#activity-log-items");
      const rows = (view.activity_log || []).slice().reverse().slice(0, 8);
      wrap.hidden = !rows.length;
      node.replaceChildren();
      for (const row of rows) {
        const item = document.createElement("li");
        const kind = document.createElement("span");
        kind.className = "kind";
        kind.textContent = activityKind(row.text);
        const body = document.createElement("span");
        body.textContent = plainActivity(activityBody(row.text));
        item.append(kind, body);
        node.appendChild(item);
      }
    }

    function renderAgent(incident) {
      const view = incident.agent;
      const panel = document.querySelector("#agent");
      const now = document.querySelector("#now");
      now.textContent = storyOf(incident);
      now.className = view && view.error ? "error" : "";
      renderStages(incident);
      panel.hidden = !view;
      if (!view) return;
      const plan = view.plan || {steps: [], focus: []};
      const focus = (plan.focus || []).map(readableName).join(", ");
      document.querySelector("#plan-focus").textContent = focus ? "Focus: " + focus : "";
      const why = document.querySelector("#plan-why");
      why.hidden = !plan.reason;
      document.querySelector("#plan-reason").textContent = plan.reason || "";
      const stepWord = {
        running: "now", pending: "waiting", done: "done", failed: "failed", skipped: "skipped"
      };
      const steps = plan.steps || [];
      let lastRunning = -1;
      steps.forEach((step, index) => { if (step.status === "running") lastRunning = index; });
      // After escalate, a propose step left "running" should not look active.
      // While HITL is pending, keep approve/communicate/learn as "now".
      const agentIdle = !view.running && !view.pending;
      fillRows(document.querySelector("#plan"), steps.map((step, index) => {
        let status = step.status === "running" && index < lastRunning ? "done" : step.status;
        if (agentIdle && status === "running") {
          status = step.name === "propose" ? "failed" : "skipped";
        } else if (view.pending && status === "running" && step.name === "propose") {
          status = "failed";
        }
        return {
          name: readableName(step.name),
          status: stepWord[status] || status,
          mark: status === "running" ? "running" : status === "failed" ? "failed" : ""
        };
      }));
      const causes = document.querySelector("#hypotheses");
      causes.previousElementSibling.hidden = !(view.hypotheses || []).length;
      causes.hidden = !(view.hypotheses || []).length;
      fillRows(causes, (view.hypotheses || []).map((item) => ({
        name: (item.rank ? item.rank + ". " : "") + readableName(item.service),
        status: String(item.fault_type || "").replaceAll("_", " ") + (item.status ? " · " + item.status : "")
      })));
      const pending = view.pending;
      const phase = phaseOf(view);
      const activity = (!pending && view.running) ? plainActivity(view.activity) : "";
      const live = document.querySelector("#live");
      const liveActivity = document.querySelector("#live-activity");
      live.hidden = !phase;
      document.querySelector("#live .pulse").hidden = !phase;
      const phaseNode = document.querySelector("#phase");
      phaseNode.hidden = !phase;
      phaseNode.textContent = phase;
      liveActivity.hidden = !activity;
      document.querySelector("#live-activity-text").textContent = activity;
      renderActivityLog(view);
      const detail = pending
        ? (pending.kind === "action" ? "Waiting for you to approve the command." :
          pending.kind === "comms" ? "Waiting for you to review the status notes. Approve publishes the external note." :
          "Waiting for you to review the proposed lessons.")
        : "";
      const pendingLine = document.querySelector("#pending");
      pendingLine.textContent = detail;
      pendingLine.className = detail ? "meta" : "";
      const error = document.querySelector("#agent-error");
      error.hidden = !view.error;
      error.textContent = view.error ? "Agent error: " + view.error : "";
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
      if (severity) parts.push(severity.toLowerCase() === "page" ? "Paging" : severity);
      parts.push(isOpen(incident) ? (firing(incident) ? "Alert active" : "Alert cleared") : decisionLabel(incident));
      if (isOpen(incident)) parts.push("open " + age(incident.starts_at));
      parts.push("started " + when(incident.starts_at));
      if (!isOpen(incident)) parts.push("closed " + when(incident.updated_at));
      return parts.join(" · ");
    }

    function leadFor(incident) {
      const open = isOpen(incident);
      const view = incident.agent;
      if (!open && incident.decision === "approve" && writesFlag(incident)) {
        return "Approved. " + flagPolicy + " This view does not run that change again.";
      }
      if (!open && incident.decision === "approve") return "Approved. The shop was left unchanged.";
      if (!open) return "Rejected. The shop was left unchanged.";
      if (view && view.pending && view.pending.kind === "action") {
        const needed = Number(view.pending.required_approvals || 1);
        if (needed > 1) {
          return "Type the confirmation code below. SEV1 needs two different approvers: approve as oncall, then switch Approver to incident-commander and approve again.";
        }
        return "Type the confirmation code below, then approve. The command runs only after that.";
      }
      if (view && view.pending && view.pending.kind === "comms") {
        return view.outcome === "escalated"
          ? "The proposals were refused, so nothing changed in the shop. Approve publishes this note. Reject leaves it unpublished."
          : "Approve publishes this note. Reject leaves it unpublished.";
      }
      if (!view && open) return "Nothing to approve yet. The agent is still working.";
      if (view && view.running && !view.pending) {
        return "Nothing to approve yet. The agent is still working.";
      }
      if (view && view.error) return "The agent stopped. The shop was left unchanged.";
      if (writesFlag(incident)) return "Approving closes this incident. " + flagPolicy;
      return "No allow-listed action was proposed for this service. Approving stores the note and closes this incident.";
    }

    function renderPayload(incident) {
      const flag = writesFlag(incident);
      payload.hidden = !flag;
      effect.hidden = !flag;
      if (!flag) return;
      payload.replaceChildren();
      const proposal = incident.agent && incident.agent.proposal;
      const lines = proposal ? [proposal.command, "rollback: " + proposal.rollback_command, "severity: " + proposal.severity]
        : ["set_flag", "flag: paymentFailure", "value: off"];
      if (incident.proposed_command && !proposal) lines.push(incident.proposed_command);
      if (incident.confirmation_code) lines.push("code: " + incident.confirmation_code);
      for (const line of lines) {
        const row = document.createElement("div");
        row.textContent = line;
        payload.appendChild(row);
      }
      effect.textContent = "Expected effect: payment errors decrease and the checkout error rate returns below the alert threshold.";
    }

    function renderEvents(incident) {
      const items = [];
      const agentEvents = (incident.agent && incident.agent.events) || [];
      if (agentEvents.length) {
        for (const row of agentEvents) {
          items.push([when(row.ts), row.what || "Update."]);
        }
      } else {
        items.push([when(incident.starts_at), "Alert received."]);
      }
      if (incident.decision === "edit") {
        items.push([when(incident.updated_at), "Note saved. Earlier approval cleared."]);
      } else if (incident.decision === "approve" && !(incident.agent && incident.agent.running)) {
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

    function hitlLabel(pendingKind, finished) {
      if (pendingKind === "comms") return "A note is ready for your approval.";
      if (pendingKind === "lessons") return "Lessons are ready for your approval.";
      if (pendingKind === "action") return "A command is waiting for your approval.";
      if (finished) return "The agent finished. Open review only if you want to close this incident.";
      return "Human approval is needed before the agent continues.";
    }

    function setHitlOpen(openModal) {
      const opening = openModal && decision.hidden;
      decision.hidden = !openModal;
      document.body.style.overflow = openModal ? "hidden" : "";
      hitlWasOpen = openModal;
      if (opening) {
        const focusTarget = !document.querySelector("#code-fields").hidden ? confirmation : approve;
        if (focusTarget && typeof focusTarget.focus === "function") focusTarget.focus();
      }
    }

    function show(incident) {
      renderAgent(incident);
      const open = isOpen(incident);
      stream.hidden = false;
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
      renderReview(incident);
      renderEvents(incident);
      if (document.activeElement !== command) command.value = noteFor(incident);
      expression.textContent = plainText(incident.expression) || "No query was stored with this alert.";
      const shownCode = document.querySelector("#shown-code");
      const pendingKind = incident.agent && incident.agent.pending && incident.agent.pending.kind;
      const actionCode = String(incident.confirmation_code || "").trim();
      // Always show the code entry for action HITL. Do not gate on confirmation_code being
      // present yet — a brief publish race used to hide the whole field.
      const waitingForCode = open && pendingKind === "action";
      document.querySelector("#code-fields").hidden = !waitingForCode;
      shownCode.hidden = !waitingForCode;
      shownCode.textContent = waitingForCode
        ? (actionCode ? "Code to type: " + actionCode : "Type the confirmation code for this command.")
        : "";
      if (waitingForCode && document.activeElement !== confirmation) confirmation.value = "";
      confirmation.placeholder = actionCode || "Type the code shown with the command";
      confirmation.required = waitingForCode;
      command.readOnly = !open;
      const stillWorking = incident.agent && incident.agent.running && !(incident.agent.pending);
      const waitingOnYou = Boolean(pendingKind);
      const agentFinishedOpen = incident.agent
        && !incident.agent.running
        && !incident.agent.pending
        && Boolean(incident.agent.outcome);
      // Popup only for a real HITL wait. Finished/escalated incidents stay quiet unless Review is clicked.
      const autoHitl = open && waitingOnYou;
      const nextKey = autoHitl
        ? [incident.id, pendingKind || "", incident.confirmation_code || "", (incident.agent.pending || {}).command || ""].join("|")
        : "";
      if (nextKey !== hitlKey) {
        hitlKey = nextKey;
        hitlDismissed = false;
      }
      const form = document.querySelector("#decision-form");
      form.hidden = open && !waitingOnYou && !agentFinishedOpen;
      // Show controls for a real HITL wait, or to close a finished escalated/no-action incident.
      controls.hidden = !open || stillWorking || (incident.agent && !waitingOnYou && !agentFinishedOpen);
      approve.textContent = pendingKind === "comms" ? "Approve this note"
        : pendingKind === "lessons" ? "Approve these lessons"
        : writesFlag(incident) && waitingOnYou ? "Approve this command"
        : "Approve and close";
      const needsTwo = pendingKind === "action" && Number((incident.agent.pending || {}).required_approvals || 1) > 1;
      document.querySelector("#decision-hint").textContent = pendingKind === "comms" || pendingKind === "lessons"
        ? "Reject leaves this unpublished and keeps the incident open."
        : needsTwo
          ? "Use two different Approver ids (oncall, then incident-commander). Approving twice as oncall does nothing."
          : "Save note keeps this incident open and clears an earlier approval. Reject closes it and leaves the shop unchanged.";
      hitlBannerText.textContent = hitlLabel(pendingKind, agentFinishedOpen);
      hitlBanner.hidden = !(open && (waitingOnYou || agentFinishedOpen));
      setHitlOpen(autoHitl && !hitlDismissed);
    }

    function renderReview(incident) {
      const box = document.querySelector("#review-note");
      const pending = incident.agent && incident.agent.pending;
      const note = pending && pending.external;
      const lessons = pending && pending.lessons;
      box.hidden = !(note || (lessons && lessons.length));
      if (note) {
        box.textContent = [note.title, note.body].filter(Boolean).join(" ");
        return;
      }
      if (lessons && lessons.length) {
        box.textContent = lessons.map((lesson) => lesson.lesson || lesson.text || JSON.stringify(lesson)).join(" ");
        return;
      }
      box.textContent = "";
    }

    function showEmpty() {
      const closedView = view === "closed";
      title.textContent = closedView ? "No closed incidents" : "No open incidents";
      state.textContent = closedView
        ? "Approved and rejected incidents show up here."
        : "Approved and rejected incidents stay on Closed.";
      state.className = "meta";
      stream.hidden = true;
      hitlBanner.hidden = true;
      hitlDismissed = false;
      hitlKey = "";
      setHitlOpen(false);
      command.value = "";
      issue.textContent = "";
      alertName.textContent = "";
      expression.textContent = "";
    }

    function queueDetail(incident) {
      const severity = severityOf(incident);
      const severityLabel = severity.toLowerCase() === "page" ? "Paging" : severity;
      const prefix = severityLabel ? severityLabel + " · " : "";
      if (!isOpen(incident)) return prefix + decisionLabel(incident) + " · " + when(incident.updated_at);
      const agent = incident.agent;
      const label = agent && agent.error ? "Stopped" :
        agent && agent.pending ? "Needs you" :
        agent && agent.running ? "Working" :
        incident.decision === "edit" ? "Edited" : (firing(incident) ? "Firing" : "Not firing");
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
          message.textContent = "That incident is no longer on the server.";
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
      hitlDismissed = false;
      hitlKey = "";
      message.textContent = "";
      if (source) source.close();
      source = new EventSource("/incidents/" + id + "/stream");
      source.onmessage = (event) => show(JSON.parse(event.data));
      source.addEventListener("missing", () => {
        current = null;
        source.close();
        setHitlOpen(false);
        hitlBanner.hidden = true;
        message.textContent = "That incident is no longer on the server.";
        loadList();
      });
      renderList();
    }

    async function send(decisionName) {
      if (!current || sending) return;
      const needsCode = !document.querySelector("#code-fields").hidden;
      if (decisionName === "approve" && needsCode && !confirmation.value.trim()) {
        message.textContent = "Type the code shown above, then approve.";
        return;
      }
      sending = true;
      message.textContent = "";
      try {
        const response = await fetch("/incidents/" + current + "/decision", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            decision: decisionName,
            text: command.value,
            confirmation: confirmation.value,
            approver: document.querySelector("#approver").value || "oncall"
          })
        });
        if (!response.ok) {
          let detail = await response.text();
          try { detail = JSON.parse(detail).detail || detail; } catch (error) { /* keep the raw body */ }
          if (response.status === 404) {
            current = null;
            if (source) source.close();
            message.textContent = "That incident is no longer on the server.";
            await loadList();
            return;
          }
          message.textContent = detail;
          return;
        }
        const body = await response.json();
        const service = readableName(body.service);
        const closed = body.decision === "approve" || body.decision === "reject";
        if ((decisionName === "approve" || decisionName === "reject") && closed) {
          current = null;
          if (source) source.close();
          await loadList();
          message.textContent = decisionName === "approve"
            ? (body.flag_result ? service + " closed. " + body.flag_result + "." : service + " closed.")
            : service + " closed. The shop was left unchanged.";
          return;
        }
        show(body);
        const stillAction = body.agent && body.agent.pending && body.agent.pending.kind === "action";
        const lastWhat = ((body.agent && body.agent.events) || []).slice(-1)[0];
        const approvalNote = lastWhat && String(lastWhat.what || "");
        if (decisionName === "edit") {
          message.textContent = "Saved. The earlier approval was cleared.";
        } else if (stillAction && /duplicate_approver/.test(approvalNote)) {
          message.textContent = "Same approver already voted. Switch Approver to incident-commander, then approve again.";
        } else if (stillAction && /awaiting_second_approver|Approval not complete/.test(approvalNote)) {
          message.textContent = "First vote recorded. Switch Approver to a different id (incident-commander), then approve again.";
        } else if (stillAction) {
          message.textContent = "Recorded. This command still needs approval before it runs.";
        } else {
          message.textContent = "Recorded. This incident stays open for the next step.";
        }
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
    openHitl.addEventListener("click", () => {
      hitlDismissed = false;
      setHitlOpen(true);
    });
    closeHitl.addEventListener("click", () => {
      hitlDismissed = true;
      setHitlOpen(false);
    });
    decision.addEventListener("click", (event) => {
      if (event.target === decision) {
        hitlDismissed = true;
        setHitlOpen(false);
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !decision.hidden) {
        hitlDismissed = true;
        setHitlOpen(false);
      }
    });
    loadList();
    setInterval(loadList, 5000);
  </script>
</body>
</html>
"""
