import { useEffect, useState, type FormEvent } from "react";
import { api, fmtDate, fmtTime, type Appointment, type Service } from "../api";
import { useAuth } from "../auth";
import { Empty, PageHead, useFlash, useLoad } from "../ui";

const STATUSES = ["booked", "confirmed", "completed", "no_show", "cancelled"];
const today = () => new Date().toLocaleDateString("en-CA");

export default function Appointments() {
  const { org } = useAuth();
  const tz = org?.timezone;
  const [start, setStart] = useState(today());
  const [list, setList] = useState<Appointment[]>([]);
  const { data: services } = useLoad<Service[]>("/services", [org?.id]);
  const [showNew, setShowNew] = useState(false);
  const [f, setF] = useState({ service_id: "", day: today(), slot: "", name: "", email: "", phone: "", notes: "" });
  const [slots, setSlots] = useState<string[]>([]);
  const flash = useFlash();

  const load = () => api<Appointment[]>(`/appointments?start=${start}&days=14`).then(setList).catch(flash.fail);
  useEffect(() => { load(); }, [start, org?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!showNew || !f.service_id || !f.day) return;
    api<string[]>(`/appointments/slots?service_id=${f.service_id}&day=${f.day}`).then(setSlots).catch(() => setSlots([]));
  }, [showNew, f.service_id, f.day]);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/appointments", { method: "POST", body: { service_id: f.service_id, start: f.slot, name: f.name, email: f.email, phone: f.phone, notes: f.notes } });
      flash.ok("Appointment added. A confirmation email was sent if you entered an email.");
      setShowNew(false); setF({ ...f, slot: "", name: "", email: "", phone: "", notes: "" }); load();
    } catch (err) { flash.fail(err); }
  }

  async function setStatus(a: Appointment, status: string) {
    try { await api(`/appointments/${a.id}`, { method: "PATCH", body: { status } }); load(); } catch (err) { flash.fail(err); }
  }

  const byDay = list.reduce<Record<string, Appointment[]>>((acc, a) => {
    const k = fmtDate(a.start, tz);
    (acc[k] = acc[k] || []).push(a);
    return acc;
  }, {});
  const bookable = (services || []).filter((s) => s.active && s.bookable);

  return (
    <div className="page">
      <PageHead eyebrow={`Next 14 days · times in ${tz}`} title="Appointments">
        <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        <button className="primary" onClick={() => { setShowNew(!showNew); setF({ ...f, service_id: f.service_id || bookable[0]?.id || "" }); }}>New appointment</button>
      </PageHead>
      {flash.node}

      {showNew && (
        <form className="card stack" onSubmit={create}>
          <h3>New appointment</h3>
          <div className="row wrap">
            <label className="grow">Service
              <select value={f.service_id} onChange={(e) => setF({ ...f, service_id: e.target.value, slot: "" })} required>
                {bookable.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.duration_minutes} min)</option>)}
              </select>
            </label>
            <label>Day<input type="date" value={f.day} onChange={(e) => setF({ ...f, day: e.target.value, slot: "" })} required /></label>
            <label className="grow">Time
              <select value={f.slot} onChange={(e) => setF({ ...f, slot: e.target.value })} required>
                <option value="">{slots.length ? "Choose a time" : "No free times"}</option>
                {slots.map((s) => <option key={s} value={s}>{fmtTime(s, tz)}</option>)}
              </select>
            </label>
          </div>
          <div className="row wrap">
            <label className="grow">Customer name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required maxLength={120} /></label>
            <label className="grow">Email<input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
            <label className="grow">Phone<input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} maxLength={40} /></label>
          </div>
          <label>Notes<input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} maxLength={2000} /></label>
          <div className="row"><button className="primary">Add appointment</button><button type="button" className="ghost" onClick={() => setShowNew(false)}>Cancel</button></div>
        </form>
      )}

      {list.length === 0 && <div className="card"><Empty>No appointments in this period.</Empty></div>}
      {Object.entries(byDay).map(([day, appts]) => (
        <section key={day} className="card">
          <h3>{day}</h3>
          <ul className="list">
            {appts.map((a) => (
              <li key={a.id} className={a.status === "cancelled" ? "faded" : ""}>
                <span className="time">{fmtTime(a.start, tz)}–{fmtTime(a.end, tz)}</span>
                <div className="grow">
                  <div><b>{a.service_name}</b> · {a.contact_name}</div>
                  <small className="muted">{[a.contact_email, a.contact_phone].filter(Boolean).join(" · ")}{a.notes && ` · “${a.notes}”`} · via {a.created_via}</small>
                </div>
                <select value={a.status} onChange={(e) => setStatus(a, e.target.value)} aria-label="Status">
                  {STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
                </select>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
