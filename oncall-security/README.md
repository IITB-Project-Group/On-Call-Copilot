# oncall-security v1.1 — red team and governance for the live On-Call Copilot

**Start with `../TESTING.md`** (or `../run_tests.sh`). v1.1 targets the live product in `../On-Call-Copilot-main`
(incident_api + safety/) automatically; the v2-simulator path still works when `oncall_copilot` is importable.

Live results (reports/): baseline 6/66 attacks succeed, hardened 0/66; false positives 1/279; hardened gate PASSES
once reviewed runbooks are pinned (`govern pin-runbooks`). The section below describes v1.0 against the v2 reference;
its numbers are for that simulator and are archived in `reports/v2-reference/`.

---

## (v1.0) oncall-security — red-team testing and security governance for the On-Call Copilot v2

Two packages that work on the delivered **On-Call Copilot v2** without modifying it:

| Package | What it does |
|---|---|
| `oncall_redteam` | 66 attacks (prompt injection incl. 16 obfuscation variants, excessive agency, approval bypass, sensitive data, unbounded consumption, integrity/supply chain, output handling, deployment) with **code oracles**, mapped to OWASP LLM Top 10 (2025) and MITRE ATLAS; runs against `baseline` (v2 as delivered) and `hardened`; JSON, SARIF and Markdown reports; detector false-positive and clean-regression checks. |
| `oncall_governance` | 33 controls with automated evidence checks and indicative NIST AI RMF / ISO/IEC 42001 / OWASP / ATLAS mappings, a 12-risk register (inherent → residual), security policy as code with a release **gate**, AI inventory and SBOM, secret scanning, security IR playbook. |
| `oncall_governance.protect` | Runtime protections: hardened injection detector, token authentication + RBAC, identity-bound approvals, signed webhooks, rate/size limits, security headers, production mode, persisted + anchored audit, runbook signing, code-integrity manifest, security monitor with automatic containment. |

## Results (reports/)
| | Baseline (v2 as delivered) | Hardened |
|---|---|---|
| Attacks succeeded | 24 / 66 (36 %) — 4 critical, 5 high, 14 medium, 1 low | **0 / 66** |
| Detector false positives (570 benign log lines) | 0 | 0 |
| Clean held-out incidents | 10/11 recovered, 0 harmful | 10/11 recovered, 0 harmful |
| Controls | 22 pass, 2 partial, 9 fail | **33 pass** |
| Release gate | FAILED (22 reasons) | **PASSED** (R-11 formally accepted until 2027-01-31) |

**Security incident found and fixed:** the original lecture programs contained hard-coded OpenRouter API keys that
had been shipped in `reference_lectures/` of the v2 zip. They were removed from the package (DP-04); **revoke them**.

## Guardrail test-case catalogue
106 named cases (42 input, 41 output, 15 evasion, 8 false-positive) in `oncall_redteam/guardrail_catalogue.py`:
```bash
python -m oncall_redteam.guardrail_catalogue --hardened   # 105 pass, 1 known gap -> reports/guardrail_catalogue_hardened.md/.csv
python -m oncall_redteam.guardrail_catalogue              # baseline detector: 9 evasion cases fail (by design)
pytest -q tests/test_guardrail_catalogue.py               # same cases as a test suite
```

## Run
```bash
make install COPILOT=../oncall-copilot-v2      # pip install -e both packages
make test                                       # 34 tests
govern scan-secrets ../oncall-copilot-v2        # exit 0 = clean
redteam run --profile both --target ../oncall-copilot-v2 --out reports
govern report --target ../oncall-copilot-v2 --redteam reports/redteam_results.json
govern gate   --profile hardened --target ../oncall-copilot-v2 --redteam reports/redteam_results.json
govern users && COPILOT_WEBHOOK_SECRET=... govern serve     # hardened service on :8443
```
Documents: `docs/Red_Team_and_Security_Governance_Guide.docx`, `docs/Red_Team_Governance_Execution_and_Validation_Sequence.docx`,
`docs/SECURITY_IR_PLAYBOOK.md`; CI: `ci/security-gate.yml`.
