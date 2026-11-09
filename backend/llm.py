import json
import re
import time

from google import genai
from google.genai import types

from . import crawl

_clients: dict[str, genai.Client] = {}
_no_grounding: set[str] = set()  # API keys whose Google Search quota is exhausted


def client(cfg: dict) -> genai.Client:
    key = cfg.get("gemini_api_key")
    if not key:
        raise RuntimeError("Add your Gemini API key in Settings")
    if key not in _clients:
        _clients[key] = genai.Client(api_key=key)
    return _clients[key]


def model(cfg: dict) -> str:
    return cfg.get("gemini_model") or "gemini-2.5-flash"


def _call(cfg: dict, **kwargs):
    """generate_content with backoff on 429 (free tier allows only a few requests per minute)."""
    for attempt in range(4):
        try:
            return client(cfg).models.generate_content(**kwargs)
        except Exception as ex:
            if "429" not in str(ex) or attempt == 3:
                raise
            m = re.search(r"retry in ([\d.]+)s|'retryDelay': '(\d+)s'", str(ex))
            wait = float(next(g for g in m.groups() if g)) if m else 15 * (attempt + 1)
            time.sleep(min(wait + 1, 70))


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def find_contacts(cfg: dict, company: str, designation: str) -> dict:
    """Use Gemini + Google Search grounding to find official/HR emails."""
    prompt = f"""Search the web for the official contact emails of the company "{company}"
(I'm applying for a "{designation}" role there).

Find:
1. The company's official website domain.
2. HR / careers / recruitment / talent-acquisition email addresses.
3. A general company contact email (info@, contact@, hello@ ...).

Rules:
- Only include emails you actually saw on a web page (company site, careers page, LinkedIn, job portals, press releases).
- Never guess or construct email patterns. If not found, return an empty list.
- Give the exact page URL where each email was found.

Reply ONLY with JSON:
{{"website": "https://...", "emails": [{{"email": "...", "kind": "hr" | "company", "source_url": "..."}}], "notes": "short note"}}"""
    if cfg.get("gemini_api_key") not in _no_grounding:
        try:
            # No retries here: when the search-tool quota is 0, waiting doesn't help.
            resp = client(cfg).models.generate_content(
                model=model(cfg),
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.1,
                ),
            )
            data = _extract_json(resp.text)
            data.setdefault("emails", [])
            if data["emails"]:
                return data
        except Exception as ex:
            if "429" not in str(ex):
                raise
            _no_grounding.add(cfg.get("gemini_api_key"))  # search quota exhausted; use the crawler from now on
    return crawl.find_contacts(company, official_website(cfg, company))


def official_website(cfg: dict, company: str) -> str | None:
    resp = _call(
        cfg,
        model=model(cfg),
        contents=f'What is the official website URL of the company "{company}"? '
                 'Reply ONLY with JSON: {"website": "https://..."} or {"website": null} if unsure.',
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
    )
    return _extract_json(resp.text).get("website")


def write_email(cfg: dict, company: str, designation: str, profile: dict, resume_text: str) -> dict:
    prompt = f"""Write a concise, professional job application email.

Company: {company}
Role: {designation}
Applicant name: {profile.get('name')}
Phone: {profile.get('phone')}
LinkedIn: {profile.get('linkedin')}
Applicant summary: {profile.get('summary')}
Resume text (may be empty): {resume_text[:4000]}

Guidelines:
- Tailor skills/achievements to what a "{designation}" needs; mention {company} by name.
- 120-180 words, plain text, no placeholders like [X], no markdown.
- Mention the resume is attached. End with a signature containing name, phone, LinkedIn.

Reply ONLY with JSON: {{"subject": "...", "body": "..."}}"""
    resp = _call(
        cfg,
        model=model(cfg),
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.7, response_mime_type="application/json"),
    )
    data = _extract_json(resp.text)
    return {
        "subject": data.get("subject") or f"Application for {designation} - {profile.get('name')}",
        "body": data.get("body") or "",
    }
