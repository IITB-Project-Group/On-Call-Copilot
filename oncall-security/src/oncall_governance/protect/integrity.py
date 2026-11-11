"""Integrity protections (controls IN-01, IN-02, IN-03).

* sign_runbooks / verify_runbooks  -- HMAC-SHA256 signatures over the runbook hash (input_guardrails supports
  ``signing_key`` verification); an unsigned or re-signed-without-key runbook is refused.
* code_manifest / verify_code      -- SHA-256 manifest of the copilot's safety-critical source (guardrails, hooks,
  approval service, safety layer); any change to a guardrail without re-approval is detected.
* anchor_audit                     -- writes the audit chain head to an external anchor file so truncation or
  wholesale replacement of the log is detectable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path

SAFETY_CRITICAL = [
    "guardrail_core.py",
    "input_guardrails.py",
    "output_guardrails.py",
    "approval_service.py",
    "hooks.py",
    "oncall_copilot/safety.py",
    "oncall_copilot/shop_tools.py",
    "oncall_copilot/tools/toolbox.py",
    "oncall_copilot/agents/remediation.py",
    "oncall_copilot/api/server.py",
]


def sign_runbooks(runbook_dir: Path, key: bytes) -> dict[str, str]:
    from input_guardrails import InputGuardrails

    ig, sigs = InputGuardrails(), {}
    for p in sorted(Path(runbook_dir).glob("*.json")):
        rb = json.loads(p.read_text(encoding="utf-8"))
        sigs[rb["id"]] = hmac.new(key, ig.runbook_hash(rb).encode(), hashlib.sha256).hexdigest()
    return sigs


def verify_runbooks(runbook_dir: Path, key: bytes, signatures: dict[str, str]) -> dict[str, str]:
    from input_guardrails import InputGuardrails

    ig, out = InputGuardrails(), {}
    for p in sorted(Path(runbook_dir).glob("*.json")):
        rb = json.loads(p.read_text(encoding="utf-8"))
        r = ig.check_runbook({**rb, "signature": signatures.get(rb["id"], "")}, signing_key=key)
        out[rb["id"]] = "ok" if not r.blocked else "invalid_signature"
    return out


def code_manifest(src_root: Path) -> dict[str, str]:
    return {
        f: hashlib.sha256((Path(src_root) / f).read_bytes()).hexdigest()
        for f in SAFETY_CRITICAL
        if (Path(src_root) / f).exists()
    }


def verify_code(src_root: Path, manifest: dict[str, str]) -> dict[str, str]:
    now = code_manifest(src_root)
    return {
        f: ("ok" if now.get(f) == h else "MODIFIED" if f in now else "MISSING") for f, h in manifest.items()
    }


def anchor_audit(audit, anchor_path: Path) -> dict:
    entries = audit.entries()
    rec = {
        "t": time.time(),
        "entries": len(entries),
        "head": entries[-1]["hash"] if entries else None,
        "verified": audit.verify(),
    }
    with open(anchor_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def check_anchor(audit, anchor_path: Path) -> bool:
    """The live log must still contain every anchored head at its anchored position."""
    entries = audit.entries()
    for line in Path(anchor_path).read_text(encoding="utf-8").splitlines():
        a = json.loads(line)
        if a["entries"] and (len(entries) < a["entries"] or entries[a["entries"] - 1]["hash"] != a["head"]):
            return False
    return audit.verify()


# ---------------------------------------------------------------------- live product: Markdown runbooks
def pin_markdown_runbooks(runbook_dir: Path, manifest_path: Path, reviewer: str) -> dict:
    """Record the SHA-256 of every reviewed runbook (knowledge/runbooks/*.md). Run only after a human review."""
    files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(runbook_dir).glob("*.md"))
    }
    doc = {
        "reviewed_by": reviewer,
        "pinned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runbooks": files,
    }
    Path(manifest_path).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def verify_markdown_runbooks(runbook_dir: Path, manifest_path: Path) -> dict[str, str]:
    """ok | MODIFIED | UNPINNED (new, unreviewed file) | MISSING. Empty dict = no manifest."""
    if not Path(manifest_path).exists():
        return {}
    pinned = json.loads(Path(manifest_path).read_text(encoding="utf-8")).get("runbooks", {})
    now = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(runbook_dir).glob("*.md"))}
    out = {n: ("ok" if now.get(n) == h else "MODIFIED" if n in now else "MISSING") for n, h in pinned.items()}
    out.update({n: "UNPINNED" for n in now if n not in pinned})
    return out
