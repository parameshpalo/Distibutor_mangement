import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useApi } from "./api";
import Deliveries from "./pages/Deliveries";
import Billing from "./pages/Billing";
import Dashboard from "./pages/Dashboard";
import InvoiceDetail from "./pages/InvoiceDetail";
import Money from "./pages/Money";
import Records from "./pages/Records";
import Setup from "./pages/Setup";
import StockHome from "./pages/StockHome";

/**
 * Seven things, in the order he touches them.
 *
 * The app used to have eleven nav items, which made a small business look like
 * an ERP. The business is a loop — goods come in, go out on a van, money comes
 * back — and the sidebar is now shaped like that loop. Bills, returns and the
 * GST return share one Records page; stock and goods inward share one; the
 * two master screens share Setup.
 */
const NAV = [
  { to: "/", label: "Today", icon: "◴", end: true },
  { to: "/billing", label: "Bill", icon: "✎" },
  { to: "/deliveries", label: "Deliveries", icon: "☷" },
  { to: "/money", label: "Money", icon: "₹" },
  { to: "/stock", label: "Stock", icon: "▤" },
  { to: "/records", label: "Records", icon: "☰" },
  { to: "/setup", label: "Setup", icon: "⚙" },
];

export default function App() {
  const { data: company } = useApi("/company");

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-name">{company?.trade_name || "Distribution"}</div>
          <div className="brand-sub">
            {company ? `GSTIN ${company.gstin}` : "Loading…"}
          </div>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              <span className="nav-icon" aria-hidden="true">
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/billing" element={<Billing />} />
          <Route path="/deliveries" element={<Deliveries />} />
          <Route path="/money" element={<Money />} />
          <Route path="/stock" element={<StockHome />} />
          <Route path="/records" element={<Records />} />
          <Route path="/setup" element={<Setup />} />
          {/* An invoice keeps its own URL: it is linked from Today, from a
              van run and from a receipt, and those links have to land on the
              bill itself rather than on a tab that might be showing returns. */}
          <Route path="/invoices/:id" element={<InvoiceDetail />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
