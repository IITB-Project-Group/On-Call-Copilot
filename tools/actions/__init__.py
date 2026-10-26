"""Allow-listed writes. Each action takes typed arguments and can dry-run."""

from tools.actions.set_flag import FlagWriteError, set_payment_failure_off

WRITE_ACTIONS = ("set_flag", "restart", "scale", "rollback")

__all__ = ["WRITE_ACTIONS", "FlagWriteError", "set_payment_failure_off"]
