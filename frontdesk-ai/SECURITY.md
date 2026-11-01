# Security design

Two kinds of untrusted input reach this system: **business users** (logged-in, but must never see
another business's data) and **anonymous website visitors** (who may try to abuse the AI or the API).

| Threat | Controls |
|---|---|
| **Cross-tenant data access** | Every tenant row has `org_id`; every query filters by it; tenant chosen by `X-Org-Id` header but membership re-verified on every request; IDs inside requests (services, contacts, appointments) re-checked for ownership; 404 instead of 403 to avoid existence leaks. Covered by tests. |
| **Privilege escalation inside a business** | Roles owner > admin > staff enforced server-side; admins cannot create/demote owners or remove admins; last owner cannot leave or be demoted; billing restricted to owners. |
| **Prompt injection by visitors** | Visitor text wrapped in `<visitor>` tags, delimiter tags stripped from all content; system rules state visitor text is never instructions; the model returns schema-validated JSON with only text + one action from a fixed list; it **cannot** book, cancel, email or read records — bookings and contact capture go through validated forms. The prompt contains only that business's public info, so a jailbreak can't leak private or cross-tenant data. |
| **Widget abuse / cost attacks** | Per-IP limits on conversations, messages, polls, bookings and lead forms; max messages per conversation; monthly conversation quota per plan; body-size cap; strict field lengths. |
| **Widget hijacking / clickjacking** | Widget runs in a sandboxed iframe on our origin (no access to the host page, host page has no access to it); `frame-ancestors` built from the business's allowed domains; widget key rotatable; dashboard pages send `X-Frame-Options: DENY` and `frame-ancestors 'none'`. |
| **XSS** | React escaping in the dashboard; the widget renders all text with `textContent`; nonce-based CSP with no inline handlers; URL params embedded as escaped JSON literals. |
| **Visitor conversation hijack** | 256-bit random visitor token per conversation, stored hashed, compared in constant time. |
| **Double booking / races** | Availability re-checked server-side at booking time inside a transaction that locks the business's config row (PostgreSQL `SELECT … FOR UPDATE`). |
| **Account takeover** | Argon2id, 12+ char passwords, lockout, per-IP login limits, optional TOTP MFA with replay protection and one-time recovery codes, generic login errors, timing-equalised unknown-user path. |
| **Session theft** | 15-min access JWT in memory only; refresh token HttpOnly/Secure/SameSite=Strict cookie scoped to `/api/v1/auth`; rotation with reuse detection (replay revokes the session family); logout/revoke effective immediately; all sessions revoked on password change. |
| **CSRF** | Bearer auth for the API; cookie endpoints require `X-Requested-With` (forces a CORS preflight that CORS rejects); invite and reset tokens travel in URL fragments (not sent to servers/logs). |
| **Payment tampering** | Plan/status changes only via Stripe webhooks verified with HMAC-SHA256 signatures and a 5-minute timestamp tolerance; events deduplicated by ID; redirect URLs validated client-side. |
| **Email abuse & compliance** | Birthday/marketing emails only to contacts with recorded consent, once per year, with HMAC-signed one-click unsubscribe and `List-Unsubscribe` header; transactional emails deduplicated; CR/LF stripped from all headers. |
| **CSV/formula injection** | Exported cells starting with `= + - @` are prefixed with `'`; imports size-capped and validated. |
| **Data at rest** | Chat messages and MFA secrets encrypted with AES-256-GCM; tokens (refresh, reset, invite, visitor, booking) stored only as SHA-256 hashes. |
| **Privacy requests** | Businesses can erase a customer (contact + conversations, appointments anonymised), delete the whole business, and export customers; users can delete their account. |
| **Infrastructure** | HTTPS via Caddy with HSTS; DB/Redis on an internal network with no internet; containers non-root, read-only, all capabilities dropped; production refuses to start with default secrets, wildcard hosts, SQLite or non-HTTPS URLs; encrypted backups. |

Report vulnerabilities to security@your-domain.example.
