import { useEffect, useState, type FormEvent } from "react";
import { api, download, fmtDate, type Contact } from "../api";
import { canAdmin, useAuth } from "../auth";
import { Empty, PageHead, useFlash } from "../ui";

const blank = { name: "", email: "", phone: "", birthday: "", notes: "", tags: "", marketing_consent: false };
type Form = typeof blank;

export default function Contacts() {
  const { org } = useAuth();
  const [q, setQ] = useState("");
  const [list, setList] = useState<Contact[]>([]);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [form, setForm] = useState<Form>(blank);
  const flash = useFlash();
  const admin = canAdmin(org);

  const load = () => api<Contact[]>(`/contacts${q ? `?q=${encodeURIComponent(q)}` : ""}`).then(setList).catch(flash.fail);
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [q, org?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  function edit(c: Contact | null) {
    setEditing(c ? c.id : "new");
    setForm(c ? { name: c.name, email: c.email, phone: c.phone, birthday: c.birthday || "", notes: c.notes, tags: c.tags.join(", "), marketing_consent: c.marketing_consent } : blank);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    const body = { ...form, birthday: form.birthday || null, tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean) };
    try {
      if (editing === "new") await api("/contacts", { method: "POST", body });
      else await api(`/contacts/${editing}`, { method: "PUT", body });
      setEditing(null); flash.ok("Saved."); load();
    } catch (err) { flash.fail(err); }
  }

  async function erase(c: Contact) {
    if (!confirm(`Permanently erase ${c.name || c.email} and their conversations? Use this for privacy/deletion requests.`)) return;
    try { await api(`/contacts/${c.id}`, { method: "DELETE" }); setEditing(null); load(); flash.ok("Customer erased."); } catch (err) { flash.fail(err); }
  }

  async function exportCsv() {
    try { download(await api<Blob>("/contacts/export.csv", { raw: true }), "customers.csv"); } catch (err) { flash.fail(err); }
  }

  async function importCsv(file: File | undefined) {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api<{ imported: number; skipped: number; errors: string[] }>("/contacts/import", { method: "POST", form: fd });
      flash.ok(`Imported ${r.imported}, skipped ${r.skipped}.${r.errors.length ? " " + r.errors.join(" ") : ""}`);
      load();
    } catch (err) { flash.fail(err); }
  }

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="page">
      <PageHead eyebrow="Leads and customers captured by your assistant" title="Customers">
        <input placeholder="Search name, email, phone" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="primary" onClick={() => edit(null)}>Add customer</button>
        {admin && <button onClick={exportCsv}>Export CSV</button>}
        {admin && <label className="button file-btn">Import CSV<input type="file" accept=".csv,text/csv" onChange={(e) => { importCsv(e.target.files?.[0]); e.target.value = ""; }} /></label>}
      </PageHead>
      {admin && <p className="hint">Import columns: name, email, phone, birthday (YYYY-MM-DD), marketing_consent (yes/no). Only import consent you actually have.</p>}
      {flash.node}

      {editing && (
        <form className="card stack" onSubmit={save}>
          <h3>{editing === "new" ? "New customer" : "Edit customer"}</h3>
          <div className="row wrap">
            <label className="grow">Name<input value={form.name} onChange={set("name")} maxLength={120} /></label>
            <label className="grow">Email<input type="email" value={form.email} onChange={set("email")} /></label>
            <label className="grow">Phone<input value={form.phone} onChange={set("phone")} maxLength={40} /></label>
            <label>Birthday<input type="date" value={form.birthday} onChange={set("birthday")} /></label>
          </div>
          <label>Tags (comma separated)<input value={form.tags} onChange={set("tags")} /></label>
          <label>Notes<textarea rows={3} value={form.notes} onChange={set("notes")} maxLength={5000} /></label>
          <label className="check"><input type="checkbox" checked={form.marketing_consent} onChange={(e) => setForm({ ...form, marketing_consent: e.target.checked })} />
            Customer agreed to receive offers and birthday wishes</label>
          <div className="row">
            <button className="primary">Save</button>
            <button type="button" className="ghost" onClick={() => setEditing(null)}>Cancel</button>
            {editing !== "new" && admin && <button type="button" className="ghost danger-text" onClick={() => erase(list.find((c) => c.id === editing)!)}>Erase customer</button>}
          </div>
        </form>
      )}

      <div className="card table">
        {list.length === 0 && <Empty>No customers yet. Leads appear here when visitors leave their details or book.</Empty>}
        {list.map((c) => (
          <button key={c.id} className="task-row clickable" onClick={() => edit(c)}>
            <div className="avatar-sm">{(c.name || c.email || "?").charAt(0).toUpperCase()}</div>
            <div className="grow">
              <div className="task-title">{c.name || "(no name)"}</div>
              <small className="muted">{[c.email, c.phone].filter(Boolean).join(" · ")}{c.birthday && ` · 🎂 ${c.birthday.slice(5)}`}</small>
            </div>
            <div className="row tight">
              {c.marketing_consent && !c.unsubscribed_at && <span className="pill fyi">opted in</span>}
              {c.unsubscribed_at && <span className="pill spam">unsubscribed</span>}
              {c.tags.map((t) => <span key={t} className="tag">{t}</span>)}
              <small className="muted">{c.source} · {fmtDate(c.created_at)}</small>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
