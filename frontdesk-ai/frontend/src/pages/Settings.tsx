import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState, type FormEvent } from "react";
import { api, fmtDateTime, type Org, type Session, type User } from "../api";
import { canAdmin, useAuth } from "../auth";
import { PageHead, Section, useFlash, useLoad } from "../ui";

const INDUSTRIES = ["", "Salon & beauty", "Spa & wellness", "Fitness & gym", "Dental", "Medical clinic", "Physiotherapy",
  "Restaurant & café", "Real estate", "Legal", "Accounting", "Home services", "Education & tutoring", "Pet care", "Automotive", "Other"];

export default function Settings() {
  const { user, org, setUser, logout, reloadOrgs } = useAuth();
  const flash = useFlash();
  const [biz, setBiz] = useState({ name: "", industry: "", timezone: "" });
  const [name, setName] = useState(user?.full_name || "");
  const [pw, setPw] = useState({ current: "", next: "" });
  const [mfa, setMfa] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [mfaCode, setMfaCode] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [disable, setDisable] = useState({ password: "", code: "" });
  const [delOrg, setDelOrg] = useState({ password: "", confirm_name: "" });
  const [delAcct, setDelAcct] = useState({ password: "", confirm: "" });
  const { data: sessions, reload: reloadSessions } = useLoad<Session[]>("/auth/sessions");
  const admin = canAdmin(org);

  useEffect(() => { if (org) setBiz({ name: org.name, industry: org.industry, timezone: org.timezone }); }, [org]);
  if (!user || !org) return null;

  const call = (fn: () => Promise<unknown>, ok: string) => fn().then(() => flash.ok(ok)).catch(flash.fail);
  const zones = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone") || [org.timezone];

  async function saveBiz(e: FormEvent) {
    e.preventDefault();
    await call(async () => { await api<Org>("/org", { method: "PATCH", body: biz }); await reloadOrgs(org!.id); }, "Business details saved.");
  }

  return (
    <div className="page narrow">
      <PageHead eyebrow="Business, account & security" title="Settings" />
      {flash.node}

      <form onSubmit={saveBiz}>
        <Section title="Business">
          <fieldset disabled={!admin} className="stack">
            <label>Business name<input value={biz.name} onChange={(e) => setBiz({ ...biz, name: e.target.value })} maxLength={120} required /></label>
            <div className="row wrap">
              <label className="grow">Industry<select value={biz.industry} onChange={(e) => setBiz({ ...biz, industry: e.target.value })}>{INDUSTRIES.map((i) => <option key={i} value={i}>{i || "Choose…"}</option>)}</select></label>
              <label className="grow">Time zone<select value={biz.timezone} onChange={(e) => setBiz({ ...biz, timezone: e.target.value })}>{zones.map((z) => <option key={z}>{z}</option>)}</select></label>
            </div>
            {admin && <div><button className="primary">Save business</button></div>}
          </fieldset>
        </Section>
      </form>

      <Section title="Your profile">
        <div className="row">
          <input className="grow" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="Your name" />
          <button onClick={() => call(async () => setUser(await api<User>("/auth/me", { method: "PATCH", body: { full_name: name } })), "Profile saved.")}>Save</button>
        </div>
      </Section>

      <Section title="Password">
        <div className="row wrap">
          <input type="password" placeholder="Current password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
          <input type="password" placeholder="New password (12+ chars)" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
          <button onClick={() => api("/auth/password/change", { method: "POST", body: { current_password: pw.current, new_password: pw.next } })
            .then(() => { alert("Password changed. Please sign in again."); logout(); }).catch(flash.fail)}>Change password</button>
        </div>
      </Section>

      <Section title="Two-factor authentication">
        {user.mfa_enabled ? (
          <>
            <p className="success">✓ Enabled</p>
            <div className="row wrap">
              <input type="password" placeholder="Password" value={disable.password} onChange={(e) => setDisable({ ...disable, password: e.target.value })} />
              <input placeholder="6-digit code" maxLength={6} value={disable.code} onChange={(e) => setDisable({ ...disable, code: e.target.value })} />
              <button className="ghost" onClick={() => call(async () => { await api("/auth/mfa/disable", { method: "POST", body: disable }); setUser({ ...user, mfa_enabled: false }); }, "Two-factor disabled.")}>Disable</button>
            </div>
          </>
        ) : mfa ? (
          <>
            <p>Scan with an authenticator app (Google Authenticator, 1Password, Authy), then enter the code.</p>
            <div className="qr"><QRCodeSVG value={mfa.otpauth_uri} size={168} /></div>
            <small className="muted">Or enter manually: <code>{mfa.secret}</code></small>
            <div className="row">
              <input placeholder="123456" value={mfaCode} maxLength={6} inputMode="numeric" onChange={(e) => setMfaCode(e.target.value)} />
              <button className="primary" onClick={() => api<{ recovery_codes: string[] }>("/auth/mfa/enable", { method: "POST", body: { code: mfaCode } })
                .then((r) => { setRecovery(r.recovery_codes); setMfa(null); setUser({ ...user, mfa_enabled: true }); }).catch(flash.fail)}>Verify & enable</button>
            </div>
          </>
        ) : (
          <div><button className="primary" onClick={() => api<{ secret: string; otpauth_uri: string }>("/auth/mfa/setup", { method: "POST" }).then(setMfa).catch(flash.fail)}>Set up authenticator app</button></div>
        )}
        {recovery && (
          <div className="recovery">
            <strong>Save these recovery codes now — they won't be shown again.</strong>
            <pre>{recovery.join("\n")}</pre>
            <button onClick={() => setRecovery(null)}>I've saved them</button>
          </div>
        )}
      </Section>

      <Section title="Active sessions">
        {(sessions || []).map((s) => (
          <div key={s.id} className="row between">
            <div><strong>{s.current ? "This device" : s.user_agent.slice(0, 60) || "Unknown device"}</strong>
              <small className="muted block">{s.ip} · signed in {fmtDateTime(s.created_at)}</small></div>
            {!s.current && <button className="ghost" onClick={() => call(async () => { await api(`/auth/sessions/${s.id}`, { method: "DELETE" }); reloadSessions(); }, "Session revoked.")}>Revoke</button>}
          </div>
        ))}
        <div><button className="ghost" onClick={() => api("/auth/logout-all", { method: "POST" }).then(logout).catch(flash.fail)}>Sign out everywhere</button></div>
      </Section>

      {org.role === "owner" && (
        <Section title="Delete this business">
          <div className="danger stack">
            <small>Permanently deletes {org.name}'s assistant, conversations, customers and bookings, and cancels its subscription.</small>
            <div className="row wrap">
              <input type="password" placeholder="Your password" value={delOrg.password} onChange={(e) => setDelOrg({ ...delOrg, password: e.target.value })} />
              <input placeholder={`Type "${org.name}"`} value={delOrg.confirm_name} onChange={(e) => setDelOrg({ ...delOrg, confirm_name: e.target.value })} />
              <button className="danger-btn" disabled={delOrg.confirm_name !== org.name}
                onClick={() => api("/org", { method: "DELETE", body: delOrg }).then(() => reloadOrgs()).catch(flash.fail)}>Delete business</button>
            </div>
          </div>
        </Section>
      )}

      <Section title="Delete my account">
        <div className="danger stack">
          <small>Deletes your login. Businesses where you're the only member are deleted too; transfer ownership of shared businesses first.</small>
          <div className="row wrap">
            <input type="password" placeholder="Password" value={delAcct.password} onChange={(e) => setDelAcct({ ...delAcct, password: e.target.value })} />
            <input placeholder='Type "DELETE"' value={delAcct.confirm} onChange={(e) => setDelAcct({ ...delAcct, confirm: e.target.value })} />
            <button className="danger-btn" disabled={delAcct.confirm !== "DELETE"} onClick={() => api("/account", { method: "DELETE", body: delAcct }).then(logout).catch(flash.fail)}>Delete forever</button>
          </div>
        </div>
      </Section>
    </div>
  );
}
