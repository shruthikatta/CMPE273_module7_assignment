"""Run the three lab scenarios and print the evidence log."""

from __future__ import annotations

from fencing import FencedOrderStore, LockService
from ordering import ApplyResult, Event, OrderProcessor


def _status(status: str | None) -> str:
    return status if status is not None else "(none)"


def deliver(processor: OrderProcessor, event: Event) -> ApplyResult:
    print(
        f"deliver  order={event.order_id}  version={event.version}  status={event.status}"
    )
    result = processor.deliver(event)
    print(f"  action:          {result.action}")
    print(f"  detail:          {result.detail}")
    print(f"  applied_version: {result.applied_version}")
    print(f"  current_status:  {_status(result.status)}")
    print(f"  pending:         {result.pending_versions or '[]'}")
    print(f"  missing:         {result.missing_versions or '[]'}")
    print()
    return result


def scenario_ordered_delivery() -> None:
    print("=" * 72)
    print("1. Versioned event ordering")
    print("   Delivery order: version 2, version 1, version 2 again")
    print("=" * 72)
    processor = OrderProcessor()
    order = "order-1001"

    late = deliver(processor, Event(order, 2, "PAID"))
    assert late.action == "buffered"
    assert late.status is None
    assert late.missing_versions == [1]
    assert late.pending_versions == [2]
    assert processor.get_applied_version(order) == 0

    caught_up = deliver(processor, Event(order, 1, "CREATED"))
    assert caught_up.action == "applied"
    assert caught_up.applied_now == [1, 2]
    assert caught_up.status == "PAID"
    assert caught_up.applied_version == 2
    assert caught_up.missing_versions == []
    assert caught_up.pending_versions == []

    duplicate = deliver(processor, Event(order, 2, "PAID"))
    assert duplicate.action == "duplicate"
    assert duplicate.status == "PAID"
    assert duplicate.applied_version == 2
    assert processor.get_status(order) == "PAID"


def scenario_missing_event() -> None:
    print("=" * 72)
    print("2. Missing event")
    print("   Version 1 is applied, then only version 3 arrives")
    print("=" * 72)
    processor = OrderProcessor()
    order = "order-1002"

    created = deliver(processor, Event(order, 1, "CREATED"))
    assert created.action == "applied"
    assert created.status == "CREATED"

    gap = deliver(processor, Event(order, 3, "SHIPPED"))
    assert gap.action == "buffered"
    assert gap.status == "CREATED"
    assert gap.applied_version == 1
    assert gap.missing_versions == [2]
    assert gap.pending_versions == [3]
    assert processor.get_status(order) == "CREATED"

    print("check: status stayed CREATED; version 3 was not applied while version 2 was missing")
    print()


def scenario_stale_worker() -> None:
    print("=" * 72)
    print("3. Stale worker")
    print("   Two workers, increasing fencing tokens, one delayed writer")
    print("=" * 72)
    locks = LockService()
    store = FencedOrderStore()
    order = "order-1003"

    token_a = locks.issue_token("worker-A")
    print(f"lock service issued token {token_a} to worker-A")
    first = store.write(token_a, Event(order, 1, "CREATED"))
    print(f"worker-A write  token={token_a}  version=1  status=CREATED")
    print(f"  accepted:        {first.accepted}")
    print(f"  detail:          {first.detail}")
    print(f"  store_fence:     {store.fence}")
    print(f"  current_status:  {_status(store.processor.get_status(order))}")
    print()

    token_b = locks.issue_token("worker-B")
    print(f"lock service issued token {token_b} to worker-B")
    print("worker-A is now stale: it still holds token 1 and has not heard about token 2")
    second = store.write(token_b, Event(order, 2, "PAID"))
    print(f"worker-B write  token={token_b}  version=2  status=PAID")
    print(f"  accepted:        {second.accepted}")
    print(f"  detail:          {second.detail}")
    print(f"  store_fence:     {store.fence}")
    print(f"  current_status:  {_status(store.processor.get_status(order))}")
    print()

    stale = store.write(token_a, Event(order, 3, "SHIPPED"))
    print(f"worker-A write  token={token_a}  version=3  status=SHIPPED")
    print(f"  accepted:        {stale.accepted}")
    print(f"  detail:          {stale.detail}")
    print(f"  store_fence:     {store.fence}")
    print(f"  current_status:  {_status(store.processor.get_status(order))}")
    print(f"  applied_version: {store.processor.get_applied_version(order)}")
    print()

    assert token_a == 1 and token_b == 2
    assert first.accepted and second.accepted
    assert stale.accepted is False
    assert store.fence == 2
    assert store.processor.get_status(order) == "PAID"
    assert store.processor.get_applied_version(order) == 2
    print("check: worker-B (token 2) updated the order; worker-A (token 1) was rejected")
    print()


def main() -> None:
    scenario_ordered_delivery()
    scenario_missing_event()
    scenario_stale_worker()
    print("All checks passed.")


if __name__ == "__main__":
    main()
