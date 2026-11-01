import { useState } from "react";
import { api, fmtDate } from "../api";
import { PageHead, useFlash, useLoad } from "../ui";

interface Stats { businesses: number; active: number; trialing: number; paying: number; mrr_usd: number; users: number; signups_7d: number; conversations_this_month: number }
interface OrgRow { id: string; name: string; owner_email: string; plan: string; status: string; trial_ends_at: string | null; created_at: string; conversations_this_month: number; active: boolean }

export default function Admin() {
  const [q, setQ] = useState("");
  const { data: stats } = useLoad<Stats>("/admin/stats");
  const { data: orgs, reload } = useLoad<OrgRow[]>(`/admin/orgs${q ? `?q=${encodeURIComponent(q)}` : ""}`, [q]);
  const flash = useFlash();

  async function extend(o: OrgRow) {
    const days = Number(prompt(`Extend ${o.name}'s trial by how many days?`, "14"));
    if (!days) return;
    try { await api(`/admin/orgs/${o.id}/extend-trial`, { method: "POST", body: { days } }); reload(); flash.ok("Trial extended."); } catch (e) { flash.fail(e); }
  }

  return (
    <div className="page wide">
      <PageHead eyebrow="Your SaaS at a glance" title="Platform admin" />
      {flash.node}
      {stats && (
        <div className="stat-grid">
          <div className="card stat"><b>${stats.mrr_usd.toLocaleString()}</b><span>MRR</span></div>
          <div className="card stat"><b>{stats.paying}</b><span>paying businesses</span></div>
          <div className="card stat"><b>{stats.trialing}</b><span>on trial</span></div>
          <div className="card stat"><b>{stats.signups_7d}</b><span>signups (7 days)</span></div>
          <div className="card stat"><b>{stats.businesses}</b><span>businesses total</span></div>
          <div className="card stat"><b>{stats.users}</b><span>users</span></div>
          <div className="card stat"><b>{stats.conversations_this_month.toLocaleString()}</b><span>conversations this month</span></div>
          <div className="card stat"><b>{stats.active}</b><span>active assistants</span></div>
        </div>
      )}
      <input placeholder="Search businesses" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="card table">
        <div className="task-row head-row"><span className="grow">Business</span><span>Plan</span><span>Status</span><span>Convos</span><span>Since</span><span /></div>
        {(orgs || []).map((o) => (
          <div key={o.id} className="task-row">
            <div className="grow"><div className="task-title">{o.name}</div><small className="muted">{o.owner_email}</small></div>
            <span>{o.plan}</span>
            <span className={`pill ${o.active ? "fyi" : "spam"}`}>{o.status}{o.status === "trialing" && o.trial_ends_at && ` → ${fmtDate(o.trial_ends_at)}`}</span>
            <span>{o.conversations_this_month}</span>
            <small className="muted">{fmtDate(o.created_at)}</small>
            <button className="ghost" onClick={() => extend(o)}>Extend trial</button>
          </div>
        ))}
      </div>
    </div>
  );
}
