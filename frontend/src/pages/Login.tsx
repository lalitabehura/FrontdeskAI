import { useState, type FormEvent } from "react";
import { api, ApiError, errMsg } from "../api";
import { useAuth } from "../auth";

type Mode = "login" | "register" | "mfa" | "forgot";

export default function Login() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>(new URLSearchParams(location.search).get("signup") ? "register" : "login");
  const [f, setF] = useState({ email: "", password: "", name: "", business: "", code: "" });
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(""); setInfo(""); setBusy(true);
    try {
      if (mode === "register") await register({ email: f.email, password: f.password, full_name: f.name, business_name: f.business });
      else if (mode === "forgot") {
        await api("/auth/password/forgot", { method: "POST", body: { email: f.email } });
        setInfo("If that account exists, a reset link is on its way.");
      } else if (mode === "mfa") await login(f.email, f.password, useRecovery ? { recovery_code: f.code } : { mfa_code: f.code });
      else await login(f.email, f.password);
    } catch (err) {
      if (err instanceof ApiError && err.message === "mfa_required") setMode("mfa");
      else setError(errMsg(err));
    } finally {
      setBusy(false);
    }
  }

  const title = { login: "Welcome back", register: "Start your 14-day free trial", mfa: "Two-step verification", forgot: "Reset password" }[mode];
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  return (
    <div className="auth-page">
      <div className="auth-hero">
        <span className="brand-mark big">✦</span>
        <h1>An AI front desk for your business.</h1>
        <p>Answers customer questions 24/7, books appointments, captures every lead, and sends reminders and birthday wishes — set up in 10 minutes, no code.</p>
        <ul className="hero-points">
          <li>✓ One line to add to any website</li>
          <li>✓ Learns your services, prices, hours and FAQs</li>
          <li>✓ Hand over to your team any time</li>
        </ul>
      </div>
      <form className="card auth-card" onSubmit={submit}>
        <h2>{title}</h2>
        {mode === "mfa" ? (
          <>
            <label>{useRecovery ? "Recovery code" : "6-digit code from your authenticator"}
              <input autoFocus value={f.code} onChange={set("code")} inputMode={useRecovery ? "text" : "numeric"} autoComplete="one-time-code" maxLength={useRecovery ? 32 : 6} required />
            </label>
            <button type="button" className="link" onClick={() => setUseRecovery(!useRecovery)}>{useRecovery ? "Use authenticator code" : "Use a recovery code"}</button>
          </>
        ) : (
          <>
            {mode === "register" && (
              <>
                <label>Business name<input value={f.business} onChange={set("business")} maxLength={120} required autoComplete="organization" /></label>
                <label>Your name<input value={f.name} onChange={set("name")} maxLength={120} autoComplete="name" /></label>
              </>
            )}
            <label>Email<input type="email" value={f.email} onChange={set("email")} required autoComplete="email" /></label>
            {mode !== "forgot" && (
              <label>Password
                <input type="password" value={f.password} onChange={set("password")} required minLength={mode === "register" ? 12 : 1} maxLength={128}
                  autoComplete={mode === "register" ? "new-password" : "current-password"} />
              </label>
            )}
            {mode === "register" && <p className="hint">At least 12 characters. No credit card needed for the trial.</p>}
          </>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        {info && <p className="success">{info}</p>}
        <button className="primary" disabled={busy}>
          {busy ? "Please wait…" : mode === "register" ? "Create my assistant" : mode === "forgot" ? "Send reset link" : "Sign in"}
        </button>
        <div className="auth-links">
          {mode === "login" && (
            <>
              <button type="button" className="link" onClick={() => setMode("register")}>Create an account</button>
              <button type="button" className="link" onClick={() => setMode("forgot")}>Forgot password?</button>
            </>
          )}
          {mode !== "login" && <button type="button" className="link" onClick={() => { setMode("login"); setF({ ...f, code: "" }); }}>Back to sign in</button>}
        </div>
      </form>
    </div>
  );
}
