# Contribution log

Assign a name to each role on day 1 and append dated entries. Two separations keep results honest: the person tuning the agent does not write held-out cases; the person building defences does not write the attacks.

**Repository:** https://github.com/IITB-Project-Group/On-Call-Copilot

| Role | Owner | Owns |
| --- | --- | --- |
| 2 Knowledge & memory engineer | Siddesh R Vagal | Corpus, retrieval, memory store + policy (L4–L6, L9) |
| 3 Agents & orchestration engineer | Deepen Mantri | LangGraph graph, planner, specialists, Reflexion (L8, L10–L12) |
| 4 Tools, control & security engineer | Smarak Mishra / Ananda Narayanan G | MCP servers, hooks, approval gate, guardrails, threat model (L7, L14, L15) |
| 5 Evaluation & red-team engineer | Manam Navaneeswar / Ananda Narayanan G | Harness, judge calibration, held-out cases, red-team suite, experiments (L13, L15) |
| 6 Deployment & operations engineer | Chittaranjan Swain | FastAPI + GUI, kind/`up.sh`, CI eval gate, tracing, dashboards, alerts (L13, L16) |

## Dated entries (from merged work on `main`)

| Date | Role(s) | What | Evidence |
| --- | --- | --- | --- |
| 2026-10-28 | 6 | Incident console shows service, investigation, exact command | PR [#3](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/3) |
| 2026-10-29 | 6 | Separate issue, severity, and operator note on the console | PR [#4](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/4) |
| 2026-11-05 | 2 / 6 | Knowledge API + tool servers wired to in-process KB | PR [#5](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/5) |
| 2026-11-05 | 4 | Safety layer on the incident API (hooks, guardrails, approval path) | PR [#6](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/6) |
| 2026-11-05 | 4 / 7 | Live shop data screened before it can be followed as an instruction | PR [#8](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/8) |
| 2026-11-05 | 6 / 7 | Shop tools reach the services this cluster exposes | PR [#7](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/7) |
| 2026-11-05 | 1 / 6 | Project status + integration roadmap docs | PRs [#9](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/9), [#10](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/10) |
| 2026-11-10 | 3 | Agents orchestration (LangGraph team, specialists, checkpointer) | PR [#11](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/11) |
| 2026-11-10 | 3 / 6 | Incident graph wired to the live shop; live agent integration | PRs [#13](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/13), [#14](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/14) |
| 2026-11-10 | 6 | Grafana agent panels + live observability | PR [#15](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/15) |
| 2026-11-10 | 3 / 6 | Plan/decision controls after escalate; keep open after approve until graph finishes | PRs [#16](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/16), [#17](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/17) |
| 2026-11-11 | 1 / 3 | Redrawn architecture figures + numbered walkthrough | PR [#18](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/18) · `docs/ARCHITECTURE.md` |
| 2026-11-11 | 4 / 5 | `oncall-security`: red-team, governance controls, reports, CI gate | PR [#19](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/19) |
| 2026-11-12 | 1 / 6 | Backup demo recording | PR [#20](https://github.com/IITB-Project-Group/On-Call-Copilot/pull/20) · `Demo/video1909353936.mp4` |
| ongoing | 3 / 5 | Twin E1/E3/E4 runs, experiment log, Reflexion drafts awaiting human review | `docs/agents/evaluation.md`, `docs/agents/experiment-log.md`, `eval/` |

