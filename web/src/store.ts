/**
 * Single zustand store for chart state + ephemeral UI.
 *
 * Decision 8: one store, not two. Selectors give per-component subscription
 * granularity at the call site (only chart-pane re-renders on price change;
 * drawing toolbar re-renders on tool change). Two stores was theoretical
 * optimization — split when a profiler shows the wakeup, not before.
 */

import { create } from "zustand";
import type { Chart, Pair } from "./api";

export type DrawingTool = "select" | "trendline" | "horizontal" | "rect";
export type Interval = "1h" | "1d" | "1w";

export interface ErrorModal {
  /** Title for the modal — short, e.g., "Schema mismatch". */
  title: string;
  /** Server-side error message verbatim — see Decision 24. */
  message: string;
  /** Stable backend code, when present. */
  code?: string;
}

export interface AppState {
  // --- pairs / chart selection ---
  pairs: Pair[];
  selectedPairId: string | null;
  selectedSlug: string | null;
  /** Chart currently loaded into the canvas. */
  chart: Chart | null;
  /** Window controls — the user's view, separate from `chart.data` defaults. */
  interval: Interval;
  windowDays: number;

  // --- drawing UI state ---
  activeTool: DrawingTool;
  hoveredDrawingId: string | null;
  selectedDrawingId: string | null;

  // --- modal / errors ---
  errorModal: ErrorModal | null;

  // --- mutators ---
  setPairs(pairs: Pair[]): void;
  selectPair(pair_id: string | null): void;
  selectSlug(slug: string | null): void;
  setChart(chart: Chart | null): void;
  setInterval(i: Interval): void;
  setWindowDays(d: number): void;
  setActiveTool(t: DrawingTool): void;
  setHovered(id: string | null): void;
  setSelected(id: string | null): void;
  showError(modal: ErrorModal | null): void;
}

export const useStore = create<AppState>((set) => ({
  pairs: [],
  selectedPairId: null,
  selectedSlug: null,
  chart: null,
  interval: "1d",
  windowDays: 90,
  activeTool: "select",
  hoveredDrawingId: null,
  selectedDrawingId: null,
  errorModal: null,

  setPairs: (pairs) => set({ pairs }),
  selectPair: (selectedPairId) =>
    set({
      selectedPairId,
      // Drop selected chart when switching pairs — the chart belongs to the pair.
      selectedSlug: null,
      chart: null,
    }),
  selectSlug: (selectedSlug) => set({ selectedSlug }),
  setChart: (chart) => set({ chart }),
  setInterval: (interval) => set({ interval }),
  setWindowDays: (windowDays) => set({ windowDays }),
  setActiveTool: (activeTool) => set({ activeTool }),
  setHovered: (hoveredDrawingId) => set({ hoveredDrawingId }),
  setSelected: (selectedDrawingId) => set({ selectedDrawingId }),
  showError: (errorModal) => set({ errorModal }),
}));
