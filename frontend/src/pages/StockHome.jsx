import { useState } from "react";
import Inward from "./Inward";
import Stock from "./Stock";

/**
 * Stock: what is on hand, and what arrived.
 *
 * Goods inward was its own nav item, but receiving stock and looking at stock
 * are the same subject from two ends. The on-hand view now also says how much
 * of the total is out on vans rather than in the godown.
 */

const TABS = [
  ["onhand", "On hand", Stock],
  ["inward", "Goods received", Inward],
];

export default function StockHome() {
  const [tab, setTab] = useState("onhand");
  const Active = TABS.find(([key]) => key === tab)[2];

  return (
    <>
      <div className="toolbar">
        <div className="segmented">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              className={tab === key ? "primary" : ""}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <Active />
    </>
  );
}
