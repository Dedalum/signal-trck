"""``Store.write_ai_run`` + ``list_ai_runs`` round-trip."""

from __future__ import annotations

import json
import time

from signal_trck.storage import Store


async def test_write_and_list(store: Store) -> None:
    await store.add_pair("test:T-USD", "T", "USD", "test")
    presented = json.dumps([{"id": "sr-1", "price": 100}])
    selected = json.dumps(["sr-1"])

    run_id = await store.write_ai_run(
        pair_id="test:T-USD",
        chart_slug="chart-2",
        provider="anthropic",
        model="claude-opus-4-7",
        prompt_template_version="v1",
        system_prompt_hash="abc123",
        context_file_sha256="0" * 64,
        context_preview="some preview…",
        sr_candidates_presented_json=presented,
        sr_candidates_selected_json=selected,
        ran_at=int(time.time()),
    )
    assert run_id > 0

    runs = await store.list_ai_runs("test:T-USD")
    assert len(runs) == 1
    r = runs[0]
    assert r["chart_slug"] == "chart-2"
    assert r["model"] == "claude-opus-4-7"
    assert r["provider"] == "anthropic"
    assert json.loads(r["sr_candidates_selected"]) == ["sr-1"]
    assert json.loads(r["sr_candidates_presented"])[0]["id"] == "sr-1"


async def test_list_orders_newest_first(store: Store) -> None:
    await store.add_pair("test:T-USD", "T", "USD", "test")
    base = int(time.time())
    for i in range(3):
        await store.write_ai_run(
            pair_id="test:T-USD",
            chart_slug=f"chart-{i + 2}",
            provider="anthropic",
            model="m",
            prompt_template_version="v1",
            system_prompt_hash="h",
            context_file_sha256=None,
            context_preview=None,
            sr_candidates_presented_json="[]",
            sr_candidates_selected_json="[]",
            ran_at=base + i,
        )
    runs = await store.list_ai_runs("test:T-USD")
    assert [r["chart_slug"] for r in runs] == ["chart-4", "chart-3", "chart-2"]


async def test_list_respects_limit(store: Store) -> None:
    await store.add_pair("test:T-USD", "T", "USD", "test")
    base = int(time.time())
    for i in range(5):
        await store.write_ai_run(
            pair_id="test:T-USD",
            chart_slug=f"chart-{i}",
            provider="anthropic",
            model="m",
            prompt_template_version="v1",
            system_prompt_hash="h",
            context_file_sha256=None,
            context_preview=None,
            sr_candidates_presented_json="[]",
            sr_candidates_selected_json="[]",
            ran_at=base + i,
        )
    runs = await store.list_ai_runs("test:T-USD", limit=2)
    assert len(runs) == 2


async def test_list_empty_for_unknown_pair(store: Store) -> None:
    rows = await store.list_ai_runs("test:UNKNOWN-USD")
    assert rows == []
