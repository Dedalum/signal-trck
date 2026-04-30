/**
 * Drawing ↔ chart_schema.Drawing JSON adapter.
 *
 * For the custom-on-primitives implementation, our internal shape is *the*
 * `Drawing` model from the backend — no separate plugin shape to translate
 * from. This file exists so a future plugin swap (e.g. importing
 * `difurious/lightweight-charts-line-tools-core` once it's on npm) keeps
 * the round-trip surface contained.
 *
 * Decision 9: even though we built custom, the adapter pattern is
 * preserved so the round-trip test (`tests/drawings_adapter_round_trip`)
 * still has a meaningful boundary to assert across.
 */

import type { components } from "../api-types";

export type Drawing = components["schemas"]["Drawing"];

/** Round-trip identity for now — kept as a function so a swap is local. */
export function toBackend(d: Drawing): Drawing {
  return d;
}

export function fromBackend(d: Drawing): Drawing {
  return d;
}

/** Generate a stable id for a new drawing. UUID-like; collision-free per chart. */
export function newDrawingId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  // Fallback for environments without crypto.randomUUID — vanishingly rare in 2026.
  return `dr-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}
