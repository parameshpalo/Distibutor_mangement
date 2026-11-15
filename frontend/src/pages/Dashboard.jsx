import { Link } from "react-router-dom";
import { date, money, moneyShort, num, useApi } from "../api";
import { TrendBars } from "../components/Charts";

/** What needs doing today, and whether the month is going anywhere.
 *
 *  This page used to be a management dashboard: targets, pace against plan,
 *  a per-salesman table, call statistics. All of that is gone. It answers
 *  two questions now and nothing else -- what needs my attention, and am I
 *  selling more or less than before -- and every figure carries a line
 *  saying what it means.
 */
export default function Dashboard() {
  const { data, error, loading } = useApi("/dashboard");

  if (loading) return <div className="loading">Loading…</div>;
  if (error) return <div className="notice error">{error.message}</div>;

  const { today, month, quarter, receivables, stock, orders, vans, retailers } =
    data;
  const attention = [
    ...vans.empty_open.map((run) => ({
      key: `empty-${run.id}`,
      tone: "warning",
      text: `${run.label} is set up but has no bills on it`,
      note: `${run.delivery_no}, ${date(run.delivery_date)} — add the bills it is carrying, or leave it`,
      to: "/deliveries",
    })),
    vans.out_count > 0 && {
      key: "out",
      tone: "warning",
      text: `${vans.out_count} ${
        vans.out_count === 1 ? "van is" : "vans are"
      } out with ${moneyShort(vans.to_deliver)} of goods`,
      note: `${vans.shops_to_reach} shop${
        vans.shops_to_reach === 1 ? "" : "s"
      } to reach — mark each van back when it returns`,
      to: "/deliveries",
    },
    stock.near_expiry_count > 0 && {
      key: "expiry",
      tone: "serious",
      text: `${stock.near_expiry_count} ${
        stock.near_expiry_count === 1 ? "SKU" : "SKUs"
      } expiring within 30 days`,
      amount: stock.near_expiry_value,
      to: "/stock",
    },
    stock.expired_pieces > 0 && {
      key: "expired",
      tone: "critical",
      text: `${num(stock.expired_pieces)} pieces already past expiry`,
      note: "Write these off so stock value is honest",
      to: "/stock",
    },
    stock.out_of_stock_count > 0 && {
      key: "oos",
      tone: "warning",
      text: `${stock.out_of_stock_count} ${
        stock.out_of_stock_count === 1 ? "SKU" : "SKUs"
      } out of stock`,
      note: stock.out_of_stock.map((s) => s.name).slice(0, 3).join(" · "),
      to: "/stock",
    },
    stock.low_cover.length > 0 && {
      key: "cover",
      tone: "warning",
      text: `${stock.low_cover.length} ${
        stock.low_cover.length === 1 ? "SKU" : "SKUs"
      } with under 10 days of cover`,
      note: "At the last 30 days' rate of sale",
      to: "/stock",
    },
    receivables.overdue > 0 && {
      key: "overdue",
      tone: "serious",
      text: `${receivables.overdue_count} bills past their credit days`,
      amount: receivables.overdue,
      to: "/money",
    },
  ].filter(Boolean);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Today</h1>
          <div className="page-sub">
            {date(data.as_of)} · {num(retailers.active)} active customers
          </div>
        </div>
        <Link to="/billing">
          <button className="primary">New bill</button>
        </Link>
      </div>

      {/* The four figures worth knowing before anything else. */}
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="stat-label">Billed today</div>
          <div className="stat-value">{moneyShort(today.value)}</div>
          <div className="stat-foot">
            {today.invoices} bill{today.invoices === 1 ? "" : "s"} to{" "}
            {today.retailers_billed} shop{today.retailers_billed === 1 ? "" : "s"}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">
            {vans.out_count ? "Out for delivery" : "Vans"}
          </div>
          <div className="stat-value">
            {vans.out_count ? moneyShort(vans.to_deliver) : vans.open_count}
          </div>
          <div className="stat-foot">
            {vans.out_count ? (
              <>
                {vans.runs
                  .filter((v) => v.status === "out")
                  .map((v) => v.label)
                  .join(" · ")}{" "}
                · {vans.shops_to_reach} shop
                {vans.shops_to_reach === 1 ? "" : "s"} to reach
              </>
            ) : vans.open_count ? (
              "being loaded — nothing on the road yet"
            ) : (
              "no van out today"
            )}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">To collect</div>
          <div className="stat-value">{moneyShort(receivables.total)}</div>
          <div className="stat-foot">
            {receivables.overdue > 0 ? (
              <span style={{ color: "var(--serious)" }}>
                {moneyShort(receivables.overdue)} of it overdue
              </span>
            ) : (
              "Nothing overdue"
            )}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Stock at cost</div>
          <div className="stat-value">{moneyShort(stock.value)}</div>
          <div className="stat-foot">
            {stock.skus_in_stock} SKUs in the godown
          </div>
        </div>
      </div>

      {/* Sales: the only two periods he asked for, plus where they came from. */}
      <div className="grid g3" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="stat-label">This month — {month.label}</div>
          <div className="stat-value">{moneyShort(month.value)}</div>
          <div className="stat-foot">
            {num(month.cases)} cases · before GST
          </div>
        </div>
        <div className="card">
          <div className="stat-label">This quarter — {quarter.label}</div>
          <div className="stat-value">{moneyShort(quarter.value)}</div>
          <div className="stat-foot">
            {num(quarter.cases)} cases · before GST
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Collected today</div>
          <div className="stat-value">{moneyShort(today.collected)}</div>
          <div className="stat-foot">Receipts entered today</div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="card-title">Billed value by month</div>
        <TrendBars data={data.trend} />
        <div className="card-note">
          Taxable value of issued bills, so it is comparable month to month
          whatever the GST rate did. The current month is still running.
        </div>
      </div>

      {/* Needs attention */}
      {attention.length > 0 ? (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-title">Needs attention</div>
          <div className="attention-list">
            {attention.map((item) => (
              <Link to={item.to} key={item.key} className="attention-row">
                <span className={`dot ${item.tone}`} aria-hidden="true" />
                <span className="attention-text">
                  {item.text}
                  {item.note ? <span className="sub">{item.note}</span> : null}
                </span>
                {item.amount != null ? (
                  <span className="attention-amount">{money(item.amount)}</span>
                ) : null}
              </Link>
            ))}
          </div>
          <div className="card-note">
            Each line opens the screen where it can be dealt with.
          </div>
        </div>
      ) : (
        <div className="notice ok" style={{ marginBottom: 14 }}>
          Nothing needs attention: no near-expiry stock, nothing out of stock,
          nothing overdue.
        </div>
      )}

      {/* Moving and not moving */}
      <div className="grid g2">
        <div className="card">
          <div className="card-title">Moving this month</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="num">Cases</th>
                  <th className="num">Value</th>
                </tr>
              </thead>
              <tbody>
                {data.top_movers.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="empty">
                      Nothing billed yet this month.
                    </td>
                  </tr>
                ) : (
                  data.top_movers.map((row) => (
                    <tr key={row.product_id}>
                      <td>{row.name}</td>
                      <td className="num">{num(row.cases)}</td>
                      <td className="num">{moneyShort(row.value)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <div className="card-note">
            Most cases sold this month, highest first.
          </div>
        </div>

        <div className="card">
          <div className="card-title">Not moving</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="num">On hand</th>
                  <th className="num">Sold</th>
                  <th className="num">Value</th>
                </tr>
              </thead>
              <tbody>
                {data.slow_movers.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="empty">
                      Everything in stock is selling.
                    </td>
                  </tr>
                ) : (
                  data.slow_movers.map((row) => (
                    <tr key={row.product_id}>
                      <td>{row.name}</td>
                      <td className="num">{num(row.cases_on_hand)}</td>
                      <td className="num">{num(row.cases_sold)}</td>
                      <td className="num">{moneyShort(row.value)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <div className="card-note">
            In stock but under {data.slow_mover_cases} cases sold this month —
            cash sitting on a shelf, biggest first. Quantities are cases;
            value is at cost.
          </div>
        </div>
      </div>
    </>
  );
}
