"""The guardrail test-case catalogue as a pytest suite (hardened detector = the deployed configuration).
Known gaps are xfail(strict): they are reported every run, and the suite tells you when one gets fixed."""
import pytest

from oncall_redteam.guardrail_catalogue import CASES


@pytest.fixture(scope="module")
def ig():
    from oncall_governance.protect.detectors import hardened_input_guardrails
    return hardened_input_guardrails()


@pytest.mark.parametrize("c", CASES, ids=[c.id for c in CASES])
def test_guardrail_case(c, ig):
    if c.known_gap:
        pytest.xfail(f"known gap: {c.known_gap}")
    assert c.run(ig) == c.expected, f"{c.id} {c.description}"
