import { Link } from "react-router-dom";
import { fmtDateTime, type Appointment, type Usage } from "../api";
import { useAuth } from "../auth";
import { PageHead, useLoad } from "../ui";

interface Dash {
  conversations_7d: number; leads_7d: number; bookings_7d: number; needs_attention: number;
  upcoming: Appointment[]; usage: Usage; knowledge_items: number; onboarded: boolean;
}

export default function Home() {
  const { org } = useAuth();
  const { data, error } = useLoad<Dash>("/dashboard", [org?.id]);
  const { data: install } = useLoad<{ allowed_domains: string[] }>("/assistant/install", [org?.id]);

  if (error) return <p className="error">{error}</p>;
  if (!data || !org) return <p className="muted">Loading…</p>;

  const steps = [
    { done: true, label: "Create your account", to: "/" },
    { done: data.knowledge_items > 0, label: "Teach your assistant: services, hours & FAQs", to: "/assistant" },
    { done: !!install && install.allowed_domains.length > 0, label: "Add the chat to your website", to: "/install" },
    { done: data.conversations_7d > 0, label: "Get your first conversation", to: "/install" },
  ];
  const remaining = steps.filter((s) => !s.done).length;
  const pct = Math.min(100, Math.round((data.usage.conversations / data.usage.conversation_limit) * 100));

  return (
    <div className="page">
      <PageHead eyebrow={org.name} title="Home" />

      {remaining > 0 && (
        <section className="card checklist">
          <h3>Get set up — {steps.length - remaining}/{steps.length} done</h3>
          <ol>
            {steps.map((s) => (
              <li key={s.label} className={s.done ? "done" : ""}>
                <span className="tick">{s.done ? "✓" : ""}</span>
                {s.done ? s.label : <Link to={s.to}>{s.label} →</Link>}
              </li>
            ))}
          </ol>
        </section>
      )}

      <div className="stat-grid">
        <Link to="/inbox" className="card stat"><b>{data.conversations_7d}</b><span>conversations (7 days)</span></Link>
        <Link to="/contacts" className="card stat"><b>{data.leads_7d}</b><span>new customers (7 days)</span></Link>
        <Link to="/appointments" className="card stat"><b>{data.bookings_7d}</b><span>bookings (7 days)</span></Link>
        <Link to="/inbox" className={`card stat ${data.needs_attention ? "alert" : ""}`}><b>{data.needs_attention}</b><span>need your attention</span></Link>
      </div>

      <div className="grid-2">
        <section className="card">
          <h3>Upcoming appointments <Link to="/appointments" className="more">All →</Link></h3>
          {data.upcoming.length === 0 && <p className="muted">No upcoming appointments yet.</p>}
          <ul className="list">
            {data.upcoming.map((a) => (
              <li key={a.id}>
                <span className="time">{fmtDateTime(a.start, org.timezone)}</span>
                <div><div>{a.service_name}</div><small className="muted">{a.contact_name} · {a.contact_email || a.contact_phone}</small></div>
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h3>This month's usage <Link to="/billing" className="more">Plan →</Link></h3>
          <p className="big-num">{data.usage.conversations} <span className="muted">/ {data.usage.conversation_limit} conversations</span></p>
          <div className="meter"><div className={`meter-fill ${pct > 85 ? "warn" : ""}`} style={{ width: `${pct}%` }} /></div>
          <p className="muted">{data.usage.ai_replies} AI replies sent. {data.usage.active ? "Assistant is live." : "Assistant is paused — choose a plan to reactivate."}</p>
        </section>
      </div>
    </div>
  );
}
