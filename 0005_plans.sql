-- Complanning Phase 5: production plans made by the planning engine.
-- A plan is a stored result: its batches, their operations on machines, the deliveries against the
-- sales plan, and pegging between batches. Running the engine again makes a new plan.

CREATE TABLE plans (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  site_id       uuid NOT NULL REFERENCES sites(id),
  name          text NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
  status        text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'archived')),
  objective     text NOT NULL CHECK (objective IN ('on_time', 'sales_value', 'utilization')),
  horizon_start date NOT NULL,
  horizon_end   date NOT NULL,
  plan_date     date NOT NULL,                       -- prices valid on this date are used
  starts_at     timestamptz NOT NULL,                -- the engine schedules from here
  options       jsonb NOT NULL DEFAULT '{}'::jsonb,
  kpis          jsonb,
  notes         text,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  CHECK (horizon_end >= horizon_start)
);
CREATE INDEX plans_site_idx ON plans (site_id, created_at DESC);

CREATE TABLE plan_batches (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  plan_id       uuid NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  batch_no      text NOT NULL,
  item_id       uuid NOT NULL REFERENCES items(id),
  level         integer NOT NULL DEFAULT 0,
  quantity      numeric(18, 3) NOT NULL,
  bom_version   integer,
  need_by       timestamptz,
  start_at      timestamptz,
  end_at        timestamptz,
  available_at  timestamptz,                         -- usable by the next stage (after holding and QC release)
  ship_at       timestamptz,                         -- finished goods: may be shipped
  status        text NOT NULL CHECK (status IN ('scheduled', 'unscheduled')),
  problem       text,
  value         numeric(18, 2),
  currency      text,
  UNIQUE (plan_id, batch_no)
);
CREATE INDEX plan_batches_plan_idx ON plan_batches (plan_id);

CREATE TABLE plan_operations (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id),
  plan_id            uuid NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  batch_id           uuid NOT NULL REFERENCES plan_batches(id) ON DELETE CASCADE,
  seq                integer NOT NULL,
  step_name          text NOT NULL,
  resource_id        uuid NOT NULL REFERENCES resources(id),
  changeover_start   timestamptz,
  changeover_end     timestamptz,
  changeover_minutes numeric(10, 2) NOT NULL DEFAULT 0,
  wait_minutes       numeric(10, 2) NOT NULL DEFAULT 0,
  changeover_kind    text,
  verification       text,
  reclean_minutes    numeric(10, 2) NOT NULL DEFAULT 0,
  start_at           timestamptz NOT NULL,
  end_at             timestamptz NOT NULL,
  work_minutes       numeric(12, 2) NOT NULL
);
CREATE INDEX plan_operations_plan_idx ON plan_operations (plan_id, resource_id, start_at);

-- Which batch (or stock) supplies which batch.
CREATE TABLE plan_links (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants(id),
  plan_id      uuid NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  supplier_id  uuid NOT NULL REFERENCES plan_batches(id) ON DELETE CASCADE,
  consumer_id  uuid NOT NULL REFERENCES plan_batches(id) ON DELETE CASCADE,
  quantity     numeric(18, 3) NOT NULL
);
CREATE INDEX plan_links_plan_idx ON plan_links (plan_id);

-- Deliveries: each sales plan line in the horizon and how the plan meets it.
CREATE TABLE plan_demand (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id),
  plan_id         uuid NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  demand_line_id  uuid,                              -- the sales plan line at the time of planning
  item_id         uuid NOT NULL REFERENCES items(id),
  market_id       uuid NOT NULL REFERENCES markets(id),
  month           date NOT NULL,
  due_date        date NOT NULL,
  requested       numeric(18, 3) NOT NULL,
  quantity        numeric(18, 3) NOT NULL,           -- after the market's sales limit
  from_stock      numeric(18, 3) NOT NULL DEFAULT 0,
  batches         text[],
  available_at    timestamptz,
  late_hours      numeric(10, 1),
  on_time         boolean NOT NULL DEFAULT false,
  price           numeric(18, 4),
  currency        text
);
CREATE INDEX plan_demand_plan_idx ON plan_demand (plan_id);

-- ---------------------------------------------------------------- stamping, audit, RLS, grants
-- plans: stamped and audited row by row. The generated detail tables are covered by the audited plan
-- row (with its KPIs) and are never edited in place in this phase.
CREATE TRIGGER plans_stamp BEFORE INSERT OR UPDATE ON plans FOR EACH ROW EXECUTE FUNCTION cp_stamp();
CREATE TRIGGER plans_audit AFTER INSERT OR UPDATE OR DELETE ON plans FOR EACH ROW EXECUTE FUNCTION cp_audit_row();

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['plans', 'plan_batches', 'plan_operations', 'plan_links', 'plan_demand'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %I ON %I USING (cp_tenant_only(tenant_id)) WITH CHECK (cp_tenant_only(tenant_id))', t || '_tenant', t);
    EXECUTE format('REVOKE ALL ON %I FROM PUBLIC', t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO cp_app', t);
  END LOOP;
END $$;
