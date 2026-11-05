"""Ticket writes stay on the incident API.

create_incident, update_status, and get_incident are not registered here.
The console and IncidentStore own the incident record.
"""

from __future__ import annotations


def ticket_tools() -> tuple[str, ...]:
    """Return MCP ticket tools. The tuple is empty on purpose."""
    return ()
