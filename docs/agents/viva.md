# Viva Notes: Agents and Orchestration

Short answers to the questions the guide says every member must handle, for role 3's part.

**Redraw the architecture.**

- Alert → incident API → graph thread.
- intake → plan (commander) → triage → parallel diagnosis (`Send`) → assess.
- From assess: runbook → propose → **approve (interrupt)** → act → verify, with rollback and replan on failure.
- Then communicate → **review (interrupt)** → **learn (interrupt)**.
- Every tool call goes through role 4's hooks. The state is checkpointed in SQLite after every step.

**What does the model decide, what does code decide, what does a person decide?**

- **The model decides:**
  - which suspects to test and how to spend the tool budget;
  - the hypotheses and how they rank;
  - which single action to propose;
  - the wording of the notes and postmortem.
- **Code decides:**
  - which evidence is real (grounding);
  - refuting a hypothesis whose flag the change log shows as off;
  - whether a lesson applies (preconditions);
  - severity;
  - the dry run, the rollback and the expected effect;
  - whether recovery was sustained;
  - all budgets, loops and allow-lists.
- **A person decides:** every action (with the exact command and its code; SEV1 needs two people), every external note, and every lesson that is stored.

**Why a team rather than one agent?**

- **Narrow tools per role.** Diagnosis cannot write; only remediation reaches ops tools, and only after approval.
- **Parallel diagnosis** tests several suspects at once within a shared budget.
- **A stronger commander only where planning happens.**
- **Typed hand-offs** let code check each stage.
- **E1 measures whether this pays for its cost** against C1 (one agent, same tools and budget) and C0 (no model). Until the model runs are done, the honest answer is: here is the comparison set up, here is C0, and C1 and C2 are pending.

**Show a replan.**

- assess finds the top hypothesis refuted, for example because the flag it names is off.
- The replan hook checks the limit.
- The commander writes plan v2 with the contradiction as its reason, and diagnosis runs again.
- Trace: traces/wrong-first-hypothesis-scripted.md (mechanism check). A real-model trace comes from the same command with the key set.

**How do you stop and resume?**

- A SQLite checkpointer saves state after every step.
- `graph.cli run --crash-after assess` exits the process; `graph.cli resume` continues in a new one.
- In the API, `resume_unfinished` continues any run that stopped mid-step at startup. Runs waiting for a person keep waiting.

**What if a fix does not work?**

- Verification samples through the window.
- If the effect is not sustained, the rollback that was approved together with the action runs, and the team replans.
- After repeated rollbacks the hook halts the incident, and the agent alert `CopilotRepeatedRollbacks` fires.

**What do the lessons learn, and how do you know they help?**

- Reflexion on development cases only. Code evaluates against the injected fault, the reflection step writes a lesson with observable preconditions, a person reviews it, and the playbook is frozen.
- E3 compares held-out success with and without the frozen playbook, 3 runs each.
- A misleading lesson (pm-006) is rejected when its preconditions fail. E4 measures this with memory on and off.

**What is the shop twin, and is it cheating?**

- It answers the same tool names from a case's injected flags, so development and CI run offline.
- It never exposes the ground truth to the agent.
- Held-out results come from the live shop. Twin results are labelled as twin results.

**Known limits.**

- Restart, scale and deploy rollback are validated but not executable here (no Kubernetes write client).
- flagd keeps no change history, so live `recent_changes` reports each active flag as observed now.
- The approval service is in memory, so after an API restart a pending approval is proposed again under a new request (the code is the same, since it is bound to the command).
