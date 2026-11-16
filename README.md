# Auto Google and Yelp Review Collector

Every day this scans **new AppFolio survey responses** in Supabase, keeps the ones rated **4 or 5 stars**,
and emails that resident a thank-you with links to leave a Google (and optionally Yelp) review. Set the repo variable `YELP_REVIEW_URL` to include Yelp.

* AppFolio surveys only. Google and Yelp reviews are never read or emailed.
* One email per survey response, ever, and at most one per address every 90 days (`rc_email_log`).
* Looks back 7 days (a survey is never emailed twice), runs twice a day as a backup, and skips responses with no email, an unmatched/ambiguous name, or "test" in the name/email.
* **Dry run by default.** Nothing is sent until `SEND_EMAILS=true`.

Star rating used per survey: maintenance = overall experience, move-in = likelihood to recommend,
move-out = experience with your property, showing = satisfaction with the showing.

## Setup
1. In the Supabase SQL Editor, edit and run `supabase/rc_setup.sql` (fill in the contacts table/columns).
2. Create a Google app password for the sending mailbox.
3. In this repo: Settings > Secrets and variables > Actions. Add secrets `SUPABASE_URL`,
   `SUPABASE_SERVICE_KEY`, `SMTP_USER`, `SMTP_PASSWORD`. Leave the variable `SEND_EMAILS` unset.
4. Actions > "Daily review email" > Run workflow (send = false) and read the dry-run log.
5. When the list looks right, set the repo variable `SEND_EMAILS` to `true`.

Local: `pip install -r requirements.txt && python -m pytest && python collector.py`
