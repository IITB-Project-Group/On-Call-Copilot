"""Run incident graphs inside the incident API: start on an alert, resume on a decision.

Each incident is one LangGraph thread (thread id = incident id) in a SQLite checkpointer, so a
restarted API resumes every run that was mid-step (``resume_unfinished``) and keeps every run
that was waiting for a person. ``view`` is what the console shows: the plan and its versions,
the ranked hypotheses, the pending decision and the outcome.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from langgraph.types import Command

from agents.observability import AgentMetrics, tracing_callbacks
from graph.incident_graph import GraphDeps, build_graph

logger = logging.getLogger(__name__)

_ACTIVITY_LOG_LIMIT = 12


class AgentService:
    def __init__(
        self,
        deps: GraphDeps,
        checkpointer,
        *,
        run_async: bool = True,
        metrics: AgentMetrics | None = None,
        publish: Callable[[str, dict], None] | None = None,
    ):
        self.deps = deps
        self.deps.on_activity = self.note_activity
        self.graph = build_graph(deps, checkpointer)
        self.run_async, self.metrics, self.publish_fn = run_async, metrics, publish
        self._locks: dict[str, threading.Lock] = {}
        self._threads: list[threading.Thread] = []
        self.errors: dict[str, str] = {}
        self.activity: dict[str, str] = {}
        self.activity_log: dict[str, list[dict]] = {}

    def _config(self, incident_id: str) -> dict:
        return {"configurable": {"thread_id": incident_id}, "callbacks": tracing_callbacks()}

    def handles(self, incident_id: str) -> bool:
        return bool(self.graph.get_state(self._config(incident_id)).values)

    def start(self, incident_id: str, alert: dict) -> None:
        self._run(incident_id, {"incident_id": incident_id, "alert": alert})

    def resume(self, incident_id: str, decision: dict, *, wait: bool = False, timeout: float = 45.0) -> None:
        thread = self._run(incident_id, Command(resume=decision))
        if wait and thread is not None:
            thread.join(timeout)

    def resume_decision(self, incident_id: str, decision: dict, *, timeout: float = 20.0) -> dict:
        """Resume and wait only until this HITL step settles — not through act/verify.

        Approve used to ``join`` the whole resume thread, so the console sat on Working… for the
        full verification window (~45s+) and looked broken. Reject felt fine because it returns sooner.

        Never treat a briefly cleared interrupt as done: during Command(resume) the interrupt
        drops before ``Approved by`` / ``Approval not complete`` is checkpointed, and a separate
        pending() read can disagree with view(). Wait for a new timeline event (or a real move to
        another HITL kind / terminal outcome) from one consistent snapshot.
        """
        before = self.pending(incident_id)
        before_kind = None if before is None else before.get("kind")
        before_events = len((self.view(incident_id).get("events") or []))
        self._run(incident_id, Command(resume=decision))
        deadline = time.time() + timeout
        view = self.view(incident_id)
        while time.time() < deadline:
            view = self.view(incident_id)
            pending = view.get("pending")
            current_kind = None if pending is None else pending.get("kind")
            events = view.get("events") or []
            if len(events) > before_events:
                new_whats = [str((e or {}).get("what") or "") for e in events[before_events:]]
                blob = " ".join(new_whats)
                # Action HITL can emit an event before the next interrupt is armed
                # (SEV1 first vote, or re-propose after a lost approval request). Wait for
                # that re-arm so the console does not flash “Approved” and hide the code.
                if before_kind == "action" and current_kind != "action":
                    waiting_rearm = (
                        "Approval not complete" in blob
                        or "proposing again" in blob
                        or "missing after restart" in blob
                        or (
                            "Proposed:" in blob
                            and "Approved by" not in blob
                            and "Proposal refused" not in blob
                            and "Rejected by" not in blob
                        )
                    )
                    if waiting_rearm:
                        time.sleep(0.1)
                        continue
                return view
            if current_kind is not None and current_kind != before_kind:
                return view
            if not view.get("running") and pending is None and view.get("outcome"):
                return view
            time.sleep(0.1)
        return view

    def resume_unfinished(self, incident_ids: list[str]) -> list[str]:
        """Continue runs that stopped mid-step (process killed). Runs waiting for a person stay waiting."""
        resumed = []
        for incident_id in incident_ids:
            snapshot = self.graph.get_state(self._config(incident_id))
            if snapshot.values and snapshot.next and not snapshot.interrupts:
                self._run(incident_id, None)
                resumed.append(incident_id)
        return resumed

    def wait(self, timeout: float = 30.0) -> None:
        for thread in list(self._threads):
            thread.join(timeout)

    def _run(self, incident_id: str, value: Any) -> threading.Thread | None:
        if self.run_async:
            thread = threading.Thread(target=self._invoke, args=(incident_id, value), daemon=True)
            self._threads.append(thread)
            thread.start()
            return thread
        self._invoke(incident_id, value)
        return None

    def note_activity(self, incident_id: str, text: str) -> None:
        """Show the tool / LLM step the agent is on. The graph only checkpoints when a step finishes."""
        self.activity[incident_id] = text
        log = self.activity_log.setdefault(incident_id, [])
        # Skip consecutive duplicates so republishes do not pad or reshuffle the timeline.
        if not (log and log[-1].get("text") == text):
            log.append({"ts": time.time(), "text": text})
            del log[:-_ACTIVITY_LOG_LIMIT]
        if self.publish_fn is None:
            return
        view = self.view(incident_id)
        if not view.get("status"):
            view["status"] = "investigating"
        view["activity"] = text
        view["activity_log"] = list(log)
        view["running"] = True
        self.publish_fn(incident_id, view)

    def _announce(self, incident_id: str) -> None:
        """Show that work has started. The graph publishes again when it pauses or finishes."""
        if self.publish_fn is None:
            return
        self.publish_fn(
            incident_id,
            {
                "status": "investigating",
                "running": True,
                "outcome": None,
                "plan": None,
                "plan_versions": [],
                "hypotheses": [],
                "proposal": None,
                "verification": None,
                "pending": None,
                "events": [],
                "error": None,
            },
        )

    def _invoke(self, incident_id: str, value: Any) -> None:
        lock = self._locks.setdefault(incident_id, threading.Lock())
        with lock:
            if not isinstance(value, Command):
                self._announce(incident_id)
            try:
                self.graph.invoke(value, self._config(incident_id))
                self.errors.pop(incident_id, None)
            except Exception as exc:  # the console shows the failure; the checkpoint keeps the last good step
                logger.exception("incident graph failed for %s", incident_id)
                self.errors[incident_id] = f"{type(exc).__name__}: {exc}"
            self.publish(incident_id)

    def pending(self, incident_id: str) -> dict | None:
        snapshot = self.graph.get_state(self._config(incident_id))
        return snapshot.interrupts[0].value if snapshot.interrupts else None

    def view(self, incident_id: str) -> dict:
        snapshot = self.graph.get_state(self._config(incident_id))
        state = snapshot.values or {}
        pending = snapshot.interrupts[0].value if snapshot.interrupts else None
        proposal = state.get("proposal") or {}
        result = {
            "status": state.get("status"),
            "outcome": state.get("outcome"),
            "plan": state.get("plan"),
            "plan_versions": [
                {"version": p["version"], "focus": p["focus"], "reason": p["reason"]}
                for p in state.get("plan_history") or []
            ],
            "hypotheses": (state.get("diagnosis") or {}).get("hypotheses", [])[:3],
            "proposal": {k: proposal.get(k) for k in ("command", "rollback_command", "severity", "rationale")}
            if proposal
            else None,
            "verification": state.get("verification"),
            "pending": None
            if pending is None
            else {
                "kind": pending["kind"],
                **{
                    k: v
                    for k, v in pending.items()
                    # confirmation_code travels with the pending action so the console never
                    # waits on a separate store write before showing the code field.
                    if k in ("command", "external", "lessons", "required_approvals", "confirmation_code")
                },
            },
            "events": (state.get("events") or [])[-15:],
            "running": bool(snapshot.next) and not snapshot.interrupts,
            "activity": self.activity.get(incident_id),
            "activity_log": list(self.activity_log.get(incident_id) or []),
            "error": self.errors.get(incident_id),
        }
        if not result["running"]:
            result["activity"] = None
            # Keep the recent log so Closed / paused views still show what was tried.
        return result

    def publish(self, incident_id: str) -> None:
        view = self.view(incident_id)
        if self.publish_fn is not None:
            self.publish_fn(incident_id, view)
        if (
            self.metrics is not None
            and not view["running"]
            and view["pending"] is None
            and incident_id in self.deps.sessions
        ):
            session = self.deps.sessions[incident_id]
            hook = session.executor.mgr.state(incident_id)
            marks = {k: v - hook.started for k, v in hook.marks.items()}
            self.metrics.observe(
                {
                    "outcome": view["outcome"],
                    "time_to_diagnose_s": marks.get("diagnosed"),
                    "time_to_recover_s": marks.get("recovered"),
                    "tool_calls": hook.tool_calls,
                    "rollbacks": hook.rollbacks,
                    "replans": hook.replans,
                    "cost_usd": hook.cost_usd,
                    "halt_reason": hook.halt_reason,
                }
            )
