// API client. Access token lives only in memory; the refresh token is an HttpOnly SameSite=Strict cookie.
// The selected business (tenant) is sent as X-Org-Id; the server always re-checks membership.
const BASE = "/api/v1";
let accessToken: string | null = null;
let orgId: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSessionLost: (() => void) | null = null;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const setAccessToken = (t: string | null) => { accessToken = t; };
export const setOrgId = (id: string | null) => {
  orgId = id;
  try { if (id) localStorage.setItem("fd:org", id); else localStorage.removeItem("fd:org"); } catch { /* ignore */ }
};
export const storedOrgId = () => { try { return localStorage.getItem("fd:org"); } catch { return null; } };
export const setSessionLostHandler = (fn: () => void) => { onSessionLost = fn; };

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");
  }
  return fallback;
}

export async function refreshSession(): Promise<TokenOut | null> {
  const res = await fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } });
  if (!res.ok) return null;
  const data = (await res.json()) as TokenOut;
  accessToken = data.access_token;
  return data;
}

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) refreshing = refreshSession().then((d) => !!d).finally(() => (refreshing = null));
  return refreshing;
}

type Opts = { method?: string; body?: unknown; retry?: boolean; raw?: boolean; form?: FormData };

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  const { method = "GET", body, retry = true, form } = opts;
  const headers: Record<string, string> = { "X-Requested-With": "XMLHttpRequest" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (orgId) headers["X-Org-Id"] = orgId;
  const res = await fetch(`${BASE}${path}`, {
    method, headers, credentials: "same-origin",
    body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
  });
  if (res.status === 401 && retry && !path.startsWith("/auth/login")) {
    if (await tryRefresh()) return api<T>(path, { ...opts, retry: false });
    accessToken = null;
    onSessionLost?.();
  }
  if (opts.raw) {
    if (!res.ok) throw new ApiError(res.status, `Request failed (${res.status})`);
    return (await res.blob()) as T;
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, errorMessage(data, `Request failed (${res.status})`));
  return data as T;
}

export function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ------------------------------------------------------------------ types
export interface User { id: string; email: string; full_name: string; mfa_enabled: boolean; is_platform_admin: boolean; created_at: string }
export interface TokenOut { access_token: string; expires_in: number; user: User }
export interface Org {
  id: string; name: string; industry: string; timezone: string; plan: string; subscription_status: string;
  trial_ends_at: string | null; current_period_end: string | null; onboarded: boolean; created_at: string; role: "owner" | "admin" | "staff";
}
export type Hours = Record<string, string[][]>;
export interface Assistant {
  widget_key: string; enabled: boolean; assistant_name: string; greeting: string; tone: string; language: string;
  brand_color: string; position: "right" | "left"; business_description: string; extra_instructions: string;
  contact_email: string; contact_phone: string; address: string; website: string; hours: Hours;
  booking_enabled: boolean; slot_interval_minutes: number; min_notice_minutes: number; booking_horizon_days: number;
  capacity_per_slot: number; require_phone: boolean; allowed_domains: string[]; notify_email: string; handoff_message: string;
  reminders_enabled: boolean; reminder_hours_before: number; birthday_enabled: boolean; birthday_subject: string;
  birthday_message: string; birthday_offer: string; updated_at: string;
}
export interface Service { id: string; name: string; description: string; duration_minutes: number; price_text: string; bookable: boolean; active: boolean; sort_order: number }
export interface Knowledge { id: string; question: string; answer: string; created_at: string }
export interface Contact {
  id: string; name: string; email: string; phone: string; birthday: string | null; notes: string; tags: string[];
  source: string; marketing_consent: boolean; unsubscribed_at: string | null; created_at: string; last_seen_at: string;
}
export interface ConversationItem {
  id: string; contact_id: string | null; status: "ai" | "human" | "closed"; needs_attention: boolean; page_url: string;
  message_count: number; created_at: string; last_message_at: string; contact_name: string; contact_email: string; preview: string;
}
export interface Message { id: number; role: "visitor" | "assistant" | "staff" | "system"; content: string; created_at: string }
export interface ConversationDetail extends ConversationItem { messages: Message[]; contact: Contact | null }
export interface Appointment {
  id: string; contact_id: string | null; service_id: string | null; start: string; end: string; status: string; notes: string;
  created_via: string; contact_name: string; contact_email: string; contact_phone: string; service_name: string;
}
export interface Member { id: string; user_id: string; email: string; full_name: string; role: string; created_at: string }
export interface Invite { id: string; email: string; role: string; expires_at: string; created_at: string; invite_url?: string }
export interface Usage { period: string; conversations: number; ai_replies: number; conversation_limit: number; active: boolean }
export interface Session { id: string; created_at: string; user_agent: string; ip: string; current: boolean }

// ------------------------------------------------------------------ helpers
export const fmtTime = (iso: string, tz?: string) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: tz });
export const fmtDate = (iso: string, tz?: string) => new Date(iso).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", timeZone: tz });
export const fmtDateTime = (iso: string, tz?: string) => `${fmtDate(iso, tz)}, ${fmtTime(iso, tz)}`;
export const ago = (iso: string) => {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};
export const errMsg = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");
