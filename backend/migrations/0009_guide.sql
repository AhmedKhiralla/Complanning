-- Getting-started help: each user's checklist visibility and the page tours already seen.
-- These are personal display preferences, not records, so they are left out of the audit trail.
ALTER TABLE users ADD COLUMN guide jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE OR REPLACE FUNCTION cp_audit_ignored(col text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT col IN ('created_at', 'created_by', 'updated_at', 'updated_by',
                 'last_login_at', 'failed_attempts', 'locked_until', 'kpis', 'replanned_at', 'guide')
$$;
