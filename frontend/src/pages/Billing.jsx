import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, money, money2, moneyShort, todayIso, useApi } from "../api";
import PartyDialog from "../components/PartyForm";
import VanRun from "../components/VanRun";

const blankLine = () => ({
  key: Math.random().toString(36).slice(2),
  product_id: "",
  cases: 1,
  loose_pieces: 0,
  discount_pct: "",
  rate_per_piece: "",
  is_free: false,
});

export default function Billing() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { data: retailers, reload: reloadRetailers } = useApi("/retailers");
  const { data: products } = useApi("/products");
  const { data: routes } = useApi("/routes");
  const [runVersion, setRunVersion] = useState(0);
  const { data: openRuns } = useApi("/deliveries/open", [runVersion]);

  const [retailerId, setRetailerId] = useState(params.get("retailer") || "");
  // Null means "whatever this party usually does"; set only on an override.
  const [priceMode, setPriceMode] = useState(null);
  const [addingParty, setAddingParty] = useState(false);
  const [invoiceDate, setInvoiceDate] = useState(todayIso());
  const [note, setNote] = useState("");
  const [lines, setLines] = useState([blankLine()]);
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  // How the goods leave. "solo" is the buyer's own vehicle; "van" puts the
  // bill on one of the firm's runs. Chosen per bill, because the same shop
  // collects some weeks and is delivered to on others.
  const [howItLeaves, setHowItLeaves] = useState("solo");
  // "" until a run is chosen; "new" means start one when this bill saves.
  const [runId, setRunId] = useState("");
  // The bill just raised onto the van, so the screen can confirm it without
  // leaving: the owner's next move is usually the next shop on the same van.
  const [lastBill, setLastBill] = useState(null);

  const retailer = retailers?.find((r) => String(r.id) === String(retailerId));

  const payload = useMemo(() => {
    const usable = lines
      .filter((line) => line.product_id && (Number(line.cases) || Number(line.loose_pieces)))
      .map((line) => ({
        product_id: Number(line.product_id),
        cases: Number(line.cases) || 0,
        loose_pieces: Number(line.loose_pieces) || 0,
        discount_pct: line.discount_pct === "" ? null : Number(line.discount_pct),
        rate_per_piece:
          line.rate_per_piece === "" ? null : Number(line.rate_per_piece),
        is_free: line.is_free,
      }));
    return usable.length && retailerId
      ? {
          retailer_id: Number(retailerId),
          invoice_date: invoiceDate,
          price_mode: priceMode,
          lines: usable,
        }
      : null;
  }, [lines, retailerId, invoiceDate, priceMode]);

  // Live pricing, so the biller sees the total before committing.
  useEffect(() => {
    if (!payload) {
      setPreview(null);
      setPreviewError(null);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      api
        .post("/invoices/preview", payload)
        .then((result) => live && (setPreview(result), setPreviewError(null)))
        .catch((err) => live && (setPreview(null), setPreviewError(err)));
    }, 220);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [payload]);

  const update = (key, patch) =>
    setLines((current) =>
      current.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    );

  async function submit() {
    if (!payload) return;
    setSaving(true);
    setSaveError(null);
    try {
      // A new run is created first, so the bill can name it. If the bill
      // then fails the run is left behind empty -- visible on Deliveries
      // and removable there, which is better than losing the bill.
      let deliveryId = null;
      if (howItLeaves === "van") {
        if (runId === "new") {
          const created = await api.post("/deliveries", {
            delivery_date: invoiceDate,
          });
          deliveryId = created.id;
          setRunId(String(created.id));
        } else if (runId) {
          deliveryId = Number(runId);
        }
      }
      const invoice = await api.post("/invoices", {
        ...payload,
        note: note || null,
        delivery_id: deliveryId,
      });
      if (deliveryId) {
        // Stay on the screen. The van is still selected and the panel below
        // refreshes, so the next shop on the same run is one form away
        // instead of two navigations back.
        setLastBill(invoice);
        setRetailerId("");
        setPriceMode(null);
        setLines([blankLine()]);
        setNote("");
        setRunVersion((v) => v + 1);
      } else {
        navigate(`/invoices/${invoice.id}`);
      }
    } catch (err) {
      setSaveError(err);
    } finally {
      setSaving(false);
    }
  }

  // A warning, not a block. The bill is written at the counter with the
  // goods already handed over, so the figure has to be on screen before
  // that — never a refusal after it.
  const overLimit = preview?.credit?.would_exceed;
  const stockWarnings = preview?.stock_warnings || [];
  // What the server actually priced at, once it has answered; before that,
  // the party's own setting.
  const effectiveMode =
    preview?.price_mode || priceMode || retailer?.price_mode || "exclusive";
  const inclusive = effectiveMode === "inclusive";
  const isDistributor = retailer?.party_type === "distributor";

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">New bill</h1>
          <div className="page-sub">
            Prices come from the product master; GST from the rate in force on
            the invoice date.
          </div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 320px", gap: 14 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card">
            <div className="card-title">Bill to</div>
            <div className="row">
              <label className="field grow">
                <span>Party</span>
                <select
                  value={retailerId}
                  onChange={(event) => {
                    setRetailerId(event.target.value);
                    setPriceMode(null); // follow the new party's own setting
                  }}
                >
                  <option value="">Select a shop or sub-distributor…</option>
                  {(retailers || []).map((shop) => (
                    <option key={shop.id} value={shop.id}>
                      {shop.shop_name}
                      {shop.party_type === "distributor" ? " (sub-dist)" : ""}
                      {" — "}
                      {shop.route_name || "no route"}
                    </option>
                  ))}
                </select>
              </label>
              <button
                onClick={() => setAddingParty(true)}
                title="Add a shop that is not on the list yet"
              >
                + New party
              </button>
              <label className="field" style={{ width: 150 }}>
                <span>Invoice date</span>
                <input
                  type="date"
                  value={invoiceDate}
                  onChange={(event) => setInvoiceDate(event.target.value)}
                />
              </label>
            </div>

            {retailer ? (
              <>
                <div className="sub" style={{ marginTop: 9 }}>
                  {retailer.gstin
                    ? `GSTIN ${retailer.gstin}`
                    : "No GSTIN — B2C sale, reported under B2CS"}{" "}
                  · {retailer.state_name} ({retailer.state_code}) · credit{" "}
                  {retailer.credit_days}d / {moneyShort(retailer.credit_limit)}
                  {retailer.state_code !== "36" ? (
                    <>
                      {" · "}
                      <span className="badge">Interstate → IGST</span>
                    </>
                  ) : null}
                  {isDistributor ? (
                    <>
                      {" · "}
                      <span className="badge">Sub-distributor → PTD</span>
                    </>
                  ) : null}
                </div>

                <div className="row" style={{ marginTop: 11 }}>
                  <label className="field" style={{ width: 230 }}>
                    <span>Rate quoted</span>
                    <div className="segmented">
                      <button
                        type="button"
                        className={!inclusive ? "primary" : ""}
                        onClick={() => setPriceMode("exclusive")}
                      >
                        Plus GST
                      </button>
                      <button
                        type="button"
                        className={inclusive ? "primary" : ""}
                        onClick={() => setPriceMode("inclusive")}
                      >
                        All-in
                      </button>
                    </div>
                  </label>
                  <div className="form-hint" style={{ flex: "1 1 240px" }}>
                    {inclusive
                      ? "The rate shown is what the shop pays, GST included. The tax is backed out of it, not added on top — the supply is still taxed and still filed."
                      : "GST is added on top of the rate and shown separately on the bill."}
                    {priceMode && retailer.price_mode !== priceMode ? (
                      <>
                        {" "}
                        <button
                          className="ghost"
                          onClick={() => setPriceMode(null)}
                        >
                          Use this party's usual ({retailer.price_mode === "inclusive" ? "all-in" : "plus GST"})
                        </button>
                      </>
                    ) : null}
                  </div>
                </div>
              </>
            ) : null}
          </div>

          <div className="card">
            <div className="card-title">How it leaves</div>
            <div className="row" style={{ alignItems: "flex-start" }}>
              <label className="field" style={{ width: 260 }}>
                <span>Who moves the goods</span>
                <div className="segmented">
                  <button
                    type="button"
                    className={howItLeaves === "solo" ? "primary" : ""}
                    onClick={() => setHowItLeaves("solo")}
                  >
                    Buyer collects
                  </button>
                  <button
                    type="button"
                    className={howItLeaves === "van" ? "primary" : ""}
                    onClick={() => {
                      setHowItLeaves("van");
                      if (!runId) {
                        const first = (openRuns || [])[0];
                        setRunId(first ? String(first.id) : "new");
                      }
                    }}
                  >
                    I deliver it
                  </button>
                </div>
              </label>

              {howItLeaves === "van" ? (
                <label className="field grow">
                  <span>On which van</span>
                  <select
                    value={runId}
                    onChange={(event) => setRunId(event.target.value)}
                  >
                    {(openRuns || []).map((run) => (
                      <option key={run.id} value={run.id}>
                        {run.delivery_no} · {run.bill_count}{" "}
                        {run.bill_count === 1 ? "bill" : "bills"}
                        {run.status === "out" ? " · already out" : ""}
                      </option>
                    ))}
                    <option value="new">Start a new van run…</option>
                  </select>
                </label>
              ) : null}
            </div>

            <div className="form-hint" style={{ marginTop: 9 }}>
              {howItLeaves === "solo"
                ? "The buyer takes the goods away himself. Nothing else to arrange."
                : runId === "new"
                  ? "The run is created when you save this bill, with this bill on it. You stay here afterwards, so the next shop on the same van is one form away."
                  : "The bill is real either way — the stock leaves the godown and the money is owed now. The van run only says which van carries it."}
            </div>
          </div>

          <div className="card">
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div className="card-title" style={{ marginBottom: 0 }}>
                Items
              </div>
              <button onClick={() => setLines((c) => [...c, blankLine()])}>
                + Add line
              </button>
            </div>

            <div className="table-wrap" style={{ marginTop: 11 }}>
              <table>
                <thead>
                  <tr>
                    <th style={{ minWidth: 200 }}>Product</th>
                    <th className="num" style={{ width: 80 }}>Cases</th>
                    <th className="num" style={{ width: 80 }}>Loose</th>
                    <th className="num" style={{ width: 96 }}>
                      {inclusive ? "Rate (all-in)" : "Rate"}
                    </th>
                    <th className="num" style={{ width: 76 }}>Disc %</th>
                    <th style={{ width: 60 }}>Free</th>
                    <th className="num" style={{ width: 110 }}>Amount</th>
                    <th style={{ width: 34 }} />
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line) => {
                    const product = products?.find(
                      (p) => String(p.id) === String(line.product_id),
                    );
                    const priced = preview?.lines?.find(
                      (l) => l.product_id === Number(line.product_id),
                    );
                    return (
                      <tr key={line.key}>
                        <td>
                          <select
                            value={line.product_id}
                            onChange={(event) => {
                              const chosen = products?.find(
                                (p) => String(p.id) === event.target.value,
                              );
                              update(line.key, {
                                product_id: event.target.value,
                                // Carry the product's standing discount in,
                                // visibly, so it can be changed here.
                                discount_pct:
                                  chosen?.default_discount_pct > 0
                                    ? String(chosen.default_discount_pct)
                                    : "",
                                rate_per_piece: "",
                              });
                            }}
                          >
                            <option value="">Select…</option>
                            {(products || []).map((product) => (
                              <option key={product.id} value={product.id}>
                                {product.name}
                              </option>
                            ))}
                          </select>
                          {product ? (
                            <div className="sub" style={{ marginTop: 3 }}>
                              {product.pieces_per_case}/case ·{" "}
                              {isDistributor ? "PTD " : "PTR "}
                              {money2(isDistributor ? product.ptd : product.ptr)}{" "}
                              · MRP {money(product.mrp)}
                            </div>
                          ) : null}
                        </td>
                        <td>
                          <input
                            type="number"
                            min="0"
                            value={line.cases}
                            onChange={(event) =>
                              update(line.key, { cases: event.target.value })
                            }
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
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            placeholder={
                              priced?.quoted_rate_per_piece != null
                                ? String(priced.quoted_rate_per_piece)
                                : priced
                                  ? String(priced.rate_per_piece)
                                  : "list"
                            }
                            disabled={line.is_free}
                            value={line.rate_per_piece}
                            title="Leave blank for the list price; type one to override it."
                            onChange={(event) =>
                              update(line.key, {
                                rate_per_piece: event.target.value,
                              })
                            }
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            min="0"
                            max="100"
                            placeholder="—"
                            disabled={line.is_free}
                            value={line.discount_pct}
                            onChange={(event) =>
                              update(line.key, { discount_pct: event.target.value })
                            }
                          />
                        </td>
                        <td style={{ textAlign: "center" }}>
                          <input
                            type="checkbox"
                            style={{ width: 16 }}
                            checked={line.is_free}
                            onChange={(event) =>
                              update(line.key, {
                                is_free: event.target.checked,
                                discount_pct: "",
                              })
                            }
                          />
                        </td>
                        <td className="num">
                          {priced ? money2(priced.line_total) : <span className="muted">—</span>}
                        </td>
                        <td>
                          <button
                            className="ghost danger"
                            onClick={() =>
                              setLines((c) =>
                                c.length > 1
                                  ? c.filter((l) => l.key !== line.key)
                                  : [blankLine()],
                              )
                            }
                            title="Remove line"
                          >
                            ✕
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <label className="field" style={{ marginTop: 12 }}>
              <span>Note (optional)</span>
              <input
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="Delivery instruction, vehicle, anything to print"
              />
            </label>
          </div>
        </div>

        {/* Summary rail */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card">
            <div className="card-title">Bill summary</div>
            {previewError ? (
              <div className="notice error">{previewError.message}</div>
            ) : !preview ? (
              <div className="empty">Pick a retailer and a product.</div>
            ) : (
              <>
                <div className="totals" style={{ width: "100%" }}>
                  <div className="line">
                    <span className="muted">Taxable</span>
                    <span>{money2(preview.totals.taxable_total)}</span>
                  </div>
                  {preview.totals.discount_total > 0 ? (
                    <div className="line">
                      <span className="muted">Scheme discount</span>
                      <span>−{money2(preview.totals.discount_total)}</span>
                    </div>
                  ) : null}
                  {preview.interstate ? (
                    <div className="line">
                      <span className="muted">IGST</span>
                      <span>{money2(preview.totals.igst_total)}</span>
                    </div>
                  ) : (
                    <>
                      <div className="line">
                        <span className="muted">CGST</span>
                        <span>{money2(preview.totals.cgst_total)}</span>
                      </div>
                      <div className="line">
                        <span className="muted">SGST</span>
                        <span>{money2(preview.totals.sgst_total)}</span>
                      </div>
                    </>
                  )}
                  {preview.totals.round_off !== 0 ? (
                    <div className="line">
                      <span className="muted">Round off</span>
                      <span>{money2(preview.totals.round_off)}</span>
                    </div>
                  ) : null}
                  <div className="line grand">
                    <span>Payable</span>
                    <span>{money(preview.totals.grand_total)}</span>
                  </div>
                </div>
                <div className="sub" style={{ marginTop: 8 }}>
                  {preview.amount_in_words}
                </div>
                {inclusive ? (
                  <div className="form-hint" style={{ marginTop: 6 }}>
                    Rates were quoted all-in; the GST above is contained in
                    them. The bill prints a note saying so.
                  </div>
                ) : null}
              </>
            )}
          </div>

          {preview ? (
            <div className="card">
              <div className="card-title">Credit position</div>
              <div className="kv">
                <dt>Already owes</dt>
                <dd>{money(preview.credit.outstanding)}</dd>
                <dt>After this bill</dt>
                <dd>{money(preview.credit.after_this_bill)}</dd>
                <dt>Limit</dt>
                <dd>
                  {preview.credit.limit > 0
                    ? money(preview.credit.limit)
                    : "none set"}
                </dd>
              </div>
              {overLimit ? (
                <div className="notice warn" style={{ marginTop: 10 }}>
                  This bill takes the shop{" "}
                  {money(
                    preview.credit.after_this_bill - preview.credit.limit,
                  )}{" "}
                  past its credit limit. Your call — the bill will go through.
                </div>
              ) : null}
            </div>
          ) : null}

          {stockWarnings.length ? (
            <div className="notice warn">
              <strong>Not enough stock</strong>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                {stockWarnings.map((warning) => (
                  <li key={warning.product_id}>{warning.message}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {saveError ? <div className="notice error">{saveError.message}</div> : null}

          <div className="row">
            <button
              className="primary grow"
              disabled={!preview || saving || stockWarnings.length > 0}
              onClick={submit}
            >
              {saving ? "Saving…" : "Raise invoice"}
            </button>
          </div>
        </div>
      </div>

      {/* The van, right here. Once a bill is going on a run the next thing
          the owner wants is what is already aboard, what to load, and the
          button that sends it out -- not a trip to another screen to find
          them. The same component Deliveries uses, so the two never drift. */}
      {howItLeaves === "van" && runId && runId !== "new" ? (
        <div style={{ marginTop: 14 }}>
          {lastBill ? (
            <div className="notice" style={{ marginBottom: 12 }}>
              <strong>{lastBill.invoice_no}</strong> raised for{" "}
              {lastBill.retailer_name} — {money(lastBill.grand_total)}, and it
              is on the van below.{" "}
              <Link to={`/invoices/${lastBill.id}`}>Open the bill</Link> if you
              want to print it, or pick the next shop above to keep going.
            </div>
          ) : null}
          <VanRun
            runId={Number(runId)}
            version={runVersion}
            onChanged={() => setRunVersion((v) => v + 1)}
          />
        </div>
      ) : null}

      {addingParty ? (
        <PartyDialog
          routes={routes}
          compact
          onClose={() => setAddingParty(false)}
          onSaved={(saved) => {
            setAddingParty(false);
            reloadRetailers();
            setRetailerId(String(saved.id));
            setPriceMode(null);
          }}
        />
      ) : null}
    </>
  );
}
