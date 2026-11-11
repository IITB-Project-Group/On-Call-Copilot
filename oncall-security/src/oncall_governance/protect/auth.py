"""Authentication and role-based access control for the copilot API (controls AC-06, AC-07).

Users and service accounts hold random API tokens; only SHA-256 hashes are stored. Each request is
authenticated with ``Authorization: Bearer <token>`` (or ``?token=`` for the SSE stream, which browsers
cannot send headers on). The authenticated identity -- never a field in the request body -- is the approver.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

import yaml

ROLES = {"viewer", "oncall", "incident_commander", "comms_lead", "security_admin", "alertmanager", "prometheus"}

# endpoint permission matrix (least privilege)
PERMISSIONS = {
    "read": {"viewer", "oncall", "incident_commander", "comms_lead", "security_admin"},
    "approve_action": {"oncall", "incident_commander"},
    "approve_comms": {"comms_lead", "incident_commander"},
    "reject": {"oncall", "incident_commander", "comms_lead"},
    "kill_switch_on": {"oncall", "incident_commander", "security_admin"},
    "kill_switch_off": {"incident_commander", "security_admin"},
    "pause": {"oncall", "incident_commander"},
    "audit": {"incident_commander", "security_admin"},
    "security": {"security_admin"},
    "ingest_alert": {"alertmanager"},
    "metrics": {"prometheus", "security_admin", "viewer"},
    "start_incident": {"oncall", "incident_commander"},
}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class User:
    user_id: str
    roles: frozenset[str]
    token_sha256: str
    active: bool = True
    failed: int = 0
    locked_until: float = 0.0


@dataclass
class UserStore:
    users: dict[str, User] = field(default_factory=dict)
    max_failures: int = 5
    lockout_s: float = 900

    @classmethod
    def from_yaml(cls, path: str) -> "UserStore":
        doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
        return cls({u["id"]: User(u["id"], frozenset(u["roles"]), u["token_sha256"], u.get("active", True))
                    for u in doc.get("users", [])})

    @classmethod
    def generate(cls, spec: Iterable[tuple[str, Iterable[str]]]) -> tuple["UserStore", dict[str, str]]:
        """Create users with fresh tokens. Returns (store, {user: plaintext token}) -- show tokens once."""
        store, tokens = cls(), {}
        for uid, roles in spec:
            bad = set(roles) - ROLES
            if bad:
                raise ValueError(f"unknown roles {bad}")
            tok = secrets.token_urlsafe(32)
            tokens[uid] = tok
            store.users[uid] = User(uid, frozenset(roles), hash_token(tok))
        return store, tokens

    def authenticate(self, token: Optional[str]) -> Optional[User]:
        if not token:
            return None
        h = hash_token(token)
        for u in self.users.values():
            if hmac.compare_digest(u.token_sha256, h):
                if not u.active or u.locked_until > time.time():
                    return None
                return u
        return None

    def disable(self, user_id: str) -> bool:
        u = self.users.get(user_id)
        if u:
            u.active = False
        return bool(u)


def allowed(user: User, permission: str) -> bool:
    return bool(user.roles & PERMISSIONS[permission])


DEFAULT_TEAM = [("alice", ["oncall"]), ("bob", ["incident_commander"]), ("carol", ["comms_lead"]),
                ("dana", ["security_admin"]), ("victor", ["viewer"]), ("alertmanager", ["alertmanager"]),
                ("prometheus", ["prometheus"])]
