import { useEffect, useState } from "react";
import { api, useApi } from "../api";

/**
 * My firm: the details printed on every tax invoice.
 *
 * These start blank. `python -m app.init` deliberately invents nothing, so
 * this page is where the real figures are typed in once, from the papers.
 * Anything still missing is listed at the top, because a bill printed without
 * a GSTIN or a place of supply is not a tax invoice.
 *
 * The state code is not editable: it is the first two digits of the GSTIN,
 * which is the rule the portal applies. Letting the two disagree would put
 * the wrong place of supply on every bill.
 */

const SECTIONS = [
  {
    title: "The firm",
    note: "Printed at the top of every invoice.",
    fields: [
      ["legal_name", "Legal name", "as registered on the GST certificate", true],
      ["trade_name", "Trading name", "if it differs from the legal name"],
      ["gstin", "GSTIN", "15 characters", true],
      ["pan", "PAN", "10 characters"],
      ["fssai_no", "FSSAI licence", "food business licence number"],
    ],
  },
  {
    title: "Where it is",
    note: "This address decides the place of supply, which decides whether a bill carries CGST+SGST or IGST.",
    fields: [
      ["address_line1", "Address", "building, street", true],
      ["address_line2", "Address, second line", "area, landmark"],
      ["city", "City or town", "", true],
      ["state_name", "State", "", true],
      ["pincode", "PIN code", "6 digits", true],
      ["phone", "Phone", ""],
      ["email", "Email", ""],
    ],
  },
  {
    title: "For payment",
    note: "Printed on the invoice so a shop can transfer money without asking.",
    fields: [
      ["bank_name", "Bank and branch", ""],
      ["bank_account", "Account number", ""],
      ["bank_ifsc", "IFSC", ""],
    ],
  },
  {
    title: "Numbering",
    note: "Bills are numbered PREFIX/26-27/00001, restarting each financial year. Changing the prefix does not renumber anything already issued.",
    fields: [["invoice_prefix", "Invoice prefix", "up to 6 characters", true]],
  },
];

const REQUIRED = SECTIONS.flatMap((s) =>
  s.fields.filter(([, , , required]) => required).map(([key, label]) => [key, label]),
);

export default function MyFirm() {
  const { data: company, reload } = useApi("/company");
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (company) setForm({ ...company });
  }, [company]);

  if (!company && !form) {
    return (
      <div className="card">
        <div className="empty">
          There is no company profile yet. Start a database with{" "}
          <code>python -m app.init</code>.
        </div>
      </div>
    );
  }
  if (!form) return <div className="loading">Loading…</div>;

  const missing = REQUIRED.filter(([key]) => !String(form[key] || "").trim());
  const dirty =
    company && Object.keys(form).some((key) => form[key] !== company[key]);

  const stateCode = String(form.gstin || "").slice(0, 2);

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      // Send only what changed, and never state_code — the server derives it.
      const changes = {};
      for (const key of Object.keys(form)) {
        if (key === "state_code") continue;
        const value = String(form[key] ?? "").trim();
        if (value !== String(company[key] ?? "")) changes[key] = value || null;
      }
      await api.patch("/company", changes);
      setSaved(true);
      reload();
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
          <h1 className="page-title">My firm</h1>
          <div className="page-sub">
            The details printed on every tax invoice. Typed in once, from the
            papers.
          </div>
        </div>
      </div>

      {missing.length ? (
        <div className="notice warn" style={{ marginBottom: 14 }}>
          <strong>
            {missing.length} {missing.length === 1 ? "detail" : "details"} still
            needed before a bill is printed
          </strong>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {missing.map(([key, label]) => (
              <li key={key}>{label}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="notice ok" style={{ marginBottom: 14 }}>
          Everything a tax invoice needs is filled in.
        </div>
      )}

      {SECTIONS.map((section) => (
        <div className="card" key={section.title} style={{ marginBottom: 14 }}>
          <div className="card-title">{section.title}</div>
          <div className="form-grid">
            {section.fields.map(([key, label, hint, required]) => (
              <label className="field" key={key}>
                <span>
                  {label}
                  {required ? " *" : ""}
                </span>
                <input
                  value={form[key] ?? ""}
                  onChange={(e) => {
                    setSaved(false);
                    setForm({ ...form, [key]: e.target.value });
                  }}
                  placeholder={hint}
                />
                {hint ? <div className="form-hint">{hint}</div> : null}
              </label>
            ))}
            {section.title === "Where it is" ? (
              <label className="field">
                <span>State code</span>
                <input value={stateCode} disabled />
                <div className="form-hint">
                  Taken from the first two digits of the GSTIN, not typed.
                </div>
              </label>
            ) : null}
          </div>
          <div className="card-note">{section.note}</div>
        </div>
      ))}

      {error ? (
        <div className="notice error" style={{ marginBottom: 10 }}>
          {error.message}
        </div>
      ) : null}
      {saved ? (
        <div className="notice ok" style={{ marginBottom: 10 }}>
          Saved. New bills will carry these details.
        </div>
      ) : null}

      <div className="row">
        <button className="primary" disabled={saving || !dirty} onClick={save}>
          {saving ? "Saving…" : "Save"}
        </button>
        {dirty ? (
          <button className="ghost" onClick={() => setForm({ ...company })}>
            Undo changes
          </button>
        ) : null}
      </div>
    </>
  );
}
