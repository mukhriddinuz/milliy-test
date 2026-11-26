"""Xatolarni yig'ish: bazasiz, kam resursli, Claude/dasturchi o'qishi uchun qulay.

Qanday ishlaydi:
  * Har bir ERROR darajali log (500 xatolar, bot handlerlaridagi xatolar, cron) shu handlerga tushadi.
  * Bir xil xatolar bitta yozuvga birlashtiriladi ("fingerprint" = xato turi + kodning qaysi qatori),
    faqat soni (count) va oxirgi vaqti yangilanadi. Shuning uchun 10 000 marta takrorlangan xato ham
    bitta yozuv bo'ladi.
  * Yozuvlar logs/errors.json faylida (eng ko'pi MAX_ENTRIES ta) — baza ishlatilmaydi.
  * Ko'rish: /_errors/?key=<ERROR_LOG_KEY> (matn) yoki `python manage.py errors`.
  * Ixtiyoriy: GITHUB_ERRORS_TOKEN berilsa, har bir YANGI xato uchun GitHub Issue ochiladi
    (repo ochiq bo'lgani uchun telefon, ID, token kabi ma'lumotlar yashiriladi).
"""
import fcntl
import hashlib
import json
import logging
import os
import re
import threading
import time
import traceback
from pathlib import Path

from django.conf import settings

MAX_ENTRIES = 100            # faylda saqlanadigan turli xatolar soni
MAX_TRACE_LINES = 60         # bitta xato uchun traceback qatorlari
WRITE_INTERVAL = 10          # bir xil xato faylga ko'pi bilan har 10 soniyada yoziladi
ISSUE_RECHECK = 6 * 60 * 60  # yopilgan issue qayta ochilishi kerakmi — 6 soatda bir tekshiriladi
ISSUES_PER_HOUR = 10         # xato "bo'roni"da GitHub'ga spam qilmaslik uchun

_pending = {}                # jarayon ichida hali faylga yozilmagan takrorlar: fp -> (count, last_seen)
_last_write = {}
_issue_times = []
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Shaxsiy ma'lumotlarni yashirish
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = [
    (re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,}"), "<BOT_TOKEN>"),
    (re.compile(r"(gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}"), "<GITHUB_TOKEN>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<EMAIL>"),
    (re.compile(r"\+?998[\s-]?\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}"), "<PHONE>"),
    (re.compile(r"(?<![\w.])-?\d{7,}(?![\w.])"), "<ID>"),  # telegram_id, chat_id, telefon
]


def sanitize(text):
    text = str(text or "")
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    for name in ("SECRET_KEY", "TELEGRAM_BOT_TOKEN", "GITHUB_ERRORS_TOKEN", "ERROR_LOG_KEY"):
        value = getattr(settings, name, None)
        if value and len(str(value)) >= 8:
            text = text.replace(str(value), f"<{name}>")
    return text


# ---------------------------------------------------------------------------
# Fayl
# ---------------------------------------------------------------------------

def errors_file():
    return Path(getattr(settings, "ERROR_LOG_FILE", settings.BASE_DIR / "logs" / "errors.json"))


class _FileLock:
    """Bir nechta jarayon (Passenger, cron) bir vaqtda yozganda fayl buzilmasligi uchun."""

    def __init__(self, path):
        self.path = path.with_suffix(".lock")

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "w")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def load_errors():
    try:
        with open(errors_file(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data):
    path = errors_file()
    if len(data) > MAX_ENTRIES:
        keep = sorted(data.items(), key=lambda kv: kv[1].get("last_seen", 0), reverse=True)[:MAX_ENTRIES]
        data = dict(keep)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def clear_errors(fingerprints=None):
    """Tuzatilgan xatolarni ro'yxatdan olib tashlash (hammasi yoki berilganlari)."""
    with _FileLock(errors_file()):
        data = load_errors()
        if fingerprints is None:
            removed = len(data)
            data = {}
        else:
            removed = sum(1 for fp in fingerprints if data.pop(fp, None) is not None)
        _save(data)
    return removed


# ---------------------------------------------------------------------------
# Log yozuvidan xato ma'lumotini olish
# ---------------------------------------------------------------------------

def _project_frame(tb_frames):
    """Loyiha kodidagi eng ichki qator (venv/kutubxona emas)."""
    base = str(settings.BASE_DIR)
    for frame in reversed(tb_frames):
        if frame.filename.startswith(base) and "/venv/" not in frame.filename and "site-packages" not in frame.filename:
            return frame
    return tb_frames[-1] if tb_frames else None


def _relpath(filename):
    base = str(settings.BASE_DIR) + os.sep
    return filename[len(base):] if filename.startswith(base) else filename.rsplit("site-packages/", 1)[-1]


def build_entry(record):
    request = getattr(record, "request", None)
    where = ""
    if request is not None and hasattr(request, "path"):
        where = f"{getattr(request, 'method', '')} {request.path}"

    if record.exc_info and record.exc_info[1] is not None:
        exc_type, exc, tb = record.exc_info
        frames = traceback.extract_tb(tb)
        frame = _project_frame(frames)
        location = f"{_relpath(frame.filename)}:{frame.lineno} ({frame.name})" if frame else "?"
        kind = exc_type.__name__
        message = str(exc)
        trace_lines = "".join(traceback.format_exception(exc_type, exc, tb)).splitlines()
        trace = "\n".join(trace_lines[-MAX_TRACE_LINES:])
        trace = trace.replace(str(settings.BASE_DIR) + os.sep, "")
        fp_source = f"{kind}|{location}"
    else:
        location = f"{_relpath(record.pathname)}:{record.lineno} ({record.funcName})"
        kind = f"log:{record.name}"
        message = record.getMessage()
        trace = ""
        # Xabardagi raqamlar (ID, son) har xil bo'lsa ham bitta xato hisoblanadi
        fp_source = f"{kind}|{location}|{re.sub(r'[0-9]+', '#', str(record.msg))[:200]}"

    fingerprint = hashlib.sha1(fp_source.encode()).hexdigest()[:12]
    return fingerprint, {
        "fingerprint": fingerprint,
        "type": kind,
        "message": sanitize(message)[:1000],
        "location": location,
        "logger": record.name,
        "where": sanitize(where),
        "log_message": sanitize(record.getMessage())[:300] if record.exc_info else "",
        "traceback": sanitize(trace),
    }


# ---------------------------------------------------------------------------
# Logging handler
# ---------------------------------------------------------------------------

class ErrorCollector(logging.Handler):
    def emit(self, record):
        try:
            self._emit(record)
        except Exception:
            pass  # log yozish hech qachon asosiy ishni buzmasligi kerak

    def _emit(self, record):
        fingerprint, entry = build_entry(record)
        now = time.time()
        with _lock:
            count, _ = _pending.get(fingerprint, (0, now))
            _pending[fingerprint] = (count + 1, now)
            if now - _last_write.get(fingerprint, 0) < WRITE_INTERVAL:
                return  # tez takrorlanayotgan xato — keyingi safar birga yoziladi
            _last_write[fingerprint] = now
            pending, _ = _pending.pop(fingerprint)

        new_issue = reopen_issue = None
        with _FileLock(errors_file()):
            data = load_errors()
            old = data.get(fingerprint)
            if old is None:
                entry.update(count=pending, first_seen=now, last_seen=now, issue=None)
                data[fingerprint] = entry
                new_issue = entry
            else:
                old.update({k: entry[k] for k in ("message", "where", "traceback", "log_message")})
                old["count"] = old.get("count", 0) + pending
                old["last_seen"] = now
                if old.get("issue") and now - old.get("issue_checked", 0) > ISSUE_RECHECK:
                    old["issue_checked"] = now
                    reopen_issue = old
            _save(data)

        if github_enabled() and (new_issue or reopen_issue):
            threading.Thread(target=_github_sync, args=(new_issue, reopen_issue), daemon=True).start()


# ---------------------------------------------------------------------------
# GitHub Issues (ixtiyoriy)
# ---------------------------------------------------------------------------

def github_enabled():
    return bool(getattr(settings, "GITHUB_ERRORS_TOKEN", None) and getattr(settings, "GITHUB_ERRORS_REPO", None))


def _github(method, path, payload=None):
    import requests

    return requests.request(
        method, f"https://api.github.com/repos/{settings.GITHUB_ERRORS_REPO}{path}", json=payload, timeout=8,
        headers={"Authorization": f"Bearer {settings.GITHUB_ERRORS_TOKEN}",
                 "Accept": "application/vnd.github+json", "User-Agent": "error-reporter"},
    )


def issue_body(e):
    return (
        f"Server avtomatik ochgan xato hisoboti.\n\n"
        f"- **Turi:** `{e['type']}`\n- **Joyi:** `{e['location']}`\n"
        f"- **So'rov:** `{e.get('where') or '—'}`\n- **Logger:** `{e['logger']}`\n"
        f"- **Fingerprint:** `{e['fingerprint']}`\n\n"
        f"**Xabar:**\n```\n{e['message']}\n```\n"
        + (f"\n**Log:** {e['log_message']}\n" if e.get("log_message") else "")
        + (f"\n**Traceback:**\n```python\n{e['traceback']}\n```\n" if e.get("traceback") else "")
        + "\n> Telefon, ID, token kabi ma'lumotlar yashirilgan (`<PHONE>`, `<ID>`, ...). "
          "Xato tuzatilgach issue'ni yoping — xato yana chiqsa, issue avtomatik qayta ochiladi."
    )


def _rate_ok():
    now = time.time()
    with _lock:
        _issue_times[:] = [t for t in _issue_times if now - t < 3600]
        if len(_issue_times) >= ISSUES_PER_HOUR:
            return False
        _issue_times.append(now)
        return True


def _github_sync(new_entry, recurring_entry):
    try:
        if new_entry and _rate_ok():
            title = f"[xato {new_entry['fingerprint']}] {new_entry['type']}: {new_entry['message'][:80]}"
            r = _github("POST", "/issues", {"title": title, "body": issue_body(new_entry), "labels": ["auto-error"]})
            if r.status_code == 201:
                _set_issue(new_entry["fingerprint"], r.json()["number"])
        if recurring_entry:
            number = recurring_entry["issue"]
            r = _github("GET", f"/issues/{number}")
            if r.status_code == 200 and r.json().get("state") == "closed" and _rate_ok():
                _github("PATCH", f"/issues/{number}", {"state": "open"})
                _github("POST", f"/issues/{number}/comments", {
                    "body": f"Xato yopilgandan keyin yana takrorlandi (jami {recurring_entry.get('count')} marta).\n\n"
                            f"```\n{recurring_entry['message']}\n```"})
    except Exception:
        pass


def _set_issue(fingerprint, number):
    with _FileLock(errors_file()):
        data = load_errors()
        if fingerprint in data:
            data[fingerprint]["issue"] = number
            data[fingerprint]["issue_checked"] = time.time()
            _save(data)


# ---------------------------------------------------------------------------
# Matn ko'rinishi
# ---------------------------------------------------------------------------

def render_text(data=None, limit=50):
    data = load_errors() if data is None else data
    entries = sorted(data.values(), key=lambda e: e.get("last_seen", 0), reverse=True)[:limit]
    if not entries:
        return "Xatolar yo'q.\n"
    fmt = lambda ts: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts or 0))
    out = [f"# Server xatolari ({len(data)} xil, eng oxirgisi birinchi)\n"]
    for e in entries:
        out.append(
            f"## [{e['fingerprint']}] {e['type']} — {e['count']} marta\n"
            f"Joyi: {e['location']}\nSo'rov: {e.get('where') or '—'}\n"
            f"Birinchi: {fmt(e.get('first_seen'))} | Oxirgi: {fmt(e.get('last_seen'))}"
            + (f" | GitHub issue #{e['issue']}" if e.get("issue") else "") + "\n"
            f"Xabar: {e['message']}\n"
            + (f"Log: {e['log_message']}\n" if e.get("log_message") else "")
            + (f"\n{e['traceback']}\n" if e.get("traceback") else "")
        )
    return "\n".join(out)
