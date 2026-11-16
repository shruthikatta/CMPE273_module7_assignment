"""Fencing tokens for rejecting updates from a stale worker.

A lock service hands out increasing tokens. The order store remembers the
highest token it has accepted. A write whose token is lower than that value
is rejected and does not change the order.
"""

from __future__ import annotations

from dataclasses import dataclass

from ordering import ApplyResult, Event, OrderProcessor


@dataclass
class WriteResult:
    accepted: bool
    token: int
    fence: int
    detail: str
    apply_result: ApplyResult | None = None


class LockService:
    def __init__(self) -> None:
        self._next = 0

    def issue_token(self, worker: str) -> int:
        self._next += 1
        return self._next


class FencedOrderStore:
    def __init__(self, processor: OrderProcessor | None = None) -> None:
        self.processor = processor or OrderProcessor()
        self.fence = 0

    def write(self, token: int, event: Event) -> WriteResult:
        if token < self.fence:
            return WriteResult(
                accepted=False,
                token=token,
                fence=self.fence,
                detail=(
                    f"rejected token {token}; store fence is {self.fence} "
                    f"(stale worker)"
                ),
            )

        self.fence = token
        applied = self.processor.deliver(event)
        return WriteResult(
            accepted=True,
            token=token,
            fence=self.fence,
            detail=f"accepted token {token}; {applied.detail}",
            apply_result=applied,
        )
