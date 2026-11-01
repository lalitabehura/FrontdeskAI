import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, errMsg, type Org } from "../api";
import { useAuth } from "../auth";

export default function Invite() {
  const token = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
  const { user, register, login, reloadOrgs } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"register" | "login">("register");
  const [f, setF] = useState({ email: "", password: "", name: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function acceptAsCurrent() {
    setBusy(true);
    try {
      const org = await api<Org>("/invitations/accept", { method: "POST", body: { token } });
      await reloadOrgs(org.id);
      history.replaceState(null, "", "/");
      navigate("/");
    } catch (e) { setError(errMsg(e)); } finally { setBusy(false); }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      if (mode === "register") {
        await register({ email: f.email, password: f.password, full_name: f.name, invite_token: token });
        history.replaceState(null, "", "/");
        navigate("/");
      } else {
        await login(f.email, f.password);
      }
    } catch (err) {
      setError(err instanceof ApiError && err.message === "mfa_required" ? "Sign in from the login page first, then reopen this invite link." : errMsg(err));
    } finally { setBusy(false); }
  }

  if (!token) return <div className="auth-page single"><div className="card auth-card"><p className="error">This invitation link is invalid.</p></div></div>;

  return (
    <div className="auth-page single">
      <div className="card auth-card">
        <h2>Join your team</h2>
        {user ? (
          <>
            <p>Signed in as <b>{user.email}</b>. Accept the invitation with this account?</p>
            {error && <p className="error">{error}</p>}
            <button className="primary" onClick={acceptAsCurrent} disabled={busy}>Accept invitation</button>
          </>
        ) : (
          <form className="stack" onSubmit={submit}>
            {mode === "register" && <label>Your name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} maxLength={120} /></label>}
            <label>Email (the address the invite was sent to)<input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required /></label>
            <label>Password<input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required minLength={mode === "register" ? 12 : 1} maxLength={128} /></label>
            {error && <p className="error">{error}</p>}
            <button className="primary" disabled={busy}>{mode === "register" ? "Create account & join" : "Sign in"}</button>
            <button type="button" className="link" onClick={() => setMode(mode === "register" ? "login" : "register")}>
              {mode === "register" ? "I already have an account" : "Create a new account instead"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
