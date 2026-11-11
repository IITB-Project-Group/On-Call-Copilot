"""Repository secret scanning (control DP-01): API keys, tokens, private keys, connection strings, .env files."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

PATTERNS = [
    ("openrouter_key", re.compile(r"sk-or-v1-[0-9a-f]{32,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    (
        "assigned_secret",
        re.compile(r"(?i)\b(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
    ),
]
# A value that only references a variable or is an obvious placeholder is not a committed secret
# (e.g. up.sh: --from-literal=api-key="${OPENROUTER_API_KEY}").
_INDIRECT = re.compile(
    r"""['"]\s*(?:\$\{?[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}?|\{\{[^}]*\}\}|<[^>]+>|REPLACE_ME|CHANGE_ME|changeme|xxx+)\s*['"]$""",
    re.I,
)
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "reports"}
TEST_MARKERS = (
    "test",
    "fixture",
    "redteam",
    "simulator",
    "conftest",
)  # deliberate fake secrets used as test data


def _gitignore(root: Path) -> list[str]:
    gi = Path(root) / ".gitignore"
    if not gi.exists():
        return []
    return [
        line.strip().rstrip("/")
        for line in gi.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip() and not line.startswith(("#", "!"))
    ]


def _ignored(rel: str, patterns: list[str]) -> bool:
    """True if git would not commit this path (simple .gitignore semantics: name, path or directory patterns)."""
    parts = rel.split("/")
    for pat in patterns:
        for i in range(len(parts)):
            sub = "/".join(parts[i:]) if "/" not in pat else rel
            if fnmatch.fnmatch(sub, pat) or fnmatch.fnmatch(parts[i], pat):
                return True
    return False


def scan(root: Path) -> dict:
    """Scan a repository. Files excluded by .gitignore (e.g. a local .env) are reported as local_only:
    they never reach the repository, so they are not repository findings -- but keys in any committed file are."""
    root = Path(root)
    patterns = _gitignore(root)
    findings, files = [], 0
    for p in root.rglob("*"):
        if (
            not p.is_file()
            or set(p.parts) & SKIP_DIRS
            or p.suffix in {".png", ".jpg", ".pdf", ".docx", ".zip"}
        ):
            continue
        files += 1
        rel = p.relative_to(root).as_posix()
        local = _ignored(rel, patterns)
        if p.name == ".env":
            findings.append({"file": rel, "kind": "dotenv_file", "test_data": False, "local_only": local})
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for kind, pat in PATTERNS:
            for m in pat.finditer(text):
                if kind == "assigned_secret" and _INDIRECT.search(m.group(0)):
                    continue
                findings.append(
                    {
                        "file": rel,
                        "kind": kind,
                        "line": text[: m.start()].count("\n") + 1,
                        "test_data": any(t in rel.lower() for t in TEST_MARKERS),
                        "local_only": local,
                    }
                )
    real = [f for f in findings if not f["test_data"] and not f["local_only"]]
    return {
        "files_scanned": files,
        "findings": findings,
        "real_findings": real,
        "clean": not real,
        "local_only": [f for f in findings if f["local_only"]],
    }
