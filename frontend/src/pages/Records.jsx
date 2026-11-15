import { useState } from "react";
import Gst from "./Gst";
import Invoices from "./Invoices";
import Returns from "./Returns";

/**
 * Records: what has already happened.
 *
 * Three things that were three nav items, and are really one question — "show
 * me what was done" — asked about bills, returns, or the GST return. Keeping
 * them apart in the sidebar made the app look like eleven jobs instead of
 * five.
 */

const TABS = [
  ["bills", "Bills raised", Invoices],
  ["returns", "Returns", Returns],
  ["gst", "GST return", Gst],
];

export default function Records() {
  const [tab, setTab] = useState("bills");
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
