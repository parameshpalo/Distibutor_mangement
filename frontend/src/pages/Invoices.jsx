import { useState } from "react";
import { Link } from "react-router-dom";
import { date, money, useApi } from "../api";

export default function Invoices() {
  const [search, setSearch] = useState("");
  const [routeId, setRouteId] = useState("");
  const [unpaidOnly, setUnpaidOnly] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const { data: routes } = useApi("/routes");

  const query = new URLSearchParams({ limit: "200" });
  if (search.trim()) query.set("search", search.trim());
  if (routeId) query.set("route_id", routeId);
  if (unpaidOnly) query.set("unpaid_only", "true");
  if (from) query.set("date_from", from);
  if (to) query.set("date_to", to);

  const { data, error, loading } = useApi(`/invoices?${query}`);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Invoices</h1>
          <div className="page-sub">
            {data ? `${data.length} shown` : "Loading…"}
          </div>
        </div>
        <Link to="/billing">
          <button className="primary">New bill</button>
        </Link>
      </div>

      <div className="toolbar">
        <input
          className="grow"
          placeholder="Invoice number or shop name"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          style={{ maxWidth: 280 }}
        />
        <select
          value={routeId}
          onChange={(event) => setRouteId(event.target.value)}
          style={{ width: 170 }}
        >
          <option value="">All routes</option>
          {(routes || []).map((route) => (
            <option key={route.id} value={route.id}>
              {route.name}
            </option>
          ))}
        </select>
        <input
          type="date"
          value={from}
          onChange={(event) => setFrom(event.target.value)}
          style={{ width: 150 }}
        />
        <input
          type="date"
          value={to}
          onChange={(event) => setTo(event.target.value)}
          style={{ width: 150 }}
        />
        <label
          style={{ display: "inline-flex", gap: 6, alignItems: "center", fontSize: 13 }}
        >
          <input
            type="checkbox"
            style={{ width: 16 }}
            checked={unpaidOnly}
            onChange={(event) => setUnpaidOnly(event.target.checked)}
          />
          Unpaid only
        </label>
      </div>

      {error ? <div className="notice error">{error.message}</div> : null}

      <div className="card">
        {loading ? (
          <div className="loading">Loading…</div>
        ) : !data?.length ? (
          <div className="empty">No invoices match those filters.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Date</th>
                  <th>Shop</th>
                  <th>Route</th>
                  <th className="num">Total</th>
                  <th className="num">Paid</th>
                  <th className="num">Balance</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.map((invoice) => {
                  const overdue =
                    invoice.balance > 0 &&
                    new Date(`${invoice.due_date}T23:59:59`) < new Date();
                  return (
                    <tr key={invoice.id}>
                      <td className="mono">
                        <Link to={`/invoices/${invoice.id}`}>{invoice.invoice_no}</Link>
                      </td>
                      <td className="shrink">{date(invoice.invoice_date)}</td>
                      <td>
                        {invoice.retailer_name}
                        {invoice.is_interstate ? (
                          <span className="badge" style={{ marginLeft: 6 }}>
                            IGST
                          </span>
                        ) : null}
                      </td>
                      <td className="sub">{invoice.route_name || "—"}</td>
                      <td className="num">{money(invoice.grand_total)}</td>
                      <td className="num muted">{money(invoice.amount_paid)}</td>
                      <td className="num">
                        {invoice.balance > 0 ? money(invoice.balance) : "—"}
                      </td>
                      <td>
                        {invoice.balance <= 0 ? (
                          <span className="badge good">Paid</span>
                        ) : overdue ? (
                          <span className="badge critical">Overdue</span>
                        ) : (
                          <span className="badge">Due {date(invoice.due_date)}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
