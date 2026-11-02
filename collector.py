#!/usr/bin/env python3
"""Auto Review Collector.

Every day: read new AppFolio survey responses from Supabase, keep the ones rated 4 or 5 stars,
and email a thank-you (with a Google review link) to that resident. AppFolio surveys ONLY:
Google and Yelp reviews are never read and never emailed.

Safe by default: nothing is sent unless SEND_EMAILS=true (or --send). Each response is emailed
at most once (rc_email_log), and an address is emailed at most once per COOLDOWN_DAYS.
"""
import argparse
import os
import re
import smtplib
import sys
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage

import requests

TIMEOUT = 30
MIN_STARS = 4
# Which question holds the star rating for each AppFolio survey type (case-insensitive substring).
RATING_QUESTIONS = {
    "maintenance": "overall experience",
    "move-in": "recommend",
    "move-out": "experience with your property",
    "showing": "satisfied were you with the showing",
}


def env(name, default=None, required=False):
    v = os.environ.get(name, default)
    if required and not v:
        sys.exit(f"Missing required setting: {name}")
    return v


def rating_of(survey_type, questions):
    """Star rating (1-5) of one survey response, or None if it can't be determined."""
    key = RATING_QUESTIONS.get((survey_type or "").lower())
    if not key:
        return None
    for q in questions or []:
        if key in str(q.get("id", "")).lower():
            m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", str(q.get("value", "")))
            if m and 1 <= float(m.group(1)) <= 5:
                return int(float(m.group(1)))
    return None


def is_valid_email(s):
    return bool(s) and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s.strip()) is not None


def is_test(row):
    blob = f"{row.get('resident_name') or ''} {row.get('resident_email') or ''}"
    return re.search(r"\btest(er|ing)?\b", blob, re.I) is not None


class Supabase:
    def __init__(self, url, key):
        self.base = url.rstrip("/") + "/rest/v1"
        self.h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def get(self, table, params):
        out, start = [], 0
        while True:
            r = requests.get(f"{self.base}/{table}", params=params, timeout=TIMEOUT,
                             headers=dict(self.h, Range=f"{start}-{start + 999}"))
            if not r.ok:
                sys.exit(f"Supabase {r.status_code} reading {table}: {r.text[:300]}")
            out += r.json()
            if len(r.json()) < 1000:
                return out
            start += 1000

    def claim(self, row):
        """Insert the log row first. Returns False if this response was already claimed."""
        r = requests.post(f"{self.base}/rc_email_log", json=row, timeout=TIMEOUT,
                          headers=dict(self.h, Prefer="return=minimal"))
        if r.status_code == 409:
            return False
        if not r.ok:
            sys.exit(f"Supabase {r.status_code} writing rc_email_log: {r.text[:300]}")
        return True

    def finish(self, response_key, **fields):
        requests.patch(f"{self.base}/rc_email_log", params={"response_key": f"eq.{response_key}"},
                       json=fields, timeout=TIMEOUT, headers=self.h)


# One warm, specific line per survey type. {co} is the company name.
INTROS = {
    "maintenance": "It was our pleasure serving you, and we're so glad our maintenance team could help.",
    "move-in": "Welcome to the {co} family! We're delighted your move-in went so well and hope you love your new home.",
    "move-out": "Thank you for being part of the {co} family. We're sorry to see you go and wish you all the best in what's next.",
    "showing": "Thank you for visiting. It was a pleasure showing you around.",
}
DEFAULT_INTRO = "Thank you for the great feedback about your experience with {co}. It means a lot to our team."


def _button(url, label, color):
    return (f'<p style="margin:12px 0"><a href="{url}" style="background:{color};color:#fff;padding:12px 22px;'
            f'border-radius:6px;text-decoration:none;font-weight:bold;display:inline-block">{label}</a></p>')


def build_message(to, name, sender, sender_name, review_url, company, yelp_url=None, survey_type=None):
    intro = INTROS.get((survey_type or "").lower(), DEFAULT_INTRO).format(co=company)
    first = (name or "").strip().split(" ")[0].title() if name else ""
    hi = f"Hi {first}," if first else "Hi,"
    text = (f"{hi}\n\nThank you for your wonderful feedback! {intro}\n\n"
            f"If you have a minute, would you share it as a review? It helps future residents find us:\n"
            f"Google: {review_url}\n"
            + (f"Yelp: {yelp_url}\n" if yelp_url else "")
            + f"\nThank you again,\nThe {company} Team\n")
    html = (f"<p>{hi}</p><p>Thank you for your wonderful feedback! {intro}</p>"
            "<p>If you have a minute, would you share it as a review? "
            "It helps future residents find us:</p>"
            + _button(review_url, "Leave a Google review", "#4285F4")
            + (_button(yelp_url, "Leave a Yelp review", "#D32323") if yelp_url else "")
            + f"<p>Thank you again,<br>The {company} Team</p>")
    msg = EmailMessage()
    msg["Subject"] = f"Thank you from {company}"
    msg["From"] = f"{sender_name} <{sender}>"
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send_smtp(msg):
    host, port = env("SMTP_HOST", "smtp.gmail.com"), int(env("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port, timeout=TIMEOUT) as s:
        s.login(env("SMTP_USER", required=True), env("SMTP_PASSWORD", required=True))
        s.send_message(msg)


def select_candidates(rows, since, already_responses, recent_emails):
    """Pure function: which survey rows should get an email."""
    picked, seen = [], set(recent_emails)
    for r in rows:
        if r["response_key"] in already_responses:
            continue
        if (r.get("date_received") or "") < since:
            continue
        stars = rating_of(r.get("survey_type"), r.get("questions"))
        if stars is None or stars < MIN_STARS:
            continue
        email = (r.get("resident_email") or "").strip().lower()
        if not is_valid_email(email) or is_test(r) or email in seen:
            continue
        seen.add(email)
        picked.append(dict(r, stars=stars, email=email))
    return picked


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--send", action="store_true", help="actually send emails (same as SEND_EMAILS=true)")
    ap.add_argument("--lookback-days", type=int, default=int(env("LOOKBACK_DAYS", "3")))
    ap.add_argument("--limit", type=int, default=int(env("MAX_EMAILS_PER_RUN", "50")))
    args = ap.parse_args()
    send = args.send or env("SEND_EMAILS", "false").lower() == "true"

    db = Supabase(env("SUPABASE_URL", required=True), env("SUPABASE_SERVICE_KEY", required=True))
    since = (date.today() - timedelta(days=args.lookback_days)).isoformat()
    cooldown = int(env("COOLDOWN_DAYS", "90"))

    rows = db.get("rc_appfolio_candidates", {"select": "*", "date_received": f"gte.{since}"})
    log = db.get("rc_email_log", {"select": "response_key,email,created_at"})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=cooldown)).isoformat()
    done = {x["response_key"] for x in log}
    recent = {x["email"] for x in log if x["created_at"] >= cutoff}

    todo = select_candidates(rows, since, done, recent)
    print(f"{len(rows)} AppFolio responses since {since}; {len(todo)} rated {MIN_STARS}-5 stars with a usable email")
    if len(todo) > args.limit:
        print(f"Capping at {args.limit} emails this run (MAX_EMAILS_PER_RUN)")
        todo = todo[:args.limit]

    sent = 0
    for r in todo:
        label = f"{r['survey_type']} / {r['property']} / {r['stars']} stars / {r['email']}"
        if not send:
            print(f"[dry run] would email: {label}")
            continue
        if not db.claim({"response_key": r["response_key"], "email": r["email"],
                         "survey_type": r["survey_type"], "property": r["property"],
                         "rating": r["stars"], "status": "claimed"}):
            continue
        try:
            sender = env("SMTP_USER", required=True)
            send_smtp(build_message(r["email"], r.get("resident_name"), sender,
                                    env("SENDER_NAME", "Zuma Housing"),
                                    env("GOOGLE_REVIEW_URL", "https://search.google.com/local/writereview?placeid=ChIJcTynjYG8woARQfVrh25QzU4"),
                                    env("COMPANY_NAME", "Zuma Housing"),
                                    env("YELP_REVIEW_URL") or None, r.get("survey_type")))
            db.finish(r["response_key"], status="sent", sent_at=datetime.now(timezone.utc).isoformat())
            sent += 1
            print(f"sent: {label}")
        except Exception as e:  # keep going; the failure is recorded and not retried automatically
            db.finish(r["response_key"], status="failed", error=str(e)[:300])
            print(f"FAILED: {label}: {e}", file=sys.stderr)
    if send:
        print(f"done: {sent} sent")


if __name__ == "__main__":
    main()
