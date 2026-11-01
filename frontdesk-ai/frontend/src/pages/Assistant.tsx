import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, type Assistant, type Hours, type Knowledge, type Service } from "../api";
import { canAdmin, useAuth } from "../auth";
import { PageHead, Section, Toggle, useAssistant, useFlash, useLoad } from "../ui";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const TABS = [["profile", "Profile & tone"], ["hours", "Hours & booking"], ["services", "Services"], ["knowledge", "FAQs"]] as const;

export default function AssistantPage() {
  const { org } = useAuth();
  const { assistant, setAssistant, save, saving } = useAssistant();
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("profile");
  const flash = useFlash();
  const readOnly = !canAdmin(org);

  if (!assistant) return <p className="muted">Loading…</p>;
  const set = <K extends keyof Assistant>(k: K, v: Assistant[K]) => setAssistant({ ...assistant, [k]: v });

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    try { await save(assistant!); flash.ok("Saved — your assistant is using the new settings."); } catch (err) { flash.fail(err); }
  }

  return (
    <div className="page wide">
      <PageHead eyebrow="Teach it about your business" title="Assistant">
        {readOnly && <span className="pill spam">view only</span>}
      </PageHead>
      <div className="seg wrap">{TABS.map(([k, l]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}</div>
      {flash.node}
      <div className="assistant-layout">
        <div className="stack">
          {tab === "profile" && (
            <form className="stack" onSubmit={submit}>
              <fieldset disabled={readOnly} className="stack">
                <Section title="Identity">
                  <Toggle checked={assistant.enabled} onChange={(v) => set("enabled", v)} label="Assistant is live on your website" />
                  <div className="row wrap">
                    <label className="grow">Assistant name<input value={assistant.assistant_name} onChange={(e) => set("assistant_name", e.target.value)} maxLength={60} required /></label>
                    <label>Brand colour<input type="color" value={assistant.brand_color} onChange={(e) => set("brand_color", e.target.value)} /></label>
                    <label>Position<select value={assistant.position} onChange={(e) => set("position", e.target.value as Assistant["position"])}><option value="right">Bottom right</option><option value="left">Bottom left</option></select></label>
                  </div>
                  <label>Greeting<input value={assistant.greeting} onChange={(e) => set("greeting", e.target.value)} maxLength={500} required /></label>
                  <div className="row wrap">
                    <label>Tone
                      <select value={assistant.tone} onChange={(e) => set("tone", e.target.value)}>
                        <option value="friendly">Friendly</option><option value="professional">Professional</option>
                        <option value="playful">Playful</option><option value="concise">Concise</option>
                      </select>
                    </label>
                    <label className="grow">Language<input value={assistant.language} onChange={(e) => set("language", e.target.value)} maxLength={40} placeholder="auto = match the visitor" /></label>
                  </div>
                </Section>
                <Section title="About your business">
                  <label>Description — what you do, who you serve, what makes you different
                    <textarea rows={5} value={assistant.business_description} onChange={(e) => set("business_description", e.target.value)} maxLength={4000}
                      placeholder="e.g. Family-run hair salon in downtown Austin since 2012. We specialise in curly hair, balayage and bridal styling…" />
                  </label>
                  <div className="row wrap">
                    <label className="grow">Phone<input value={assistant.contact_phone} onChange={(e) => set("contact_phone", e.target.value)} maxLength={40} /></label>
                    <label className="grow">Email<input type="email" value={assistant.contact_email} onChange={(e) => set("contact_email", e.target.value)} /></label>
                  </div>
                  <div className="row wrap">
                    <label className="grow">Address<input value={assistant.address} onChange={(e) => set("address", e.target.value)} maxLength={300} /></label>
                    <label className="grow">Website<input value={assistant.website} onChange={(e) => set("website", e.target.value)} maxLength={300} /></label>
                  </div>
                  <label>Extra instructions for the assistant (policies, things to always/never say)
                    <textarea rows={3} value={assistant.extra_instructions} onChange={(e) => set("extra_instructions", e.target.value)} maxLength={2000}
                      placeholder="e.g. Cancellations need 24 hours notice. Always mention our new-client 10% discount." />
                  </label>
                  <label>Message when handing over to your team<input value={assistant.handoff_message} onChange={(e) => set("handoff_message", e.target.value)} maxLength={500} /></label>
                  <label>Email new leads & handoffs to<input type="email" value={assistant.notify_email} onChange={(e) => set("notify_email", e.target.value)} /></label>
                </Section>
                <button className="primary" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
              </fieldset>
            </form>
          )}
          {tab === "hours" && (
            <form className="stack" onSubmit={submit}>
              <fieldset disabled={readOnly} className="stack">
                <Section title={`Opening hours (${org?.timezone})`}>
                  <HoursEditor hours={assistant.hours} onChange={(h) => set("hours", h)} />
                </Section>
                <Section title="Online booking">
                  <Toggle checked={assistant.booking_enabled} onChange={(v) => set("booking_enabled", v)} label="Let visitors book appointments" hint="Shows real-time availability based on your hours and existing bookings." />
                  <div className="row wrap">
                    <label>Time slot every (min)<input type="number" min={5} max={240} value={assistant.slot_interval_minutes} onChange={(e) => set("slot_interval_minutes", +e.target.value)} /></label>
                    <label>Minimum notice (min)<input type="number" min={0} max={10080} value={assistant.min_notice_minutes} onChange={(e) => set("min_notice_minutes", +e.target.value)} /></label>
                    <label>Book up to (days ahead)<input type="number" min={1} max={180} value={assistant.booking_horizon_days} onChange={(e) => set("booking_horizon_days", +e.target.value)} /></label>
                    <label>Bookings per time slot<input type="number" min={1} max={50} value={assistant.capacity_per_slot} onChange={(e) => set("capacity_per_slot", +e.target.value)} /></label>
                  </div>
                  <Toggle checked={assistant.require_phone} onChange={(v) => set("require_phone", v)} label="Require a phone number to book" />
                </Section>
                <button className="primary" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
              </fieldset>
            </form>
          )}
          {tab === "services" && <Services readOnly={readOnly} />}
          {tab === "knowledge" && <KnowledgeBase readOnly={readOnly} />}
        </div>
        <TestChat assistant={assistant} />
      </div>
    </div>
  );
}

function HoursEditor({ hours, onChange }: { hours: Hours; onChange: (h: Hours) => void }) {
  const upd = (d: number, ranges: string[][]) => onChange({ ...hours, [String(d)]: ranges });
  return (
    <div className="hours">
      {DAYS.map((name, d) => {
        const ranges = hours[String(d)] || [];
        return (
          <div key={d} className="hours-row">
            <label className="check day-name"><input type="checkbox" checked={ranges.length > 0} onChange={(e) => upd(d, e.target.checked ? [["09:00", "17:00"]] : [])} />{name}</label>
            {ranges.length === 0 ? <span className="muted">Closed</span> : (
              <div className="row wrap tight">
                {ranges.map((r, i) => (
                  <span key={i} className="row tight">
                    <input type="time" value={r[0]} onChange={(e) => upd(d, ranges.map((x, j) => (j === i ? [e.target.value, x[1]] : x)))} />–
                    <input type="time" value={r[1]} onChange={(e) => upd(d, ranges.map((x, j) => (j === i ? [x[0], e.target.value] : x)))} />
                    {ranges.length > 1 && <button type="button" className="icon ghost" onClick={() => upd(d, ranges.filter((_, j) => j !== i))}>✕</button>}
                  </span>
                ))}
                {ranges.length < 3 && <button type="button" className="ghost" onClick={() => upd(d, [...ranges, ["13:00", "17:00"]])}>+ split</button>}
                {d > 0 && <button type="button" className="ghost" onClick={() => upd(d, hours[String(d - 1)] || [])}>same as above</button>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

const blankService = { name: "", description: "", duration_minutes: 30, price_text: "", bookable: true, active: true, sort_order: 0 };

function Services({ readOnly }: { readOnly: boolean }) {
  const { data, reload } = useLoad<Service[]>("/services");
  const [edit, setEdit] = useState<(typeof blankService & { id?: string }) | null>(null);
  const flash = useFlash();

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!edit) return;
    const { id, ...body } = edit;
    try {
      await api(id ? `/services/${id}` : "/services", { method: id ? "PUT" : "POST", body });
      setEdit(null); reload(); flash.ok("Service saved.");
    } catch (err) { flash.fail(err); }
  }
  const services = (data || []).filter((s) => s.active);
  return (
    <Section title="Services & prices" actions={!readOnly && <button className="primary" onClick={() => setEdit({ ...blankService })}>Add service</button>}>
      <p className="hint">Your assistant quotes these prices and visitors can book them.</p>
      {flash.node}
      {edit && (
        <form className="card stack inset" onSubmit={save}>
          <div className="row wrap">
            <label className="grow">Name<input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required maxLength={120} /></label>
            <label>Duration (min)<input type="number" min={5} max={600} value={edit.duration_minutes} onChange={(e) => setEdit({ ...edit, duration_minutes: +e.target.value })} /></label>
            <label>Price<input value={edit.price_text} onChange={(e) => setEdit({ ...edit, price_text: e.target.value })} maxLength={60} placeholder="$45 / from $80 / Free" /></label>
          </div>
          <label>Description<input value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} maxLength={1000} /></label>
          <label className="check"><input type="checkbox" checked={edit.bookable} onChange={(e) => setEdit({ ...edit, bookable: e.target.checked })} />Can be booked online</label>
          <div className="row"><button className="primary">Save service</button><button type="button" className="ghost" onClick={() => setEdit(null)}>Cancel</button></div>
        </form>
      )}
      <div className="table">
        {services.map((s) => (
          <div key={s.id} className="task-row">
            <div className="grow"><div className="task-title">{s.name} {s.price_text && <span className="muted">· {s.price_text}</span>}</div>
              <small className="muted">{s.duration_minutes} min{s.bookable ? " · bookable" : ""}{s.description && ` · ${s.description}`}</small></div>
            {!readOnly && <>
              <button onClick={() => setEdit({ ...s })}>Edit</button>
              <button className="ghost" onClick={async () => { if (confirm(`Remove ${s.name}?`)) { await api(`/services/${s.id}`, { method: "DELETE" }); reload(); } }}>Remove</button>
            </>}
          </div>
        ))}
        {services.length === 0 && <p className="muted">No services yet.</p>}
      </div>
    </Section>
  );
}

const STARTERS = [
  ["Do you have parking?", ""], ["What is your cancellation policy?", ""], ["Do you accept walk-ins?", ""],
  ["What payment methods do you accept?", ""], ["Do you offer gift cards?", ""],
];

function KnowledgeBase({ readOnly }: { readOnly: boolean }) {
  const { data, reload } = useLoad<Knowledge[]>("/knowledge");
  const [edit, setEdit] = useState<{ id?: string; question: string; answer: string } | null>(null);
  const flash = useFlash();

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!edit) return;
    try {
      await api(edit.id ? `/knowledge/${edit.id}` : "/knowledge", { method: edit.id ? "PUT" : "POST", body: { question: edit.question, answer: edit.answer } });
      setEdit(null); reload(); flash.ok("Saved.");
    } catch (err) { flash.fail(err); }
  }
  const existing = new Set((data || []).map((k) => k.question.toLowerCase()));
  return (
    <Section title="Frequently asked questions" actions={!readOnly && <button className="primary" onClick={() => setEdit({ question: "", answer: "" })}>Add FAQ</button>}>
      <p className="hint">The assistant answers from these — the more you add, the better it gets. It never makes up policies.</p>
      {!readOnly && (
        <div className="chips">
          {STARTERS.filter(([q]) => !existing.has(q.toLowerCase())).map(([q]) => (
            <button key={q} className="chip" onClick={() => setEdit({ question: q, answer: "" })}>+ {q}</button>
          ))}
        </div>
      )}
      {flash.node}
      {edit && (
        <form className="card stack inset" onSubmit={save}>
          <label>Question<input value={edit.question} onChange={(e) => setEdit({ ...edit, question: e.target.value })} required maxLength={300} /></label>
          <label>Answer<textarea rows={4} value={edit.answer} onChange={(e) => setEdit({ ...edit, answer: e.target.value })} required maxLength={4000} autoFocus /></label>
          <div className="row"><button className="primary">Save</button><button type="button" className="ghost" onClick={() => setEdit(null)}>Cancel</button></div>
        </form>
      )}
      <div className="table">
        {(data || []).map((k) => (
          <div key={k.id} className="task-row">
            <div className="grow"><div className="task-title">{k.question}</div><small className="muted pre">{k.answer}</small></div>
            {!readOnly && <>
              <button onClick={() => setEdit({ ...k })}>Edit</button>
              <button className="ghost" onClick={async () => { await api(`/knowledge/${k.id}`, { method: "DELETE" }); reload(); }}>Delete</button>
            </>}
          </div>
        ))}
        {data?.length === 0 && <p className="muted">No FAQs yet — add the questions customers ask you most.</p>}
      </div>
    </Section>
  );
}

function TestChat({ assistant }: { assistant: Assistant }) {
  const [msgs, setMsgs] = useState<{ role: "visitor" | "assistant"; content: string; note?: string }[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs]);

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput(""); setBusy(true);
    const history = msgs.map(({ role, content }) => ({ role, content }));
    setMsgs((m) => [...m, { role: "visitor", content: text }]);
    try {
      const r = await api<{ reply: string; action: string | null; used_ai: boolean }>("/assistant/test", { method: "POST", body: { message: text, history } });
      const note = { show_booking: "→ opens the booking form", show_contact: "→ asks for contact details", handoff: "→ alerts your team" }[r.action || ""] || "";
      setMsgs((m) => [...m, { role: "assistant", content: r.reply, note: [note, r.used_ai ? "" : "(rule-based reply — add an AI key for smarter answers)"].filter(Boolean).join(" ") }]);
    } catch (err) {
      setMsgs((m) => [...m, { role: "assistant", content: err instanceof Error ? err.message : "Error" }]);
    } finally { setBusy(false); }
  }

  return (
    <aside className="card test-chat">
      <div className="test-head" style={{ background: assistant.brand_color }}>
        <strong>{assistant.assistant_name}</strong><small>Test with saved settings</small>
      </div>
      <div className="thread">
        <div className="bubble assistant">{assistant.greeting}</div>
        {msgs.map((m, i) => (
          <div key={i} className={`bubble ${m.role === "visitor" ? "them-right" : "assistant"}`}>
            {m.content}{m.note && <small className="muted block">{m.note}</small>}
          </div>
        ))}
        {busy && <div className="bubble assistant typing">Typing…</div>}
        <div ref={end} />
      </div>
      <form className="composer" onSubmit={send}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask like a customer would…" maxLength={2000} />
        <button className="primary" disabled={busy}>Send</button>
      </form>
      {msgs.length > 0 && <button className="ghost" onClick={() => setMsgs([])}>Reset test</button>}
    </aside>
  );
}
