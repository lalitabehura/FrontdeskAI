import { useState, type FormEvent } from "react";
import { api, fmtDate, type Invite, type Member } from "../api";
import { canAdmin, useAuth } from "../auth";
import { PageHead, Section, useFlash, useLoad } from "../ui";

export default function Team() {
  const { org, user, reloadOrgs } = useAuth();
  const admin = canAdmin(org);
  const { data: members, reload } = useLoad<Member[]>("/org/members", [org?.id]);
  const { data: invites, reload: reloadInvites } = useLoad<Invite[]>(admin ? "/org/invitations" : null, [org?.id]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("staff");
  const [link, setLink] = useState("");
  const flash = useFlash();

  async function invite(e: FormEvent) {
    e.preventDefault();
    try {
      const r = await api<Invite>("/org/invitations", { method: "POST", body: { email, role } });
      setEmail(""); setLink(r.invite_url || ""); reloadInvites();
      flash.ok(`Invitation emailed to ${r.email}.`);
    } catch (err) { flash.fail(err); }
  }

  async function changeRole(m: Member, r: string) {
    try { await api(`/org/members/${m.id}`, { method: "PATCH", body: { role: r } }); reload(); } catch (err) { flash.fail(err); }
  }

  async function remove(m: Member) {
    const self = m.user_id === user?.id;
    if (!confirm(self ? "Leave this business?" : `Remove ${m.email}?`)) return;
    try { await api(`/org/members/${m.id}`, { method: "DELETE" }); if (self) await reloadOrgs(); else reload(); } catch (err) { flash.fail(err); }
  }

  return (
    <div className="page">
      <PageHead eyebrow="Who can answer chats and manage bookings" title="Team" />
      {flash.node}
      {admin && (
        <Section title="Invite a team member">
          <form className="row wrap" onSubmit={invite}>
            <input type="email" className="grow" placeholder="colleague@business.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="staff">Staff — inbox, customers, bookings</option>
              <option value="admin">Admin — also settings & team</option>
            </select>
            <button className="primary">Send invite</button>
          </form>
          {link && <p className="hint">Or share this link directly (valid 7 days, works only for that email): <code className="break">{link}</code></p>}
        </Section>
      )}
      <Section title="Members">
        <div className="table">
          {(members || []).map((m) => (
            <div key={m.id} className="task-row">
              <div className="avatar-sm">{(m.full_name || m.email).charAt(0).toUpperCase()}</div>
              <div className="grow"><div className="task-title">{m.full_name || m.email}{m.user_id === user?.id && " (you)"}</div><small className="muted">{m.email} · joined {fmtDate(m.created_at)}</small></div>
              {admin && m.user_id !== user?.id ? (
                <select value={m.role} onChange={(e) => changeRole(m, e.target.value)} disabled={org?.role !== "owner" && m.role !== "staff"}>
                  <option value="staff">Staff</option><option value="admin">Admin</option>{org?.role === "owner" && <option value="owner">Owner</option>}
                </select>
              ) : <span className="pill fyi">{m.role}</span>}
              {(m.user_id === user?.id || (admin && (org?.role === "owner" || m.role === "staff"))) &&
                <button className="ghost" onClick={() => remove(m)}>{m.user_id === user?.id ? "Leave" : "Remove"}</button>}
            </div>
          ))}
        </div>
      </Section>
      {admin && invites && invites.length > 0 && (
        <Section title="Pending invitations">
          {invites.map((i) => (
            <div key={i.id} className="row between">
              <span>{i.email} · {i.role} · expires {fmtDate(i.expires_at)}</span>
              <button className="ghost" onClick={async () => { await api(`/org/invitations/${i.id}`, { method: "DELETE" }); reloadInvites(); }}>Revoke</button>
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}
