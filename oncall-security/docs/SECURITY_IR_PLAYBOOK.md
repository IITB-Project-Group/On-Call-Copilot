# Security incident response playbook: AI agent incidents (MON-03)

Triggers: SecurityMonitor events SM-01..SM-07, Prometheus alerts CopilotInjectionAttempt / CopilotRepeatedRollbacks /
CopilotLoopDetected, red-team regression in CI, a secret-scan hit, or a report from an engineer.

## 1. Triage (security_admin, 15 min)
Classify: injection attempt | approval abuse | credential exposure | integrity (audit, runbook, code) | runaway agent.
Severity: S1 = an unapproved or harmful change reached production, or a credential leaked outside the team;
S2 = control defeated without production impact; S3 = attempt fully blocked.

## 2. Containment
- S1/S2: `POST /control/kill-switch {"on": true}` (IC or security_admin) -- stops every agent call, rollbacks included.
- Approval abuse: `POST /control/pause`; disable the user token (`UserStore.disable`); rotate all approver tokens.
- Credential exposure: revoke and rotate the key at the provider first, then purge it from the repository history.
- Integrity: verify the audit chain and anchor (`check_anchor`), runbook signatures and the code manifest; redeploy
  from a signed release if anything is MODIFIED.

## 3. Eradication and recovery
Fix the root cause, add a red-team attack that reproduces it (oncall_redteam/attacks.py), confirm it fails against the
fix, then lift the kill switch (IC + security_admin, two people).

## 4. Lessons
Post-incident review within 5 working days; update the risk register, the policy thresholds and the threat model.
