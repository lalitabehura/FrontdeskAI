import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, refreshSession, setAccessToken, setOrgId, setSessionLostHandler, storedOrgId, type Org, type TokenOut, type User } from "./api";

interface AuthState {
  user: User | null;
  orgs: Org[];
  org: Org | null;
  loading: boolean;
  login: (email: string, password: string, extra?: { mfa_code?: string; recovery_code?: string }) => Promise<void>;
  register: (data: { email: string; password: string; full_name: string; business_name?: string; invite_token?: string }) => Promise<void>;
  logout: () => Promise<void>;
  setUser: (u: User) => void;
  switchOrg: (id: string) => void;
  reloadOrgs: (selectId?: string) => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [org, setOrg] = useState<Org | null>(null);
  const [loading, setLoading] = useState(true);

  const reloadOrgs = useCallback(async (selectId?: string) => {
    const list = await api<Org[]>("/orgs");
    setOrgs(list);
    const wanted = selectId || storedOrgId();
    const chosen = list.find((o) => o.id === wanted) || list[0] || null;
    setOrgId(chosen?.id ?? null);
    setOrg(chosen);
  }, []);

  const accept = useCallback(async (d: TokenOut) => {
    setAccessToken(d.access_token);
    await reloadOrgs();
    setUser(d.user);
  }, [reloadOrgs]);

  useEffect(() => {
    setSessionLostHandler(() => { setUser(null); setOrg(null); });
    refreshSession()
      .then(async (d) => { if (d) await accept(d); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [accept]);

  const login = useCallback<AuthState["login"]>(async (email, password, extra = {}) => {
    await accept(await api<TokenOut>("/auth/login", { method: "POST", body: { email, password, ...extra }, retry: false }));
  }, [accept]);

  const register = useCallback<AuthState["register"]>(async (data) => {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    await accept(await api<TokenOut>("/auth/register", { method: "POST", body: { ...data, timezone } }));
  }, [accept]);

  const logout = useCallback(async () => {
    try { await api("/auth/logout", { method: "POST", retry: false }); } finally {
      setAccessToken(null); setUser(null); setOrg(null); setOrgs([]);
    }
  }, []);

  const switchOrg = useCallback((id: string) => {
    const o = orgs.find((x) => x.id === id);
    if (o) { setOrgId(o.id); setOrg(o); }
  }, [orgs]);

  return <Ctx.Provider value={{ user, orgs, org, loading, login, register, logout, setUser, switchOrg, reloadOrgs }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}

export const canAdmin = (org: Org | null) => org?.role === "owner" || org?.role === "admin";
