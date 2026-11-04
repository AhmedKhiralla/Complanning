-- Complanning Phase 2: master data
-- Units, items, markets and prices, bills of materials, resources and routings, calendars.
-- Business data is visible only inside its own company (cp_tenant_only): the platform
-- administrator does not see it.

-- ---------------------------------------------------------------- units of measure
CREATE TABLE uoms (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES tenants(id),
  code           text NOT NULL CHECK (code ~ '^[A-Za-z0-9][A-Za-z0-9_./-]{0,11}$'),
  name_en        text NOT NULL,
  name_ar        text,
  dimension      text NOT NULL CHECK (dimension IN ('mass', 'volume', 'count', 'time', 'energy', 'gas', 'other')),
  -- Size of one unit in the dimension's base unit (kg, L, h, kWh, Nm3). Count units convert per item.
  factor_to_base numeric(20, 10) NOT NULL DEFAULT 1 CHECK (factor_to_base > 0),
  is_system      boolean NOT NULL DEFAULT false,
  active         boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at     timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  UNIQUE (tenant_id, code)
);

-- ---------------------------------------------------------------- items
CREATE TABLE items (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id),
  code               text NOT NULL CHECK (code ~ '^[A-Za-z0-9][A-Za-z0-9_./-]{0,39}$'),
  name_en            text NOT NULL CHECK (length(trim(name_en)) > 0),
  name_ar            text,
  type               text NOT NULL CHECK (type IN ('raw_material', 'packaging', 'wip', 'semi_finished', 'finished')),
  stock_uom_id       uuid NOT NULL REFERENCES uoms(id),
  dispensing_uom_id  uuid REFERENCES uoms(id),
  density_kg_per_l   numeric(12, 6) CHECK (density_kg_per_l > 0),
  description        text,
  grade              text,
  dosage_form        text,
  cleaning_group     text,
  lead_time_days     integer CHECK (lead_time_days >= 0),
  moq                numeric(18, 4) CHECK (moq >= 0),
  safety_stock       numeric(18, 4) CHECK (safety_stock >= 0),
  qc_release_days    numeric(8, 2) CHECK (qc_release_days >= 0),
  shelf_life_months  integer CHECK (shelf_life_months > 0),
  pack_size          numeric(18, 4) CHECK (pack_size > 0),
  units_per_shipper  integer CHECK (units_per_shipper > 0),
  standard_cost      numeric(18, 4) CHECK (standard_cost >= 0),
  test_before_sale   boolean NOT NULL DEFAULT false,
  release_lead_days  numeric(8, 2) CHECK (release_lead_days >= 0),
  active             boolean NOT NULL DEFAULT true,
  created_at         timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at         timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  UNIQUE (tenant_id, code)
);
CREATE INDEX items_tenant_type_idx ON items (tenant_id, type);

-- Item-specific pack conversions: 1 <uom> = factor <stock unit>, e.g. 1 carton = 30 tablets.
CREATE TABLE item_uom_conversions (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  item_id     uuid NOT NULL REFERENCES items(id),
  uom_id      uuid NOT NULL REFERENCES uoms(id),
  factor      numeric(20, 10) NOT NULL CHECK (factor > 0),
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  UNIQUE (item_id, uom_id)
);

-- ---------------------------------------------------------------- markets and prices
CREATE TABLE markets (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  code        text NOT NULL CHECK (code ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$'),
  name_en     text NOT NULL,
  name_ar     text,
  currency    char(3) NOT NULL DEFAULT 'EGP',
  active      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  UNIQUE (tenant_id, code)
);

-- Per finished item and market: sales limits and shelf-life requirement.
CREATE TABLE item_markets (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id                uuid NOT NULL REFERENCES tenants(id),
  item_id                  uuid NOT NULL REFERENCES items(id),
  market_id                uuid NOT NULL REFERENCES markets(id),
  max_sellable_per_month   numeric(18, 4) CHECK (max_sellable_per_month >= 0),
  min_remaining_shelf_pct  numeric(5, 2) CHECK (min_remaining_shelf_pct BETWEEN 0 AND 100),
  active                   boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  UNIQUE (item_id, market_id)
);

-- Prices are never overwritten: a price is ended (valid_to) and a new one added.
CREATE TABLE prices (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  item_id     uuid NOT NULL REFERENCES items(id),
  market_id   uuid NOT NULL REFERENCES markets(id),
  price       numeric(18, 4) NOT NULL CHECK (price >= 0),
  currency    char(3) NOT NULL,
  valid_from  date NOT NULL,
  valid_to    date,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE INDEX prices_item_market_idx ON prices (item_id, market_id, valid_from);

CREATE OR REPLACE FUNCTION cp_price_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.price IS DISTINCT FROM OLD.price OR NEW.currency IS DISTINCT FROM OLD.currency
       OR NEW.valid_from IS DISTINCT FROM OLD.valid_from OR NEW.item_id IS DISTINCT FROM OLD.item_id
       OR NEW.market_id IS DISTINCT FROM OLD.market_id THEN
      RAISE EXCEPTION 'A price cannot be changed; end it and add a new price.' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.valid_to IS NOT NULL THEN
      RAISE EXCEPTION 'This price has already ended.' USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  IF EXISTS (
    SELECT 1 FROM prices p
     WHERE p.item_id = NEW.item_id AND p.market_id = NEW.market_id AND p.id <> NEW.id
       AND daterange(p.valid_from, p.valid_to, '[]') && daterange(NEW.valid_from, NEW.valid_to, '[]')
  ) THEN
    RAISE EXCEPTION 'Price periods for the same item and market cannot overlap.' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER prices_guard BEFORE INSERT OR UPDATE ON prices FOR EACH ROW EXECUTE FUNCTION cp_price_guard();

-- ---------------------------------------------------------------- bills of materials
CREATE TABLE boms (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES tenants(id),
  item_id        uuid NOT NULL REFERENCES items(id),
  version        integer NOT NULL CHECK (version > 0),
  status         text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),
  valid_from     date,
  valid_to       date,
  batch_size     numeric(18, 4) NOT NULL CHECK (batch_size > 0),
  batch_uom_id   uuid NOT NULL REFERENCES uoms(id),
  yield_pct      numeric(6, 2) NOT NULL DEFAULT 100 CHECK (yield_pct > 0 AND yield_pct <= 100),
  batch_mode     text NOT NULL DEFAULT 'fixed' CHECK (batch_mode IN ('fixed', 'partial')),
  min_batch_pct  numeric(6, 2) CHECK (min_batch_pct > 0 AND min_batch_pct <= 100),
  notes          text,
  created_at     timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at     timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  UNIQUE (item_id, version)
);
CREATE UNIQUE INDEX boms_one_active_idx ON boms (item_id) WHERE status = 'active';

CREATE TABLE bom_lines (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id),
  bom_id             uuid NOT NULL REFERENCES boms(id),
  line_no            integer NOT NULL CHECK (line_no > 0),
  component_item_id  uuid NOT NULL REFERENCES items(id),
  quantity           numeric(20, 6) NOT NULL CHECK (quantity > 0),
  uom_id             uuid NOT NULL REFERENCES uoms(id),
  assay_compensated  boolean NOT NULL DEFAULT false,
  overage_pct        numeric(6, 2) NOT NULL DEFAULT 0 CHECK (overage_pct >= 0 AND overage_pct <= 100),
  is_compensating    boolean NOT NULL DEFAULT false,
  notes              text,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  CONSTRAINT bom_lines_line_no_key UNIQUE (bom_id, line_no) DEFERRABLE INITIALLY DEFERRED,
  CHECK (NOT (is_compensating AND assay_compensated))
);
CREATE UNIQUE INDEX bom_lines_one_compensating_idx ON bom_lines (bom_id) WHERE is_compensating;

-- Lines of an active or archived version are frozen; create a new version instead.
CREATE OR REPLACE FUNCTION cp_bom_line_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE st text;
BEGIN
  SELECT status INTO st FROM boms WHERE id = coalesce(NEW.bom_id, OLD.bom_id);
  IF st <> 'draft' THEN
    RAISE EXCEPTION 'Only draft versions can be edited; create a new version.' USING ERRCODE = 'check_violation';
  END IF;
  RETURN coalesce(NEW, OLD);
END $$;
CREATE TRIGGER bom_lines_guard BEFORE INSERT OR UPDATE OR DELETE ON bom_lines FOR EACH ROW EXECUTE FUNCTION cp_bom_line_guard();

-- ---------------------------------------------------------------- resources and routings (per site)
CREATE TABLE resources (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id),
  site_id         uuid NOT NULL REFERENCES sites(id),
  code            text NOT NULL CHECK (code ~ '^[A-Za-z0-9][A-Za-z0-9_./-]{0,19}$'),
  name_en         text NOT NULL CHECK (length(trim(name_en)) > 0),
  name_ar         text,
  type            text NOT NULL DEFAULT 'machine' CHECK (type IN ('machine', 'qc_lab', 'room', 'operator_group')),
  area            text,
  location        text,
  efficiency_pct  numeric(6, 2) NOT NULL DEFAULT 100 CHECK (efficiency_pct > 0 AND efficiency_pct <= 100),
  notes           text,
  active          boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  UNIQUE (site_id, code)
);

CREATE TABLE routings (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  site_id     uuid NOT NULL REFERENCES sites(id),
  item_id     uuid NOT NULL REFERENCES items(id),
  notes       text,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  UNIQUE (site_id, item_id)
);

CREATE TABLE routing_steps (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES tenants(id),
  routing_id     uuid NOT NULL REFERENCES routings(id),
  seq            integer NOT NULL CHECK (seq > 0),
  name           text NOT NULL CHECK (length(trim(name)) > 0),
  time_model     text NOT NULL CHECK (time_model IN ('fixed', 'rate')),
  fixed_minutes  numeric(12, 2) CHECK (fixed_minutes > 0),
  rate_per_hour  numeric(18, 4) CHECK (rate_per_hour > 0),
  setup_minutes  numeric(12, 2) NOT NULL DEFAULT 0 CHECK (setup_minutes >= 0),
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  CHECK ((time_model = 'fixed' AND fixed_minutes IS NOT NULL) OR (time_model = 'rate' AND rate_per_hour IS NOT NULL))
);
CREATE INDEX routing_steps_routing_idx ON routing_steps (routing_id, seq);
ALTER TABLE routing_steps ADD CONSTRAINT routing_steps_seq_key UNIQUE (routing_id, seq) DEFERRABLE INITIALLY DEFERRED;

-- Qualified resources for a step; the preferred one is tried first. Optional own speed.
CREATE TABLE routing_step_resources (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES tenants(id),
  step_id        uuid NOT NULL REFERENCES routing_steps(id),
  resource_id    uuid NOT NULL REFERENCES resources(id),
  preferred      boolean NOT NULL DEFAULT false,
  fixed_minutes  numeric(12, 2) CHECK (fixed_minutes > 0),
  rate_per_hour  numeric(18, 4) CHECK (rate_per_hour > 0),
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  UNIQUE (step_id, resource_id)
);

-- ---------------------------------------------------------------- calendars (per site)
-- A period with its own shift pattern, for example Ramadan. Shifts without a period are the default.
CREATE TABLE calendar_periods (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  site_id     uuid NOT NULL REFERENCES sites(id),
  name        text NOT NULL,
  start_date  date NOT NULL,
  end_date    date NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  CHECK (end_date >= start_date)
);

CREATE TABLE shifts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  site_id     uuid NOT NULL REFERENCES sites(id),
  period_id   uuid REFERENCES calendar_periods(id),
  weekday     smallint NOT NULL CHECK (weekday BETWEEN 1 AND 7),   -- ISO: 1 Monday ... 7 Sunday
  name        text NOT NULL,
  start_time  time NOT NULL,
  end_time    time NOT NULL,                                       -- end <= start means it ends next day
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid
);
CREATE INDEX shifts_site_idx ON shifts (site_id, period_id, weekday);

CREATE TABLE holidays (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  site_id     uuid NOT NULL REFERENCES sites(id),
  date        date NOT NULL,
  name        text NOT NULL,
  source      text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'imported')),
  estimated   boolean NOT NULL DEFAULT false,
  confirmed   boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  UNIQUE (site_id, date)
);

CREATE TABLE resource_exceptions (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants(id),
  site_id      uuid NOT NULL REFERENCES sites(id),
  resource_id  uuid NOT NULL REFERENCES resources(id),
  starts_at    timestamptz NOT NULL,
  ends_at      timestamptz NOT NULL,
  reason       text NOT NULL CHECK (reason IN ('maintenance', 'calibration', 'qualification', 'breakdown', 'other')),
  notes        text,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  CHECK (ends_at > starts_at)
);
CREATE INDEX resource_exceptions_idx ON resource_exceptions (resource_id, starts_at);

-- ---------------------------------------------------------------- stamping, audit, RLS, grants
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['uoms', 'items', 'item_uom_conversions', 'markets', 'item_markets', 'prices',
                           'boms', 'bom_lines', 'resources', 'routings', 'routing_steps',
                           'routing_step_resources', 'calendar_periods', 'shifts', 'holidays',
                           'resource_exceptions'] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION cp_stamp()', t || '_stamp', t);
    EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION cp_audit_row()', t || '_audit', t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %I ON %I USING (cp_tenant_only(tenant_id)) WITH CHECK (cp_tenant_only(tenant_id))', t || '_tenant', t);
    EXECUTE format('REVOKE ALL ON %I FROM PUBLIC', t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %I TO cp_app', t);
  END LOOP;
END $$;

-- Rows that can be removed (removal is audited with the old values).
GRANT DELETE ON item_uom_conversions, item_markets, bom_lines, routing_steps, routing_step_resources,
                calendar_periods, shifts, holidays, resource_exceptions TO cp_app;
-- Draft BOM versions can be discarded.
GRANT DELETE ON boms TO cp_app;

-- Readable record labels in the audit trail for the new tables.
CREATE OR REPLACE FUNCTION cp_audit_row() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  old_j  jsonb := CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END;
  new_j  jsonb := CASE WHEN TG_OP IN ('UPDATE', 'INSERT') THEN to_jsonb(NEW) END;
  ref_j  jsonb := coalesce(new_j, old_j);
  o      jsonb := '{}'::jsonb;
  n      jsonb := '{}'::jsonb;
  k      text;
  v_tenant uuid;
  v_label  text;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    FOR k IN SELECT jsonb_object_keys(new_j) LOOP
      CONTINUE WHEN cp_audit_ignored(k);
      IF (old_j -> k) IS DISTINCT FROM (new_j -> k) THEN
        IF cp_audit_redacted(k) THEN
          o := o || jsonb_build_object(k, '[redacted]');
          n := n || jsonb_build_object(k, '[changed]');
        ELSE
          o := o || jsonb_build_object(k, old_j -> k);
          n := n || jsonb_build_object(k, new_j -> k);
        END IF;
      END IF;
    END LOOP;
    IF n = '{}'::jsonb THEN
      RETURN NEW;
    END IF;
  ELSE
    FOR k IN SELECT jsonb_object_keys(ref_j) LOOP
      CONTINUE WHEN cp_audit_ignored(k);
      IF cp_audit_redacted(k) THEN
        IF TG_OP = 'INSERT' THEN n := n || jsonb_build_object(k, '[set]'); END IF;
      ELSIF TG_OP = 'INSERT' THEN
        n := n || jsonb_build_object(k, ref_j -> k);
      ELSE
        o := o || jsonb_build_object(k, ref_j -> k);
      END IF;
    END LOOP;
  END IF;

  IF TG_TABLE_NAME = 'tenants' THEN
    v_tenant := (ref_j ->> 'id')::uuid;
  ELSE
    v_tenant := (ref_j ->> 'tenant_id')::uuid;
  END IF;

  v_label := coalesce(ref_j ->> 'code', ref_j ->> 'email', ref_j ->> 'name', ref_j ->> 'role');
  IF v_label IS NULL THEN
    v_label := CASE TG_TABLE_NAME
      WHEN 'boms' THEN (SELECT i.code FROM items i WHERE i.id = (ref_j ->> 'item_id')::uuid) || ' v' || (ref_j ->> 'version')
      WHEN 'bom_lines' THEN (SELECT i.code || ' v' || b.version FROM boms b JOIN items i ON i.id = b.item_id
                              WHERE b.id = (ref_j ->> 'bom_id')::uuid) || ' line ' || (ref_j ->> 'line_no')
      WHEN 'prices' THEN (SELECT i.code FROM items i WHERE i.id = (ref_j ->> 'item_id')::uuid)
                         || ' / ' || (SELECT m.code FROM markets m WHERE m.id = (ref_j ->> 'market_id')::uuid)
      WHEN 'item_markets' THEN (SELECT i.code FROM items i WHERE i.id = (ref_j ->> 'item_id')::uuid)
                         || ' / ' || (SELECT m.code FROM markets m WHERE m.id = (ref_j ->> 'market_id')::uuid)
      WHEN 'item_uom_conversions' THEN (SELECT i.code FROM items i WHERE i.id = (ref_j ->> 'item_id')::uuid)
                         || ' / ' || (SELECT u.code FROM uoms u WHERE u.id = (ref_j ->> 'uom_id')::uuid)
      WHEN 'routings' THEN (SELECT i.code FROM items i WHERE i.id = (ref_j ->> 'item_id')::uuid)
      WHEN 'routing_step_resources' THEN (SELECT r.code FROM resources r WHERE r.id = (ref_j ->> 'resource_id')::uuid)
      WHEN 'resource_exceptions' THEN (SELECT r.code FROM resources r WHERE r.id = (ref_j ->> 'resource_id')::uuid)
                         || ' ' || (ref_j ->> 'reason')
      WHEN 'holidays' THEN ref_j ->> 'date'
      ELSE NULL END;
  END IF;

  INSERT INTO audit_log (tenant_id, site_id, user_id, user_name, action, entity,
                         record_id, record_label, old_values, new_values)
  VALUES (
    v_tenant,
    CASE WHEN TG_TABLE_NAME = 'sites' THEN (ref_j ->> 'id')::uuid
         ELSE (ref_j ->> 'site_id')::uuid END,
    cp_current_user_id(),
    coalesce(cp_setting('app.user_name'), 'system'),
    TG_OP,
    TG_TABLE_NAME,
    ref_j ->> 'id',
    v_label,
    CASE WHEN o = '{}'::jsonb THEN NULL ELSE o END,
    CASE WHEN n = '{}'::jsonb THEN NULL ELSE n END
  );
  RETURN coalesce(NEW, OLD);
END $$;

-- ---------------------------------------------------------------- default units
CREATE OR REPLACE FUNCTION cp_seed_uoms(p_tenant uuid) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  INSERT INTO uoms (tenant_id, code, name_en, name_ar, dimension, factor_to_base, is_system)
  SELECT p_tenant, v.code, v.en, v.ar, v.dim, v.f, true
    FROM (VALUES
      ('KG', 'Kilogram', 'كيلوجرام', 'mass', 1::numeric),
      ('G', 'Gram', 'جرام', 'mass', 0.001),
      ('MG', 'Milligram', 'مليجرام', 'mass', 0.000001),
      ('T', 'Tonne', 'طن', 'mass', 1000),
      ('L', 'Litre', 'لتر', 'volume', 1),
      ('ML', 'Millilitre', 'مليلتر', 'volume', 0.001),
      ('M3', 'Cubic metre', 'متر مكعب', 'volume', 1000),
      ('EA', 'Unit', 'وحدة', 'count', 1),
      ('TAB', 'Tablet', 'قرص', 'count', 1),
      ('CAP', 'Capsule', 'كبسولة', 'count', 1),
      ('BLS', 'Blister', 'شريط', 'count', 1),
      ('BTL', 'Bottle', 'زجاجة', 'count', 1),
      ('AMP', 'Ampoule', 'أمبول', 'count', 1),
      ('VIAL', 'Vial', 'فيال', 'count', 1),
      ('CTN', 'Carton', 'علبة', 'count', 1),
      ('BOX', 'Shipper box', 'كرتونة', 'count', 1),
      ('ROLL', 'Roll', 'بكرة', 'count', 1),
      ('H', 'Hour', 'ساعة', 'time', 1),
      ('MIN', 'Minute', 'دقيقة', 'time', 0.0166666667),
      ('KWH', 'Kilowatt-hour', 'كيلووات ساعة', 'energy', 1),
      ('NM3', 'Normal cubic metre', 'متر مكعب قياسي', 'gas', 1)
    ) AS v(code, en, ar, dim, f)
  ON CONFLICT (tenant_id, code) DO NOTHING
$$;

REVOKE ALL ON FUNCTION cp_seed_uoms(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cp_seed_uoms(uuid) TO cp_app;

SELECT cp_seed_uoms(id) FROM tenants;

-- ---------------------------------------------------------------- audit events: add IMPORT
CREATE OR REPLACE FUNCTION cp_audit_event(
  p_action text, p_entity text, p_record_id text, p_record_label text,
  p_details jsonb, p_tenant uuid, p_user uuid, p_user_name text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF p_action NOT IN ('LOGIN', 'LOGIN_FAILED', 'LOGOUT', 'LOCKED', 'UNLOCKED',
                      'SESSION_TIMEOUT', 'PASSWORD_CHANGED', 'PASSWORD_RESET',
                      'EXPORT', 'IMPORT', 'BOOTSTRAP', 'SAMPLE_DATA') THEN
    RAISE EXCEPTION 'Unknown audit event: %', p_action;
  END IF;
  INSERT INTO audit_log (tenant_id, user_id, user_name, action, entity,
                         record_id, record_label, details)
  VALUES (p_tenant, p_user, coalesce(p_user_name, 'system'), p_action, p_entity,
          p_record_id, p_record_label, p_details);
END $$;
