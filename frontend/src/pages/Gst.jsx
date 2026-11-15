import { useState } from "react";
import { Link } from "react-router-dom";
import { api, date, money, moneyShort, num, useApi } from "../api";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const CSV_SECTIONS = [
  ["b2b", "B2B"],
  ["b2cl", "B2CL"],
  ["b2cs", "B2CS"],
  ["cdnr", "CDNR"],
  ["hsn", "HSN"],
  ["docs", "Docs"],
];

export default function Gst() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">GST filing</h1>
          <div className="page-sub">
            GSTR-1, built from the invoices and credit notes themselves so it
            always agrees with the books. E-way bills are raised on the
            government portal, not here.
          </div>
        </div>
      </div>

      <div className="toolbar">
        <select
          value={month}
          onChange={(e) => setMonth(Number(e.target.value))}
          style={{ width: 150 }}
        >
          {MONTHS.map((label, index) => (
            <option key={label} value={index + 1}>
              {label}
            </option>
          ))}
        </select>
        <select
          value={year}
          onChange={(e) => setYear(Number(e.target.value))}
          style={{ width: 110 }}
        >
          {[year - 1, year, year + 1].map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </div>

      <Gstr1 year={year} month={month} />
    </>
  );
}

/* --- GSTR-1 ------------------------------------------------------------ */

function Gstr1({ year, month }) {
  const { data, error, loading } = useApi(
    `/gst/gstr1?year=${year}&month=${month}`,
  );

  if (loading) return <div className="loading">Building the return…</div>;
  if (error) return <div className="notice error">{error.message}</div>;

  const base = `/api/gst/gstr1`;
  const period = `year=${year}&month=${month}`;
  const blocked = data.checks.filter((c) => !c.ok);

  return (
    <>
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="stat-label">Net taxable</div>
          <div className="stat-value">{moneyShort(data.totals.taxable)}</div>
          <div className="stat-foot">
            {data.totals.invoices} invoices, {data.totals.credit_notes} credit
            notes
          </div>
        </div>
        <div className="card">
          <div className="stat-label">CGST + SGST</div>
          <div className="stat-value">
            {moneyShort(data.totals.cgst + data.totals.sgst)}
          </div>
          <div className="stat-foot">Intrastate supplies</div>
        </div>
        <div className="card">
          <div className="stat-label">IGST</div>
          <div className="stat-value">{moneyShort(data.totals.igst)}</div>
          <div className="stat-foot">Interstate supplies</div>
        </div>
        <div className="card">
          <div className="stat-label">GSTR-1 due</div>
          <div className="stat-value sm" style={{ marginTop: 10 }}>
            {date(data.due_dates.gstr1)}
          </div>
          <div className="stat-foot">
            GSTR-3B by {date(data.due_dates.gstr3b)}
          </div>
        </div>
      </div>

      <div className="grid g2" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="card-title">
            Sections · {data.period_label} · period code {data.period}
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Section</th>
                  <th>Table</th>
                  <th className="num">Parties</th>
                  <th className="num">Docs</th>
                  <th className="num">Taxable</th>
                </tr>
              </thead>
              <tbody>
                {data.sections.map((section) => (
                  <tr key={section.code}>
                    <td>
                      <div style={{ fontWeight: 550 }}>{section.code}</div>
                      <div className="sub">{section.label}</div>
                    </td>
                    <td className="mono sub">{section.table}</td>
                    <td className="num">
                      {section.counterparties || <span className="muted">—</span>}
                    </td>
                    <td className="num">{section.documents}</td>
                    <td className="num">
                      <span
                        style={{
                          color:
                            section.taxable < 0 ? "var(--critical)" : "inherit",
                        }}
                      >
                        {money(section.taxable)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card-note">
            B2C credit notes are netted off inside B2CS rather than reported
            separately — CDNUR is only for B2CL and exports.
          </div>
        </div>

        <div className="card">
          <div className="card-title">Before you file</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {data.checks.map((check) => (
              <div
                key={check.label}
                style={{ display: "flex", gap: 10, alignItems: "flex-start" }}
              >
                <span
                  className={`badge ${check.ok ? "good" : "critical"}`}
                  style={{ minWidth: 54, justifyContent: "center" }}
                >
                  {check.ok ? "✓ ok" : "✕ check"}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 550 }}>{check.label}</div>
                  <div className="sub">{check.detail}</div>
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              marginTop: 14,
              paddingTop: 12,
              borderTop: "1px solid var(--border)",
            }}
          >
            <div className="card-title">Download</div>
            <div className="row">
              <a href={`${base}/json?${period}&download=true`}>
                <button className="primary">Offline tool JSON</button>
              </a>
              {CSV_SECTIONS.map(([key, label]) => (
                <a key={key} href={`${base}/csv?${period}&section=${key}`}>
                  <button>{label}</button>
                </a>
              ))}
            </div>
            <div className="card-note">
              The JSON loads into the GST offline utility. CSVs match its
              sheets, for checking by eye first.
            </div>
          </div>
        </div>
      </div>

      {blocked.length ? (
        <div className="notice error">
          {blocked.length} check{blocked.length === 1 ? "" : "s"} did not pass.
          Clear them before filing — the portal will not tell you what the
          books say.
        </div>
      ) : (
        <div className="notice ok">
          Everything reconciles. The return matches the books to the rupee.
        </div>
      )}
    </>
  );
}
