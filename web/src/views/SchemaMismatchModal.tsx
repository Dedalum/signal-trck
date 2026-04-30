/**
 * Schema-version mismatch + generic-error modal (Decision 24).
 *
 * Triggered by the `errorModal` slot in the store. Shows the server error
 * message verbatim, with copy-to-clipboard + close affordances. Not a
 * banner, not a toast.
 */

import { useStore } from "../store";

export function ErrorModal() {
  const modal = useStore((s) => s.errorModal);
  const close = useStore((s) => s.showError);
  if (!modal) return null;

  const copy = () => {
    void navigator.clipboard.writeText(modal.message);
  };

  return (
    <div className="modal-backdrop" onClick={() => close(null)}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{modal.title}</h2>
        <pre>{modal.message}</pre>
        {modal.code !== undefined && (
          <p style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 8 }}>
            code: <code>{modal.code}</code>
          </p>
        )}
        <div className="modal-buttons">
          <button onClick={copy}>Copy message</button>
          <button onClick={() => close(null)}>Close</button>
        </div>
      </div>
    </div>
  );
}
