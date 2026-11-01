import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { api, errMsg, type Org } from "./api";
import { canAdmin, useAuth } from "./auth";
import Admin from "./pages/Admin";
import Appointments from "./pages/Appointments";
import AssistantPage from "./pages/Assistant";
import Automations from "./pages/Automations";
import Billing from "./pages/Billing";
import Contacts from "./pages/Contacts";
import Home from "./pages/Home";
import Inbox from "./pages/Inbox";
import Install from "./pages/Install";
import Invite from "./pages/Invite";
import Login from "./pages/Login";
import ResetPassword from "./pages/ResetPassword";
import Settings from "./pages/Settings";
import Team from "./pages/Team";

function TrialBanner({ org }: { org: Org }) {
  const trialLeft = org.trial_ends_at ? Math.ceil((new Date(org.trial_ends_at).getTime() - Date.now()) / 86400000) : 0;
  const inactive = (org.subscription_status === "trialing" && trialLeft <= 0) || ["canceled", "unpaid", "incomplete_expired"].includes(org.subscription_status);
  if (inactive) return <div className="banner danger-banner">Your assistant is paused. <Link to="/billing">Choose a plan</Link> to turn it back on.</div>;
  if (org.subscription_status === "past_due") return <div className="banner">Payment failed — <Link to="/billing">update your card</Link> to avoid interruption.</div>;
  if (org.subscription_status === "trialing" && trialLeft <= 7) return <div className="banner">{trialLeft} day(s) left in your free trial. <Link to="/billing">Pick a plan</Link></div>;
  return null;
}

function OrgSwitcher() {
  const { orgs, org, switchOrg, reloadOrgs } = useAuth();
  const navigate = useNavigate();
  async function create() {
    const name = prompt("Name of the new business:")?.trim();
    if (!name) return;
    try {
      const o = await api<Org>("/orgs", { method: "POST", body: { name, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC" } });
      await reloadOrgs(o.id);
      navigate("/");
    } catch (e) { alert(errMsg(e)); }
  }
  return (
    <div className="org-switch">
      <select value={org?.id} onChange={(e) => { if (e.target.value === "__new") create(); else { switchOrg(e.target.value); navigate("/"); } }} aria-label="Business">
        {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        <option value="__new">+ Add another business</option>
      </select>
    </div>
  );
}

function Shell() {
  const { user, org, logout } = useAuth();
  const [attention, setAttention] = useState(0);

  useEffect(() => {
    if (!org) return;
    const load = () => api<unknown[]>("/conversations?status=attention&limit=99").then((a) => setAttention(a.length)).catch(() => {});
    load();
    const id = setInterval(load, 20000);
    window.addEventListener("fd:inbox-changed", load);
    return () => { clearInterval(id); window.removeEventListener("fd:inbox-changed", load); };
  }, [org]);

  if (!org) return <div className="center-screen">No business found. <button onClick={logout}>Sign out</button></div>;
  const admin = canAdmin(org);
  const nav: [string, string, boolean][] = [
    ["/", "Home", true], ["/inbox", "Inbox", true], ["/appointments", "Appointments", true], ["/contacts", "Customers", true],
    ["/assistant", "Assistant", true], ["/install", "Add to website", true], ["/automations", "Automations", admin],
    ["/team", "Team", true], ["/billing", "Billing", true], ["/settings", "Settings", true],
  ];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">✦</span>
          <div><strong>Frontdesk AI</strong><small>{user?.email}</small></div>
        </div>
        <OrgSwitcher />
        <nav>
          {nav.filter(([, , show]) => show).map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              {label}
              {to === "/inbox" && attention > 0 && <span className="badge">{attention}</span>}
            </NavLink>
          ))}
          {user?.is_platform_admin && <NavLink to="/admin" className={({ isActive }) => (isActive ? "active" : "")}>Platform admin</NavLink>}
        </nav>
        <button className="ghost signout" onClick={logout}>Sign out</button>
      </aside>
      <main className="content">
        <TrialBanner org={org} />
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/appointments" element={<Appointments />} />
          <Route path="/contacts" element={<Contacts />} />
          <Route path="/assistant" element={<AssistantPage />} />
          <Route path="/install" element={<Install />} />
          <Route path="/automations" element={<Automations />} />
          <Route path="/team" element={<Team />} />
          <Route path="/billing" element={<Billing />} />
          <Route path="/settings" element={<Settings />} />
          {user?.is_platform_admin && <Route path="/admin" element={<Admin />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="center-screen">Loading…</div>;
  return (
    <Routes>
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/invite" element={<Invite />} />
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route path="/*" element={user ? <Shell /> : <Navigate to="/login" replace />} />
    </Routes>
  );
}
