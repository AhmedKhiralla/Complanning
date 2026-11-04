-- Complanning Phase 6: editing and releasing plans.
-- Locks: batches the planner placed by hand; the engine re-plans everything else around them.
-- Release: one plan per site is the official plan.

ALTER TABLE plans ADD COLUMN locks jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE plans ADD COLUMN released_at timestamptz;
ALTER TABLE plans ADD COLUMN released_by uuid;
ALTER TABLE plans ADD COLUMN replanned_at timestamptz;
ALTER TABLE plans DROP CONSTRAINT plans_status_check;
ALTER TABLE plans ADD CONSTRAINT plans_status_check CHECK (status IN ('draft', 'released', 'archived'));
CREATE UNIQUE INDEX plans_one_released_idx ON plans (site_id) WHERE status = 'released';

ALTER TABLE plan_batches ADD COLUMN ordinal integer NOT NULL DEFAULT 0;
ALTER TABLE plan_batches ADD COLUMN locked boolean NOT NULL DEFAULT false;
ALTER TABLE plan_operations ADD COLUMN locked boolean NOT NULL DEFAULT false;

-- The KPI summary is rewritten on every re-plan; the audit trail records the locks and status instead.
CREATE OR REPLACE FUNCTION cp_audit_ignored(col text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT col IN ('created_at', 'created_by', 'updated_at', 'updated_by',
                 'last_login_at', 'failed_attempts', 'locked_until', 'kpis', 'replanned_at')
$$;
