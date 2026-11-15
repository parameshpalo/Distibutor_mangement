import { useState } from "react";
import Masters from "./Masters";
import MyFirm from "./MyFirm";
import Parties from "./Parties";

/** Setup: the things that are typed once and then mostly left alone. */

const TABS = [
  ["parties", "Customers", Parties],
  ["masters", "Products & rates", Masters],
  ["firm", "My firm", MyFirm],
];

export default function Setup() {
  const [tab, setTab] = useState("parties");
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
