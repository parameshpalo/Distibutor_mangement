import { useState } from "react";
import { date, money, moneyShort, num, useApi } from "../api";

const RISK_FILTERS = [
  ["", "All stock"],
  ["near_expiry", "Near expiry"],
  ["expired", "Expired"],
  ["low_cover", "Running low"],
];

export default function Stock() {
  const [search, setSearch] = useState("");
  const [risk, setRisk] = useState("");
  const [open, setOpen] = useState(null);

  const query = new URLSearchParams();
  if (search.trim()) query.set("search", search.trim());
  if (risk) query.set("risk", risk);
  const { data, error, loading } = useApi(`/stock?${query}`);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Stock</h1>
          <div className="page-sub">
            Batch-wise, valued at cost. Sold first-expiry-first-out.
          </div>
        </div>
      </div>

      {data ? (
        <div className="grid g4" style={{ marginBottom: 14 }}>
          <div className="card">
            <div className="stat-label">Value at cost</div>
            <div className="stat-value">{moneyShort(data.totals.value)}</div>
            <div className="stat-foot">{data.totals.skus} SKUs in stock</div>
          </div>
          <div className="card">
            <div className="stat-label">Pieces</div>
            <div className="stat-value">{num(data.totals.pieces)}</div>
          </div>
          <div className="card">
            <div className="stat-label">Near expiry</div>
            <div
              className="stat-value"
              style={{
                color: data.totals.near_expiry_value > 0 ? "var(--serious)" : "inherit",
              }}
            >
              {moneyShort(data.totals.near_expiry_value)}
            </div>
            <div className="stat-foot">Within 90 days</div>
          </div>
          <div className="card">
            <div className="stat-label">Expired</div>
            <div
              className="stat-value"
              style={{
                color: data.totals.expired_pieces > 0 ? "var(--critical)" : "inherit",
              }}
            >
              {num(data.totals.expired_pieces)}
            </div>
            <div className="stat-foot">Pieces to write off</div>
          </div>
        </div>
      ) : null}

      <div className="toolbar">
        <input
          placeholder="Product or SKU code"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          style={{ maxWidth: 280 }}
        />
        <select
          value={risk}
          onChange={(event) => setRisk(event.target.value)}
          style={{ width: 170 }}
        >
          {RISK_FILTERS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      {error ? <div className="notice error">{error.message}</div> : null}

      <div className="card">
        {loading ? (
          <div className="loading">Loading…</div>
        ) : !data?.items?.length ? (
          <div className="empty">Nothing matches that filter.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="num">Cases</th>
                  <th className="num">Pieces</th>
                  <th className="num">At cost</th>
                  <th className="num">Cover</th>
                  <th className="num">Earliest expiry</th>
                  <th className="num">At risk</th>
                  <th style={{ width: 70 }} />
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <>
                    <tr key={item.product_id}>
                      <td>
                        <div>{item.name}</div>
                        <div className="sub mono">{item.sku_code}</div>
                      </td>
                      <td className="num">{item.cases}</td>
                      <td className="num muted">{num(item.pieces)}</td>
                      <td className="num">{money(item.value)}</td>
                      <td className="num">
                        {item.cover_days == null ? (
                          <span className="muted">no sales</span>
                        ) : (
                          <span
                            style={{
                              color:
                                item.cover_days < 7
                                  ? "var(--critical)"
                                  : item.cover_days < 10
                                    ? "var(--serious)"
                                    : "inherit",
                            }}
                          >
                            {item.cover_days}d
                          </span>
                        )}
                      </td>
                      <td className="num shrink">{date(item.earliest_expiry)}</td>
                      <td className="num">
                        {item.expired_pieces > 0 ? (
                          <span className="badge critical">
                            {num(item.expired_pieces)} expired
                          </span>
                        ) : item.near_expiry_value > 0 ? (
                          <span className="badge serious">
                            {moneyShort(item.near_expiry_value)}
                          </span>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td>
                        <button
                          className="ghost"
                          onClick={() =>
                            setOpen(open === item.product_id ? null : item.product_id)
                          }
                        >
                          {open === item.product_id ? "hide" : `${item.batches.length} batches`}
                        </button>
                      </td>
                    </tr>
                    {open === item.product_id ? (
                      <tr key={`${item.product_id}-batches`}>
                        <td colSpan={8} style={{ background: "var(--surface-2)" }}>
                          <table>
                            <thead>
                              <tr>
                                <th>Batch</th>
                                <th className="num">Manufactured</th>
                                <th className="num">Expires</th>
                                <th className="num">Days left</th>
                                <th className="num">Cases</th>
                                <th className="num">Pieces</th>
                              </tr>
                            </thead>
                            <tbody>
                              {item.batches.map((batch) => (
                                <tr key={batch.batch_id}>
                                  <td className="mono">{batch.batch_no}</td>
                                  <td className="num">{date(batch.mfg_date)}</td>
                                  <td className="num">{date(batch.expiry_date)}</td>
                                  <td className="num">
                                    <span
                                      style={{
                                        color:
                                          batch.days_left < 0
                                            ? "var(--critical)"
                                            : batch.days_left <= 90
                                              ? "var(--serious)"
                                              : "inherit",
                                      }}
                                    >
                                      {batch.days_left < 0
                                        ? `${Math.abs(batch.days_left)}d ago`
                                        : `${batch.days_left}d`}
                                    </span>
                                  </td>
                                  <td className="num">{batch.cases}</td>
                                  <td className="num">{num(batch.pieces)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    ) : null}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
