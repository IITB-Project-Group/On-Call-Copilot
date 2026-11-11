# Run from oncall-security/. COPILOT = the live On-Call Copilot repo. The top-level run_tests.sh wraps the same steps.
COPILOT ?= ../On-Call-Copilot-main
export COPILOT_LLM = off
export PYTHONUTF8 = 1
export ONCALL_COPILOT_REPO = $(abspath $(COPILOT))
export PYTHONPATH = $(ONCALL_COPILOT_REPO)/safety:$(ONCALL_COPILOT_REPO)/incident_api:$(ONCALL_COPILOT_REPO):$(abspath src)
.PHONY: install test catalogue hooks redteam govern gate secrets pin verify
install:   ; pip install -r ../requirements-test.txt && pip install -e ".[dev]"
test:      ; python -m pytest -q -p no:cacheprovider tests
catalogue: ; python -m oncall_redteam.guardrail_catalogue --hardened
hooks:     ; python scripts/hooks_check.py
redteam:   ; redteam run --profile both --target $(ONCALL_COPILOT_REPO) --out reports
govern:    ; govern report --target $(ONCALL_COPILOT_REPO) --redteam reports/redteam_results.json
gate:      ; govern gate --profile hardened --target $(ONCALL_COPILOT_REPO) --redteam reports/redteam_results.json
secrets:   ; govern scan-secrets $(ONCALL_COPILOT_REPO)
pin:       ; govern pin-runbooks --target $(ONCALL_COPILOT_REPO) --reviewer "$(REVIEWER)"
verify:    ; govern verify-runbooks --target $(ONCALL_COPILOT_REPO)
