import { useState } from "react";
import { Link } from "react-router-dom";
import { api, date, money, num, useApi } from "../api";

// Three words, in the order they happen. Both screens show the same line,
// because "where is that van" is the one question either of them answers.
const STAGES = [
  { key: "open", label: "Adding bills" },
  { key: "out", label: "On the road" },
  { key: "done", label: "Back" },
];

export const RUN_TONE = { open: "", out: "warn", done: "good" };

export function Stages({ status }) {
  const at = STAGES.findIndex((s) => s.key === status);
  return (
    <div className="stages">
      {STAGES.map((stage, index) => (
        <span
          key={stage.key}
          className={`stage ${index <= at ? "done" : ""} ${
            index === at ? "now" : ""
          }`}
        >
          {stage.label}
        </span>
      ))}
    </div>
  );
}

/**
 * One van run, with everything on it.
 *
 * The same component appears on Deliveries and inside the Bill screen. That
 * is the point: once a bill is going on a van, the next thing the owner
 * wants is this view — what is aboard so far, what to load, and the button
 * that sends it out — without changing screens to find it.
 *
 * `onChanged` fires after anything that alters the run, so the host page can
 * refresh its own lists.
 */
export default function VanRun({ runId, onChanged, onClose, version = 0 }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [local, setLocal] = useState(0);
  const [addBill, setAddBill] = useState("");

  const bump = () => {
    setLocal((v) => v + 1);
    onChanged?.();
  };

  const { data: run } = useApi(runId ? `/deliveries/${runId}` : null, [
    runId,
    version,
    local,
  ]);
  const { data: load } = useApi(
    runId ? `/deliveries/${runId}/loading-list` : null,
    [runId, version, local],
  );
  // Bills with no van yet: the pool this run can draw from.
  const { data: recent } = useApi("/invoices?limit=60", [version, local]);
  const unassigned = (recent || []).filter(
    (b) => !b.delivery_id && b.status !== "cancelled",
  );

  async function act(work) {
    setBusy(true);
    setError(null);
    try {
      await work();
      bump();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!runId) return null;
  if (!run) return <div className="loading">Loading the van…</div>;

  const live = run.status !== "done";

  return (
    <div className="card">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 12,
        }}
      >
        <div>
          <div className="card-title" style={{ marginBottom: 2 }}>
            {run.delivery_no}
          </div>
          <div className="sub">{date(run.delivery_date)}</div>
        </div>
        <div className="row">
          <span className={`badge ${RUN_TONE[run.status] || ""}`}>
            {run.status}
          </span>
          {onClose ? (
            <button className="ghost" onClick={onClose}>
              Close
            </button>
          ) : null}
        </div>
      </div>

      <div style={{ margin: "12px 0" }}>
        <Stages status={run.status} />
      </div>

      {error ? (
        <div className="notice error" style={{ marginBottom: 12 }}>
          {error.message}
        </div>
      ) : null}

      <div className="grid g4" style={{ marginBottom: 12 }}>
        <div>
          <div className="stat-label">Bills</div>
          <div className="stat-value">{run.bill_count}</div>
          <div className="stat-note">
            {run.shop_count} {run.shop_count === 1 ? "shop" : "shops"}
          </div>
        </div>
        <div>
          <div className="stat-label">Value</div>
          <div className="stat-value">{money(run.value)}</div>
          <div className="stat-note">already billed</div>
        </div>
        <div>
          <div className="stat-label">To load</div>
          <div className="stat-value">{run.total_cases}</div>
          <div className="stat-note">cases · {num(run.total_pieces)} pc</div>
        </div>
        <div>
          <div className="stat-label">Products</div>
          <div className="stat-value">{load?.line_count ?? "—"}</div>
          <div className="stat-note">lines on the loading list</div>
        </div>
      </div>

      {live ? (
        <div className="row" style={{ marginBottom: 12 }}>
          {run.status === "open" ? (
            <button
              className="primary"
              disabled={busy || !run.bill_count}
              title={
                run.bill_count ? "" : "Add the bills the van is carrying first"
              }
              onClick={() =>
                act(() =>
                  api.post(`/deliveries/${run.id}/status`, { status: "out" }),
                )
              }
            >
              Send the van out
            </button>
          ) : (
            <button
              className="primary"
              disabled={busy}
              onClick={() =>
                act(() =>
                  api.post(`/deliveries/${run.id}/status`, { status: "done" }),
                )
              }
            >
              Van is back
            </button>
          )}
        </div>
      ) : null}

      <div
        className="grid"
        style={{
          gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)",
          gap: 14,
        }}
      >
        <div>
          <div className="card-title">On this run</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Bill</th>
                  <th>Shop</th>
                  <th className="num">Pieces</th>
                  <th className="num">Amount</th>
                  <th style={{ width: 40 }} />
                </tr>
              </thead>
              <tbody>
                {run.bills.map((bill) => (
                  <tr key={bill.id}>
                    <td className="mono">
                      <Link to={`/invoices/${bill.id}`}>{bill.invoice_no}</Link>
                    </td>
                    <td>
                      {bill.shop_name}
                      {bill.address_line ? (
                        <div className="sub">{bill.address_line}</div>
                      ) : null}
                    </td>
                    <td className="num">{num(bill.pieces)}</td>
                    <td className="num">{money(bill.grand_total)}</td>
                    <td>
                      {live ? (
                        <button
                          className="ghost"
                          disabled={busy}
                          title="Take this bill off the van. The bill itself is unchanged."
                          onClick={() =>
                            act(() =>
                              api.del(
                                `/deliveries/${run.id}/bills/${bill.id}`,
                              ),
                            )
                          }
                        >
                          ✕
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
                {!run.bills.length ? (
                  <tr>
                    <td colSpan={5} className="sub">
                      Nothing on this van yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>

          {live ? (
            <div className="row" style={{ marginTop: 11 }}>
              <label className="field grow">
                <span>Add a bill already raised</span>
                <select
                  value={addBill}
                  onChange={(e) => setAddBill(e.target.value)}
                >
                  <option value="">Pick a bill with no van…</option>
                  {unassigned.map((bill) => (
                    <option key={bill.id} value={bill.id}>
                      {bill.invoice_no} · {bill.retailer_name} ·{" "}
                      {money(bill.grand_total)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                disabled={busy || !addBill}
                onClick={() =>
                  act(async () => {
                    await api.post(`/deliveries/${run.id}/bills/${addBill}`);
                    setAddBill("");
                  })
                }
              >
                Add to van
              </button>
            </div>
          ) : null}
        </div>

        <div>
          <div className="card-title">Load this into the van</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="num">Cases</th>
                  <th className="num">Loose</th>
                  <th className="num">Pieces</th>
                </tr>
              </thead>
              <tbody>
                {(load?.items || []).map((item) => (
                  <tr key={item.product_id}>
                    <td>
                      {item.name}
                      <div className="sub mono">{item.sku_code}</div>
                    </td>
                    <td className="num">{item.cases || "—"}</td>
                    <td className="num">{item.loose_pieces || "—"}</td>
                    <td className="num">{num(item.pieces)}</td>
                  </tr>
                ))}
                {!(load?.items || []).length ? (
                  <tr>
                    <td colSpan={4} className="sub">
                      Add bills and the loading list builds itself.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <div className="form-hint" style={{ marginTop: 9 }}>
            Every bill on this run, added up by product, so the godown is
            walked once. These goods are already sold — this is a packing
            list, not a stock movement.
          </div>
        </div>
      </div>
    </div>
  );
}
