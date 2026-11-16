# Order Processing Simulation

A small Python simulation of an order that moves through versioned states:

`CREATED` (version 1) → `PAID` (version 2) → `SHIPPED` (version 3)

Each update carries an `order_id`, a `version`, and a `status`. The processor applies versions in order, holds an update when an earlier version has not arrived, ignores a version it has already seen, and rejects a write from a worker whose fencing token is older than the token the store has already accepted.

No third-party packages are required.

## Run

From this directory, with Python 3.10 or newer:

```bash
python3 simulate.py
```

The program prints the three scenarios below and exits with status 0 after its checks pass. A copy of that output is saved in [`evidence/demo_output.txt`](evidence/demo_output.txt).

| File | Role |
| --- | --- |
| `ordering.py` | Per-order version log: buffer, apply, and duplicate detection |
| `fencing.py` | Increasing fencing tokens and stale-write rejection |
| `simulate.py` | The three required scenarios |

## 1. Correct event ordering

Delivery order for `order-1001`: version 2, then version 1, then version 2 again.

Version 2 arrives first and is held, because version 1 is missing and the order has no status yet. When version 1 arrives, the processor applies version 1 (`CREATED`) and then the buffered version 2 (`PAID`). The order does not become `PAID` before it is `CREATED`.

```text
deliver  order=order-1001  version=2  status=PAID
  action:          buffered
  detail:          held version 2 (PAID); waiting for missing version(s) [1]
  applied_version: 0
  current_status:  (none)
  pending:         [2]
  missing:         [1]

deliver  order=order-1001  version=1  status=CREATED
  action:          applied
  detail:          applied version 1 (CREATED), version 2 (PAID)
  applied_version: 2
  current_status:  PAID
  pending:         []
  missing:         []
```

## 2. Duplicate handling

The same version 2 update is delivered again after it has already been applied. The processor ignores it. The applied version stays 2 and the status stays `PAID`.

```text
deliver  order=order-1001  version=2  status=PAID
  action:          duplicate
  detail:          ignored version 2; it was already applied or buffered
  applied_version: 2
  current_status:  PAID
  pending:         []
  missing:         []
```

## 3. Missing event

`order-1002` is `CREATED` at version 1. The next delivery is version 3 (`SHIPPED`) while version 2 (`PAID`) has not arrived.

Version 3 is stored as pending and version 2 is recorded as missing. The current status stays `CREATED`. The order does not jump to `SHIPPED`.

```text
deliver  order=order-1002  version=1  status=CREATED
  action:          applied
  detail:          applied version 1 (CREATED)
  applied_version: 1
  current_status:  CREATED
  pending:         []
  missing:         []

deliver  order=order-1002  version=3  status=SHIPPED
  action:          buffered
  detail:          held version 3 (SHIPPED); waiting for missing version(s) [2]
  applied_version: 1
  current_status:  CREATED
  pending:         [3]
  missing:         [2]

check: status stayed CREATED; version 3 was not applied while version 2 was missing
```

## 4. Stale worker rejection

A lock service issues an increasing fencing token to each worker. The store remembers the highest token it has accepted.

- Worker A receives token 1 and writes version 1 (`CREATED`). The write is accepted and the store fence becomes 1.
- Worker B receives token 2 and writes version 2 (`PAID`). The newer token is accepted and the store fence becomes 2.
- Worker A later tries to write version 3 (`SHIPPED`) with token 1. Token 1 is older than the store fence, so the write is rejected. The status stays `PAID` and the applied version stays 2.

```text
lock service issued token 1 to worker-A
worker-A write  token=1  version=1  status=CREATED
  accepted:        True
  detail:          accepted token 1; applied version 1 (CREATED)
  store_fence:     1
  current_status:  CREATED

lock service issued token 2 to worker-B
worker-B write  token=2  version=2  status=PAID
  accepted:        True
  detail:          accepted token 2; applied version 2 (PAID)
  store_fence:     2
  current_status:  PAID

worker-A write  token=1  version=3  status=SHIPPED
  accepted:        False
  detail:          rejected token 1; store fence is 2 (stale worker)
  store_fence:     2
  current_status:  PAID
  applied_version: 2

check: worker-B (token 2) updated the order; worker-A (token 1) was rejected
```

## Reflection

Timestamps alone cannot guarantee correct event ordering because each machine has its own clock, and those clocks drift even when they are periodically synchronized. A message sent earlier can still arrive later, so the arrival time is not the order in which the business event happened, and the sender's timestamp can be ahead of or behind the receiver's clock. Two updates can also carry the same timestamp, which leaves the receiver with no unique order. This simulation uses a per-order version instead: an update is applied only when every lower version is already applied, later versions wait in a buffer, and a repeated version is ignored. Fencing tokens solve a different problem from ordering. A worker that lost the lock can still send a write that looks new by the clock, so the store rejects any token older than the highest token it has already accepted.
