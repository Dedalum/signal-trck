/**
 * Left sidebar — lists tracked pairs + saved charts per pair.
 *
 * Phase B: chart cards are plain (no AI badge — that's Phase C). Click a
 * pair to select it; click a chart slug to load it.
 */

import { useEffect, useState } from "react";
import * as api from "../api";
import { useStore } from "../store";

export function PairList() {
  const pairs = useStore((s) => s.pairs);
  const setPairs = useStore((s) => s.setPairs);
  const selectedPairId = useStore((s) => s.selectedPairId);
  const selectPair = useStore((s) => s.selectPair);
  const selectedSlug = useStore((s) => s.selectedSlug);
  const selectSlug = useStore((s) => s.selectSlug);
  const showError = useStore((s) => s.showError);

  const [charts, setCharts] = useState<api.ChartListItem[]>([]);
  const [pairInput, setPairInput] = useState("");

  // Load pair list on mount.
  useEffect(() => {
    void api
      .listPairs()
      .then(setPairs)
      .catch((e: unknown) => {
        showError({
          title: "Failed to load pairs",
          message: e instanceof Error ? e.message : String(e),
        });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load charts when pair changes.
  useEffect(() => {
    if (!selectedPairId) {
      setCharts([]);
      return;
    }
    void api.listCharts(selectedPairId).then(setCharts);
  }, [selectedPairId]);

  const handleAddPair = async () => {
    if (!pairInput.trim()) return;
    try {
      await api.createPair(pairInput.trim());
      setPairInput("");
      const fresh = await api.listPairs();
      setPairs(fresh);
    } catch (e) {
      const err = e instanceof api.ApiError ? e : null;
      showError({
        title: "Could not add pair",
        message: err ? err.detail : String(e),
        ...(err?.code !== undefined && { code: err.code }),
      });
    }
  };

  return (
    <aside className="sidebar">
      <h2>Pairs</h2>
      <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
        <input
          type="text"
          placeholder="coinbase:BTC-USD"
          value={pairInput}
          onChange={(e) => setPairInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleAddPair();
          }}
        />
        <button onClick={() => void handleAddPair()}>Add</button>
      </div>
      <ul className="pair-list">
        {pairs.map((p) => (
          <li
            key={p.pair_id}
            className={p.pair_id === selectedPairId ? "active" : ""}
            onClick={() => selectPair(p.pair_id)}
          >
            {p.pair_id}
          </li>
        ))}
        {pairs.length === 0 && (
          <li style={{ color: "var(--text-dim)", cursor: "default" }}>
            no pairs yet
          </li>
        )}
      </ul>

      {selectedPairId && (
        <>
          <h2>Charts</h2>
          <ul className="chart-list">
            {charts.map((c) => (
              <li
                key={c.slug}
                className={c.slug === selectedSlug ? "active" : ""}
                onClick={() => selectSlug(c.slug)}
              >
                {c.slug} — {c.title}
              </li>
            ))}
            {charts.length === 0 && (
              <li style={{ color: "var(--text-dim)", cursor: "default" }}>
                no charts saved
              </li>
            )}
          </ul>
        </>
      )}
    </aside>
  );
}
