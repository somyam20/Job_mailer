# 📨 JobMailer

A multi-user web app for sending lots of job applications quickly. Each day you add the companies and job titles you're
applying for. JobMailer then:

1. keeps a daily list you can download as Excel;
2. after you approve them, finds HR and company email addresses and checks they look real;
3. writes an email for each company from **your** resume and summary, for that job title;
4. sends it from **your own** mailbox with your resume attached, or gives you a `.eml` draft to open in Outlook.

It's built for about 40 applications a day per user. Each user has their own login, settings, resume and data.

---

## Contents
- [Features](#features)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Setup](#setup)
- [Using the app](#using-the-app)
- [Settings (per user)](#settings-per-user)
- [Database](#database)
- [How email search works](#how-email-search-works)
- [Security notes](#security-notes)
- [API reference](#api-reference)
- [Troubleshooting](#troubleshooting)

---

## Features

**Accounts**
- Sign up / sign in. Passwords are hashed (PBKDF2-SHA256), and you stay logged in for 30 days with an HTTP-only cookie.
- Every user's companies, contacts, drafts, settings and resume are private to them.

**Daily workflow**
- Add companies one at a time, or paste many at once (`Company, Designation` per line).
- A daily limit (default 40, set per user). The same company and job title can't be added twice, even on another day.
- A sidebar lists every day with how many you added and sent, so you can go back to earlier days.
- Download any day as an Excel file.

**Finding emails**
- Gemini with Google Search finds HR and company emails, with the page each one came from.
- If Gemini's search quota runs out, the app reads the company's own website instead (contact, careers, jobs and about pages).
- Every email is checked for format, a working mail server (MX record) and a domain that matches the company. Emails that pass are ticked automatically; you can add emails by hand.

**Writing and sending**
- One card per company with recipients, subject and body, written by Gemini from the user's resume, summary and the job title.
- Edit, rewrite, copy, download `.eml` (resume attached), or send through the user's own SMTP login.

**Interface**
- Light, Dark or Auto mode, 5 colour themes, and 3 animated wallpapers (paper planes, aurora, starfield) or none.
- A sign-in page with Pip the mascot, a password-strength bar, and a layout that works on phones.

---

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Database | SQLAlchemy 2: SQLite (default) or PostgreSQL / Supabase (psycopg 3) |
| AI | Google Gemini (`google-genai`), optionally with Google Search |
| Email | `smtplib` (STARTTLS); `.eml` drafts |
| Other | openpyxl (Excel), pypdf (reads resume text), dnspython (MX checks), cryptography (encrypts secrets) |
| Frontend | Plain HTML, CSS and JavaScript (no build step), canvas wallpapers |

---

## Project structure

```
job_mailer/
├── backend/
│   ├── main.py        # FastAPI app: auth, settings, applications, search, drafts, sending, Excel
│   ├── db.py          # SQLAlchemy models + engine (SQLite or Postgres from .env)
│   ├── auth.py        # password hashing, sessions, encryption of stored secrets
│   ├── llm.py         # Gemini: find contacts, official website, write email (per-user key/model)
│   ├── crawl.py       # fallback: read the company website for emails
│   └── verify.py      # email checks: format, MX record, domain match
├── frontend/
│   ├── login.html     # sign in / sign up with Pip the mascot
│   ├── index.html     # main app (3 steps, days sidebar, settings window)
│   ├── theme.css      # design tokens, light/dark modes, colour themes
│   └── theme.js       # theme picker, live wallpaper, logo
├── data/              # created on first run (git-ignore this folder)
│   ├── jobs.db        # SQLite database (when not using Postgres)
│   ├── resumes/       # old resume files (now imported into the database automatically)
│   └── secret.key     # encryption key for saved passwords/API keys
├── migrate_to_postgres.py   # one-time copy SQLite → Postgres (incl. resume files)
├── pyproject.toml     # dependencies + Vercel entrypoint
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup

### 1. Install
```bash
cd job_mailer
python -m venv venv
venv\Scripts\activate          # Windows  (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
```

### 2. Configure `.env` (optional)
Copy `.env.example` to `.env`. **Nothing in it is required.** Each user's settings are entered in the app. `.env` only
covers server-wide options:

```ini
# Encryption key for saved SMTP passwords / Gemini keys.
# If unset, one is generated in data/secret.key.
# APP_SECRET_KEY=

# Database: leave unset to use local SQLite (data/jobs.db).
# DB_HOST=aws-0-ap-southeast-1.pooler.supabase.com
# DB_PORT=5432
# DB_NAME=postgres
# DB_USER=postgres.<project-ref>
# DB_PASSWORD=
# ...or a single DATABASE_URL=postgresql://user:password@host:5432/postgres
```

### 3. Run
```bash
uvicorn backend.main:app --reload
```
Open **http://127.0.0.1:8000**. You'll be sent to the sign-in page. Create an account, and the Settings window opens.

> To let other devices on your network use it: `uvicorn backend.main:app --host 0.0.0.0 --port 8000`.
> For use over the internet, put it behind HTTPS (see [Security notes](#security-notes)).

### Deploy to Vercel
The repo includes `pyproject.toml` with `[tool.vercel] entrypoint = "backend.main:app"`, so Vercel detects the
FastAPI app. Vercel runs it as serverless functions: only `/tmp` can be written and it is wiped between runs. So:

1. **Use Postgres (Supabase).** SQLite won't work, and the app refuses to start on Vercel without it.
2. In *Vercel → Project → Settings → Environment Variables*, add:

   | Variable | Value |
   |---|---|
   | `DB_HOST` | `aws-0-ap-southeast-1.pooler.supabase.com` (your Session pooler host) |
   | `DB_PORT` | `5432` |
   | `DB_NAME` | `postgres` |
   | `DB_USER` | `postgres.<project-ref>` |
   | `DB_PASSWORD` | your database password |
   | `APP_SECRET_KEY` | **required.** The contents of your local `data/secret.key` (so existing saved secrets still decrypt), or a new key from `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

3. If you have local data, copy it into Supabase first with `python migrate_to_postgres.py`. Resumes are copied too.
4. Redeploy.

Notes:
- Resumes are stored **in the database**, so they survive deploys. Maximum 4 MB, because Vercel limits request size.
- The email search runs after the response, inside the same function. Approve a few companies at a time so it finishes
  within your plan's function time limit.

---

## Using the app

| Step | What you do | What happens |
|---|---|---|
| **1 · Add companies** | Type company + designation and press Enter, or paste a list | Saved under today's date; status `pending`. **⬇ Excel** exports the day |
| **2 · Find emails** | Tick companies → **Approve & search** | Status `searching` → `searched`. Emails show ✔ (passed checks) or ⚠ (with the reason), plus a source link |
| **3 · Write & send** | **✨ Write all emails**, review each card | Tick or untick recipients, edit subject/body, then **🚀 Send**, **⬇ .eml**, **⧉ Copy** or **↻ Rewrite**. Status `drafted` → `sent` |

Use the **Days** sidebar or the date picker to go back to an earlier day.

**Statuses:** `pending` → `searching` → `searched` → `drafted` → `sent` (or `error`; you can approve it again).

---

## Settings (per user)

Open **⚙ Settings** in the header. Each user has their own values:

| Section | Field | Notes |
|---|---|---|
| Profile | Full name, Phone, LinkedIn, Summary | Used to write emails and the signature |
| Profile | Resume (PDF) | Click or drag & drop. Its text is read to tailor each email and it's attached to every email |
| Sending email | SMTP host / port | Gmail: `smtp.gmail.com` / `587`. Outlook: `smtp.office365.com` / `587` |
| Sending email | Email (username) | Your **full** email address |
| Sending email | App password | Gmail needs a 16-letter **App Password** (see below). Saved encrypted; leave blank to keep the current one |
| Gemini | API key | From https://aistudio.google.com/apikey. Saved encrypted |
| Gemini | Model | e.g. `gemini-2.5-flash`, `gemini-3.5-flash-lite`. Check your limits on AI Studio's **Rate Limit** page |
| Gemini | Daily company limit | Default 40 |

**Gmail App Password:** turn on 2-Step Verification, then go to https://myaccount.google.com/apppasswords, create one
named "JobMailer", and paste the 16 letters (spaces are removed automatically).

---

## Database

### How data is separated between users
There is **one database**. Every row is linked to its owner:

| Table | Holds | Owner link |
|---|---|---|
| `users` | email, password hash | — |
| `auth_sessions` | login tokens | `user_id` |
| `user_settings` | per-user settings (secrets encrypted) | `user_id` |
| `applications` | company, designation, day, status, website | `user_id` |
| `contacts` | found emails, kind (hr/company), check result | → `applications` |
| `email_drafts` | subject, body, sent time | → `applications` |

Every API call works out the logged-in user from the session cookie and filters by that user. Opening another user's
record returns *404 Not found*.

### SQLite (default)
Nothing to set up. Data is stored in `data/jobs.db`, and tables are created on first run.

### PostgreSQL / Supabase
1. In `.env`, set the `DB_*` values (or `DATABASE_URL`). Supabase: *Project Settings → Database*, using the
   **Session pooler** host on port `5432`. Connections use SSL.
2. Copy your existing SQLite data across (one time; the script stops if Postgres already has users):
   ```bash
   python migrate_to_postgres.py
   ```
3. Restart the app. Tables are created automatically if they're missing.

> Resumes are stored in the database. `data/secret.key` stays on disk: back it up, or set `APP_SECRET_KEY`.

### Upgrading from the single-user version
On startup, an old `jobs.db` is upgraded in place. The **first account that signs up** takes over the existing
companies, resume, old settings and any `APPLICANT_*`, `SMTP_*` and `GEMINI_*` values still in `.env`.

---

## How email search works

1. **Gemini + Google Search.** Gemini is asked to find HR, careers and general emails it actually saw on web
   pages, never guessed, along with each page's URL.
2. **Fallback crawler.** If the search add-on returns *429 / quota exhausted* (common on the free tier), JobMailer
   stops using it for that API key and instead:
   - asks Gemini (without search) for the company's official website;
   - reads up to 12 pages on that site (home, `/contact`, `/careers`, `/jobs`, `/about`, and similar links);
   - collects the emails written there and drops junk like `noreply@`, `privacy@`, `abuse@`;
   - ranks HR-like addresses (`hr`, `careers`, `jobs`, `talent`, `recruit`…) first and keeps the top 5.
3. **Checks** ([verify.py](backend/verify.py)): valid format → domain has an MX record → not a free webmail
   domain → domain matches the company website, or looks like the company name. Only emails that pass are
   ticked automatically.

Gemini calls retry automatically after a 429, and searches wait 5 s between companies to stay under free-tier
per-minute limits.

---

## Security notes

- Passwords: PBKDF2-SHA256, 200k iterations, random salt per user.
- Sessions: random 256-bit tokens in an `HttpOnly`, `SameSite=Lax` cookie, valid for 30 days. Logging out deletes the token.
- SMTP passwords and Gemini keys are **encrypted at rest** (Fernet) using `APP_SECRET_KEY` or `data/secret.key`, and
  are never sent back to the browser.
  **Keep `secret.key` safe:** if it's lost, users must re-enter their secrets; if it leaks, those secrets can be decrypted.
- Never commit `.env`, `data/` or `venv/` to git.
- For use over the internet: serve over **HTTPS** (e.g. behind Nginx/Caddy) and set the cookie's `secure=True` in
  `_login_response` in `backend/main.py`.

---

## API reference

All endpoints except sign-up and login need the session cookie. They return `401` when it's missing.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/signup` | `{email, password}`. Creates the account and logs in |
| POST | `/api/login` | `{email, password}` |
| POST | `/api/logout` | End the session |
| GET | `/api/me` | Current user, whether a resume is uploaded, whether settings are configured |
| GET / PUT | `/api/settings` | Read (secrets hidden) / save settings |
| POST / GET | `/api/resume` | Upload PDF / download your resume |
| GET | `/api/days` | Per-day counts + daily limit |
| GET | `/api/applications?day=YYYY-MM-DD` | List applications for a day |
| POST | `/api/applications` | `{company, designation, day?}` |
| DELETE | `/api/applications/{id}` | Remove |
| GET | `/api/excel?day=YYYY-MM-DD` | Download Excel |
| POST | `/api/approve` | `{ids: [...]}`. Starts the email search in the background |
| PATCH | `/api/contacts/{id}` | `{selected}`. Tick or untick a recipient |
| POST | `/api/applications/{id}/contacts` | `{email, kind}`. Add an email by hand |
| POST | `/api/generate` | `{ids: [...]}`. Write emails |
| PUT | `/api/applications/{id}/draft` | `{subject, body}`. Save edits |
| GET | `/api/applications/{id}/eml` | Download a `.eml` draft with resume attached |
| POST | `/api/applications/{id}/send` | Send through the user's SMTP login |

Interactive docs: **http://127.0.0.1:8000/docs**

---

## Troubleshooting

| Problem | Cause / fix |
|---|---|
| `Search failed: 429 RESOURCE_EXHAUSTED` | The Gemini quota is per **Google Cloud project**, not per key, so a new key in the same project doesn't help. The Google Search add-on often has 0 free quota. The app falls back to reading the company website automatically. For more quota, enable billing or use a key from another project. |
| `Email login failed…` / `Connection unexpectedly closed` | You used your normal Gmail password. Create an **App Password** and put it in Settings. |
| `Add your Gemini API key in Settings first` | Open ⚙ Settings → Gemini → API key. |
| Login returns `401` | Wrong email or password, **or** the app is now using a different database (e.g. you switched to Supabase without running `migrate_to_postgres.py`). Sign up again or run the migration. |
| `Daily limit of N reached` | Raise **Daily company limit** in Settings, or pick another day. |
| No emails found for a company | Many companies don't publish HR emails. Add one by hand on the card (you'll get a ⚠ if it fails the checks). |
| Settings show blank secrets | Expected. Secrets are never shown again; a blank field keeps the saved value. |
| Saved secrets stopped working | `data/secret.key` (or `APP_SECRET_KEY`) changed or was lost. Re-enter them in Settings. |
| Wallpaper is distracting or slow | 🎨 → Live wallpaper → **Off**. It's also turned off for people who have animations disabled in their system. |
