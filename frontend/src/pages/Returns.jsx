import { useState } from "react";
import { Link } from "react-router-dom";
import { api, date, money, money2, moneyShort, num, todayIso, useApi } from "../api";

const REASON_TONE = {
  return_saleable: "good",
  near_expiry_return: "warning",
  return_damaged: "critical",
  shortage: "serious",
  rate_difference: "",
};

export default function Returns() {
  const [tab, setTab] = useState("notes");
  const [version, setVersion] = useState(0);

  const { data: notes, reload } = useApi("/credit-notes?limit=60", [version]);
  const { data: damage } = useApi("/damage-register", [version]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Returns &amp; credit notes</h1>
          <div className="page-sub">
            Tax is reversed at the rate the original invoice used. Saleable
            stock goes back to its own batch; damaged stock never does.
          </div>
        </div>
      </div>

      <div className="grid g4" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="stat-label">Credit notes</div>
          <div className="stat-value">{notes?.length || 0}</div>
          <div className="stat-foot">Most recent first</div>
        </div>
        <div className="card">
          <div className="stat-label">Credited</div>
          <div className="stat-value">
            {moneyShort((notes || []).reduce((s, n) => s + n.grand_total, 0))}
          </div>
          <div className="stat-foot">Off the receivable</div>
        </div>
        <div className="card">
          <div className="stat-label">Damaged stock</div>
          <div className="stat-value" style={{ color: "var(--critical)" }}>
            {moneyShort(damage?.total_value || 0)}
          </div>
          <div className="stat-foot">
            {num(damage?.total_pieces || 0)} pieces at cost
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Back in stock</div>
          <div className="stat-value" style={{ color: "var(--good)" }}>
            {(notes || []).filter((n) => n.restocked).length}
          </div>
          <div className="stat-foot">Notes that restocked</div>
        </div>
      </div>

      <div className="toolbar">
        <button
          className={tab === "notes" ? "primary" : ""}
          onClick={() => setTab("notes")}
        >
          Credit notes
        </button>
        <button
          className={tab === "new" ? "primary" : ""}
          onClick={() => setTab("new")}
        >
          Raise a credit note
        </button>
        <button
          className={tab === "damage" ? "primary" : ""}
          onClick={() => setTab("damage")}
        >
          Damage register
        </button>
      </div>

      {tab === "notes" ? <NoteList notes={notes} /> : null}
      {tab === "new" ? (
        <RaiseNote
          onDone={() => {
            setVersion((v) => v + 1);
            reload();
            setTab("notes");
          }}
        />
      ) : null}
      {tab === "damage" ? <DamageRegister damage={damage} /> : null}
    </>
  );
}

function NoteList({ notes }) {
  const [openId, setOpenId] = useState(null);
  if (!notes) return <div className="loading">Loading…</div>;
  if (!notes.length)
    return (
      <div className="card">
        <div className="empty">No credit notes yet.</div>
      </div>
    );

  return (
    <div className="card">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Note</th>
              <th>Date</th>
              <th>Shop</th>
              <th>Against</th>
              <th>Reason</th>
              <th className="num">Taxable</th>
              <th className="num">Credited</th>
              <th style={{ width: 60 }} />
            </tr>
          </thead>
          <tbody>
            {notes.map((note) => (
              <tr key={note.id}>
                <td className="mono">{note.note_no}</td>
                <td className="shrink">{date(note.note_date)}</td>
                <td>{note.retailer_name}</td>
                <td className="mono sub">
                  <Link to={`/invoices/${note.invoice_id}`}>
                    {note.invoice_no}
                  </Link>
                </td>
                <td>
                  <span className={`badge ${REASON_TONE[note.reason] || ""}`}>
                    {note.reason.replace(/_/g, " ")}
                  </span>
                </td>
                <td className="num muted">{money(note.taxable_total)}</td>
                <td className="num">{money(note.grand_total)}</td>
                <td>
                  <button
                    className="ghost"
                    onClick={() => setOpenId(openId === note.id ? null : note.id)}
                  >
                    {openId === note.id ? "hide" : "view"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {openId ? <NoteDetail note={notes.find((n) => n.id === openId)} /> : null}
    </div>
  );
}

function NoteDetail({ note }) {
  if (!note) return null;
  return (
    <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
      <div className="card-title">
        {note.note_no} · {note.restocked ? "returned to stock" : "not restocked"}
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Product</th>
              <th>HSN</th>
              <th className="num">Qty</th>
              <th className="num">Rate</th>
              <th className="num">Taxable</th>
              <th className="num">GST</th>
              <th className="num">Credited</th>
            </tr>
          </thead>
          <tbody>
            {note.lines.map((line) => (
              <tr key={line.id}>
                <td>{line.product_name}</td>
                <td className="mono">{line.hsn}</td>
                <td className="num">
                  {line.cases ? `${line.cases} cs` : ""}
                  {line.loose_pieces ? ` ${line.loose_pieces} pc` : ""}
                </td>
                <td className="num">{line.rate_per_piece.toFixed(4)}</td>
                <td className="num">{money2(line.taxable)}</td>
                <td className="num">
                  {line.gst_rate}%
                  <div className="sub">
                    {note.is_interstate
                      ? money2(line.igst)
                      : `${money2(line.cgst)} + ${money2(line.sgst)}`}
                  </div>
                </td>
                <td className="num">{money2(line.line_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="totals">
        <div className="line">
          <span className="muted">Taxable</span>
          <span>{money2(note.taxable_total)}</span>
        </div>
        {note.is_interstate ? (
          <div className="line">
            <span className="muted">IGST</span>
            <span>{money2(note.igst_total)}</span>
          </div>
        ) : (
          <>
            <div className="line">
              <span className="muted">CGST</span>
              <span>{money2(note.cgst_total)}</span>
            </div>
            <div className="line">
              <span className="muted">SGST</span>
              <span>{money2(note.sgst_total)}</span>
            </div>
          </>
        )}
        {note.round_off !== 0 ? (
          <div className="line">
            <span className="muted">Round off</span>
            <span>{money2(note.round_off)}</span>
          </div>
        ) : null}
        <div className="line grand">
          <span>Total credited</span>
          <span>{money(note.grand_total)}</span>
        </div>
      </div>
      <div className="sub" style={{ marginTop: 8 }}>
        {note.amount_in_words}
        {note.note ? ` · ${note.note}` : ""}
      </div>
    </div>
  );
}

function RaiseNote({ onDone }) {
  const [invoiceNo, setInvoiceNo] = useState("");
  const [invoiceId, setInvoiceId] = useState(null);
  const [reason, setReason] = useState("return_saleable");
  const [noteDate, setNoteDate] = useState(todayIso());
  const [qty, setQty] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const { data: reasons } = useApi("/credit-notes/reasons");
  const { data: recent } = useApi("/invoices?limit=60");
  const { data: returnable } = useApi(
    invoiceId ? `/invoices/${invoiceId}/returnable` : null,
    [invoiceId],
  );

  const lines = Object.entries(qty)
    .filter(([, value]) => Number(value) > 0)
    .map(([lineId, cases]) => ({
      invoice_line_id: Number(lineId),
      cases: Number(cases),
      loose_pieces: 0,
    }));

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/credit-notes", {
        invoice_id: invoiceId,
        reason,
        note_date: noteDate,
        lines,
      });
      setQty({});
      setInvoiceId(null);
      setInvoiceNo("");
      onDone();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const selectedReason = (reasons || []).find((r) => r.value === reason);

  return (
    <div className="card">
      <div className="card-title">Raise a credit note</div>
      <div className="row">
        <label className="field grow">
          <span>Against invoice</span>
          <select
            value={invoiceNo}
            onChange={(event) => {
              setInvoiceNo(event.target.value);
              const match = (recent || []).find(
                (i) => i.invoice_no === event.target.value,
              );
              setInvoiceId(match ? match.id : null);
              setQty({});
            }}
          >
            <option value="">Select a recent invoice…</option>
            {(recent || []).map((invoice) => (
              <option key={invoice.id} value={invoice.invoice_no}>
                {invoice.invoice_no} — {invoice.retailer_name} —{" "}
                {money(invoice.grand_total)}
              </option>
            ))}
          </select>
        </label>
        <label className="field" style={{ width: 200 }}>
          <span>Reason</span>
          <select value={reason} onChange={(e) => setReason(e.target.value)}>
            {(reasons || []).map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field" style={{ width: 150 }}>
          <span>Note date</span>
          <input
            type="date"
            value={noteDate}
            onChange={(e) => setNoteDate(e.target.value)}
          />
        </label>
      </div>

      {selectedReason ? (
        <div className="sub" style={{ marginTop: 8 }}>
          {selectedReason.restocks
            ? "Goods go back into saleable stock, on the batch they left on."
            : "No stock returns to saleable stock; a damaged return is written off to the damage register."}
        </div>
      ) : null}

      {returnable ? (
        <>
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="num">Sold</th>
                  <th className="num">Already credited</th>
                  <th className="num">Still open</th>
                  <th className="num" style={{ width: 110 }}>Return (cases)</th>
                </tr>
              </thead>
              <tbody>
                {returnable.lines.map((line) => {
                  const openCases = Math.floor(
                    line.returnable_pieces / line.pieces_per_case,
                  );
                  return (
                    <tr key={line.invoice_line_id}>
                      <td>
                        {line.product_name}
                        {line.is_free ? (
                          <span className="badge" style={{ marginLeft: 6 }}>
                            free
                          </span>
                        ) : null}
                      </td>
                      <td className="num muted">{num(line.sold_pieces)}</td>
                      <td className="num muted">{num(line.returned_pieces)}</td>
                      <td className="num">
                        {num(line.returnable_pieces)}
                        <span className="sub"> ({openCases} cs)</span>
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          max={openCases}
                          disabled={openCases < 1}
                          value={qty[line.invoice_line_id] || ""}
                          onChange={(e) =>
                            setQty({
                              ...qty,
                              [line.invoice_line_id]: e.target.value,
                            })
                          }
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="row" style={{ marginTop: 12 }}>
            <button
              className="primary"
              disabled={busy || !lines.length}
              onClick={submit}
            >
              {busy ? "Saving…" : `Raise credit note (${lines.length} lines)`}
            </button>
          </div>
        </>
      ) : invoiceId ? (
        <div className="loading">Loading invoice…</div>
      ) : null}

      {error ? (
        <div className="notice error" style={{ marginTop: 10 }}>
          {error.message}
        </div>
      ) : null}
    </div>
  );
}

function DamageRegister({ damage }) {
  if (!damage) return <div className="loading">Loading…</div>;
  return (
    <div className="card">
      <div className="card-title">
        Damage register · {damage.count} entries ·{" "}
        {money(damage.total_value)} at cost
      </div>
      {damage.entries.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Product</th>
                <th>Batch</th>
                <th className="num">Expiry</th>
                <th className="num">Cases</th>
                <th className="num">Pieces</th>
                <th className="num">At cost</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {damage.entries.map((entry) => (
                <tr key={entry.id}>
                  <td className="shrink">{date(entry.occurred_on)}</td>
                  <td>{entry.product_name}</td>
                  <td className="mono sub">{entry.batch_no}</td>
                  <td className="num sub">{date(entry.expiry_date)}</td>
                  <td className="num">{entry.cases}</td>
                  <td className="num muted">{num(entry.pieces)}</td>
                  <td className="num">{money(entry.value_at_cost)}</td>
                  <td className="sub">{entry.note || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty">Nothing written off as damaged.</div>
      )}
      <div className="card-note">
        Everything here left saleable stock. Claim it against the company with
        the batch numbers above.
      </div>
    </div>
  );
}
