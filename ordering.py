"""Versioned event ordering for a single order log.

Updates carry an order id, a monotonically increasing version, and a status.
The log applies a version only after every earlier version has been applied,
keeps later versions in a buffer, and ignores a version it has already seen.
"""

from __future__ import annotations

from dataclasses import dataclass, field


EXPECTED_STATUS = {
    1: "CREATED",
    2: "PAID",
    3: "SHIPPED",
}


@dataclass(frozen=True)
class Event:
    order_id: str
    version: int
    status: str


@dataclass
class ApplyResult:
    action: str
    detail: str
    order_id: str
    applied_version: int
    status: str | None
    pending_versions: list[int]
    missing_versions: list[int]
    applied_now: list[int] = field(default_factory=list)


@dataclass
class _OrderLog:
    applied_version: int = 0
    status: str | None = None
    pending: dict[int, Event] = field(default_factory=dict)
    seen_versions: set[int] = field(default_factory=set)


class OrderProcessor:
    """Applies per-order updates in version order."""

    def __init__(self) -> None:
        self._orders: dict[str, _OrderLog] = {}

    def get_status(self, order_id: str) -> str | None:
        log = self._orders.get(order_id)
        return None if log is None else log.status

    def get_applied_version(self, order_id: str) -> int:
        log = self._orders.get(order_id)
        return 0 if log is None else log.applied_version

    def pending_versions(self, order_id: str) -> list[int]:
        log = self._orders.get(order_id)
        if log is None:
            return []
        return sorted(log.pending)

    def missing_versions(self, order_id: str) -> list[int]:
        log = self._orders.get(order_id)
        if log is None:
            return []
        return _missing(log)

    def deliver(self, event: Event) -> ApplyResult:
        self._validate(event)
        log = self._orders.setdefault(event.order_id, _OrderLog())

        if event.version in log.seen_versions or event.version <= log.applied_version:
            return self._result(
                log,
                event.order_id,
                "duplicate",
                f"ignored version {event.version}; it was already applied or buffered",
            )

        log.seen_versions.add(event.version)

        if event.version > log.applied_version + 1:
            log.pending[event.version] = event
            missing = _missing(log)
            return self._result(
                log,
                event.order_id,
                "buffered",
                (
                    f"held version {event.version} ({event.status}); "
                    f"waiting for missing version(s) {missing}"
                ),
            )

        applied_now = self._apply_ready(log, event)
        return self._result(
            log,
            event.order_id,
            "applied",
            "applied " + ", ".join(
                f"version {version} ({EXPECTED_STATUS[version]})" for version in applied_now
            ),
            applied_now,
        )

    def _apply_ready(self, log: _OrderLog, first: Event) -> list[int]:
        applied: list[int] = []
        event: Event | None = first
        while event is not None and event.version == log.applied_version + 1:
            log.applied_version = event.version
            log.status = event.status
            log.pending.pop(event.version, None)
            applied.append(event.version)
            event = log.pending.get(log.applied_version + 1)
        return applied

    def _result(
        self,
        log: _OrderLog,
        order_id: str,
        action: str,
        detail: str,
        applied_now: list[int] | None = None,
    ) -> ApplyResult:
        return ApplyResult(
            action=action,
            detail=detail,
            order_id=order_id,
            applied_version=log.applied_version,
            status=log.status,
            pending_versions=sorted(log.pending),
            missing_versions=_missing(log),
            applied_now=applied_now or [],
        )

    @staticmethod
    def _validate(event: Event) -> None:
        expected = EXPECTED_STATUS.get(event.version)
        if expected is None:
            known = ", ".join(f"{v}={s}" for v, s in EXPECTED_STATUS.items())
            raise ValueError(f"unsupported version {event.version}; expected one of {known}")
        if event.status != expected:
            raise ValueError(
                f"version {event.version} must have status {expected}, got {event.status}"
            )
        if not event.order_id:
            raise ValueError("order_id is required")


def _missing(log: _OrderLog) -> list[int]:
    if not log.pending:
        return []
    highest = max(log.pending)
    return [
        version
        for version in range(log.applied_version + 1, highest + 1)
        if version not in log.pending and version not in _applied_range(log)
    ]


def _applied_range(log: _OrderLog) -> set[int]:
    return set(range(1, log.applied_version + 1))
