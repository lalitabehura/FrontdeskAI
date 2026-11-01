# Frontdesk AI — an AI front desk that any business can add to its website

Multi-tenant SaaS. Each business signs up, teaches its assistant (services, prices, hours, FAQs,
tone, branding), pastes **one line of code** into its website, and the assistant then:

- answers customer questions 24/7 from the business's own information (never invents policies)
- **books appointments** against real availability (hours, buffers, capacity, no double booking)
- **captures leads** and emails the business instantly
- **hands over to a human** — staff reply from a shared inbox and the AI steps aside
- sends **booking confirmations, appointment reminders and birthday wishes** with an offer

You (the platform owner) get subscriptions via Stripe, a 14-day free trial, usage limits per plan,
and a **Platform admin** console with MRR, signups and trial extensions.

## How each business customises it (no code)

| Area | What they can change |
|---|---|
| Identity | Assistant name, greeting, brand colour, left/right position, tone (friendly / professional / playful / concise), language |
| Knowledge | Business description, FAQs (with one-click starter questions), services with prices & durations, address/phone/email, extra rules ("cancellations need 24h notice") |
| Booking | Opening hours per day (split shifts), slot interval, minimum notice, how far ahead, bookings per slot, phone required |
| Automations | Reminder timing, birthday wish subject/message/offer with placeholders and live preview |
| Security | Lock the widget to their own domains; rotate the widget key |
| Team | Invite staff/admins; roles: owner, admin, staff |
| Test | Live test chat and on-page widget preview before going live |

## Plans (edit `backend/app/plans.py`)

| Plan | Price | Conversations/month | Team | Extras |
|---|---|---|---|---|
| Starter | $29 | 300 | 2 | chat, leads, booking, reminders |
| Growth | $79 | 1,500 | 5 | + birthday wishes, team inbox, CSV export |
| Pro | $199 | 6,000 | 15 | + higher limits |

Trials get Growth limits for 14 days (`TRIAL_DAYS`). When a trial ends or a subscription lapses,
the widget politely shows the business's phone/email instead of chatting.

## Architecture

```
Visitor's browser ── <script widget.js> ── sandboxed iframe (/widget/{key}) ──┐
Business dashboard (React) ───────────────────────────────────────────────────┤
                                   Caddy (HTTPS) → nginx → FastAPI ──────────── PostgreSQL
                                                         └─ arq worker ──────── Redis
                                                             (reminders, birthdays)
backend/app
  api/        auth, orgs (tenants/team), assistant, inbox (+contacts), appointments, billing, public (widget API), widget, admin
  services/   engine (AI + rule fallback), booking (availability), notify (emails/automations), usage, tenancy, ai, providers/stripe_billing
frontend/src  pages: Home, Inbox, Appointments, Customers, Assistant, Install, Automations, Team, Billing, Settings, Admin
```

## Run locally

```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

cd frontend && npm install && npm run dev      # http://localhost:5173
```

Sign up, open **Assistant** to add FAQs, then **Add to website** to try the live preview.
Set `ANTHROPIC_API_KEY` for free-form AI answers; without it the assistant uses your FAQs and built-in rules.
Emails print to the backend log until SMTP is configured.

Tests: `cd backend && pytest -q` — 28 tests covering tenant isolation, roles, invitations, token
rotation, widget security headers, booking & double-booking, handoff, usage limits, trial expiry,
Stripe webhook signatures/idempotency, reminders, birthday consent & unsubscribe, CSV injection.

## Deploy (DigitalOcean / Hetzner / any Ubuntu server)

1. Create a 2 vCPU / 4 GB Ubuntu 24.04 server, point your domain's **A record** at it.
2. `scp scripts/server-setup.sh root@SERVER:` then `ssh root@SERVER bash server-setup.sh`
   (Docker, firewall 22/80/443, automatic security updates, SSH keys only).
3. Copy the project to `/opt/frontdesk-ai`, then `cp .env.example .env` and fill it in.
4. `docker compose up -d --build` — Caddy gets HTTPS certificates automatically; migrations run on start.
5. Stripe: create 3 monthly prices, add the webhook `https://YOUR_DOMAIN/api/v1/billing/webhook`
   (events: `checkout.session.completed`, `customer.subscription.*`, `invoice.payment_failed`),
   paste keys/IDs into `.env`, `docker compose up -d`.
6. Email: verify your sending domain (SPF + DKIM) with your SMTP provider so reminders don't land in spam.
7. Backups: `BACKUP_PASSPHRASE=... scripts/backup.sh` nightly via cron, and copy files off-server.
8. Add a free uptime monitor (UptimeRobot, Better Stack) on `https://YOUR_DOMAIN/api/v1/health`.

**Back up `ENCRYPTION_KEY`** in a password manager — chat history is encrypted with it.

## Before you sell it
- Publish a Privacy Policy, Terms of Service and a Data Processing Agreement for businesses
  (you process their customers' personal data; disclose the AI provider as a sub-processor).
- Test the full flow on your phone with a real card in Stripe test mode, then switch to live keys.
