/**
 * Drawing adapter round-trip.
 *
 * Per Decision 9 (post-amend): the adapter is identity for the
 * custom-on-primitives implementation, but the test exists so a future
 * plugin swap (`difurious` once it's on npm) has a concrete contract to
 * preserve.
 */

import { describe, expect, it } from "vitest";
import type { Drawing } from "./serialize";
import { fromBackend, newDrawingId, toBackend } from "./serialize";

const sample: Drawing = {
  id: "dr-h1",
  kind: "horizontal",
  anchors: [{ ts_utc: 1704067200, price: 42000, candidate_id: null }],
  style: { color: "#2a9d8f", dash: "solid" },
  provenance: null,
};

describe("drawing adapter", () => {
  it("toBackend → fromBackend is identity", () => {
    expect(fromBackend(toBackend(sample))).toEqual(sample);
  });

  it("toBackend on AI-provenance drawing preserves provenance fields", () => {
    const ai: Drawing = {
      id: "dr-ai-1",
      kind: "horizontal",
      anchors: [{ ts_utc: 1704067200, price: 42103.5, candidate_id: "sr-12" }],
      style: { color: "#e76f51", dash: "dashed" },
      provenance: {
        kind: "ai",
        model: "claude-opus-4-7",
        created_at: "2026-04-22T11:30:00Z",
        confidence: 0.78,
        rationale: "Tested 3 times",
        prompt_template_version: null,
      },
    };
    const round = fromBackend(toBackend(ai));
    expect(round.provenance?.kind).toBe("ai");
    expect(round.provenance?.confidence).toBe(0.78);
    expect(round.anchors[0]?.candidate_id).toBe("sr-12");
  });

  it("newDrawingId returns unique strings", () => {
    const ids = new Set<string>();
    for (let i = 0; i < 100; i++) ids.add(newDrawingId());
    expect(ids.size).toBe(100);
  });
});
