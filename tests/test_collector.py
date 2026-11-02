import collector as c

Q = lambda text, val: {"id": text, "value": val}


def test_rating_per_survey_type():
    assert c.rating_of("maintenance", [Q("How satisfied are you with the overall experience?", "5")]) == 5
    assert c.rating_of("move-in", [Q("How likely are you to recommend us to somebody else?", "4")]) == 4
    assert c.rating_of("move-out", [Q("Rate your experience with your property:", "1")]) == 1
    assert c.rating_of("maintenance", [Q("Any additional feedback?", "great")]) is None
    assert c.rating_of("unknown", [Q("overall experience", "5")]) is None


def row(key, stars, email="a@b.com", date="2026-11-01", name="Ana Lopez"):
    return {"response_key": key, "survey_type": "maintenance", "property": "P", "date_received": date,
            "resident_name": name, "resident_email": email,
            "questions": [Q("How satisfied are you with the overall experience?", str(stars))]}


def test_selection_rules():
    rows = [row("1", 5), row("2", 4, "c@d.com"), row("3", 3, "e@f.com"), row("4", 5, ""), row("5", 5, "bad"),
            row("6", 5, "g@h.com", name="Test User"), row("7", 5, "i@j.com", date="2026-01-01"),
            row("8", 5, "k@l.com"), row("9", 5, "A@B.com")]
    out = c.select_candidates(rows, "2026-10-29", already_responses={"8"}, recent_emails={"zz@zz.com"})
    assert [r["response_key"] for r in out] == ["1", "2"]   # 9 is a duplicate address of 1


def test_email_message():
    m = c.build_message("a@b.com", "ana lopez", "me@zuma.com", "Zuma", "https://x.y/review", "Zuma Housing")
    assert m["To"] == "a@b.com" and "Hi Ana," in m.get_body(("plain",)).get_content()
    assert "https://x.y/review" in m.get_body(("html",)).get_content()


def test_yelp_link_optional():
    m = c.build_message("a@b.com", "ana", "me@zuma.com", "Zuma", "https://g/r", "Zuma Housing", "https://yelp/r")
    assert "https://yelp/r" in m.get_body(("plain",)).get_content()
    assert "https://yelp/r" in m.get_body(("html",)).get_content()
    m = c.build_message("a@b.com", "ana", "me@zuma.com", "Zuma", "https://g/r", "Zuma Housing")
    assert "yelp" not in m.get_body(("plain",)).get_content().lower()
