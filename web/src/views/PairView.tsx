/**
 * Main view — toolbar (interval/window controls + save/save-as/export/import)
 * + chart canvas. Loads the selected chart on slug change.
 */

import { useEffect, useRef } from "react";
import * as api from "../api";
import { ChartView } from "../chart/ChartView";
import { useStore, type DrawingTool, type Interval } from "../store";

export function PairView() {
  const selectedPairId = useStore((s) => s.selectedPairId);
  const selectedSlug = useStore((s) => s.selectedSlug);
  const chart = useStore((s) => s.chart);
  const setChart = useStore((s) => s.setChart);
  const interval = useStore((s) => s.interval);
  const windowDays = useStore((s) => s.windowDays);
  const setInterval = useStore((s) => s.setInterval);
  const setWindowDays = useStore((s) => s.setWindowDays);
  const showError = useStore((s) => s.showError);
  const importInputRef = useRef<HTMLInputElement | null>(null);

  // Load chart when slug changes.
  useEffect(() => {
    if (!selectedSlug) {
      setChart(null);
      return;
    }
    void api
      .getChart(selectedSlug)
      .then((c) => {
        setChart(c);
        setInterval(c.data.default_interval as Interval);
        setWindowDays(c.data.default_window_days);
      })
      .catch((e: unknown) => {
        const err = e instanceof api.ApiError ? e : null;
        showError({
          title:
            err?.code === "SCHEMA_MISMATCH" ? "Schema mismatch" : "Could not load chart",
          message: err ? err.detail : String(e),
          ...(err?.code !== undefined && { code: err.code }),
        });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSlug]);

  const handleSaveAs = async () => {
    if (!selectedPairId) return;
    const title = prompt("Title for new chart?", "New chart");
    if (!title) return;
    // Build a fresh chart with no slug (backend allocates).
    // For Phase B.1 the user starts a chart by clicking "New" — server
    // can't allocate a slug from POST /charts directly because the body
    // includes `slug`. We hit /charts/{next-slug}/... — actually simplest:
    // ask user for slug.
    const slug = prompt("Slug?", "chart-1");
    if (!slug) return;

    try {
      const newChart = await api.createChart({
        schemaVersion: 1,
        slug,
        title,
        pair: selectedPairId,
        provenance: {
          kind: "user",
          created_at: new Date().toISOString(),
        },
        parent_chart_id: null,
        data: {
          default_window_days: windowDays,
          default_interval: interval,
        },
        view: {
          indicators: chart?.view.indicators ?? [],
          drawings: (chart?.view.drawings ?? []) as never,
          analysis_text: chart?.view.analysis_text ?? null,
        },
        ai_run: null,
      });
      setChart(newChart);
      useStore.getState().selectSlug(newChart.slug);
    } catch (e) {
      const err = e instanceof api.ApiError ? e : null;
      showError({
        title: "Could not save chart",
        message: err ? err.detail : String(e),
        ...(err?.code !== undefined && { code: err.code }),
      });
    }
  };

  const handleSave = async () => {
    if (!chart || !selectedSlug) {
      void handleSaveAs();
      return;
    }
    try {
      const updated = await api.updateChart(selectedSlug, {
        ...chart,
        data: {
          default_window_days: windowDays,
          default_interval: interval,
        },
      });
      setChart(updated);
    } catch (e) {
      const err = e instanceof api.ApiError ? e : null;
      showError({
        title: "Could not save chart",
        message: err ? err.detail : String(e),
        ...(err?.code !== undefined && { code: err.code }),
      });
    }
  };

  const handleExport = async () => {
    if (!selectedSlug) return;
    const blob = await api.exportChart(selectedSlug);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selectedSlug}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = async (file: File) => {
    try {
      const imported = await api.importChart(file);
      setChart(imported);
      useStore.getState().selectSlug(imported.slug);
    } catch (e) {
      const err = e instanceof api.ApiError ? e : null;
      showError({
        title:
          err?.code === "SCHEMA_MISMATCH" ? "Schema mismatch" : "Could not import chart",
        message: err ? err.detail : String(e),
        ...(err?.code !== undefined && { code: err.code }),
      });
    }
  };

  if (!selectedPairId) {
    return (
      <main className="main">
        <div className="empty-state">Select or add a pair to get started</div>
      </main>
    );
  }

  return (
    <main className="main">
      <div className="toolbar">
        <select
          value={interval}
          onChange={(e) => setInterval(e.target.value as Interval)}
        >
          <option value="1h">1h</option>
          <option value="1d">1d</option>
          <option value="1w">1w</option>
        </select>
        <select
          value={windowDays}
          onChange={(e) => setWindowDays(Number(e.target.value))}
        >
          <option value={30}>30d</option>
          <option value={90}>90d</option>
          <option value={180}>180d</option>
          <option value={365}>1y</option>
          <option value={730}>2y</option>
        </select>
        <span style={{ color: "var(--text-dim)" }}>{selectedPairId}</span>
        <span style={{ flex: 1 }} />
        <DrawingToolButtons />
        <button onClick={() => void handleSave()}>Save</button>
        <button onClick={() => void handleSaveAs()}>Save as</button>
        <button onClick={() => void handleExport()} disabled={!selectedSlug}>
          Export
        </button>
        <button onClick={() => importInputRef.current?.click()}>Import</button>
        <input
          ref={importInputRef}
          type="file"
          accept="application/json"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void handleImport(f);
            e.target.value = "";
          }}
        />
      </div>
      <ChartView
        pairId={selectedPairId}
        interval={interval}
        windowDays={windowDays}
      />
    </main>
  );
}

function DrawingToolButtons() {
  const activeTool = useStore((s) => s.activeTool);
  const setActiveTool = useStore((s) => s.setActiveTool);
  const tools: { id: DrawingTool; label: string }[] = [
    { id: "select", label: "Select" },
    { id: "horizontal", label: "H-line" },
    { id: "trendline", label: "Trend" },
    { id: "rect", label: "Rect" },
  ];
  return (
    <div style={{ display: "flex", gap: 4 }}>
      {tools.map((t) => (
        <button
          key={t.id}
          onClick={() => setActiveTool(t.id)}
          style={
            activeTool === t.id
              ? { borderColor: "var(--accent)", color: "var(--accent)" }
              : {}
          }
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
