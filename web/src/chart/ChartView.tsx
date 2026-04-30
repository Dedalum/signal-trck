/**
 * ChartView — Lightweight Charts v5 wiring.
 *
 * Mounts a single chart per pair view, with one main candle pane + optional
 * sub-panes for indicators (volume, RSI, MACD). SMA/EMA overlay onto the
 * price pane.
 *
 * Per the §Chart rendering strategy in the Phase B plan: indicators come and
 * go via `addLineSeries` / `removeSeries` based on the chart's `view.indicators`.
 * Volume gets its own pane via the v5 panes API.
 */

import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import * as api from "../api";
import { DrawingLayer } from "../drawings/DrawingLayer";
import type { Drawing } from "../drawings/serialize";
import { useStore, type Interval } from "../store";
import type { components } from "../api-types";

type Indicator = components["schemas"]["Indicator"];

interface Props {
  pairId: string;
  interval: Interval;
  windowDays: number;
}

export function ChartView({ pairId, interval, windowDays }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  // Indicator id -> ISeriesApi (one per output key in case of multi-output)
  const indicatorSeriesRef = useRef<Map<string, ISeriesApi<"Line">[]>>(new Map());
  // Force re-render after chart mounts so the DrawingLayer can read the refs.
  const [mounted, setMounted] = useState(false);

  const chart = useStore((s) => s.chart);
  const setChart = useStore((s) => s.setChart);

  // Mount chart once.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const c = createChart(el, {
      width: el.clientWidth,
      height: el.clientHeight,
      layout: {
        background: { color: "#0e1116" },
        textColor: "#e6edf3",
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "#161b22" },
        horzLines: { color: "#161b22" },
      },
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: "#30363d" },
      crosshair: { mode: 1 },
    });
    const candleSeries = c.addSeries(CandlestickSeries, {
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderUpColor: "#26a69a",
      borderDownColor: "#ef5350",
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });
    const volumeSeries = c.addSeries(
      HistogramSeries,
      {
        color: "rgba(38, 166, 154, 0.5)",
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      },
      1, // pane index — sub-pane below price
    );
    c.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.7, bottom: 0 },
    });
    chartRef.current = c;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    setMounted(true);

    // Resize handling
    const ro = new ResizeObserver(() => {
      if (!chartRef.current || !el) return;
      chartRef.current.applyOptions({
        width: el.clientWidth,
        height: el.clientHeight,
      });
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      c.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      indicatorSeriesRef.current.clear();
    };
  }, []);

  // Load + render candles whenever pair / interval / window changes.
  useEffect(() => {
    let cancelled = false;
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return;
    void api.getCandles(pairId, interval, windowDays).then((candles) => {
      if (cancelled) return;
      const candleSeries = candleSeriesRef.current;
      const volumeSeries = volumeSeriesRef.current;
      if (!candleSeries || !volumeSeries) return;
      candleSeries.setData(
        candles.map((c) => ({
          time: c.ts_utc as UTCTimestamp,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        })),
      );
      volumeSeries.setData(
        candles.map((c) => ({
          time: c.ts_utc as UTCTimestamp,
          value: c.volume,
          color:
            c.close >= c.open
              ? "rgba(38, 166, 154, 0.5)"
              : "rgba(239, 83, 80, 0.5)",
        })),
      );
      chartRef.current?.timeScale().fitContent();
    });
    return () => {
      cancelled = true;
    };
  }, [pairId, interval, windowDays]);

  // Render indicators when chart.view.indicators changes.
  useEffect(() => {
    if (!chartRef.current) return;
    const c = chartRef.current;
    const seriesMap = indicatorSeriesRef.current;

    // Compute desired ID set
    const desired: Indicator[] = chart?.view.indicators ?? [];
    const desiredIds = new Set(desired.map((i) => i.id));

    // Remove stale series
    for (const [id, list] of seriesMap.entries()) {
      if (!desiredIds.has(id)) {
        for (const s of list) c.removeSeries(s);
        seriesMap.delete(id);
      }
    }

    // Add new series
    let cancelled = false;
    for (const ind of desired) {
      if (seriesMap.has(ind.id)) continue;
      const params: api.IndicatorParams = {};
      const indParams = ind.params ?? {};
      if (typeof indParams.period === "number") params.period = indParams.period;
      if (typeof indParams.fast === "number") params.fast = indParams.fast;
      if (typeof indParams.slow === "number") params.slow = indParams.slow;
      if (typeof indParams.signal === "number") params.signal = indParams.signal;
      if (typeof indParams.stddev === "number") params.stddev = indParams.stddev;

      // Pane 0 = price overlay (SMA/EMA/BB); pane 1+ = sub-pane (RSI, MACD).
      const pane = ind.pane ?? 0;
      const colors = ["#f4a261", "#e76f51", "#2a9d8f", "#a594f9"];
      void api.getIndicator(pairId, ind.name, interval, params).then((resp) => {
        if (cancelled || !chartRef.current) return;
        const list: ISeriesApi<"Line">[] = [];
        resp.series.forEach((s, idx) => {
          const series = c.addSeries(
            LineSeries,
            {
              color: colors[(idx + 1) % colors.length] ?? "#ffffff",
              lineWidth: 2,
              priceLineVisible: false,
              lastValueVisible: false,
            },
            pane,
          );
          series.setData(
            s.points.map((p) => ({
              time: p.ts_utc as UTCTimestamp,
              value: p.value,
            })),
          );
          list.push(series);
        });
        seriesMap.set(ind.id, list);
      });
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chart?.view.indicators, pairId, interval]);

  const handleDrawingsChange = (drawings: Drawing[]) => {
    if (!chart) return;
    setChart({
      ...chart,
      view: { ...chart.view, drawings },
    });
  };

  const drawings: Drawing[] = chart?.view.drawings ?? [];

  return (
    <>
      <div ref={containerRef} className="chart-area" />
      {mounted && (
        <DrawingLayer
          chart={chartRef.current}
          series={candleSeriesRef.current}
          containerEl={containerRef.current}
          drawings={drawings}
          onDrawingsChange={handleDrawingsChange}
        />
      )}
    </>
  );
}
