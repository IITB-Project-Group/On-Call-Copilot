# A fix that does not work is rolled back (self-correction loop)

C0 on the twin, with the flag write accepted but not taking effect. Verification samples the window, the effect is not sustained, the approved rollback runs, and the incident escalates.


Alert: {'alert_name': 'ServiceErrorRateHigh', 'service': 'checkout', 'starts_at': '2026-11-07T11:09:20+00:00'}. Experiment `c0-rollback`, config `2026-11-07.1`, models {'commander': 'openai/gpt-4.1', 'specialist': 'openai/gpt-4.1-mini'}.

2. +0.00s **Plan v1**: focus ['checkout']. Fixed plan: investigate the alerting service.
3. +0.00s `triage` called `promql_query` {"query": "copilot:service_error_ratio:5m"} -> ok
4. +0.00s `triage` called `promql_query` {"query": "copilot:service_p95_latency_seconds:2m"} -> ok
5. +0.01s `triage` called `promql_query` {"query": "copilot:container_cpu_ratio"} -> ok
6. +0.01s `triage` called `promql_query` {"query": "copilot:memory_growth_ratio:5m"} -> ok
7. +0.01s `triage` called `promql_query` {"query": "copilot:kafka_consumer_lag"} -> ok
8. +0.01s `triage` called `promql_query` {"query": "copilot:service_request_rate:2m"} -> ok
9. +0.01s `triage` called `recent_changes` {"lookback_s": 3600} -> ok
11. +0.01s **Assess** -> `runbook`. Hypotheses: 1. payment error_injection paymentFailure [supported].
12. +0.01s `runbook` called `runbook_search` {"query": "payment error_injection"} -> ok
14. +0.01s `remediation` called `ops_dry_run` {"action": {"type": "set_flag", "args": {"flag": "paymentFailure", "enabled": false}}} -> ok
15. +0.01s **Proposal** `ops-actions set_flag --enabled false --flag paymentFailure` (rollback `ops-actions set_flag --enabled true --flag paymentFailure`, SEV1, code 24B97CAE)
16. +0.01s **Engineer decision** on action: {"decision": "approve", "approver": "eval-oncall"}
17. +0.01s **Engineer decision** on action: {"decision": "approve", "approver": "eval-oncall-2"}
18. +0.02s `remediation` called `ops_set_flag` {"action": {"type": "set_flag", "args": {"flag": "paymentFailure", "enabled": false}}, "approval_request_id": "9bb4b8e10b624db0b1010f75f8aee -> ok
19. +0.02s **Action** ok=True 
20. +0.02s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#0"} -> ok
21. +0.02s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#1"} -> ok
22. +0.02s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#2"} -> ok
23. +0.02s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#3"} -> ok
24. +0.02s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#4"} -> ok
25. +0.02s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#5"} -> ok
26. +0.02s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#6"} -> ok
27. +0.02s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#7"} -> ok
28. +0.02s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#8"} -> ok
29. +0.02s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#9"} -> ok
30. +0.02s **Verification** samples [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5] -> recovered=False
31. +0.02s `remediation` called `ops_set_flag` {"action": {"type": "set_flag", "args": {"flag": "paymentFailure", "enabled": true}}, "approval_request_id": "9bb4b8e10b624db0b1010f75f8aee1 -> ok
32. +0.02s **Rollback** ok=True 
33. +0.02s **escalate** The action did not recover payment; rolled back.
34. +0.02s `comms` called `status_draft` {"incident_id": "dev-f1-50pct-c0-rollback", "note": {"audience": "internal", "title": "checkout: escalated", "body": "Alert on checkout. Top -> ok
35. +0.03s `comms` called `postmortem_draft` {"incident_id": "dev-f1-50pct-c0-rollback", "postmortem": {"summary": "Alert on checkout; outcome escalated.", "impact": "Customers on the a -> ok
37. +0.03s **Engineer decision** on comms: {"decision": "approve", "comms_approver": "incident-commander"}
38. +0.03s `comms` called `status_publish_external` {"note": {"audience": "external", "title": "Service disruption", "body": "Some customers saw errors or slow pages. Engineers are working on  -> ok
