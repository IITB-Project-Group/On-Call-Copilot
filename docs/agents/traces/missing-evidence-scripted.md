# Missing evidence ends with a person, not a guess (mechanism check)

**Scripted model.** Jaeger is down (every trace_search fails). Without trace evidence no hypothesis is supported, the team replans within its limit, and then escalates.


Alert: {'alert_name': 'ServiceErrorRateHigh', 'service': 'checkout', 'starts_at': '2026-11-07T11:09:20+00:00'}. Experiment `c2-scripted-missing-evidence`, config `2026-11-07.1`, models {'commander': 'openai/gpt-4.1', 'specialist': 'openai/gpt-4.1-mini'}.

2. +0.00s `commander` model step 1: calls ['submit']
3. +0.00s `commander` handed off (submitted): {"focus": ["checkout", "payment"], "goals": {"triage": "look"}, "reason": "start at the alert"}
4. +0.00s **Plan v1**: focus ['checkout', 'payment']. start at the alert
5. +0.00s `triage` model step 1: calls ['promql_query']
6. +0.00s `triage` called `promql_query` {"query": "copilot:service_error_ratio:5m"} -> ok
7. +0.00s `triage` model step 2: calls ['recent_changes']
8. +0.00s `triage` called `recent_changes` {"lookback_s": 3600} -> ok
9. +0.01s `triage` model step 3: calls ['submit']
10. +0.01s `triage` handed off (submitted): {"no_fault": false, "affected_services": ["checkout", "frontend"], "suspects": ["checkout", "frontend"], "error_rate": 0.9, "p99_latency_ms": 0.0, "availability_down": false, "active_flags": ["paymentUnreachable"], "evidence": ["change:0:635ce09c7d", "metric:1497d4d2af:0", "metric:1497d4d2af:1", "me
12. +0.01s `triage` called `incident_record_update` {"incident_id": "mechanism-dependency-unreachable-c2-scripted-missing-evidence", "fields": {"affected_services": ["checkout", "frontend"], " -> ok
13. +0.01s Lessons whose preconditions match: []
14. +0.01s `diagnosis` model step 1: calls ['trace_search']
15. +0.01s `diagnosis` called `trace_search` {"service": "checkout", "lookback_s": 1800, "limit": 10, "status": "ERROR"} -> refused (tool_error:RuntimeError)
16. +0.01s `diagnosis` model step 2: calls ['recent_changes']
17. +0.01s `diagnosis` called `recent_changes` {"lookback_s": 3600} -> ok (cached)
18. +0.01s `diagnosis` model step 3: calls ['submit']
19. +0.01s `diagnosis` handed off (submitted): {"investigator": "", "no_fault": false, "hypotheses": [{"id": "a", "rank": 1, "service": "checkout", "fault_type": "dependency_unreachable", "status": "supported", "evidence": ["change:0:635ce09c7d"], "flag": "paymentUnreachable", "rationale": "paymentUnreachable is on"}, {"id": "b", "rank": 2, "ser
20. +0.01s **Assess** -> `runbook`. Hypotheses: 1. checkout dependency_unreachable paymentUnreachable [supported]; 2. checkout crash  [proposed]; 3. checkout hang  [proposed].
21. +0.01s `runbook` model step 1: calls ['runbook_search']
22. +0.01s `runbook` called `runbook_search` {"query": "payment errors"} -> ok
23. +0.01s `runbook` model step 2: calls ['memory_search']
24. +0.02s `runbook` called `memory_search` {"query": "similar incidents"} -> ok
25. +0.02s `runbook` model step 3: calls ['submit']
26. +0.02s `runbook` handed off (submitted): {"runbook_ids": ["payment-failure"], "recommended_action": null, "lessons": [], "unsafe_steps": [], "notes": "scripted"}
28. +0.02s `remediation` model step 1: calls ['submit']
29. +0.02s `remediation` handed off (submitted): {"hypothesis_id": "h1", "action": {"type": "set_flag", "flag": "paymentUnreachable", "enabled": false, "service": null, "replicas": null, "to_version": null}, "rationale": "switch the injecting flag off"}
30. +0.02s `remediation` called `ops_dry_run` {"action": {"type": "set_flag", "args": {"flag": "paymentUnreachable", "enabled": false}}} -> ok
31. +0.02s **Proposal refused** by the guardrails: ['target_mismatch'] ok
32. +0.02s `commander` model step 1: calls ['submit']
33. +0.02s `commander` handed off (submitted): {"focus": ["payment"], "goals": {}, "reason": "the first hypothesis was refuted; test payment again"}
34. +0.02s **Replan v2**: focus ['payment']. the first hypothesis was refuted; test payment again
35. +0.02s Lessons whose preconditions match: []
36. +0.02s `diagnosis` model step 1: calls ['trace_search']
37. +0.02s `diagnosis` called `trace_search` {"service": "payment", "lookback_s": 1800, "limit": 10, "status": "ERROR"} -> refused (tool_error:RuntimeError)
38. +0.02s `diagnosis` model step 2: calls ['recent_changes']
39. +0.02s `diagnosis` called `recent_changes` {"lookback_s": 3600} -> ok (cached)
40. +0.02s `diagnosis` model step 3: calls ['submit']
41. +0.02s `diagnosis` handed off (submitted): {"investigator": "", "no_fault": false, "hypotheses": [{"id": "a", "rank": 1, "service": "payment", "fault_type": "dependency_unreachable", "status": "supported", "evidence": ["change:0:635ce09c7d"], "flag": "paymentUnreachable", "rationale": "paymentUnreachable is on"}, {"id": "b", "rank": 2, "serv
42. +0.02s **Assess** -> `runbook`. Hypotheses: 1. payment dependency_unreachable paymentUnreachable [supported]; 2. payment crash  [proposed]; 3. checkout hang  [proposed].
43. +0.03s `runbook` model step 1: calls ['runbook_search']
44. +0.03s `runbook` called `runbook_search` {"query": "payment errors"} -> ok (cached)
45. +0.03s `runbook` model step 2: calls ['memory_search']
46. +0.03s `runbook` called `memory_search` {"query": "similar incidents"} -> ok (cached)
47. +0.03s `runbook` model step 3: calls ['submit']
48. +0.03s `runbook` handed off (submitted): {"runbook_ids": ["payment-failure"], "recommended_action": null, "lessons": [], "unsafe_steps": [], "notes": "scripted"}
50. +0.03s `remediation` model step 1: calls ['submit']
51. +0.03s `remediation` handed off (submitted): {"hypothesis_id": "h1", "action": {"type": "set_flag", "flag": "paymentUnreachable", "enabled": false, "service": null, "replicas": null, "to_version": null}, "rationale": "switch the injecting flag off"}
52. +0.03s `remediation` called `ops_dry_run` {"action": {"type": "set_flag", "args": {"flag": "paymentUnreachable", "enabled": false}}} -> ok
53. +0.03s **Proposal** `ops-actions set_flag --enabled false --flag paymentUnreachable` (rollback `ops-actions set_flag --enabled true --flag paymentUnreachable`, SEV1, code C37A53EE)
54. +0.03s **Engineer decision** on action: {"decision": "approve", "approver": "eval-oncall"}
55. +0.04s **Engineer decision** on action: {"decision": "approve", "approver": "eval-oncall-2"}
56. +0.04s `remediation` called `ops_set_flag` {"action": {"type": "set_flag", "args": {"flag": "paymentUnreachable", "enabled": false}}, "approval_request_id": "a1f821fe0de84f9d8d1f20ae9 -> ok
57. +0.04s **Action** ok=True 
58. +0.04s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#0"} -> ok
59. +0.04s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#1"} -> ok
60. +0.04s `remediation` called `promql_query` {"query": "copilot:service_error_ratio:5m{service=\"payment\"}", "time": "2026-11-07T11:28:50+00:00#2"} -> ok
61. +0.04s **Verification** samples [0.002, 0.002, 0.002] -> recovered=True
62. +0.04s `comms` model step 1: calls ['submit']
63. +0.04s `comms` handed off (submitted): {"internal": {"audience": "internal", "title": "Incident update", "body": "Checkout errors were fixed.", "severity": "SEV2"}, "external": {"audience": "external", "title": "Some checkouts failed", "body": "Some customers could not check out. It is resolved.", "severity": "SEV2"}, "summary": "s", "im
64. +0.04s `comms` called `status_draft` {"incident_id": "mechanism-dependency-unreachable-c2-scripted-missing-evidence", "note": {"audience": "internal", "title": "Incident update" -> ok
65. +0.04s `comms` called `postmortem_draft` {"incident_id": "mechanism-dependency-unreachable-c2-scripted-missing-evidence", "postmortem": {"summary": "s", "impact": "i", "timeline": [ -> ok
67. +0.05s **Engineer decision** on comms: {"decision": "approve", "comms_approver": "incident-commander"}
68. +0.05s `comms` called `status_publish_external` {"note": {"audience": "external", "title": "Some checkouts failed", "body": "Some customers could not check out. It is resolved.", "severity -> ok
