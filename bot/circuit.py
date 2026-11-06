from __future__ import annotations


class CircuitBreaker:
    def __init__(self, max_errors: int):
        self.max_errors = max_errors
        self.errors = 0
        self.tripped = False
        self.reason = ""

    def record_error(self, reason: str):
        self.errors += 1
        if self.errors >= self.max_errors:
            self.trip(f"erros consecutivos: {reason}")

    def record_ok(self):
        self.errors = 0

    def trip(self, reason: str):
        self.tripped, self.reason = True, reason
