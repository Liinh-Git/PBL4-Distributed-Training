from __future__ import annotations

import pytest

from pbl4.management_backend.websocket import AttemptBroadcastHub


@pytest.mark.asyncio
async def test_attempt_broadcast_hub_delivery():
    hub = AttemptBroadcastHub()
    q1 = hub.subscribe("att-1")
    q2 = hub.subscribe("att-1")
    q_other = hub.subscribe("att-2")

    assert hub.subscriber_count("att-1") == 2
    assert hub.subscriber_count("att-2") == 1

    # Broadcast to att-1
    msg = {"type": "RUNTIME_EVENT", "data": {"runtime_event_seq": 1}}
    await hub.broadcast("att-1", msg)

    # Both att-1 subscribers should receive it
    rec1 = q1.get_nowait()
    rec2 = q2.get_nowait()
    assert rec1 == msg
    assert rec2 == msg

    # att-2 subscriber should NOT receive it
    assert q_other.empty()

    # Unsubscribe
    hub.unsubscribe("att-1", q1)
    assert hub.subscriber_count("att-1") == 1
    hub.unsubscribe("att-1", q2)
    assert hub.subscriber_count("att-1") == 0


@pytest.mark.asyncio
async def test_attempt_broadcast_hub_backpressure():
    hub = AttemptBroadcastHub()
    q = hub.subscribe("att-bp")

    # Fill queue to capacity (256 items)
    for i in range(256):
        q.put_nowait({"type": "EVENT", "seq": i})

    assert q.full()

    # Broadcasting when full should trigger backpressure overflow sentinel
    await hub.broadcast("att-bp", {"type": "EVENT", "seq": 999})

    # The queue should still contain items, and the overflow sentinel should be placed
    items = []
    while not q.empty():
        items.append(q.get_nowait())

    has_overflow_sentinel = any(
        isinstance(it, dict) and it.get("type") == "BACKPRESSURE_OVERFLOW"
        for it in items
    )
    assert has_overflow_sentinel is True
