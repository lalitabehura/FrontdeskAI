import { useState } from "react";
import { api } from "../api";
import { canAdmin, useAuth } from "../auth";
import { PageHead, Section, useAssistant, useFlash, useLoad } from "../ui";

const PLATFORMS: [string, string][] = [
  ["Any website", "Paste the code just before the closing </body> tag on every page (or in your site-wide footer)."],
  ["WordPress", "Install the free “WPCode” plugin → Code Snippets → Header & Footer → paste into Footer → Save."],
  ["Wix", "Settings → Custom Code → + Add Custom Code → paste, choose “All pages” and “Body – end” → Apply."],
  ["Squarespace", "Settings → Advanced → Code Injection → paste into Footer → Save."],
  ["Shopify", "Online Store → Themes → … → Edit code → theme.liquid → paste just above </body> → Save."],
  ["Webflow", "Project settings → Custom code → Footer code → paste → Save and publish."],
];

export default function Install() {
  const { org } = useAuth();
  const { data, reload } = useLoad<{ snippet: string; preview_url: string; allowed_domains: string[] }>("/assistant/install", [org?.id]);
  const { assistant, save } = useAssistant();
  const [domains, setDomains] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);
  const flash = useFlash();
  const admin = canAdmin(org);

  if (!data || !assistant) return <p className="muted">Loading…</p>;
  const domainText = domains ?? assistant.allowed_domains.join("\n");

  async function copy() {
    try { await navigator.clipboard.writeText(data!.snippet); setCopied(true); setTimeout(() => setCopied(false), 2000); }
    catch { flash.fail(new Error("Copy failed — select the code and copy it manually.")); }
  }

  async function saveDomains() {
    try {
      await save({ ...assistant!, allowed_domains: domainText.split(/[\s,]+/).filter(Boolean) });
      setDomains(null); reload(); flash.ok("Allowed websites saved.");
    } catch (err) { flash.fail(err); }
  }

  async function rotate() {
    if (!confirm("Generate a new key? The old code stops working immediately and must be replaced on your website.")) return;
    try { await api("/assistant/rotate-key", { method: "POST" }); reload(); setPreviewKey((k) => k + 1); flash.ok("New key generated — update the code on your website."); }
    catch (err) { flash.fail(err); }
  }

  return (
    <div className="page wide">
      <PageHead eyebrow="One line of code — works on any website" title="Add to your website" />
      {flash.node}
      <div className="assistant-layout">
        <div className="stack">
          <Section title="1. Copy your code" actions={<button className="primary" onClick={copy}>{copied ? "Copied ✓" : "Copy code"}</button>}>
            <pre className="code">{data.snippet}</pre>
          </Section>
          <Section title="2. Paste it into your website">
            <div className="platforms">
              {PLATFORMS.map(([name, how]) => <details key={name}><summary>{name}</summary><p>{how}</p></details>)}
            </div>
            <p className="hint">Not technical? Send the code to whoever manages your website — it takes them two minutes.</p>
          </Section>
          <Section title="3. Lock it to your website (recommended)">
            <p className="hint">List the domains allowed to show your assistant, one per line (e.g. <code>mysalon.com</code>, <code>www.mysalon.com</code>, <code>*.mysalon.com</code>). Leave empty to allow any site.</p>
            <textarea rows={3} value={domainText} onChange={(e) => setDomains(e.target.value)} disabled={!admin} placeholder="mysalon.com&#10;www.mysalon.com" />
            {admin && <div className="row"><button onClick={saveDomains} disabled={domains === null}>Save websites</button>
              <button className="ghost" onClick={rotate}>Generate new key</button></div>}
          </Section>
        </div>
        <aside className="card preview">
          <div className="row between"><h3>Live preview</h3><button className="ghost" onClick={() => setPreviewKey((k) => k + 1)}>Reload</button></div>
          <p className="hint">Click the bubble to try it. Preview chats appear in your inbox and count toward usage.</p>
          <div className="preview-frame">
            <iframe key={previewKey} title="Assistant preview" src={`${data.preview_url}?page=dashboard-preview`} />
          </div>
        </aside>
      </div>
    </div>
  );
}
