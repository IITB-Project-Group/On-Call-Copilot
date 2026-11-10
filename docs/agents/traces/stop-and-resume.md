# Stop and resume (L8)

Fixed workflow (C0) on the shop twin, case dev-f1-50pct. The process exits after `assess` (`--crash-after assess`, exit code 3); a new process resumes from the SQLite checkpoint. Console transcript: stop-and-resume-console.txt.


Alert: {'alert_name': 'ServiceErrorRateHigh', 'service': 'checkout', 'starts_at': '2026-11-07T11:09:15+00:00'}. Experiment `cli-c0`, config `2026-11-07.1`, models {'commander': 'openai/gpt-4.1', 'specialist': 'openai/gpt-4.1-mini'}.

2. +0.00s **Plan v1**: focus ['checkout']. Fixed plan: investigate the alerting service.
3. +0.01s `triage` called `promql_query` {"query": "copilot:service_error_ratio:5m"} -> ok
4. +0.01s `triage` called `promql_query` {"query": "copilot:service_p95_latency_seconds:2m"} -> ok
5. +0.01s `triage` called `promql_query` {"query": "copilot:container_cpu_ratio"} -> ok
6. +0.01s `triage` called `promql_query` {"query": "copilot:memory_growth_ratio:5m"} -> ok
7. +0.01s `triage` called `promql_query` {"query": "copilot:kafka_consumer_lag"} -> ok
8. +0.01s `triage` called `promql_query` {"query": "copilot:service_request_rate:2m"} -> ok
9. +0.01s `triage` called `recent_changes` {"lookback_s": 3600} -> ok
11. +0.02s **Assess** -> `runbook`. Hypotheses: 1. payment error_injection paymentFailure [supported].
12. +0.97s `runbook` called `runbook_search` {"query": "payment error_injection"} -> ok
14. +0.98s `remediation` called `ops_dry_run` {"action": {"type": "set_flag", "args": {"flag": "paymentFailure", "enabled": false}}} -> ok
15. +0.98s **Proposal** `ops-actions set_flag --enabled false --flag paymentFailure` (rollback `ops-actions set_flag --enabled true --flag paymentFailure`, SEV1, code 0A0447AA)
16. +2.09s **Engineer decision** on action: {"decision": "approve", "approver": "eval-oncall", "text": "", "comms_approver": "incident-commander"}
17. +3.23s **Engineer decision** on action: {"decision": "approve", "approver": "eval-oncall-2", "text": "", "comms_approver": "incident-commander"}
18. +3.24s `remediation` called `ops_set_flag` {"action": {"type": "set_flag", "args": {"flag": "paymentFailure", "enabled": false}}, "approval_request_id": "29f76e8fd7774d0f9efcf3afb271e -> ok
19. +3.24s **Action** ok=True 
20. +3.25s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:49+00:00#0"} -> ok
21. +3.25s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:49+00:00#1"} -> ok
22. +3.25s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:49+00:00#2"} -> ok
23. +3.25s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:49+00:00#3"} -> ok
24. +3.25s **Verification** samples [0.5, 0.002, 0.002, 0.002] -> recovered=True
25. +3.25s `comms` called `status_draft` {"incident_id": "dev-f1-50pct-demo", "note": {"audience": "internal", "title": "checkout: resolved", "body": "Alert on checkout. Top hypothe -> ok
26. +3.25s `comms` called `postmortem_draft` {"incident_id": "dev-f1-50pct-demo", "postmortem": {"summary": "Alert on checkout; outcome resolved.", "impact": "Customers on the affected  -> ok
28. +4.37s **Engineer decision** on comms: {"decision": "approve", "approver": "eval-oncall", "text": "", "comms_approver": "incident-commander"}
29. +4.37s `comms` called `status_publish_external` {"note": {"audience": "external", "title": "Service disruption resolved", "body": "Some customers saw errors or slow pages. Service has reco -> ok
