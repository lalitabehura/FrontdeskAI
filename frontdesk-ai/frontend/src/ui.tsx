import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, errMsg, type Assistant } from "./api";

export function Section({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card stack">
      <div className="row between"><h3>{title}</h3>{actions}</div>
      {children}
    </section>
  );
}

export function PageHead({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <header className="page-head">
      <div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div>
      {children && <div className="row wrap">{children}</div>}
    </header>
  );
}

export function useFlash() {
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const ok = (m: string) => { setMsg(m); setError(""); };
  const fail = (e: unknown) => { setError(errMsg(e)); setMsg(""); };
  const node = (
    <>
      {msg && <p className="success" onClick={() => setMsg("")}>{msg}</p>}
      {error && <p className="error" role="alert" onClick={() => setError("")}>{error}</p>}
    </>
  );
  return { ok, fail, node };
}

export function useLoad<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    if (!path) return Promise.resolve();
    return api<T>(path).then((d) => { setData(d); setError(""); }).catch((e) => setError(errMsg(e)));
  }, [path]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, [reload, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, setData, error, reload };
}

/** Load the assistant config, edit a draft, save the whole object. */
export function useAssistant() {
  const { data, setData, error, reload } = useLoad<Assistant>("/assistant");
  const [saving, setSaving] = useState(false);
  const save = async (draft: Assistant) => {
    setSaving(true);
    try {
      const { widget_key: _k, updated_at: _u, ...body } = draft;
      const saved = await api<Assistant>("/assistant", { method: "PUT", body });
      setData(saved);
      return saved;
    } finally {
      setSaving(false);
    }
  };
  return { assistant: data, setAssistant: setData, error, reload, save, saving };
}

export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="switch" aria-hidden="true" />
      <span><strong>{label}</strong>{hint && <small className="muted block">{hint}</small>}</span>
    </label>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}
