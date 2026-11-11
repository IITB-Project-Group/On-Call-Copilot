"""Runtime protections that harden the On-Call Copilot without editing it.

    from oncall_governance.protect import install_runtime_protections
    install_runtime_protections()        # hardened injection detection everywhere the copilot screens input
    app = build_hardened_app(store, policy)   # authenticated, role-checked API
"""
from __future__ import annotations

from .detectors import HardenedInjectionDetector, hardened_input_guardrails

_INSTALLED = {"done": False}


def _has_v2() -> bool:
    try:
        import oncall_copilot.safety  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def install_runtime_protections() -> list[str]:
    """Swap the copilot's input-guardrail factory for the hardened one in every module that screens input.

    Live product (no ``oncall_copilot`` package): ``api.live_screen.guardrails`` already builds InputGuardrails with
    the hardened detector, so nothing is patched; the API-level protections come from ``live_app``."""
    if not _has_v2():
        _INSTALLED["done"] = True
        return []
    import oncall_copilot.api.server as srv
    import oncall_copilot.safety as safety
    import oncall_copilot.shop_tools as tools

    patched = []
    for mod in (safety, tools, srv):
        if getattr(mod, "InputGuardrails", None) is not hardened_input_guardrails:
            mod.InputGuardrails = hardened_input_guardrails
            patched.append(mod.__name__)
    import oncall_copilot.factory as factory
    factory._KB = None   # rebuild the knowledge base with the hardened screening
    _INSTALLED["done"] = True
    return patched


def uninstall_runtime_protections() -> None:
    if not _has_v2():
        _INSTALLED["done"] = False
        return
    import input_guardrails
    import oncall_copilot.api.server as srv
    import oncall_copilot.safety as safety
    import oncall_copilot.shop_tools as tools
    import oncall_copilot.factory as factory

    for mod in (safety, tools, srv):
        mod.InputGuardrails = input_guardrails.InputGuardrails
    factory._KB = None
    _INSTALLED["done"] = False


def protections_installed() -> bool:
    return _INSTALLED["done"]
