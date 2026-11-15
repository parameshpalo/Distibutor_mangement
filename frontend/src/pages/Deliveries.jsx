import { useState } from "react";
import { api, dateShort, money, todayIso, useApi } from "../api";
import VanRun, { RUN_TONE } from "../components/VanRun";

export default function Deliveries() {
  const [version, setVersion] = useState(0);
  const [openId, setOpenId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [runDate, setRunDate] = useState(todayIso());

  const { data: runs } = useApi("/deliveries?limit=30", [version]);
  const { data: recentBills } = useApi("/invoices?limit=60", [version]);

  const refresh = () => setVersion((v) => v + 1);

  const list = runs || [];
  const outNow = list.filter((r) => r.status === "out");
  const openNow = list.filter((r) => r.status === "open");
  const unassigned = (recentBills || []).filter(
    (b) => !b.delivery_id && b.status !== "cancelled",
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Deliveries</h1>
          <div className="page-sub">
            A van run is the bills it is carrying. Put bills on it, print the
            loading list, send it out.
          </div>
        </div>
        <button
          className="primary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              const created = await api.post("/deliveries", {
                delivery_date: runDate,
              });
              setOpenId(created.id);
              refresh();
            } catch (err) {
              setError(err);
            } finally {
              setBusy(false);
            }
          }}
        >
          + Start a run
        </button>
      </div>

      {error ? (
        <div className="notice error" style={{ marginBottom: 14 }}>
          {error.message}
        </div>
      ) : null}

      <div className="grid g4" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="stat-label">Vans out</div>
          <div className="stat-value">{outNow.length}</div>
          <div className="stat-note">
            {outNow.length
              ? outNow.map((r) => r.delivery_no).join(" · ")
              : "none on the road"}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Value out there</div>
          <div className="stat-value">
            {money(outNow.reduce((sum, r) => sum + r.value, 0))}
          </div>
          <div className="stat-note">billed, not yet handed over</div>
        </div>
        <div className="card">
          <div className="stat-label">Being loaded</div>
          <div className="stat-value">{openNow.length}</div>
          <div className="stat-note">runs still taking bills</div>
        </div>
        <div className="card">
          <div className="stat-label">Bills with no van</div>
          <div className="stat-value">{unassigned.length}</div>
          <div className="stat-note">
            of the last {(recentBills || []).length} — most are collected by
            the buyer
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="row">
          <label className="field" style={{ width: 180 }}>
            <span>New run dated</span>
            <input
              type="date"
              value={runDate}
              onChange={(e) => setRunDate(e.target.value)}
            />
          </label>
          <div className="form-hint" style={{ flex: "1 1 320px" }}>
            A run starts empty. You can also start one straight from the Bill
            screen, which puts that bill on it and keeps you there to add the
            next.
          </div>
        </div>
      </div>

      {openId ? (
        <div style={{ marginBottom: 14 }}>
          <VanRun
            runId={openId}
            version={version}
            onChanged={refresh}
            onClose={() => setOpenId(null)}
          />
        </div>
      ) : null}

      <div className="card">
        <div className="card-title">Recent runs</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Date</th>
                <th className="num">Bills</th>
                <th className="num">Shops</th>
                <th className="num">Cases</th>
                <th className="num">Value</th>
                <th>Stage</th>
                <th style={{ width: 60 }} />
              </tr>
            </thead>
            <tbody>
              {list.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.delivery_no}</td>
                  <td className="shrink">{dateShort(row.delivery_date)}</td>
                  <td className="num">{row.bill_count}</td>
                  <td className="num">{row.shop_count}</td>
                  <td className="num">{row.total_cases || "—"}</td>
                  <td className="num">{money(row.value)}</td>
                  <td>
                    <span className={`badge ${RUN_TONE[row.status] || ""}`}>
                      {row.status}
                    </span>
                  </td>
                  <td>
                    <button className="ghost" onClick={() => setOpenId(row.id)}>
                      open
                    </button>
                  </td>
                </tr>
              ))}
              {!list.length ? (
                <tr>
                  <td colSpan={8} className="sub">
                    No van runs yet. Start one above, or choose “I deliver it”
                    on a bill.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
