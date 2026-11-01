import type { FormEvent } from "react";
import type { Assistant } from "../api";
import { useAuth } from "../auth";
import { PageHead, Section, Toggle, useAssistant, useFlash } from "../ui";

const render = (t: string, a: Assistant, business: string) =>
  t.replaceAll("{first_name}", "Maria").replaceAll("{name}", "Maria Lopez").replaceAll("{business}", business).replaceAll("{offer}", a.birthday_offer || "a special treat");

export default function Automations() {
  const { org } = useAuth();
  const { assistant, setAssistant, save, saving } = useAssistant();
  const flash = useFlash();
  if (!assistant || !org) return <p className="muted">Loading…</p>;
  const set = <K extends keyof Assistant>(k: K, v: Assistant[K]) => setAssistant({ ...assistant, [k]: v });
  const starter = org.plan === "starter";

  async function submit(e: FormEvent) {
    e.preventDefault();
    try { await save(assistant!); flash.ok("Automations saved."); } catch (err) { flash.fail(err); }
  }

  return (
    <form className="page" onSubmit={submit}>
      <PageHead eyebrow="Runs automatically in the background" title="Automations" />
      {flash.node}
      <Section title="Appointment reminders">
        <Toggle checked={assistant.reminders_enabled} onChange={(v) => set("reminders_enabled", v)} label="Email customers before their appointment" hint="Reduces no-shows. Sent once per booking." />
        <label>Send this many hours before<input type="number" min={1} max={168} value={assistant.reminder_hours_before} onChange={(e) => set("reminder_hours_before", +e.target.value)} /></label>
      </Section>

      <Section title="Birthday wishes 🎂">
        {starter && <p className="banner">Birthday wishes are included in the Growth plan and above.</p>}
        <Toggle checked={assistant.birthday_enabled} onChange={(v) => set("birthday_enabled", v)} label="Send customers a birthday email with an offer"
          hint="Sent at 9am your time, only to customers who opted in. Every email includes an unsubscribe link." />
        <div className="grid-2">
          <div className="stack">
            <label>Offer<input value={assistant.birthday_offer} onChange={(e) => set("birthday_offer", e.target.value)} maxLength={200} placeholder="15% off / a free dessert" /></label>
            <label>Subject<input value={assistant.birthday_subject} onChange={(e) => set("birthday_subject", e.target.value)} maxLength={200} /></label>
            <label>Message<textarea rows={7} value={assistant.birthday_message} onChange={(e) => set("birthday_message", e.target.value)} maxLength={3000} /></label>
            <p className="hint">Placeholders: <code>{"{first_name}"}</code> <code>{"{name}"}</code> <code>{"{business}"}</code> <code>{"{offer}"}</code></p>
          </div>
          <div className="email-preview-card">
            <small className="muted">Preview</small>
            <strong>{render(assistant.birthday_subject, assistant, org.name)}</strong>
            <pre>{render(assistant.birthday_message, assistant, org.name)}</pre>
            <small className="muted">— Unsubscribe link added automatically</small>
          </div>
        </div>
        <p className="hint">Birthdays are collected in the chat (optional) and can be added or imported on the Customers page.</p>
      </Section>
      <div><button className="primary" disabled={saving}>{saving ? "Saving…" : "Save automations"}</button></div>
    </form>
  );
}
