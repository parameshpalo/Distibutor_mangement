import { useState } from "react";
import { WEEKDAYS, api, date, money, money2, useApi } from "../api";
import ProductDialog from "../components/ProductForm";

const TABS = [
  ["products", "Products"],
  ["routes", "Routes"],
  ["gst", "GST rates"],
];

export default function Masters() {
  const [tab, setTab] = useState("products");
  const [search, setSearch] = useState("");

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Masters</h1>
          <div className="page-sub">
            Products, routes and the dated GST rates that billing reads.
            Shops and sub-distributors live under Parties.
          </div>
        </div>
      </div>

      <div className="toolbar">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            className={tab === key ? "primary" : ""}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
        {tab === "products" ? (
          <input
            placeholder="Search SKU, name or brand"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            style={{ maxWidth: 280, marginLeft: "auto" }}
          />
        ) : null}
      </div>

      {tab === "products" ? <Products search={search} /> : null}
      {tab === "routes" ? <Routes /> : null}
      {tab === "gst" ? <GstRates /> : null}
    </>
  );
}

function Products({ search }) {
  const [showRetired, setShowRetired] = useState(false);
  const [editing, setEditing] = useState(null); // product, or "new"
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const query = new URLSearchParams();
  if (search.trim()) query.set("search", search.trim());
  if (showRetired) query.set("active_only", "false");
  const suffix = query.toString() ? `?${query}` : "";

  const { data, loading, reload } = useApi(`/products${suffix}`);
  const { data: brands } = useApi("/brands");

  async function remove(product) {
    const ok = window.confirm(
      `Remove ${product.name}?\n\nIf it has ever been bought or sold it will ` +
        "be retired instead of deleted, so old bills stay intact.",
    );
    if (!ok) return;
    setBusy(true);
    setNotice(null);
    try {
      const result = await api.del(`/products/${product.id}`);
      setNotice({ kind: result.deleted ? "good" : "warn", text: result.message });
      reload();
    } catch (err) {
      setNotice({ kind: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  }

  async function restore(product) {
    setBusy(true);
    try {
      await api.patch(`/products/${product.id}`, { is_active: true });
      setNotice({ kind: "good", text: `${product.name} is back on the list.` });
      reload();
    } catch (err) {
      setNotice({ kind: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="loading">Loading…</div>;

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <button className="primary" onClick={() => setEditing("new")}>
          + Add product
        </button>
        <label className="check" style={{ padding: 0 }}>
          <input
            type="checkbox"
            checked={showRetired}
            onChange={(event) => setShowRetired(event.target.checked)}
          />
          Show retired
        </label>
      </div>

      {notice ? (
        <div
          className={`notice ${notice.kind === "good" ? "" : notice.kind}`}
          style={{ marginBottom: 12 }}
        >
          {notice.text}
        </div>
      ) : null}

      <div className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>SKU</th>
                <th>Product</th>
                <th>Brand</th>
                <th>HSN</th>
                <th className="num">Pack</th>
                <th className="num">Per case</th>
                <th className="num">MRP</th>
                <th className="num">PTR</th>
                <th className="num">PTD</th>
                <th className="num">Cost</th>
                <th className="num">Sch.</th>
                <th className="num">Margin</th>
                <th className="num">Disc.</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(data || []).map((product) => {
                // Margin against what he really pays the company -- landing
                // rate less the purchase scheme -- and only against PTD when
                // the sheet gave no landing rate.
                const cost =
                  product.landing_rate > 0
                    ? product.landing_rate *
                      (1 - (product.purchase_scheme_pct || 0) / 100)
                    : product.ptd;
                const pct = cost > 0 ? ((product.ptr - cost) / cost) * 100 : 0;
                return (
                  <tr
                    key={product.id}
                    style={{ opacity: product.is_active ? 1 : 0.5 }}
                  >
                    <td className="mono sub">{product.sku_code}</td>
                    <td>
                      {product.name}
                      {!product.is_active ? (
                        <span className="badge" style={{ marginLeft: 6 }}>
                          retired
                        </span>
                      ) : null}
                    </td>
                    <td className="sub">{product.brand}</td>
                    <td className="mono sub">{product.hsn}</td>
                    <td className="num">{product.pack_size_g}g</td>
                    <td className="num">{product.pieces_per_case}</td>
                    <td className="num">{money(product.mrp)}</td>
                    <td className="num">{money2(product.ptr)}</td>
                    <td className="num muted">{money2(product.ptd)}</td>
                    <td className="num">
                      {product.landing_rate > 0 ? (
                        money2(cost)
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="num sub">
                      {product.purchase_scheme_pct > 0
                        ? `${product.purchase_scheme_pct}%`
                        : "—"}
                    </td>
                    <td className="num">{pct.toFixed(1)}%</td>
                    <td className="num sub">
                      {product.default_discount_pct > 0
                        ? `${product.default_discount_pct}%`
                        : "—"}
                    </td>
                    <td>
                      <div className="row-actions">
                        <button
                          className="ghost"
                          disabled={busy}
                          onClick={() => setEditing(product)}
                        >
                          Edit
                        </button>
                        {product.is_active ? (
                          <button
                            className="ghost danger"
                            disabled={busy}
                            onClick={() => remove(product)}
                          >
                            Remove
                          </button>
                        ) : (
                          <button
                            className="ghost"
                            disabled={busy}
                            onClick={() => restore(product)}
                          >
                            Restore
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="card-note">
          All rates are per piece and exclusive of GST, as the trade quotes
          them. <strong>Cost</strong> is the company's landing rate less the
          purchase scheme it allows — what you actually pay — and{" "}
          <strong>Margin</strong> is PTR over that cost. MRP, pack and cost
          come from the supplier's order sheet; PTR and PTD were worked back
          from MRP and are the two figures to check against your own rate card.
          Editing a price changes what the next bill costs; invoices already
          raised keep the rate they were printed with.
        </div>
      </div>

      {editing ? (
        <ProductDialog
          product={editing === "new" ? null : editing}
          brands={brands}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload();
          }}
        />
      ) : null}
    </>
  );
}

function Routes() {
  const { data, loading } = useApi("/routes");
  if (loading) return <div className="loading">Loading…</div>;
  return (
    <div className="card">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Route</th>
              <th>Visit day</th>
              <th className="num">Retailers</th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((route) => (
              <tr key={route.id}>
                <td style={{ fontWeight: 550 }}>{route.name}</td>
                <td>{WEEKDAYS[route.day_of_week]}</td>
                <td className="num">{route.retailer_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card-note">
        A route is a standing list of shops with a usual weekday. Who takes
        the van out, and on which day, is decided per trip -- not here.
      </div>
    </div>
  );
}

function GstRates() {
  const { data, loading } = useApi("/gst-rates");
  if (loading) return <div className="loading">Loading…</div>;
  return (
    <div className="card">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>HSN</th>
              <th className="num">Rate</th>
              <th>From</th>
              <th>To</th>
              <th>Status</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((rate) => (
              <tr key={rate.id}>
                <td className="mono">{rate.hsn}</td>
                <td className="num">{rate.rate}%</td>
                <td className="shrink">{date(rate.effective_from)}</td>
                <td className="shrink">
                  {rate.effective_to ? date(rate.effective_to) : <span className="muted">open</span>}
                </td>
                <td>
                  {rate.is_current ? (
                    <span className="badge good">In force</span>
                  ) : (
                    <span className="badge">Historic</span>
                  )}
                </td>
                <td className="sub">{rate.note || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card-note">
        Rates are resolved against the invoice date, so reprinting an old bill
        shows the rate that applied then. Confirm the current slab with your CA
        before go-live.
      </div>
    </div>
  );
}
