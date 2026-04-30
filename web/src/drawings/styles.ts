/**
 * Drawing stroke styles — distinguishes user-drawn from AI-drawn (Decision 10).
 *
 * AI provenance → dashed stroke; user → solid. This lives inside the
 * drawing-render path so Phase C doesn't need to refactor it; only the
 * `onDrawingClick` handler swaps from `console.debug` to opening the
 * rationale panel.
 */

export interface ResolvedStyle {
  color: string;
  lineDash: number[];
  lineWidth: number;
}

export function resolveStyle(
  baseColor: string,
  provenanceKind: "user" | "ai" | null | undefined,
): ResolvedStyle {
  return {
    color: baseColor || (provenanceKind === "ai" ? "#e76f51" : "#2a9d8f"),
    lineDash: provenanceKind === "ai" ? [6, 4] : [],
    lineWidth: 2,
  };
}
