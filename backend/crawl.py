"""Fallback email finder: read the company's own website and collect emails printed on it."""
import re
import urllib.request
from html import unescape
from urllib.parse import urljoin, urlparse

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HREF_RE = re.compile(r'href=["\']([^"\'#]+)', re.I)
HR_WORDS = ("hr", "career", "job", "recruit", "talent", "hiring", "people", "resume", "cv")
PAGE_WORDS = ("contact", "career", "job", "about", "join", "hiring", "work-with-us")
SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
JUNK = ("abuse", "privacy", "legal", "cancel", "renewal", "upgrade", "noreply", "no-reply", "press", "pr@",
        "billing", "security", "dpo", "gdpr", "unsubscribe", "webmaster", "media")
GOOD = ("info", "contact", "hello", "enquir", "inquir", "connect", "office", "admin")
COMMON_PATHS = ["", "/contact", "/contact-us", "/careers", "/jobs", "/about", "/about-us"]


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (JobMailer)"})
    with urllib.request.urlopen(req, timeout=10) as r:
        if "html" not in r.headers.get("Content-Type", ""):
            return ""
        return r.read(1_500_000).decode("utf-8", "ignore")


def find_contacts(company: str, website: str | None) -> dict:
    if not website:
        return {"website": None, "emails": [], "notes": "Could not determine the company website"}
    if not website.startswith("http"):
        website = "https://" + website
    host = urlparse(website).netloc
    queue = [urljoin(website, p) for p in COMMON_PATHS]
    seen_pages, found = set(), {}
    while queue and len(seen_pages) < 12:
        url = queue.pop(0).rstrip("/")
        if url in seen_pages:
            continue
        seen_pages.add(url)
        try:
            html = unescape(_get(url))
        except Exception:
            continue
        for e in EMAIL_RE.findall(html.replace("[at]", "@").replace("(at)", "@")):
            e = e.lower().strip(".")
            if e.endswith(SKIP_EXT) or "example" in e or "sentry" in e or e in found or any(j in e for j in JUNK):
                continue
            kind = "hr" if any(w in e.split("@")[0] for w in HR_WORDS) else "company"
            found[e] = {"email": e, "kind": kind, "source_url": url}
        # follow contact/career links on the same site
        for href in HREF_RE.findall(html):
            link = urljoin(url + "/", href)
            if urlparse(link).netloc == host and any(w in link.lower() for w in PAGE_WORDS):
                queue.append(link)
    # HR emails first, then generic company inboxes; keep the list short
    def rank(c):
        local = c["email"].split("@")[0]
        return 0 if c["kind"] == "hr" else 1 if any(g in local for g in GOOD) else 2
    emails = sorted(found.values(), key=rank)[:5]
    note = f"Crawled {len(seen_pages)} pages on {host}"
    return {"website": website, "emails": emails,
            "notes": note if found else note + " — no emails published on the site"}
