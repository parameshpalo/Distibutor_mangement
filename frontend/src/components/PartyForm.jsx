import { useState } from "react";
import { api } from "../api";
import Modal, { Field, Segmented } from "./Modal";

/** GST state codes. The first two digits of a GSTIN must match the state. */
export const STATES = [
  ["36", "Telangana"],
  ["37", "Andhra Pradesh"],
  ["29", "Karnataka"],
  ["33", "Tamil Nadu"],
  ["27", "Maharashtra"],
  ["32", "Kerala"],
  ["24", "Gujarat"],
  ["21", "Odisha"],
  ["09", "Uttar Pradesh"],
  ["07", "Delhi"],
  ["19", "West Bengal"],
  ["23", "Madhya Pradesh"],
  ["08", "Rajasthan"],
  ["10", "Bihar"],
  ["03", "Punjab"],
  ["06", "Haryana"],
  ["22", "Chhattisgarh"],
  ["20", "Jharkhand"],
  ["18", "Assam"],
  ["30", "Goa"],
];

export const OUTLET_TYPES = [
  ["kirana", "Kirana"],
  ["supermarket", "Supermarket"],
  ["bakery", "Bakery"],
  ["tea_stall", "Tea stall"],
  ["pan_shop", "Pan shop"],
  ["canteen", "Canteen"],
  ["wholesale", "Wholesale"],
];

export const blankParty = () => ({
  shop_name: "",
  owner_name: "",
  gstin: "",
  party_type: "retailer",
  price_mode: "exclusive",
  phone: "",
  address_line: "",
  city: "",
  state_name: "Telangana",
  state_code: "36",
  pincode: "",
  outlet_type: "kirana",
  route_id: "",
  credit_limit: "0",
  credit_days: "7",
});

/** Only the keys the API accepts, with blanks turned into nulls. */
function toPayload(form) {
  return {
    shop_name: form.shop_name.trim(),
    owner_name: form.owner_name?.trim() || null,
    gstin: form.gstin?.trim() ? form.gstin.trim().toUpperCase() : null,
    party_type: form.party_type,
    price_mode: form.price_mode,
    phone: form.phone?.trim() || null,
    address_line: form.address_line?.trim() || null,
    city: form.city?.trim() || null,
    state_name: form.state_name,
    state_code: form.state_code,
    pincode: form.pincode?.trim() || null,
    outlet_type: form.outlet_type,
    route_id: form.route_id ? Number(form.route_id) : null,
    credit_limit: Number(form.credit_limit) || 0,
    credit_days: Number(form.credit_days) || 0,
  };
}

/**
 * Add or edit a party.
 *
 * `compact` drops the address and route fields, for the quick-add on the
 * billing screen where the shop is standing at the counter and the rest
 * can be filled in later.
 */
export default function PartyDialog({
  party,
  routes,
  compact = false,
  onClose,
  onSaved,
}) {
  const editing = Boolean(party?.id);
  const [form, setForm] = useState(() =>
    party
      ? {
          ...blankParty(),
          ...party,
          gstin: party.gstin || "",
          route_id: party.route_id ?? "",
          credit_limit: String(party.credit_limit ?? 0),
          credit_days: String(party.credit_days ?? 7),
        }
      : blankParty(),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));

  const setState = (code) => {
    const found = STATES.find(([key]) => key === code);
    setForm((f) => ({
      ...f,
      state_code: code,
      state_name: found ? found[1] : f.state_name,
    }));
  };

  const gstin = form.gstin.trim().toUpperCase();
  const gstinMismatch = gstin.length >= 2 && gstin.slice(0, 2) !== form.state_code;
  const gstinWrongLength = gstin.length > 0 && gstin.length !== 15;

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const payload = toPayload(form);
      const saved = editing
        ? await api.patch(`/retailers/${party.id}`, payload)
        : await api.post("/retailers", payload);
      onSaved?.(saved);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  const blocked =
    !form.shop_name.trim() || gstinMismatch || gstinWrongLength || saving;

  return (
    <Modal
      title={editing ? `Edit ${party.shop_name}` : "Add a party"}
      subtitle={
        editing
          ? party.code
          : "A shop or a sub-distributor. A GSTIN is optional."
      }
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
            {saving ? "Saving…" : editing ? "Save changes" : "Add party"}
          </button>
        </>
      }
    >
      <div className="form-grid">
        <Field
          label="Shop / firm name"
          value={form.shop_name}
          onChange={set("shop_name")}
          placeholder="Sri Venkateswara Kirana"
          autoFocus
        />
        <Field
          label="Owner"
          value={form.owner_name}
          onChange={set("owner_name")}
          placeholder="Optional"
        />
        <Field
          label="Phone"
          value={form.phone}
          onChange={set("phone")}
          placeholder="Optional"
        />

        <div className="form-section">How they buy</div>
        <Segmented
          label="Party type"
          value={form.party_type}
          onChange={(value) =>
            setForm((f) => ({
              ...f,
              party_type: value,
              // A sub-distributor is a wholesale buyer on longer terms.
              outlet_type:
                value === "distributor" ? "wholesale" : f.outlet_type,
              credit_days:
                value === "distributor" && f.credit_days === "7"
                  ? "21"
                  : f.credit_days,
            }))
          }
          options={[
            ["retailer", "Retailer"],
            ["distributor", "Sub-distributor"],
          ]}
          hint={
            form.party_type === "distributor"
              ? "Billed at PTD, the distributor price."
              : "Billed at PTR, the retailer price."
          }
        />
        <Segmented
          label="Rate quoted"
          value={form.price_mode}
          onChange={set("price_mode")}
          options={[
            ["exclusive", "Plus GST"],
            ["inclusive", "All-in"],
          ]}
          hint={
            form.price_mode === "inclusive"
              ? "GST is contained in the rate, not added to it. The supply is still taxed and still filed."
              : "GST is added on top of the rate, and shown separately."
          }
        />
        <Field
          label="Outlet type"
          value={form.outlet_type}
          onChange={set("outlet_type")}
          options={OUTLET_TYPES}
        />

        <div className="form-section">Tax</div>
        <Field
          label="GSTIN"
          value={form.gstin}
          onChange={(value) => set("gstin")(value.toUpperCase())}
          placeholder="Leave blank if unregistered"
          maxLength={15}
          hint={
            gstinWrongLength
              ? `A GSTIN is 15 characters; this one has ${gstin.length}.`
              : gstinMismatch
                ? `This GSTIN starts ${gstin.slice(0, 2)}, but the state code is ${form.state_code}.`
                : gstin
                  ? "Registered: this party's bills go to B2B in GSTR-1."
                  : "Unregistered is normal for a kirana. The bill still carries GST and still reaches GSTR-1, under B2CS."
          }
        />
        <Field
          label="State"
          value={form.state_code}
          onChange={setState}
          options={STATES.map(([code, name]) => [code, `${name} (${code})`])}
          hint={
            form.state_code !== "36"
              ? "Outside Telangana: this party is billed IGST."
              : undefined
          }
        />

        <div className="form-section">Credit</div>
        <Field
          label="Credit limit (₹)"
          type="number"
          min="0"
          step="1000"
          value={form.credit_limit}
          onChange={set("credit_limit")}
          hint="0 means cash only; no limit is enforced."
        />
        <Field
          label="Credit days"
          type="number"
          min="0"
          max="120"
          value={form.credit_days}
          onChange={set("credit_days")}
        />

        {compact ? null : (
          <>
            <div className="form-section">Where</div>
            <Field
              label="Address"
              value={form.address_line}
              onChange={set("address_line")}
              span
            />
            <Field label="City" value={form.city} onChange={set("city")} />
            <Field
              label="PIN code"
              value={form.pincode}
              onChange={set("pincode")}
              maxLength={6}
            />
            <Field
              label="Route"
              value={form.route_id}
              onChange={set("route_id")}
              options={[
                ["", "No route"],
                ...(routes || []).map((route) => [String(route.id), route.name]),
              ]}
              hint="Which day's run this shop sits on."
            />
          </>
        )}
      </div>
    </Modal>
  );
}
