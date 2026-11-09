import io
import os
import re
import smtplib
import time
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import selectinload

from . import auth, llm
from .auth import current_user
from .db import DATA_DIR, Application, Contact, EmailDraft, SessionLocal, User, UserSetting
from .verify import verify

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
RESUME_DIR = DATA_DIR / "resumes"
RESUME_DIR.mkdir(exist_ok=True)

# Every per-user setting and its default. Secrets are encrypted at rest and never sent back to the browser.
SETTINGS = {
    "name": "", "phone": "", "linkedin": "", "summary": "",
    "smtp_host": "smtp.gmail.com", "smtp_port": "587", "smtp_user": "", "smtp_password": "",
    "gemini_api_key": "", "gemini_model": "gemini-2.5-flash", "daily_limit": "40",
}
SECRETS = {"smtp_password", "gemini_api_key"}

app = FastAPI(title="Job Mailer")


# ---------- per-user settings ----------
def settings(user_id: int) -> dict:
    with SessionLocal() as s:
        rows = {r.key: r.value for r in s.scalars(select(UserSetting).where(UserSetting.user_id == user_id))}
    cfg = {k: rows.get(k, d) for k, d in SETTINGS.items()}
    for k in SECRETS:
        cfg[k] = auth.decrypt(cfg[k])
    return cfg


def save_settings(user_id: int, values: dict):
    with SessionLocal() as s:
        for k, v in values.items():
            if k in SETTINGS:
                s.merge(UserSetting(user_id=user_id, key=k, value=auth.encrypt(v) if k in SECRETS else v))
        s.commit()


def daily_limit(cfg: dict) -> int:
    try:
        return max(1, int(cfg["daily_limit"]))
    except ValueError:
        return 40


def resume_pdf(user_id: int) -> Path:
    return RESUME_DIR / f"{user_id}.pdf"


def resume_text(user_id: int) -> str:
    p = RESUME_DIR / f"{user_id}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def claim_legacy_data(user_id: int):
    """The first account takes over data from the single-user version (companies, resume, .env, old settings)."""
    with SessionLocal() as s:
        if s.scalar(select(func.count()).select_from(User)) != 1:
            return
        s.query(Application).filter(Application.user_id.is_(None)).update({"user_id": user_id})
        legacy = {}
        # check first: on Postgres a failed SELECT would abort the whole transaction
        if inspect(s.get_bind()).has_table("settings_legacy"):
            legacy = dict(s.execute(text("SELECT key, value FROM settings_legacy")).all())
        s.commit()
    env = {
        "name": os.getenv("APPLICANT_NAME"), "phone": os.getenv("APPLICANT_PHONE"),
        "linkedin": os.getenv("APPLICANT_LINKEDIN"), "summary": os.getenv("APPLICANT_SUMMARY"),
        "smtp_host": os.getenv("SMTP_HOST"), "smtp_port": os.getenv("SMTP_PORT"),
        "smtp_user": os.getenv("SMTP_USER"), "smtp_password": os.getenv("SMTP_PASSWORD"),
        "gemini_api_key": os.getenv("GEMINI_API_KEY"), "gemini_model": os.getenv("GEMINI_MODEL"),
        "daily_limit": os.getenv("DAILY_LIMIT"),
    }
    env.update({k: v for k, v in legacy.items() if k in SETTINGS and v})
    save_settings(user_id, {k: v for k, v in env.items() if v})
    for ext in ("pdf", "txt"):
        old = DATA_DIR / f"resume.{ext}"
        if old.exists():
            old.replace(RESUME_DIR / f"{user_id}.{ext}")


# ---------- auth routes ----------
class Credentials(BaseModel):
    email: str
    password: str


def _login_response(resp: Response, user_id: int):
    resp.set_cookie(auth.COOKIE, auth.new_session(user_id), httponly=True, samesite="lax",
                    max_age=auth.SESSION_DAYS * 86400)


@app.post("/api/signup")
def signup(body: Credentials, resp: Response):
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Enter a valid email")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    with SessionLocal() as s:
        if s.scalar(select(User).where(User.email == email)):
            raise HTTPException(409, "An account with this email already exists")
        user = User(email=email, password_hash=auth.hash_password(body.password))
        s.add(user)
        s.commit()
    claim_legacy_data(user.id)
    save_settings(user.id, {"smtp_user": settings(user.id)["smtp_user"] or email})
    _login_response(resp, user.id)
    return {"email": email}


@app.post("/api/login")
def login(body: Credentials, resp: Response):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user or not auth.check_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    _login_response(resp, user.id)
    return {"email": user.email}


@app.post("/api/logout")
def logout(resp: Response, jm_session: str | None = Cookie(default=None)):
    auth.end_session(jm_session)
    resp.delete_cookie(auth.COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    cfg = settings(user.id)
    return {"email": user.email, "name": cfg["name"], "has_resume": resume_pdf(user.id).exists(),
            "configured": bool(cfg["gemini_api_key"])}


# ---------- settings + resume ----------
@app.get("/api/settings")
def get_settings(user: User = Depends(current_user)):
    cfg = settings(user.id)
    for k in SECRETS:  # only say whether a secret is set
        cfg[k + "_set"] = bool(cfg[k])
        cfg[k] = ""
    cfg["has_resume"] = resume_pdf(user.id).exists()
    return cfg


class SettingsIn(BaseModel):
    name: str = ""
    phone: str = ""
    linkedin: str = ""
    summary: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: str = "587"
    smtp_user: str = ""
    smtp_password: str = ""  # blank = keep the saved one
    gemini_api_key: str = ""  # blank = keep the saved one
    gemini_model: str = "gemini-2.5-flash"
    daily_limit: str = "40"


@app.put("/api/settings")
def put_settings(body: SettingsIn, user: User = Depends(current_user)):
    values = {k: v.strip() for k, v in body.model_dump().items()}
    values["smtp_password"] = values["smtp_password"].replace(" ", "")  # Gmail shows app passwords with spaces
    for k in SECRETS:
        if not values[k]:
            values.pop(k)
    save_settings(user.id, values)
    return {"ok": True}


@app.post("/api/resume")
async def upload_resume(file: UploadFile = File(...), user: User = Depends(current_user)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF")
    pdf = resume_pdf(user.id)
    pdf.write_bytes(await file.read())
    try:
        from pypdf import PdfReader
        txt = "\n".join(p.extract_text() or "" for p in PdfReader(pdf).pages)
    except Exception:
        txt = ""
    (RESUME_DIR / f"{user.id}.txt").write_text(txt, encoding="utf-8")
    return {"ok": True, "chars_extracted": len(txt)}


@app.get("/api/resume")
def get_resume(user: User = Depends(current_user)):
    if not resume_pdf(user.id).exists():
        raise HTTPException(404, "No resume uploaded")
    return FileResponse(resume_pdf(user.id), media_type="application/pdf")


# ---------- helpers ----------
def serialize(a: Application) -> dict:
    return {
        "id": a.id,
        "day": a.day.isoformat(),
        "company": a.company,
        "designation": a.designation,
        "status": a.status,
        "website": a.website,
        "notes": a.search_notes,
        "contacts": [
            {"id": c.id, "email": c.email, "kind": c.kind, "source_url": c.source_url,
             "verified": c.verified, "reason": c.verify_reason, "selected": c.selected}
            for c in a.contacts
        ],
        "draft": None if not a.draft else {
            "subject": a.draft.subject, "body": a.draft.body,
            "sent_at": a.draft.sent_at.isoformat() if a.draft.sent_at else None,
        },
    }


def load(s, app_id: int, user_id: int) -> Application:
    a = s.scalar(select(Application).options(selectinload(Application.contacts), selectinload(Application.draft))
                 .where(Application.id == app_id, Application.user_id == user_id))
    if not a:
        raise HTTPException(404, "Application not found")
    return a


def parse_day(day: str | None) -> date:
    try:
        return date.fromisoformat(day) if day else date.today()
    except ValueError:
        raise HTTPException(400, f"Invalid day: {day}")


# ---------- applications ----------
class NewApp(BaseModel):
    company: str
    designation: str
    day: str | None = None


@app.get("/api/days")
def days(user: User = Depends(current_user)):
    with SessionLocal() as s:
        rows = s.execute(select(Application.day, Application.status, func.count())
                         .where(Application.user_id == user.id)
                         .group_by(Application.day, Application.status)
                         .order_by(Application.day.desc())).all()
    out: dict[str, dict] = {}
    for d, st, n in rows:
        out.setdefault(d.isoformat(), {"day": d.isoformat(), "total": 0})
        out[d.isoformat()]["total"] += n
        out[d.isoformat()][st] = n
    return {"limit": daily_limit(settings(user.id)), "today": date.today().isoformat(), "days": list(out.values())}


@app.get("/api/applications")
def list_apps(day: str | None = None, user: User = Depends(current_user)):
    with SessionLocal() as s:
        apps = s.scalars(select(Application).options(selectinload(Application.contacts), selectinload(Application.draft))
                         .where(Application.user_id == user.id, Application.day == parse_day(day))
                         .order_by(Application.id)).all()
        return [serialize(a) for a in apps]


@app.post("/api/applications")
def add_app(body: NewApp, user: User = Depends(current_user)):
    d = parse_day(body.day)
    company, desig = body.company.strip(), body.designation.strip()
    if not company or not desig:
        raise HTTPException(400, "Company and designation are required")
    limit = daily_limit(settings(user.id))
    with SessionLocal() as s:
        count = s.scalar(select(func.count()).select_from(Application)
                         .where(Application.user_id == user.id, Application.day == d))
        if count >= limit:
            raise HTTPException(400, f"Daily limit of {limit} reached for {d}")
        dup = s.scalar(select(Application).where(Application.user_id == user.id,
                                                 func.lower(Application.company) == company.lower(),
                                                 func.lower(Application.designation) == desig.lower()))
        if dup:
            raise HTTPException(409, f"Already applied to {company} for {desig} on {dup.day}")
        a = Application(user_id=user.id, company=company, designation=desig, day=d)
        s.add(a)
        s.commit()
        return serialize(load(s, a.id, user.id))


@app.delete("/api/applications/{app_id}")
def delete_app(app_id: int, user: User = Depends(current_user)):
    with SessionLocal() as s:
        s.delete(load(s, app_id, user.id))
        s.commit()
    return {"ok": True}


@app.get("/api/excel")
def excel(day: str | None = None, user: User = Depends(current_user)):
    d = parse_day(day)
    with SessionLocal() as s:
        apps = s.scalars(select(Application).options(selectinload(Application.contacts))
                         .where(Application.user_id == user.id, Application.day == d).order_by(Application.id)).all()
        wb = Workbook()
        ws = wb.active
        ws.title = d.isoformat()
        headers = ["#", "Company", "Designation", "Status", "Website", "HR Emails", "Company Emails", "Date"]
        ws.append(headers)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="4F46E5")
        for i, a in enumerate(apps, 1):
            hr = ", ".join(c.email for c in a.contacts if c.kind == "hr" and c.verified)
            co = ", ".join(c.email for c in a.contacts if c.kind == "company" and c.verified)
            ws.append([i, a.company, a.designation, a.status, a.website or "", hr, co, a.day.isoformat()])
        for col, w in zip("ABCDEFGH", [5, 30, 30, 12, 35, 40, 40, 12]):
            ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="applications_{d}.xlsx"'})


# ---------- approval + search ----------
class Ids(BaseModel):
    ids: list[int]


def run_search(user_id: int, ids: list[int]):
    cfg = settings(user_id)
    for app_id in ids:
        with SessionLocal() as s:
            a = load(s, app_id, user_id)
            try:
                data = llm.find_contacts(cfg, a.company, a.designation)
                a.website = data.get("website")
                a.search_notes = data.get("notes")
                a.contacts.clear()
                seen = set()
                for e in data["emails"]:
                    email = (e.get("email") or "").strip().lower()
                    if not email or email in seen:
                        continue
                    seen.add(email)
                    ok, reason = verify(email, a.website, a.company)
                    a.contacts.append(Contact(email=email, kind=e.get("kind", "company"), source_url=e.get("source_url"),
                                              verified=ok, verify_reason=reason, selected=ok))
                a.status = "searched"
            except Exception as ex:  # keep going with the rest of the batch
                a.status = "error"
                a.search_notes = f"Search failed: {ex}"
            s.commit()
        time.sleep(5)  # stay under free-tier requests-per-minute


@app.post("/api/approve")
def approve(body: Ids, bg: BackgroundTasks, user: User = Depends(current_user)):
    if not settings(user.id)["gemini_api_key"]:
        raise HTTPException(400, "Add your Gemini API key in Settings first")
    with SessionLocal() as s:
        for i in body.ids:
            a = load(s, i, user.id)
            if a.status in ("pending", "error", "searched"):
                a.status = "searching"
        s.commit()
    bg.add_task(run_search, user.id, body.ids)
    return {"queued": len(body.ids)}


class ContactPatch(BaseModel):
    selected: bool | None = None


class NewContact(BaseModel):
    email: str
    kind: str = "hr"


@app.patch("/api/contacts/{cid}")
def patch_contact(cid: int, body: ContactPatch, user: User = Depends(current_user)):
    with SessionLocal() as s:
        c = s.scalar(select(Contact).join(Application)
                     .where(Contact.id == cid, Application.user_id == user.id))
        if not c:
            raise HTTPException(404)
        if body.selected is not None:
            c.selected = body.selected
        s.commit()
    return {"ok": True}


@app.post("/api/applications/{app_id}/contacts")
def add_contact(app_id: int, body: NewContact, user: User = Depends(current_user)):
    with SessionLocal() as s:
        a = load(s, app_id, user.id)
        ok, reason = verify(body.email, a.website, a.company)
        a.contacts.append(Contact(email=body.email.strip().lower(), kind=body.kind, verified=ok,
                                  verify_reason=f"added manually; {reason}", selected=True))
        s.commit()
        return serialize(load(s, app_id, user.id))


# ---------- email drafts ----------
@app.post("/api/generate")
def generate(body: Ids, user: User = Depends(current_user)):
    cfg, rt = settings(user.id), resume_text(user.id)
    if not cfg["gemini_api_key"]:
        raise HTTPException(400, "Add your Gemini API key in Settings first")
    out = []
    with SessionLocal() as s:
        for i in body.ids:
            a = load(s, i, user.id)
            try:
                d = llm.write_email(cfg, a.company, a.designation, cfg, rt)
            except Exception as ex:
                raise HTTPException(500, f"Gemini failed for {a.company}: {ex}")
            if a.draft:
                a.draft.subject, a.draft.body = d["subject"], d["body"]
            else:
                a.draft = EmailDraft(subject=d["subject"], body=d["body"])
            if a.status != "sent":
                a.status = "drafted"
            s.commit()
            out.append(serialize(load(s, i, user.id)))
    return out


class DraftPatch(BaseModel):
    subject: str
    body: str


@app.put("/api/applications/{app_id}/draft")
def save_draft(app_id: int, body: DraftPatch, user: User = Depends(current_user)):
    with SessionLocal() as s:
        a = load(s, app_id, user.id)
        if not a.draft:
            raise HTTPException(400, "Generate the email first")
        a.draft.subject, a.draft.body = body.subject, body.body
        s.commit()
    return {"ok": True}


def build_message(a: Application, user: User, cfg: dict) -> EmailMessage:
    to = [c.email for c in a.contacts if c.selected]
    if not to:
        raise HTTPException(400, f"No recipient selected for {a.company}")
    msg = EmailMessage()
    msg["To"] = ", ".join(to)
    msg["From"] = cfg["smtp_user"] or user.email
    msg["Subject"] = a.draft.subject
    msg.set_content(a.draft.body)
    pdf = resume_pdf(user.id)
    if pdf.exists():
        name = (cfg["name"] or "Resume").replace(" ", "_") + "_Resume.pdf"
        msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf", filename=name)
    return msg


@app.get("/api/applications/{app_id}/eml")
def download_eml(app_id: int, user: User = Depends(current_user)):
    """Opens in Outlook / Thunderbird / Mail as a ready draft with the resume attached."""
    with SessionLocal() as s:
        a = load(s, app_id, user.id)
        if not a.draft:
            raise HTTPException(400, "Generate the email first")
        msg = build_message(a, user, settings(user.id))
        msg["X-Unsent"] = "1"  # Outlook opens it as an editable draft
        safe = "".join(ch for ch in a.company if ch.isalnum() or ch in " _-").strip()
    return StreamingResponse(io.BytesIO(bytes(msg)), media_type="message/rfc822",
                             headers={"Content-Disposition": f'attachment; filename="{safe}.eml"'})


@app.post("/api/applications/{app_id}/send")
def send(app_id: int, user: User = Depends(current_user)):
    cfg = settings(user.id)
    host, smtp_user, pwd = cfg["smtp_host"], cfg["smtp_user"], cfg["smtp_password"]
    if not (host and smtp_user and pwd):
        raise HTTPException(400, "Add your email login (SMTP) in Settings, or use 'Download .eml' instead")
    with SessionLocal() as s:
        a = load(s, app_id, user.id)
        if not a.draft:
            raise HTTPException(400, "Generate the email first")
        msg = build_message(a, user, cfg)
        try:
            with smtplib.SMTP(host, int(cfg["smtp_port"] or 587), timeout=30) as smtp:
                smtp.starttls()
                smtp.login(smtp_user, pwd)
                smtp.send_message(msg)
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPServerDisconnected):
            raise HTTPException(400, "Email login failed. For Gmail, the SMTP password must be a 16-letter App Password "
                                     "(myaccount.google.com/apppasswords), not your normal password.")
        except (smtplib.SMTPException, OSError, ValueError) as ex:
            raise HTTPException(502, f"Sending failed: {ex}")
        a.draft.sent_at = datetime.now()
        a.status = "sent"
        s.commit()
        return serialize(load(s, app_id, user.id))


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
