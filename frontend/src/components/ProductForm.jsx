import { useMemo, useState } from "react";
import { api, money2 } from "../api";
import Modal, { Field } from "./Modal";

export const blankProduct = () => ({
  sku_code: "",
  brand: "",
  name: "",
  pack_size_g: "100",
  pieces_per_case: "48",
  hsn: "1905",
  mrp: "",
  ptr: "",
  ptd: "",
  landing_rate: "",
  purchase_scheme_pct: "0",
  default_discount_pct: "0",
  shelf_life_days: "240",
});

export default function ProductDialog({ product, brands, onClose, onSaved }) {
  const editing = Boolean(product?.id);
  const [form, setForm] = useState(() =>
    product
      ? {
          sku_code: product.sku_code,
          brand: product.brand,
          // The list sends a display name with the pack size baked in; strip
          // it back off so an edit does not double it up.
          name: String(product.name).replace(
            new RegExp(`\\s+${product.pack_size_g}g$`),
            "",
          ),
          pack_size_g: String(product.pack_size_g),
          pieces_per_case: String(product.pieces_per_case),
          hsn: product.hsn,
          mrp: String(product.mrp),
          ptr: String(product.ptr),
          ptd: String(product.ptd),
          landing_rate: String(product.landing_rate ?? ""),
          purchase_scheme_pct: String(product.purchase_scheme_pct ?? 0),
          default_discount_pct: String(product.default_discount_pct ?? 0),
          shelf_life_days: String(product.shelf_life_days),
        }
      : blankProduct(),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));

  // The three prices have to stack up, so show the margins as they are typed.
  const maths = useMemo(() => {
    const mrp = Number(form.mrp) || 0;
    const ptr = Number(form.ptr) || 0;
    const ptd = Number(form.ptd) || 0;
    const perCase = Number(form.pieces_per_case) || 0;
    const landing = Number(form.landing_rate) || 0;
    const scheme = Number(form.purchase_scheme_pct) || 0;
    // What he actually pays, once the company's scheme comes off. That is the
    // number his margin should be measured against, not the list rate.
    const cost = landing > 0 ? landing * (1 - scheme / 100) : 0;
    return {
      retailerMargin: ptr > 0 ? ((mrp / 1.05 - ptr) / ptr) * 100 : 0,
      ownMargin: ptd > 0 ? ((ptr - ptd) / ptd) * 100 : 0,
      cost,
      realMargin: cost > 0 && ptr > 0 ? ((ptr - cost) / cost) * 100 : 0,
      caseValue: ptr * perCase,
      inverted: ptd > 0 && ptr > 0 && ptd > ptr,
      overMrp: mrp > 0 && ptr > 0 && ptr > mrp,
      belowCost: cost > 0 && ptr > 0 && ptr < cost,
    };
  }, [form]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const body = {
        brand: form.brand.trim(),
        name: form.name.trim(),
        pack_size_g: Number(form.pack_size_g),
        pieces_per_case: Number(form.pieces_per_case),
        hsn: form.hsn.trim(),
        mrp: Number(form.mrp),
        ptr: Number(form.ptr),
        ptd: Number(form.ptd),
        landing_rate: Number(form.landing_rate) || 0,
        purchase_scheme_pct: Number(form.purchase_scheme_pct) || 0,
        default_discount_pct: Number(form.default_discount_pct) || 0,
        shelf_life_days: Number(form.shelf_life_days),
      };
      const saved = editing
        ? await api.patch(`/products/${product.id}`, body)
        : await api.post("/products", { ...body, sku_code: form.sku_code.trim() });
      onSaved?.(saved);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  const blocked =
    saving ||
    !form.brand.trim() ||
    !form.name.trim() ||
    !(Number(form.mrp) > 0) ||
    !(Number(form.ptr) > 0) ||
    !(Number(form.ptd) > 0) ||
    (!editing && form.sku_code.trim().length < 2);

  return (
    <Modal
      title={editing ? `Edit ${product.sku_code}` : "Add a product"}
      subtitle="Prices are per piece and exclusive of GST, as the trade quotes them."
      onClose={onClose}
      footer={
        <>
          {error ? (
            <div className="spacer notice error" style={{ margin: 0 }}>
              {error.message}
            </div>
          ) : (
            <div className="spacer" />
          )}
          <button onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button className="primary" onClick={save} disabled={blocked}>
            {saving ? "Saving…" : editing ? "Save changes" : "Add product"}
          </button>
        </>
      }
    >
      <div className="form-grid">
        <Field
          label="SKU code"
          value={form.sku_code}
          onChange={set("sku_code")}
          placeholder="PRL-PG-100"
          disabled={editing}
          hint={
            editing
              ? "Fixed: invoices already printed quote it."
              : "Your own code for this pack."
          }
        />
        <Field
          label="Brand"
          value={form.brand}
          onChange={set("brand")}
          placeholder="Keki"
          list="brand-list"
        />
        <datalist id="brand-list">
          {(brands || []).map((brand) => (
            <option key={brand} value={brand} />
          ))}
        </datalist>
        <Field
          label="Product"
          value={form.name}
          onChange={set("name")}
          placeholder="Cream Bites Litchi"
          hint="The full name as the company writes it, without the pack size."
        />

        <div className="form-section">Pack</div>
        <Field
          label="Pack size (g)"
          type="number"
          min="1"
          value={form.pack_size_g}
          onChange={set("pack_size_g")}
        />
        <Field
          label="Pieces per case"
          type="number"
          min="1"
          value={form.pieces_per_case}
          onChange={set("pieces_per_case")}
          hint="Stock, bills and van loads all convert through this."
        />
        <Field
          label="Shelf life (days)"
          type="number"
          min="1"
          value={form.shelf_life_days}
          onChange={set("shelf_life_days")}
        />

        <div className="form-section">Price</div>
        <Field
          label="MRP (₹)"
          type="number"
          min="0"
          step="0.5"
          value={form.mrp}
          onChange={set("mrp")}
          hint="Printed on the pack, inclusive of GST."
        />
        <Field
          label="PTR (₹ / piece)"
          type="number"
          min="0"
          step="0.01"
          value={form.ptr}
          onChange={set("ptr")}
          hint={
            maths.overMrp
              ? "PTR is above MRP."
              : maths.retailerMargin > 0
                ? `Retailer makes ${maths.retailerMargin.toFixed(1)}%.`
                : "What a shop pays."
          }
        />
        <Field
          label="PTD (₹ / piece)"
          type="number"
          min="0"
          step="0.01"
          value={form.ptd}
          onChange={set("ptd")}
          hint={
            maths.inverted
              ? "PTD is above PTR; a sub-distributor would pay more than a shop."
              : maths.ownMargin > 0
                ? `You make ${maths.ownMargin.toFixed(1)}% on a retail sale.`
                : "What a sub-distributor pays."
          }
        />
        <Field
          label="HSN"
          value={form.hsn}
          onChange={set("hsn")}
          hint="Biscuits are 1905. The GST rate is read from this, by date."
        />

        <div className="form-section">What you pay the company</div>
        <Field
          label="Landing rate (₹ / piece)"
          type="number"
          min="0"
          step="0.0001"
          value={form.landing_rate}
          onChange={set("landing_rate")}
          hint={
            maths.belowCost
              ? "PTR is below what this costs you."
              : maths.realMargin > 0
                ? `After scheme you pay ${money2(maths.cost)}, so you make ${maths.realMargin.toFixed(1)}%.`
                : "Basic rate per case on the order sheet, divided by packets per case."
          }
        />
        <Field
          label="Purchase scheme (%)"
          type="number"
          min="0"
          max="100"
          step="0.5"
          value={form.purchase_scheme_pct}
          onChange={set("purchase_scheme_pct")}
          hint="The scheme the company allows you on this SKU. Not a discount you give."
        />

        <div className="form-section">What you give away</div>
        <Field
          label="Standing discount (%)"
          type="number"
          min="0"
          max="100"
          step="0.5"
          value={form.default_discount_pct}
          onChange={set("default_discount_pct")}
          hint="Pre-filled on every bill line, and changeable there."
        />

        {maths.caseValue > 0 ? (
          <div className="form-hint span-all">
            A case of {form.pieces_per_case} works out to{" "}
            <strong>{money2(maths.caseValue)}</strong> before GST, at PTR.
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
