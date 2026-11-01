import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { ago, api, fmtDateTime, type ConversationDetail, type ConversationItem } from "../api";
import { canAdmin, useAuth } from "../auth";
import { Empty, PageHead, useFlash } from "../ui";

const FILTERS = [["attention", "Needs attention"], ["", "All"], ["leads", "Leads"], ["human", "With team"], ["closed", "Closed"]] as const;
const changed = () => window.dispatchEvent(new Event("fd:inbox-changed"));

export default function Inbox() {
  const { org } = useAuth();
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<string>("");
  const [items, setItems] = useState<ConversationItem[]>([]);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [reply, setReply] = useState("");
  const flash = useFlash();
  const endRef = useRef<HTMLDivElement>(null);
  const selected = params.get("c");

  const loadList = () => api<ConversationItem[]>(`/conversations${filter ? `?status=${filter}` : ""}`).then(setItems).catch(flash.fail);
  const loadDetail = (id: string) => api<ConversationDetail>(`/conversations/${id}`).then(setDetail).catch(flash.fail);

  useEffect(() => { loadList(); const t = setInterval(loadList, 15000); return () => clearInterval(t); }, [filter, org?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    loadDetail(selected);
    const t = setInterval(() => loadDetail(selected), 5000);
    return () => clearInterval(t);
  }, [selected]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [detail?.messages.length]);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!detail || !reply.trim()) return;
    try {
      await api(`/conversations/${detail.id}/reply`, { method: "POST", body: { content: reply } });
      setReply(""); loadDetail(detail.id); loadList(); changed();
    } catch (err) { flash.fail(err); }
  }

  async function update(body: Record<string, unknown>, note: string) {
    if (!detail) return;
    try {
      await api(`/conversations/${detail.id}`, { method: "PATCH", body });
      flash.ok(note); loadDetail(detail.id); loadList(); changed();
    } catch (err) { flash.fail(err); }
  }

  async function remove() {
    if (!detail || !confirm("Delete this conversation permanently?")) return;
    await api(`/conversations/${detail.id}`, { method: "DELETE" }).catch(flash.fail);
    setParams({}); loadList(); changed();
  }

  return (
    <div className="page wide">
      <PageHead eyebrow="Every chat from your website" title="Inbox" />
      <div className="seg wrap">
        {FILTERS.map(([k, label]) => <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{label}</button>)}
      </div>
      {flash.node}
      <div className="inbox">
        <div className="card mail-list">
          {items.length === 0 && <Empty>No conversations here yet. Once the chat is on your website, every conversation shows up here.</Empty>}
          {items.map((c) => (
            <button key={c.id} className={`mail-item ${selected === c.id ? "sel" : ""} ${c.needs_attention ? "unread" : ""}`} onClick={() => setParams({ c: c.id })}>
              <div className="row between">
                <strong className="ellipsis">{c.contact_name || "Website visitor"}</strong>
                <small className="muted">{ago(c.last_message_at)}</small>
              </div>
              <div className="ellipsis muted">{c.preview || "…"}</div>
              <div className="row tight">
                {c.needs_attention && <span className="pill urgent">needs reply</span>}
                {c.status === "human" && <span className="pill action">team</span>}
                {c.status === "closed" && <span className="pill spam">closed</span>}
                {c.contact_email && <span className="pill fyi">lead</span>}
              </div>
            </button>
          ))}
        </div>
        <div className="card mail-view">
          {!detail ? <Empty>Select a conversation.</Empty> : (
            <>
              <div className="row between wrap">
                <div>
                  <h2>{detail.contact?.name || "Website visitor"}</h2>
                  <small className="muted">
                    {detail.contact?.email}{detail.contact?.phone && ` · ${detail.contact.phone}`} · started {fmtDateTime(detail.created_at, org?.timezone)}
                    {detail.page_url && <> · from <span className="ellipsis inline">{detail.page_url.slice(0, 60)}</span></>}
                  </small>
                </div>
                <div className="row tight">
                  {detail.status === "human"
                    ? <button onClick={() => update({ status: "ai" }, "The AI assistant will answer again.")}>Hand back to AI</button>
                    : <button onClick={() => update({ status: "human" }, "You've taken over — the AI is paused for this chat.")}>Take over</button>}
                  {detail.needs_attention && <button onClick={() => update({ needs_attention: false }, "Marked as handled.")}>Mark handled</button>}
                  {detail.status !== "closed" && <button className="ghost" onClick={() => update({ status: "closed" }, "Closed.")}>Close</button>}
                  {canAdmin(org) && <button className="ghost" onClick={remove}>Delete</button>}
                </div>
              </div>
              <div className="thread">
                {detail.messages.map((m) => (
                  <div key={m.id} className={`bubble ${m.role === "visitor" ? "them" : m.role}`}>
                    <span className="who">{m.role === "visitor" ? "Visitor" : m.role === "staff" ? "Team" : "AI assistant"} · {new Date(m.created_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
                    {m.content}
                  </div>
                ))}
                <div ref={endRef} />
              </div>
              <form className="composer" onSubmit={send}>
                <input value={reply} onChange={(e) => setReply(e.target.value)} maxLength={4000}
                  placeholder={detail.status === "human" ? "Reply to the visitor…" : "Reply as a team member (pauses the AI for this chat)…"} />
                <button className="primary" disabled={!reply.trim()}>Send</button>
              </form>
              <small className="muted">Visitors see your reply in the chat window within a few seconds if it's still open.</small>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
