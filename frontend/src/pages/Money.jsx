import { useState } from "react";
import { Link } from "react-router-dom";
import { api, date, money, moneyShort, num, todayIso, useApi } from "../api";
import { AgeingBars } from "../components/Charts";

/**
 * Money: who owes, and taking it in.
 *
 * This replaces a five-card ageing screen. The complaint about it was never
 * that knowing who owes money is unimportant — it was that the page opened on
 * an accountant's matrix. So it opens on two numbers and a list of shops in
 * the order you would chase them, oldest debt first. The ageing breakdown and
 * the receipt history are still here, one click behind.
 *
 * "Receive" takes an amount and spreads it over the oldest bills first, which
 * is what everyone does by hand anyway.
 */

const MODES = [
  ["cash", "Cash"],
  ["upi", "UPI"],
  ["cheque", "Cheque"],
  ["bank_transfer", "Bank transfer"],
];

const BUCKET_WORDS = {
  current: "not due yet",
  "1-7": "a week over",
  "8-15": "two weeks over",
  "16-30": "a month over",
  "30+": "over a month",
};

/** How worried to look about a debt this old. */
function ageTone(days) {
  if (days <= 0) return "";
  if (days <= 7) return "warning";
  if (days <= 30) return "serious";
  return "critical";
}

function ageWords(days) {
  if (days <= 0) return "not due yet";
  if (days === 1) return "1 day over";
  return `${days} days over`;
}

function ReceiveDialog({ shop, onClose, onDone }) {
  const { data: bills } = useApi(
    `/retailers/${shop.retailer_id}/open-invoices`,
  );
  const [amount, setAmount] = useState(String(Math.round(shop.balance)));
  const [mode, setMode] = useState("cash");
  const [reference, setReference] = useState("");
  const [payDate, setPayDate] = useState(todayIso());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const entered = Number(amount) || 0;
  // Show which bills this amount will clear, before it is recorded, because
  // "₹12,000 against the three oldest" is the sentence the shopkeeper and the
  // owner both have in their heads.
  let left = entered;
  const willClear = (bills || []).map((bill) => {
    const applied = Math.min(left, bill.balance);
    left -= applied;
    return { ...bill, applied };
  });
  const touched = willClear.filter((b) => b.applied > 0);
  const surplus = Math.max(left, 0);

  async function record() {
    setSaving(true);
    setError(null);
    try {
      const payment = await api.post("/payments", {
        retailer_id: shop.retailer_id,
        payment_date: payDate,
        mode,
        amount: entered,
        reference: reference || null,
      });
      onDone(payment);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        style={{ maxWidth: 640 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <div className="modal-title">Receive from {shop.shop_name}</div>
          <button className="ghost" onClick={onClose}>
            close
          </button>
        </div>
        <div className="modal-body">
          <div className="sub" style={{ marginBottom: 12 }}>
            Owes {money(shop.balance)} across {shop.invoices}{" "}
            {shop.invoices === 1 ? "bill" : "bills"} · oldest{" "}
            {ageWords(shop.worst_overdue)}
          </div>

          <div className="row">
            <label className="field" style={{ width: 150 }}>
              <span>Amount</span>
              <input
                type="number"
                min="0"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            </label>
            <label className="field" style={{ width: 150 }}>
              <span>Date</span>
              <input
                type="date"
                value={payDate}
                onChange={(e) => setPayDate(e.target.value)}
              />
            </label>
            <label className="field" style={{ width: 150 }}>
              <span>How</span>
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                {MODES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field grow">
              <span>Reference</span>
              <input
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder={mode === "cheque" ? "cheque no." : "UPI ref, optional"}
              />
            </label>
          </div>

          <div className="row" style={{ marginTop: 10, gap: 6 }}>
            {[0.25, 0.5, 1].map((part) => (
              <button
                key={part}
                className="ghost"
                onClick={() =>
                  setAmount(String(Math.round(shop.balance * part)))
                }
              >
                {part === 1 ? "all of it" : `${part * 100}%`}
              </button>
            ))}
          </div>

          {touched.length ? (
            <>
              <div className="card-title" style={{ marginTop: 16 }}>
                This clears, oldest first
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Bill</th>
                      <th>Raised</th>
                      <th className="num">Owed</th>
                      <th className="num">Applied</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {touched.map((bill) => (
                      <tr key={bill.id}>
                        <td className="mono">{bill.invoice_no}</td>
                        <td className="shrink sub">{date(bill.invoice_date)}</td>
                        <td className="num muted">{money(bill.balance)}</td>
                        <td className="num" style={{ fontWeight: 600 }}>
                          {money(bill.applied)}
                        </td>
                        <td>
                          {bill.applied >= bill.balance - 0.01 ? (
                            <span className="badge good">settled</span>
                          ) : (
                            <span className="badge warning">part paid</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}

          {surplus > 0 ? (
            <div className="notice warn" style={{ marginTop: 10 }}>
              {money(surplus)} more than this shop owes. It will be recorded
              and left unallocated — it sits against the shop until the next
              bill.
            </div>
          ) : null}
          {error ? (
            <div className="notice error" style={{ marginTop: 10 }}>
              {error.message}
            </div>
          ) : null}
        </div>
        <div className="modal-foot">
          <span className="spacer" />
          <button className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="primary"
            disabled={saving || entered <= 0}
            onClick={record}
          >
            {saving ? "Recording…" : `Receive ${money(entered)}`}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Money() {
  const [version, setVersion] = useState(0);
  const [receiving, setReceiving] = useState(null);
  const [view, setView] = useState("shops");
  const [done, setDone] = useState(null);
  const [search, setSearch] = useState("");

  const { data: ageing, reload: reloadAgeing } = useApi("/outstanding", [
    version,
  ]);
  const { data: payments, reload: reloadPayments } = useApi(
    "/payments?limit=60",
    [version],
  );

  const refresh = () => {
    setVersion((v) => v + 1);
    reloadAgeing();
    reloadPayments();
  };

  const debtors = (ageing?.debtors || []).filter((d) =>
    search
      ? `${d.shop_name} ${d.route || ""}`
          .toLowerCase()
          .includes(search.toLowerCase())
      : true,
  );

  const todaysReceipts = (payments || []).filter(
    (p) => p.payment_date === todayIso(),
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Money</h1>
          <div className="page-sub">
            What the shops owe, oldest first, and recording what comes in.
          </div>
        </div>
      </div>

      <div className="grid g3" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="stat-label">To collect</div>
          <div className="stat-value">{moneyShort(ageing?.total || 0)}</div>
          <div className="stat-foot">
            across {ageing?.invoice_count || 0} unpaid bills
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Of that, overdue</div>
          <div className="stat-value">{moneyShort(ageing?.overdue || 0)}</div>
          <div className="stat-foot">
            {ageing?.overdue_count || 0} bills past their due date
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Received today</div>
          <div className="stat-value">
            {moneyShort(todaysReceipts.reduce((s, p) => s + p.amount, 0))}
          </div>
          <div className="stat-foot">
            {todaysReceipts.length}{" "}
            {todaysReceipts.length === 1 ? "receipt" : "receipts"} entered
          </div>
        </div>
      </div>

      {done ? (
        <div className="notice ok" style={{ marginBottom: 14 }}>
          Recorded {money(done.amount)} from {done.shop_name} —{" "}
          {done.note || "allocated to the oldest bills"}
        </div>
      ) : null}

      <div className="card">
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 10,
            marginBottom: 10,
          }}
        >
          <div className="segmented">
            <button
              className={view === "shops" ? "primary" : ""}
              onClick={() => setView("shops")}
            >
              Shops ({ageing?.debtors?.length || 0})
            </button>
            <button
              className={view === "ageing" ? "primary" : ""}
              onClick={() => setView("ageing")}
            >
              Ageing detail
            </button>
            <button
              className={view === "receipts" ? "primary" : ""}
              onClick={() => setView("receipts")}
            >
              Receipts
            </button>
          </div>
          {view === "shops" ? (
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="find a shop"
              style={{ width: 200 }}
            />
          ) : null}
        </div>

        {view === "shops" ? (
          debtors.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Shop</th>
                    <th>Oldest bill</th>
                    <th className="num">Bills</th>
                    <th className="num">Owes</th>
                    <th style={{ width: 110 }} />
                  </tr>
                </thead>
                <tbody>
                  {debtors.map((shop) => (
                    <tr key={shop.retailer_id}>
                      <td>
                        {shop.shop_name}
                        <div className="sub">{shop.route || "no route"}</div>
                      </td>
                      <td className="shrink">
                        <span
                          className={`dot ${ageTone(shop.worst_overdue)}`}
                          aria-hidden="true"
                        />
                        {ageWords(shop.worst_overdue)}
                      </td>
                      <td className="num muted">{shop.invoices}</td>
                      <td className="num" style={{ fontWeight: 600 }}>
                        {money(shop.balance)}
                      </td>
                      <td>
                        <div className="row-actions">
                          <button
                            className="primary"
                            onClick={() => {
                              setDone(null);
                              setReceiving(shop);
                            }}
                          >
                            Receive
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty">
              {search
                ? "No shop by that name owes anything."
                : "Nothing outstanding. Every bill is settled."}
            </div>
          )
        ) : null}

        {view === "ageing" && ageing ? (
          <>
            <AgeingBars buckets={ageing.buckets} total={ageing.total} />
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table>
                <thead>
                  <tr>
                    <th>How late</th>
                    <th className="num">Bills</th>
                    <th className="num">Amount</th>
                    <th className="num">Share</th>
                  </tr>
                </thead>
                <tbody>
                  {ageing.buckets.map((bucket) => (
                    <tr key={bucket.label}>
                      <td>
                        {BUCKET_WORDS[bucket.label] || bucket.label}
                        <div className="sub mono">{bucket.label} days</div>
                      </td>
                      <td className="num muted">{bucket.count}</td>
                      <td className="num">{money(bucket.amount)}</td>
                      <td className="num muted">
                        {ageing.total
                          ? `${Math.round((bucket.amount / ageing.total) * 100)}%`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {ageing.over_limit.length ? (
              <>
                <div className="card-title" style={{ marginTop: 18 }}>
                  Past their credit limit
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Shop</th>
                        <th className="num">Owes</th>
                        <th className="num">Limit</th>
                        <th className="num">Over by</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ageing.over_limit.map((shop) => (
                        <tr key={shop.retailer_id}>
                          <td>{shop.shop_name}</td>
                          <td className="num">{money(shop.balance)}</td>
                          <td className="num muted">
                            {money(shop.credit_limit)}
                          </td>
                          <td className="num">
                            {money(shop.balance - shop.credit_limit)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="card-note">
                  A limit does not stop a bill — it is here so you know before
                  you load the van, not after the goods are on the counter.
                </div>
              </>
            ) : null}
          </>
        ) : null}

        {view === "receipts" ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Receipt</th>
                  <th>Date</th>
                  <th>Shop</th>
                  <th>How</th>
                  <th>Reference</th>
                  <th className="num">Amount</th>
                </tr>
              </thead>
              <tbody>
                {(payments || []).map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.receipt_no}</td>
                    <td className="shrink">{date(row.payment_date)}</td>
                    <td>
                      {row.retailer_name}
                    </td>
                    <td className="sub">
                      {MODES.find(([m]) => m === row.mode)?.[1] || row.mode}
                    </td>
                    <td className="sub mono">{row.reference || "—"}</td>
                    <td className="num">{money(row.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        <div className="card-note">
          A bill raised is money earned; a receipt is money arrived. These are
          the bills where the two have not met yet.
        </div>
      </div>

      {receiving ? (
        <ReceiveDialog
          shop={receiving}
          onClose={() => setReceiving(null)}
          onDone={(payment) => {
            setDone({ ...payment, shop_name: receiving.shop_name });
            setReceiving(null);
            refresh();
          }}
        />
      ) : null}
    </>
  );
}
