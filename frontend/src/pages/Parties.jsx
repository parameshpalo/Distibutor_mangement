import { useState } from "react";
import { Link } from "react-router-dom";
import { api, moneyShort, useApi } from "../api";
import PartyDialog from "../components/PartyForm";

const FILTERS = [
  ["", "Everyone"],
  ["retailer", "Retailers"],
  ["distributor", "Sub-distributors"],
];

export default function Parties() {
  const [search, setSearch] = useState("");
  const [partyType, setPartyType] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState(null); // party object, or "new"

  const query = new URLSearchParams();
  if (search.trim()) query.set("search", search.trim());
  if (partyType) query.set("party_type", partyType);
  if (showInactive) query.set("active_only", "false");
  const suffix = query.toString() ? `?${query}` : "";

  const { data: parties, loading, reload } = useApi(`/retailers${suffix}`);
  const { data: routes } = useApi("/routes");

  const counts = (parties || []).reduce(
    (acc, p) => ({
      ...acc,
      [p.party_type]: (acc[p.party_type] || 0) + 1,
      unregistered: acc.unregistered + (p.gstin ? 0 : 1),
    }),
    { unregistered: 0 },
  );

  async function setActive(party, active) {
    await api.patch(`/retailers/${party.id}`, { is_active: active });
    reload();
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Parties</h1>
          <div className="page-sub">
            Everyone you bill: shops, and sub-distributors who buy at PTD and
            resell. A GSTIN is optional — most kiranas have none.
          </div>
        </div>
        <button className="primary" onClick={() => setEditing("new")}>
          + Add party
        </button>
      </div>

      <div className="toolbar">
        {FILTERS.map(([key, label]) => (
          <button
            key={key}
            className={partyType === key ? "primary" : ""}
            onClick={() => setPartyType(key)}
          >
            {label}
          </button>
        ))}
        <label className="check" style={{ padding: 0 }}>
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(event) => setShowInactive(event.target.checked)}
          />
          Show retired
        </label>
        <input
          placeholder="Search name, code, owner or phone"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          style={{ maxWidth: 300, marginLeft: "auto" }}
        />
      </div>

      {loading ? (
        <div className="loading">Loading…</div>
      ) : (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Party</th>
                  <th>Type</th>
                  <th>Route</th>
                  <th>GSTIN</th>
                  <th>Rate</th>
                  <th className="num">Credit</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(parties || []).map((party) => (
                  <tr key={party.id} style={{ opacity: party.is_active ? 1 : 0.5 }}>
                    <td className="mono sub">{party.code}</td>
                    <td>
                      {party.shop_name}
                      {party.state_code !== "36" ? (
                        <span className="badge" style={{ marginLeft: 6 }}>
                          {party.state_name} · IGST
                        </span>
                      ) : null}
                      {!party.is_active ? (
                        <span className="badge" style={{ marginLeft: 6 }}>
                          retired
                        </span>
                      ) : null}
                      <div className="sub">
                        {party.owner_name || "—"}
                        {party.phone ? ` · ${party.phone}` : ""}
                      </div>
                    </td>
                    <td>
                      {party.party_type === "distributor" ? (
                        <span className="badge">Sub-distributor</span>
                      ) : (
                        <span className="sub">
                          {party.outlet_type.replace(/_/g, " ")}
                        </span>
                      )}
                    </td>
                    <td className="sub">{party.route_name || "—"}</td>
                    <td className="mono sub">
                      {party.gstin || (
                        <span className="muted">unregistered</span>
                      )}
                    </td>
                    <td className="sub">
                      {party.price_mode === "inclusive" ? (
                        <span className="badge">all-in</span>
                      ) : (
                        <span className="muted">plus GST</span>
                      )}
                    </td>
                    <td className="num">
                      {party.credit_limit > 0
                        ? moneyShort(party.credit_limit)
                        : <span className="muted">cash</span>}
                      <div className="sub">{party.credit_days}d</div>
                    </td>
                    <td>
                      <div className="row-actions">
                        <Link
                          className="ghost"
                          to={`/billing?retailer=${party.id}`}
                          style={{ padding: "4px 6px" }}
                          title="Raise a bill for this party"
                        >
                          Bill
                        </Link>
                        <button
                          className="ghost"
                          onClick={() => setEditing(party)}
                        >
                          Edit
                        </button>
                        <button
                          className="ghost"
                          onClick={() => setActive(party, !party.is_active)}
                          title={
                            party.is_active
                              ? "Stop this party appearing on new bills"
                              : "Bring this party back"
                          }
                        >
                          {party.is_active ? "Retire" : "Restore"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card-note">
            {(parties || []).length} shown · {counts.retailer || 0} retailers ·{" "}
            {counts.distributor || 0} sub-distributors · {counts.unregistered}{" "}
            without a GSTIN. A party is retired rather than deleted, because
            their invoices and payments stay on the books.
          </div>
        </div>
      )}

      {editing ? (
        <PartyDialog
          party={editing === "new" ? null : editing}
          routes={routes}
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
