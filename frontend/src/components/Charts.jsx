/* Charts for the dashboard.
   Colours come from the validated reference palette via CSS custom
   properties: categorical slots 1-3 for brand identity, a single-hue ordinal
   blue ramp for the ageing progression, and the reserved status palette for
   target state (always paired with a label, never colour alone).
   Every chart carries a hover layer; bars with sub-3:1 fills carry visible
   direct labels as the contrast relief. */

import { useState } from "react";
import { money, moneyShort } from "../api";

/** Shared floating tooltip, positioned off the pointer. */
function useTip() {
  const [tip, setTip] = useState(null);
  const show = (event, content) =>
    setTip({ x: event.clientX, y: event.clientY, content });
  const hide = () => setTip(null);
  const node = tip ? (
    <div
      className="chart-tip"
      style={{
        left: Math.min(tip.x + 12, window.innerWidth - 250),
        top: Math.max(tip.y - 46, 8),
      }}
    >
      {tip.content}
    </div>
  ) : null;
  return { show, hide, node };
}

/* --- monthly trend ------------------------------------------------------ */

/** Billed value by month.
 *  One series, so no legend box at all: the card title names it. There is no
 *  target reference line any more -- this business does not run against a
 *  plan, and a bar with nothing to route is just a bar. */
export function TrendBars({ data }) {
  const tip = useTip();
  if (!data?.length) return <div className="empty">No history yet.</div>;

  const width = 100;
  const height = 42;
  const top = 5;
  const plot = height - top - 9;
  const peak = Math.max(...data.map((d) => d.value), 1);
  const slot = width / data.length;
  const barWidth = Math.min(slot - 2.2, 9);

  return (
    <>
      <svg
        className="chart"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        style={{ height: 150 }}
        role="img"
        aria-label="Billed value by month"
      >
        {[0.5, 1].map((frac) => (
          <line
            key={frac}
            x1="0"
            x2={width}
            y1={top + plot - plot * frac}
            y2={top + plot - plot * frac}
            stroke="var(--grid)"
            strokeWidth="0.3"
          />
        ))}

        {data.map((point, index) => {
          const x = slot * index + (slot - barWidth) / 2;
          const barHeight = Math.max((point.value / peak) * plot, 0.6);
          const y = top + plot - barHeight;
          const isLast = index === data.length - 1;
          return (
            <g
              key={point.month}
              onMouseEnter={(event) =>
                tip.show(
                  event,
                  <>
                    <div style={{ fontWeight: 600 }}>{point.month}</div>
                    <div>
                      Billed <b>{money(point.value)}</b>
                    </div>
                    {point.cases != null ? (
                      <div className="muted">{point.cases} cases</div>
                    ) : null}
                  </>,
                )
              }
              onMouseLeave={tip.hide}
            >
              <rect
                x={slot * index}
                y={top}
                width={slot}
                height={plot}
                fill="transparent"
              />
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={barHeight}
                rx="1.2"
                fill="var(--series-1)"
                opacity={isLast ? 1 : 0.78}
              />
              <text
                x={slot * index + slot / 2}
                y={height - 2.2}
                textAnchor="middle"
                fontSize="3.1"
                fill="var(--text-muted)"
              >
                {point.month.split(" ")[0]}
              </text>
            </g>
          );
        })}
      </svg>
      {tip.node}
    </>
  );
}

/* --- ageing buckets ----------------------------------------------------- */

const AGEING_TONE = {
  current: "var(--ordinal-1)",
  "1-7": "var(--ordinal-2)",
  "8-15": "var(--ordinal-3)",
  "16-30": "var(--ordinal-4)",
  "30+": "var(--ordinal-5)",
};

const AGEING_CAPTION = {
  current: "Within credit terms",
  "1-7": "1 to 7 days overdue",
  "8-15": "8 to 15 days overdue",
  "16-30": "16 to 30 days overdue",
  "30+": "Over 30 days overdue",
};

/** Outstanding money by how late it is.
 *  Ordered severity, so a single-hue ordinal ramp rather than categorical
 *  hues; every bar is directly labelled with its value. */
export function AgeingBars({ buckets, total }) {
  const tip = useTip();
  if (!buckets?.length) return <div className="empty">Nothing outstanding.</div>;
  const peak = Math.max(...buckets.map((b) => b.amount), 1);

  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
        {buckets.map((bucket) => (
          <div
            key={bucket.label}
            onMouseEnter={(event) =>
              tip.show(
                event,
                <>
                  <div style={{ fontWeight: 600 }}>
                    {AGEING_CAPTION[bucket.label] || bucket.label}
                  </div>
                  <div>
                    <b>{money(bucket.amount)}</b> across {bucket.count} bill
                    {bucket.count === 1 ? "" : "s"}
                  </div>
                  {total > 0 ? (
                    <div className="muted">
                      {Math.round((bucket.amount / total) * 100)}% of the book
                    </div>
                  ) : null}
                </>,
              )
            }
            onMouseLeave={tip.hide}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 10,
                fontSize: 12,
                marginBottom: 3,
              }}
            >
              <span style={{ color: "var(--text-secondary)" }}>
                {bucket.label === "current" ? "Within terms" : `${bucket.label} days`}
                <span className="muted"> · {bucket.count}</span>
              </span>
              <span style={{ fontVariantNumeric: "tabular-nums", fontWeight: 550 }}>
                {moneyShort(bucket.amount)}
              </span>
            </div>
            <div
              style={{
                height: 8,
                background: "var(--surface-2)",
                borderRadius: 999,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${Math.max((bucket.amount / peak) * 100, bucket.amount > 0 ? 1.5 : 0)}%`,
                  height: "100%",
                  borderRadius: 999,
                  background: AGEING_TONE[bucket.label] || "var(--ordinal-3)",
                }}
              />
            </div>
          </div>
        ))}
      </div>
      {tip.node}
    </>
  );
}
