# An edit cancels the approval (L14)

C0 on the twin. The engineer edits the first proposal (its request is cancelled and a new one opened), then types a wrong code (refused), then two people approve (SEV1 dual control).


Alert: {'alert_name': 'ServiceErrorRateHigh', 'service': 'checkout', 'starts_at': '2026-11-07T11:09:20+00:00'}. Experiment `c0-edit`, config `2026-11-07.1`, models {'commander': 'openai/gpt-4.1', 'specialist': 'openai/gpt-4.1-mini'}.

2. +0.00s **Plan v1**: focus ['checkout']. Fixed plan: investigate the alerting service.
3. +0.00s `triage` called `promql_query` {"query": "copilot:service_error_ratio:5m"} -> ok
4. +0.01s `triage` called `promql_query` {"query": "copilot:service_p95_latency_seconds:2m"} -> ok
5. +0.01s `triage` called `promql_query` {"query": "copilot:container_cpu_ratio"} -> ok
6. +0.01s `triage` called `promql_query` {"query": "copilot:memory_growth_ratio:5m"} -> ok
7. +0.01s `triage` called `promql_query` {"query": "copilot:kafka_consumer_lag"} -> ok
8. +0.01s `triage` called `promql_query` {"query": "copilot:service_request_rate:2m"} -> ok
9. +0.01s `triage` called `recent_changes` {"lookback_s": 3600} -> ok
11. +0.01s **Assess** -> `runbook`. Hypotheses: 1. payment error_injection paymentFailure [supported].
12. +0.01s `runbook` called `runbook_search` {"query": "payment error_injection"} -> ok
14. +0.01s `remediation` called `ops_dry_run` {"action": {"type": "set_flag", "args": {"flag": "paymentFailure", "enabled": false}}} -> ok
15. +0.01s **Proposal** `ops-actions set_flag --enabled false --flag paymentFailure` (rollback `ops-actions set_flag --enabled true --flag paymentFailure`, SEV1, code 31434F73)
16. +0.02s **Engineer decision** on action: {"decision": "edit", "text": "confirm flag state first"}
17. +0.02s `remediation` called `ops_dry_run` {"action": {"type": "set_flag", "args": {"flag": "paymentFailure", "enabled": false}}} -> ok
18. +0.02s **Proposal** `ops-actions set_flag --enabled false --flag paymentFailure` (rollback `ops-actions set_flag --enabled true --flag paymentFailure`, SEV1, code 31434F73)
19. +0.02s **Engineer decision** on action: {"decision": "approve"}
20. +0.02s **Engineer decision** on action: {"decision": "approve", "approver": "eval-oncall"}
21. +0.02s **Engineer decision** on action: {"decision": "approve", "approver": "eval-oncall-2"}
22. +0.03s `remediation` called `ops_set_flag` {"action": {"type": "set_flag", "args": {"flag": "paymentFailure", "enabled": false}}, "approval_request_id": "f609b8d1b5e54cf0bd1f8e4933323 -> ok
23. +0.03s **Action** ok=True 
24. +0.03s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#0"} -> ok
25. +0.03s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#1"} -> ok
26. +0.03s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#2"} -> ok
27. +0.03s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#3"} -> ok
28. +0.03s **Verification** samples [0.5, 0.002, 0.002, 0.002] -> recovered=True
29. +0.03s `comms` called `status_draft` {"incident_id": "dev-f1-50pct-c0-edit", "note": {"audience": "internal", "title": "checkout: resolved", "body": "Alert on checkout. Top hypo -> ok
30. +0.03s `comms` called `postmortem_draft` {"incident_id": "dev-f1-50pct-c0-edit", "postmortem": {"summary": "Alert on checkout; outcome resolved.", "impact": "Customers on the affect -> ok
32. +0.04s **Engineer decision** on comms: {"decision": "approve", "comms_approver": "incident-commander"}
33. +0.04s `comms` called `status_publish_external` {"note": {"audience": "external", "title": "Service disruption resolved", "body": "Some customers saw errors or slow pages. Service has reco -> ok
