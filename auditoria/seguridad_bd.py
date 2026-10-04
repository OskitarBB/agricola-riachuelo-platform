"""Supabase/PostgreSQL security helpers.

Run from a migration or management command when the production database is
ready. The intent is explicit: browser/API roles must not read tables directly.
"""


RLS_SQL = [
    "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;",
    "REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;",
]
