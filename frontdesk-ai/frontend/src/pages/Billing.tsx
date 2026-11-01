import { useEffect } from "react";
import { api, fmtDate, type Usage } from "../api";
import { useAuth } from "../auth";
import { PageHead, Section, useFlash, useLoad } from "../ui";

interface Plan { key: string; name: string; price: number; conversations: number; members: number; features: string[] }
interface BillingInfo {
  enabled: boolean; plan: string; status: string; trial_ends_at: string | null; current_period_end: string | null;
  has_subscription: boolean; usage: Usage; plans: Plan[];
}

export default function Billing() {
  const { org, reloadOrgs } = useAuth();
  const { data, reload } = useLoad<BillingInfo>("/billing", [org?.id]);
  const flash = useFlash();
  const owner = org?.role === "owner";

  useEffect(() => {
    const s = new URLSearchParams(location.search).get("checkout");
    if (s === "success") { flash.ok("Thanks! Your subscription is being activated — this can take a few seconds."); setTimeout(() => { reload(); reloadOrgs(org?.id); }, 3000); }
    if (s === "cancelled") flash.fail(new Error("Checkout cancelled — no charge was made."));
    if (s) history.replaceState(null, "", "/billing");
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function go(path: string, body?: unknown) {
    try {
      const { url } = await api<{ url: string }>(path, { method: "POST", body });
      if (!/^https:\/\/(checkout|billing)\.stripe\.com\//.test(url)) throw new Error("Unexpected payment URL");
      window.location.assign(url);
    } catch (err) { flash.fail(err); }
  }

  if (!data) return <p className="muted">Loading…</p>;
  const trialing = data.status === "trialing" && !data.has_subscription;

  return (
    <div className="page">
      <PageHead eyebrow="Plans & usage" title="Billing">
        {data.has_subscription && owner && <button onClick={() => go("/billing/portal")}>Manage billing & invoices</button>}
      </PageHead>
      {flash.node}
      <Section title="Current plan">
        <p className="big-num">{data.plans.find((p) => p.key === data.plan)?.name} <span className="pill fyi">{data.status.replace("_", " ")}</span></p>
        {trialing && data.trial_ends_at && <p>Free trial ends {fmtDate(data.trial_ends_at)}. Choose a plan to keep your assistant running.</p>}
        {data.current_period_end && <p className="muted">Renews {fmtDate(data.current_period_end)}</p>}
        <p className="muted">This month: {data.usage.conversations} / {data.usage.conversation_limit} conversations · {data.usage.ai_replies} AI replies</p>
        {!data.enabled && <p className="hint">Payments aren't configured on this server yet (set STRIPE_* in .env).</p>}
        {!owner && <p className="hint">Only the business owner can change the plan.</p>}
      </Section>
      <div className="plans">
        {data.plans.map((p) => {
          const current = p.key === data.plan && data.has_subscription;
          return (
            <div key={p.key} className={`card plan ${p.key === "growth" ? "featured" : ""}`}>
              {p.key === "growth" && <span className="pill action">Most popular</span>}
              <h3>{p.name}</h3>
              <p className="price">${p.price}<span>/month</span></p>
              <ul>
                <li>{p.conversations.toLocaleString()} conversations / month</li>
                <li>{p.members} team members</li>
                {p.features.map((f) => <li key={f}>{f}</li>)}
              </ul>
              {current ? <button disabled>Current plan</button>
                : data.has_subscription ? <button disabled={!owner} onClick={() => go("/billing/portal")}>Switch in billing portal</button>
                : <button className="primary" disabled={!owner || !data.enabled} onClick={() => go("/billing/checkout", { plan: p.key })}>Choose {p.name}</button>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
