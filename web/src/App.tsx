/**
 * App shell — two-column layout (sidebar + main).
 *
 * Phase C will add a third column (`RationalePanel.tsx`) by changing
 * `.app-shell` grid-template-columns from `280px 1fr` to `280px 1fr 320px`.
 */

import { PairList } from "./views/PairList";
import { PairView } from "./views/PairView";
import { ErrorModal } from "./views/SchemaMismatchModal";

export function App() {
  return (
    <div className="app-shell">
      <PairList />
      <PairView />
      <ErrorModal />
    </div>
  );
}
