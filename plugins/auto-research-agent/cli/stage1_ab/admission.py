"""Structured admission failures retain every machine-readable reason."""

from .runner import ExecutionBlocked


class AdmissionBlocked(ExecutionBlocked):
    def __init__(self, message, reason_codes):
        self.reason_codes = sorted(set(reason_codes))
        super().__init__(message + ": " + ", ".join(self.reason_codes))
