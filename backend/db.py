import os
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import (URL, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, create_engine, inspect,
                        text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")
SQLITE_URL = f"sqlite:///{DATA_DIR / 'jobs.db'}"


def database_url() -> URL | str:
    """Postgres (e.g. Supabase) from DB_* settings or DATABASE_URL in .env; otherwise the local SQLite file."""
    if os.getenv("DB_HOST"):
        # Separate fields, so passwords with @ : / # don't need URL-encoding
        return URL.create("postgresql+psycopg", username=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
                          host=os.getenv("DB_HOST"), port=int(os.getenv("DB_PORT", "5432")),
                          database=os.getenv("DB_NAME", "postgres"), query={"sslmode": "require"})
    url = os.getenv("DATABASE_URL", "")
    if url.startswith(("postgres://", "postgresql://")):
        return "postgresql+psycopg://" + url.split("://", 1)[1]
    return url or SQLITE_URL


def make_engine(url):
    if str(url).startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # pre_ping/recycle: Supabase's pooler drops idle connections
    return create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5)


engine = make_engine(database_url())
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class UserSetting(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # secrets are stored encrypted


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    day: Mapped[date] = mapped_column(Date, index=True, default=date.today)
    company: Mapped[str] = mapped_column(String(200))
    designation: Mapped[str] = mapped_column(String(200))
    # pending -> searching -> searched -> drafted -> sent
    status: Mapped[str] = mapped_column(String(20), default="pending")
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    search_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    contacts: Mapped[list["Contact"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    draft: Mapped["EmailDraft | None"] = relationship(back_populates="application", cascade="all, delete-orphan", uselist=False)


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # hr | company
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verify_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=True)

    application: Mapped[Application] = relationship(back_populates="contacts")


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), unique=True)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    application: Mapped[Application] = relationship(back_populates="draft")


def _migrate():
    """Upgrade a single-user database in place: add applications.user_id and keep the old settings table."""
    insp = inspect(engine)
    with engine.begin() as con:
        if "applications" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("applications")}
            if "user_id" not in cols:
                con.execute(text("ALTER TABLE applications ADD COLUMN user_id INTEGER REFERENCES users(id)"))
        if "settings" in insp.get_table_names():
            con.execute(text("ALTER TABLE settings RENAME TO settings_legacy"))


if engine.dialect.name == "sqlite":
    _migrate()
Base.metadata.create_all(engine)
