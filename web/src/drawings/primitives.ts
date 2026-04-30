/**
 * Custom drawing primitives on top of Lightweight Charts v5's
 * `ISeriesPrimitive` API.
 *
 * Decision 9 (post-implementation amendment): custom on primitives because
 * the difurious plugin isn't on npm. Three shapes — TrendLine,
 * HorizontalLine, Rectangle — implemented here with shared rendering
 * helpers. Wired to mouse events in `DrawingLayer.tsx`.
 *
 * Reference: tradingview/lightweight-charts/plugin-examples/trend-line
 * (Apache-2.0).
 */

import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Time,
} from "lightweight-charts";
import type { Drawing } from "./serialize";
import { resolveStyle } from "./styles";

interface PointPx {
  x: number;
  y: number;
}

function anchorToPx(
  chart: IChartApi,
  series: ISeriesApi<"Candlestick">,
  ts_utc: number,
  price: number,
): PointPx | null {
  const x = chart.timeScale().timeToCoordinate(ts_utc as Time);
  const y = series.priceToCoordinate(price);
  if (x === null || y === null) return null;
  return { x, y };
}

export function pxToAnchor(
  chart: IChartApi,
  series: ISeriesApi<"Candlestick">,
  px: PointPx,
): { ts_utc: number; price: number } | null {
  const time = chart.timeScale().coordinateToTime(px.x);
  const price = series.coordinateToPrice(px.y);
  if (time === null || price === null) return null;
  // Time can be UTCTimestamp (number) or BusinessDay; we always use UTCTimestamp.
  const ts = typeof time === "number" ? time : 0;
  return { ts_utc: ts, price };
}

class _Renderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly drawing: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<"Candlestick">,
  ) {}

  draw(target: { useBitmapCoordinateSpace: (cb: (scope: { context: CanvasRenderingContext2D; bitmapSize: { width: number; height: number } }) => void) => void }) {
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const style = resolveStyle(
        this.drawing.style.color,
        this.drawing.provenance?.kind ?? null,
      );
      ctx.save();
      ctx.strokeStyle = style.color;
      ctx.lineWidth = style.lineWidth * window.devicePixelRatio;
      if (style.lineDash.length) {
        ctx.setLineDash(
          style.lineDash.map((n) => n * window.devicePixelRatio),
        );
      }
      const dpr = window.devicePixelRatio;

      const anchors = this.drawing.anchors
        .map((a) => anchorToPx(this.chart, this.series, a.ts_utc, a.price))
        .filter((p): p is PointPx => p !== null);

      if (anchors.length === 0) {
        ctx.restore();
        return;
      }

      if (this.drawing.kind === "horizontal") {
        const a = anchors[0];
        if (!a) {
          ctx.restore();
          return;
        }
        ctx.beginPath();
        ctx.moveTo(0, a.y * dpr);
        ctx.lineTo(scope.bitmapSize.width, a.y * dpr);
        ctx.stroke();
      } else if (this.drawing.kind === "trend" && anchors.length === 2) {
        const a = anchors[0];
        const b = anchors[1];
        if (!a || !b) {
          ctx.restore();
          return;
        }
        ctx.beginPath();
        ctx.moveTo(a.x * dpr, a.y * dpr);
        ctx.lineTo(b.x * dpr, b.y * dpr);
        ctx.stroke();
      } else if (this.drawing.kind === "rect" && anchors.length === 2) {
        const a = anchors[0];
        const b = anchors[1];
        if (!a || !b) {
          ctx.restore();
          return;
        }
        const x = Math.min(a.x, b.x) * dpr;
        const y = Math.min(a.y, b.y) * dpr;
        const w = Math.abs(b.x - a.x) * dpr;
        const h = Math.abs(b.y - a.y) * dpr;
        ctx.strokeRect(x, y, w, h);
        ctx.fillStyle = style.color;
        ctx.globalAlpha = 0.08;
        ctx.fillRect(x, y, w, h);
      }

      ctx.restore();
    });
  }
}

class _PaneView implements IPrimitivePaneView {
  constructor(
    private readonly drawing: Drawing,
    private readonly chart: IChartApi,
    private readonly series: ISeriesApi<"Candlestick">,
  ) {}

  renderer(): IPrimitivePaneRenderer {
    return new _Renderer(this.drawing, this.chart, this.series);
  }
}

export class DrawingPrimitive implements ISeriesPrimitive<Time> {
  private _drawing: Drawing;
  private readonly _paneViews: _PaneView[];

  constructor(
    drawing: Drawing,
    chart: IChartApi,
    series: ISeriesApi<"Candlestick">,
  ) {
    this._drawing = drawing;
    this._paneViews = [new _PaneView(drawing, chart, series)];
  }

  get drawing(): Drawing {
    return this._drawing;
  }

  paneViews(): readonly _PaneView[] {
    return this._paneViews;
  }

  updateAllViews(): void {
    // Pane views read from `this._drawing` directly; nothing cached.
  }
}
