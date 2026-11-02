-- Run once in the Supabase SQL Editor. It creates a log table and one private view.
-- It does not change or delete any existing table.
--

create table if not exists public.rc_email_log (
  response_key text primary key,          -- one email per survey response, ever
  email        text not null,
  survey_type  text,
  property     text,
  rating       int,
  status       text not null default 'claimed',   -- claimed | sent | failed
  error        text,
  sent_at      timestamptz,
  created_at   timestamptz not null default now()
);
alter table public.rc_email_log enable row level security;   -- no policies: only the service key can use it

-- AppFolio surveys joined to a resident email. An email is used only when the name matches exactly
-- one address, so two residents with the same name are skipped rather than mixed up.
create or replace view public.rc_appfolio_candidates as
select
  md5(coalesce(s.survey_type::text, '') || '|' || coalesce(s.survey_id::text, '')) as response_key,
  s.survey_type,
  s.property,
  s.date_received,
  s.tenant as resident_name,
  (select min(c.email)
     from appfolio.tenants c
    where lower(btrim(c.name)) = lower(btrim(s.tenant))
   having count(distinct lower(c.email)) = 1) as resident_email,
  s.questions
from appfolio.survey_responses s;

revoke all on public.rc_appfolio_candidates from anon, authenticated;
grant select on public.rc_appfolio_candidates to service_role;
grant select, insert, update on public.rc_email_log to service_role;
