import { useState } from "react";
import { api, date, money, num, qtyLabel, todayIso, useApi } from "../api";

const blankLine = () => ({
  key: Math.random().toString(36).slice(2),
  product_id: "",
  batch_no: "",
  mfg_date: "",
  cases: 1,
  loose_pieces: 0,
});

export default function Inward() {
  const { data: products } = useApi("/products");
  const [version, setVersion] = useState(0);
  const { data: purchases } = useApi("/purchases?limit=40", [version]);
  const [openId, setOpenId] = useState(null);
  const { data: detail } = useApi(openId ? `/purchases/${openId}` : null, [openId]);

  const [form, setForm] = useState({
    supplier_name: "",
    company_invoice_no: "",
    company_invoice_date: todayIso(),
    received_on: todayIso(),
    note: "",
  });
  const [lines, setLines] = useState([blankLine()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);

  const set = (patch) => setForm((current) => ({ ...current, ...patch }));
  const update = (key, patch) =>
    setLines((current) =>
      current.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    );

  const ready =
    form.supplier_name &&
    form.company_invoice_no &&
    lines.some((l) => l.product_id && l.batch_no && l.mfg_date);

  async function save() {
    setSaving(true);
    setError(null);
    setDone(null);
    try {
      const grn = await api.post("/purchases", {
        ...form,
        note: form.note || null,
        lines: lines
          .filter((l) => l.product_id && l.batch_no && l.mfg_date)
          .map((l) => ({
            product_id: Number(l.product_id),
            batch_no: l.batch_no,
            mfg_date: l.mfg_date,
            cases: Number(l.cases) || 0,
            loose_pieces: Number(l.loose_pieces) || 0,
          })),
      });
      setDone(grn);
      setLines([blankLine()]);
      setVersion((v) => v + 1);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Goods inward</h1>
          <div className="page-sub">
            Receiving stock creates a batch and posts it to the stock ledger.
            Expiry is derived from the product's shelf life unless given.
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="card-title">New GRN</div>
        <div className="row">
          <label className="field grow">
            <span>Supplier / depot</span>
            <input
              value={form.supplier_name}
              onChange={(event) => set({ supplier_name: event.target.value })}
              placeholder="Bhagwati - cluster depot"
            />
          </label>
          <label className="field" style={{ width: 180 }}>
            <span>Company invoice no.</span>
            <input
              value={form.company_invoice_no}
              onChange={(event) => set({ company_invoice_no: event.target.value })}
            />
          </label>
          <label className="field" style={{ width: 150 }}>
            <span>Invoice date</span>
            <input
              type="date"
              value={form.company_invoice_date}
              onChange={(event) => set({ company_invoice_date: event.target.value })}
            />
          </label>
          <label className="field" style={{ width: 150 }}>
            <span>Received on</span>
            <input
              type="date"
              value={form.received_on}
              onChange={(event) => set({ received_on: event.target.value })}
            />
          </label>
        </div>

        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr>
                <th style={{ minWidth: 220 }}>Product</th>
                <th style={{ width: 120 }}>Batch no.</th>
                <th style={{ width: 150 }}>Manufactured</th>
                <th className="num" style={{ width: 80 }}>Cases</th>
                <th className="num" style={{ width: 80 }}>Loose</th>
                <th style={{ width: 34 }} />
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => (
                <tr key={line.key}>
                  <td>
                    <select
                      value={line.product_id}
                      onChange={(event) =>
                        update(line.key, { product_id: event.target.value })
                      }
                    >
                      <option value="">Select…</option>
                      {(products || []).map((product) => (
                        <option key={product.id} value={product.id}>
                          {product.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      value={line.batch_no}
                      onChange={(event) =>
                        update(line.key, { batch_no: event.target.value })
                      }
                      placeholder="e.g. 260915"
                    />
                  </td>
                  <td>
                    <input
                      type="date"
                      value={line.mfg_date}
                      onChange={(event) =>
                        update(line.key, { mfg_date: event.target.value })
                      }
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      min="0"
                      value={line.cases}
                      onChange={(event) => update(line.key, { cases: event.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      min="0"
                      value={line.loose_pieces}
                      onChange={(event) =>
                        update(line.key, { loose_pieces: event.target.value })
                      }
                    />
                  </td>
                  <td>
                    <button
                      className="ghost danger"
                      onClick={() =>
                        setLines((c) =>
                          c.length > 1 ? c.filter((l) => l.key !== line.key) : [blankLine()],
                        )
                      }
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="row" style={{ marginTop: 12 }}>
          <button onClick={() => setLines((c) => [...c, blankLine()])}>+ Add line</button>
          <button className="primary" disabled={!ready || saving} onClick={save}>
            {saving ? "Saving…" : "Receive stock"}
          </button>
        </div>

        {error ? (
          <div className="notice error" style={{ marginTop: 10 }}>
            {error.message}
          </div>
        ) : null}
        {done ? (
          <div className="notice ok" style={{ marginTop: 10 }}>
            <strong>{done.grn_no}</strong> received — {money(done.grand_total)} across{" "}
            {done.line_count} line{done.line_count === 1 ? "" : "s"}.
          </div>
        ) : null}
      </div>

      <div className="card">
        <div className="card-title">Recent GRNs</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>GRN</th>
                <th>Received</th>
                <th>Supplier</th>
                <th>Their invoice</th>
                <th className="num">Lines</th>
                <th className="num">Value</th>
                <th style={{ width: 60 }} />
              </tr>
            </thead>
            <tbody>
              {(purchases || []).map((purchase) => (
                <tr key={purchase.id}>
                  <td className="mono">{purchase.grn_no}</td>
                  <td className="shrink">{date(purchase.received_on)}</td>
                  <td>{purchase.supplier_name}</td>
                  <td className="sub mono">{purchase.company_invoice_no}</td>
                  <td className="num">{purchase.line_count}</td>
                  <td className="num">{money(purchase.grand_total)}</td>
                  <td>
                    <button
                      className="ghost"
                      onClick={() => setOpenId(openId === purchase.id ? null : purchase.id)}
                    >
                      {openId === purchase.id ? "hide" : "view"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {openId && detail ? (
          <div style={{ marginTop: 14 }}>
            <div className="card-title">{detail.grn_no} lines</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>Batch</th>
                    <th className="num">Expires</th>
                    <th className="num">Qty</th>
                    <th className="num">Pieces</th>
                    <th className="num">Rate</th>
                    <th className="num">Taxable</th>
                    <th className="num">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.lines.map((line, index) => (
                    <tr key={`${line.batch_no}-${index}`}>
                      <td>{line.product_name}</td>
                      <td className="mono">{line.batch_no}</td>
                      <td className="num shrink">{date(line.expiry_date)}</td>
                      <td className="num">{qtyLabel(line.cases, line.loose_pieces)}</td>
                      <td className="num muted">{num(line.qty_pieces)}</td>
                      <td className="num">{line.rate_per_piece.toFixed(4)}</td>
                      <td className="num">{money(line.taxable)}</td>
                      <td className="num">{money(line.line_total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
}
