import { Link, useParams } from "react-router-dom";
import { date, money, money2, num, qtyLabel, useApi } from "../api";

export default function InvoiceDetail() {
  const { id } = useParams();
  const { data: invoice, error, loading } = useApi(`/invoices/${id}`);

  if (loading) return <div className="loading">Loading invoice…</div>;
  if (error) return <div className="notice error">{error.message}</div>;

  const pdfUrl = `/api/invoices/${invoice.id}/pdf`;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{invoice.invoice_no}</h1>
          <div className="page-sub">
            {invoice.retailer_name} · {date(invoice.invoice_date)}
            {invoice.is_interstate ? " · interstate (IGST)" : " · intrastate"}
          </div>
        </div>
        <div className="row">
          <Link to="/records">
            <button>Back</button>
          </Link>
          <a href={`${pdfUrl}?format=memo`} target="_blank" rel="noreferrer">
            <button>Shop's memo</button>
          </a>
          <a href={pdfUrl} target="_blank" rel="noreferrer">
            <button>Tax invoice</button>
          </a>
          <a href={`${pdfUrl}?download=true`}>
            <button className="primary">Download</button>
          </a>
        </div>
      </div>

      <div className="notice" style={{ marginBottom: 14 }}>
        Two prints, one sale. <strong>Shop&rsquo;s memo</strong> is the plain
        slip that goes with the goods: the same amounts, no GSTIN and no tax
        breakup. <strong>Tax invoice</strong> is the document the firm keeps
        and files. Printing one or the other changes nothing here &mdash; this
        sale and its GST are already recorded.
      </div>

      <div className="grid g4" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="stat-label">Payable</div>
          <div className="stat-value">{money(invoice.grand_total)}</div>
        </div>
        <div className="card">
          <div className="stat-label">Paid</div>
          <div className="stat-value">{money(invoice.amount_paid)}</div>
        </div>
        <div className="card">
          <div className="stat-label">Balance</div>
          <div
            className="stat-value"
            style={{ color: invoice.balance > 0 ? "var(--critical)" : "var(--good)" }}
          >
            {money(invoice.balance)}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Due</div>
          <div className="stat-value sm" style={{ marginTop: 10 }}>
            {date(invoice.due_date)}
          </div>
          <div className="stat-foot">
            {invoice.balance <= 0 ? "Settled" : "Outstanding"}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="card-title">Billed to</div>
        <dl className="kv" style={{ maxWidth: 520 }}>
          <dt>Shop</dt>
          <dd>{invoice.retailer_name}</dd>
          <dt>GSTIN</dt>
          <dd>{invoice.retailer_gstin || "Unregistered (B2C)"}</dd>
          <dt>Place of supply</dt>
          <dd>{invoice.place_of_supply}</dd>
          <dt>Route</dt>
          <dd>{invoice.route_name || "—"}</dd>
          {invoice.note ? (
            <>
              <dt>Note</dt>
              <dd>{invoice.note}</dd>
            </>
          ) : null}
        </dl>
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="card-title">Items</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th>HSN</th>
                <th className="num">Qty</th>
                <th className="num">Pieces</th>
                <th className="num">Rate</th>
                <th className="num">Disc.</th>
                <th className="num">Taxable</th>
                <th className="num">GST</th>
                <th className="num">Amount</th>
                <th>Batch</th>
              </tr>
            </thead>
            <tbody>
              {invoice.lines.map((line) => (
                <tr key={line.id}>
                  <td>
                    {line.product_name}
                    {line.is_free ? (
                      <span className="badge good" style={{ marginLeft: 6 }}>
                        free
                      </span>
                    ) : null}
                    <div className="sub mono">{line.sku_code}</div>
                  </td>
                  <td className="mono">{line.hsn}</td>
                  <td className="num">{qtyLabel(line.cases, line.loose_pieces)}</td>
                  <td className="num muted">{num(line.qty_pieces)}</td>
                  <td className="num">{line.rate_per_piece.toFixed(4)}</td>
                  <td className="num">
                    {line.discount ? money2(line.discount) : "—"}
                  </td>
                  <td className="num">{money2(line.taxable)}</td>
                  <td className="num">
                    {line.gst_rate}%
                    <div className="sub">
                      {invoice.is_interstate
                        ? money2(line.igst)
                        : `${money2(line.cgst)} + ${money2(line.sgst)}`}
                    </div>
                  </td>
                  <td className="num">{money2(line.line_total)}</td>
                  <td className="sub mono">
                    {line.batches.map((batch) => (
                      <div key={batch.batch_no}>
                        {batch.batch_no} · {num(batch.qty_pieces)}pc
                        <div className="muted">exp {date(batch.expiry_date)}</div>
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="totals">
          <div className="line">
            <span className="muted">Taxable value</span>
            <span>{money2(invoice.taxable_total)}</span>
          </div>
          {invoice.discount_total > 0 ? (
            <div className="line">
              <span className="muted">Scheme discount</span>
              <span>−{money2(invoice.discount_total)}</span>
            </div>
          ) : null}
          {invoice.is_interstate ? (
            <div className="line">
              <span className="muted">IGST</span>
              <span>{money2(invoice.igst_total)}</span>
            </div>
          ) : (
            <>
              <div className="line">
                <span className="muted">CGST</span>
                <span>{money2(invoice.cgst_total)}</span>
              </div>
              <div className="line">
                <span className="muted">SGST</span>
                <span>{money2(invoice.sgst_total)}</span>
              </div>
            </>
          )}
          {invoice.round_off !== 0 ? (
            <div className="line">
              <span className="muted">Round off</span>
              <span>{money2(invoice.round_off)}</span>
            </div>
          ) : null}
          <div className="line grand">
            <span>Total payable</span>
            <span>{money(invoice.grand_total)}</span>
          </div>
        </div>
        <div className="sub" style={{ marginTop: 8 }}>
          {invoice.amount_in_words}
        </div>
      </div>

      <div className="card">
        <div className="card-title">HSN summary</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>HSN</th>
                <th className="num">Rate</th>
                <th className="num">Taxable</th>
                {invoice.is_interstate ? (
                  <th className="num">IGST</th>
                ) : (
                  <>
                    <th className="num">CGST</th>
                    <th className="num">SGST</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {invoice.hsn_summary.map((row) => (
                <tr key={`${row.hsn}-${row.gst_rate}`}>
                  <td className="mono">{row.hsn}</td>
                  <td className="num">{row.gst_rate}%</td>
                  <td className="num">{money2(row.taxable)}</td>
                  {invoice.is_interstate ? (
                    <td className="num">{money2(row.igst)}</td>
                  ) : (
                    <>
                      <td className="num">{money2(row.cgst)}</td>
                      <td className="num">{money2(row.sgst)}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
