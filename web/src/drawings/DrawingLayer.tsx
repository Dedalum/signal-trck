/**
 * DrawingLayer — wires mouse events to drawing creation + persistence.
 *
 * The renderer (`primitives.ts`) is independent of React; this component
 * owns the lifecycle of `DrawingPrimitive` instances attached to the
 * candle series and the click-state machine for creating new drawings.
 *
 * Per Decision 10 (drawing-render scaffolding for Phase C):
 * - Dashed stroke on AI-provenance drawings → `styles.ts:resolveStyle`.
 * - `onDrawingClick(drawing)` event surface fires on click-near-drawing;
 *   in B the handler `console.debug`s for AI provenance. Phase C swaps
 *   the handler to open the rationale panel — same event surface.
 */

import { useEffect, useRef } from "react";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import { DrawingPrimitive, pxToAnchor } from "./primitives";
import { newDrawingId, type Drawing } from "./serialize";
import { useStore, type DrawingTool } from "../store";

interface Props {
  chart: IChartApi | null;
  series: ISeriesApi<"Candlestick"> | null;
  containerEl: HTMLElement | null;
  drawings: Drawing[];
  onDrawingsChange: (drawings: Drawing[]) => void;
}

const HORIZONTAL_HIT_PX = 6;

export function DrawingLayer({
  chart,
  series,
  containerEl,
  drawings,
  onDrawingsChange,
}: Props) {
  const activeTool = useStore((s) => s.activeTool);
  const onDrawingsChangeRef = useRef(onDrawingsChange);
  const drawingsRef = useRef(drawings);
  onDrawingsChangeRef.current = onDrawingsChange;
  drawingsRef.current = drawings;

  // Manage primitives — attach/detach as the drawings array changes.
  useEffect(() => {
    if (!chart || !series) return;
    const primitives = drawings.map(
      (d) => new DrawingPrimitive(d, chart, series),
    );
    for (const p of primitives) {
      (series as unknown as { attachPrimitive: (p: unknown) => void }).attachPrimitive(p);
    }
    return () => {
      for (const p of primitives) {
        (series as unknown as { detachPrimitive: (p: unknown) => void }).detachPrimitive(p);
      }
    };
  }, [chart, series, drawings]);

  // Click handlers — both for create-new-drawing and click-existing-drawing.
  useEffect(() => {
    if (!chart || !series || !containerEl) return;

    let pending: { ts_utc: number; price: number } | null = null;

    const handleClick = (ev: MouseEvent) => {
      const rect = containerEl.getBoundingClientRect();
      const px = { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
      const anchor = pxToAnchor(chart, series, px);
      if (!anchor) return;

      const tool: DrawingTool = activeTool;

      // Existing-drawing click takes precedence over new-drawing creation
      // when the user is in select mode. This is the Decision-10 hook
      // Phase C will replace with rationale-panel-open logic.
      if (tool === "select") {
        const hit = hitTestDrawings(drawingsRef.current, px.y, series);
        if (hit) {
          onDrawingClick(hit);
        }
        return;
      }

      if (tool === "horizontal") {
        const newDrawing: Drawing = {
          id: newDrawingId(),
          kind: "horizontal",
          anchors: [anchor],
          style: { color: "#2a9d8f", dash: "solid" },
          provenance: null,
        };
        onDrawingsChangeRef.current([...drawingsRef.current, newDrawing]);
        useStore.getState().setActiveTool("select");
      } else if (tool === "trendline" || tool === "rect") {
        if (pending === null) {
          pending = anchor;
        } else {
          const newDrawing: Drawing = {
            id: newDrawingId(),
            kind: tool === "trendline" ? "trend" : "rect",
            anchors: [pending, anchor],
            style: { color: "#2a9d8f", dash: "solid" },
            provenance: null,
          };
          onDrawingsChangeRef.current([...drawingsRef.current, newDrawing]);
          pending = null;
          useStore.getState().setActiveTool("select");
        }
      }
    };

    containerEl.addEventListener("click", handleClick);
    return () => {
      containerEl.removeEventListener("click", handleClick);
    };
  }, [chart, series, containerEl, activeTool]);

  return null;
}

/** Returns the nearest drawing under the click, or null.
 *
 * v1 only hit-tests horizontal lines (price tolerance HORIZONTAL_HIT_PX
 * pixels). Trend lines and rectangles will get hit-tests in Phase C
 * polish — the event surface contract is what matters in B.
 */
function hitTestDrawings(
  drawings: Drawing[],
  clickY: number,
  series: ISeriesApi<"Candlestick">,
): Drawing | null {
  for (const d of drawings) {
    if (d.kind !== "horizontal") continue;
    const a = d.anchors[0];
    if (!a) continue;
    const drawingY = series.priceToCoordinate(a.price);
    if (drawingY === null) continue;
    if (Math.abs(clickY - drawingY) <= HORIZONTAL_HIT_PX) {
      return d;
    }
  }
  return null;
}

/** Decision 10 event surface. Phase C replaces the body with rationale-panel logic.
 *
 * Exported so tests can spy on it (and so a future reader can follow the
 * Phase B → Phase C swap by grep).
 */
export function onDrawingClick(d: Drawing): void {
  if (d.provenance?.kind === "ai") {
    // eslint-disable-next-line no-console
    console.debug("AI drawing clicked", { id: d.id, model: d.provenance.model });
    // Phase C: useStore.getState().selectAIDrawing(d) → opens RationalePanel.
  } else {
    // User drawing — Phase C may add edit/select interactions here.
    useStore.getState().setSelected(d.id);
  }
}
