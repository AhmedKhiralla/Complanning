-- Complanning Phase 3: planning rules
-- Cleaning groups, changeover rules (groups first, product-pair overrides), equipment hold times,
-- campaign limits, product holding times and QC release settings.

-- ---------------------------------------------------------------- cleaning groups (company-wide)
CREATE TABLE cleaning_groups (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  code        text NOT NULL CHECK (code ~ '^[A-Za-z0-9][A-Za-z0-9_./-]{0,19}$'),
  name_en     text NOT NULL CHECK (length(trim(name_en)) > 0),
  name_ar     text,
  notes       text,
  sort_order  integer NOT NULL DEFAULT 0,
  active      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  UNIQUE (tenant_id, code)
);

-- Items keep the group code they already had; register every code that is in use.
INSERT INTO cleaning_groups (tenant_id, code, name_en)
SELECT DISTINCT tenant_id, upper(trim(cleaning_group)), upper(trim(cleaning_group))
  FROM items WHERE cleaning_group IS NOT NULL AND trim(cleaning_group) <> ''
ON CONFLICT DO NOTHING;
UPDATE items SET cleaning_group = upper(trim(cleaning_group)) WHERE cleaning_group IS NOT NULL;

-- ---------------------------------------------------------------- changeover rules (per site)
-- kind:
--   same_product   next batch of the same product (minor clean)
--   same_group     product change within one cleaning group (from_group optional: one group or all)
--   group_to_group change from one group to another, set per direction
--   product_pair   override for one product to another
--   default        any product change that no other rule covers
-- resource_id NULL = applies to every machine at the site; a machine-specific rule wins.
CREATE TABLE changeover_rules (
  id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id                 uuid NOT NULL REFERENCES tenants(id),
  site_id                   uuid NOT NULL REFERENCES sites(id),
  resource_id               uuid REFERENCES resources(id),
  kind                      text NOT NULL CHECK (kind IN ('same_product', 'same_group', 'group_to_group', 'product_pair', 'default')),
  from_group                text,
  to_group                  text,
  from_item_id              uuid REFERENCES items(id),
  to_item_id                uuid REFERENCES items(id),
  cleaning_minutes          numeric(10, 2) NOT NULL DEFAULT 0 CHECK (cleaning_minutes >= 0),
  format_minutes            numeric(10, 2) NOT NULL DEFAULT 0 CHECK (format_minutes >= 0),
  verification              text NOT NULL DEFAULT 'none' CHECK (verification IN ('none', 'visual', 'rinse', 'swab')),
  verification_wait_minutes numeric(10, 2) NOT NULL DEFAULT 0 CHECK (verification_wait_minutes >= 0),
  notes                     text,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  CHECK (kind <> 'group_to_group' OR (from_group IS NOT NULL AND to_group IS NOT NULL AND from_group <> to_group)),
  CHECK (kind <> 'product_pair' OR (from_item_id IS NOT NULL AND to_item_id IS NOT NULL AND from_item_id <> to_item_id)),
  CHECK (kind IN ('group_to_group', 'same_group') OR (from_group IS NULL AND to_group IS NULL)),
  CHECK (kind = 'product_pair' OR (from_item_id IS NULL AND to_item_id IS NULL)),
  CHECK (kind <> 'same_group' OR to_group IS NULL)
);
CREATE UNIQUE INDEX changeover_rules_unique_idx ON changeover_rules (
  site_id, coalesce(resource_id, '00000000-0000-0000-0000-000000000000'::uuid), kind,
  coalesce(from_group, ''), coalesce(to_group, ''),
  coalesce(from_item_id, '00000000-0000-0000-0000-000000000000'::uuid),
  coalesce(to_item_id, '00000000-0000-0000-0000-000000000000'::uuid));

-- ---------------------------------------------------------------- campaign limits (per site)
CREATE TABLE campaign_rules (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants(id),
  site_id      uuid NOT NULL REFERENCES sites(id),
  item_id      uuid NOT NULL REFERENCES items(id),
  resource_id  uuid REFERENCES resources(id),
  max_batches  integer CHECK (max_batches > 0),
  max_days     numeric(8, 2) CHECK (max_days > 0),
  min_batches  integer CHECK (min_batches > 0),
  notes        text,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  CHECK (max_batches IS NOT NULL OR max_days IS NOT NULL OR min_batches IS NOT NULL),
  CHECK (min_batches IS NULL OR max_batches IS NULL OR min_batches <= max_batches)
);
CREATE UNIQUE INDEX campaign_rules_unique_idx ON campaign_rules (
  site_id, item_id, coalesce(resource_id, '00000000-0000-0000-0000-000000000000'::uuid));

-- ---------------------------------------------------------------- equipment hold times and product timing
ALTER TABLE resources ADD COLUMN dirty_hold_hours numeric(8, 2) CHECK (dirty_hold_hours > 0);
ALTER TABLE resources ADD COLUMN clean_hold_hours numeric(8, 2) CHECK (clean_hold_hours > 0);

-- Holding time of a produced item before the next stage must start, and QC release behaviour.
-- release_lead_days (Phase 2) remains the QC testing time.
ALTER TABLE items ADD COLUMN hold_min_hours numeric(8, 2) CHECK (hold_min_hours >= 0);
ALTER TABLE items ADD COLUMN hold_max_hours numeric(8, 2) CHECK (hold_max_hours > 0);
ALTER TABLE items ADD COLUMN release_at_risk_allowed boolean NOT NULL DEFAULT false;
ALTER TABLE items ADD CONSTRAINT items_hold_order CHECK (hold_min_hours IS NULL OR hold_max_hours IS NULL OR hold_min_hours <= hold_max_hours);

-- ---------------------------------------------------------------- stamping, audit, RLS, grants
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['cleaning_groups', 'changeover_rules', 'campaign_rules'] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION cp_stamp()', t || '_stamp', t);
    EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION cp_audit_row()', t || '_audit', t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %I ON %I USING (cp_tenant_only(tenant_id)) WITH CHECK (cp_tenant_only(tenant_id))', t || '_tenant', t);
    EXECUTE format('REVOKE ALL ON %I FROM PUBLIC', t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO cp_app', t);
  END LOOP;
END $$;

-- Readable audit labels: one function per phase can extend this; cp_audit_row calls it.
CREATE OR REPLACE FUNCTION cp_audit_label(tbl text, j jsonb) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT coalesce(j ->> 'code', j ->> 'email', j ->> 'name', j ->> 'role', CASE tbl
    WHEN 'boms' THEN (SELECT i.code FROM items i WHERE i.id = (j ->> 'item_id')::uuid) || ' v' || (j ->> 'version')
    WHEN 'bom_lines' THEN (SELECT i.code || ' v' || b.version FROM boms b JOIN items i ON i.id = b.item_id
                            WHERE b.id = (j ->> 'bom_id')::uuid) || ' line ' || (j ->> 'line_no')
    WHEN 'prices' THEN (SELECT i.code FROM items i WHERE i.id = (j ->> 'item_id')::uuid)
                       || ' / ' || (SELECT m.code FROM markets m WHERE m.id = (j ->> 'market_id')::uuid)
    WHEN 'item_markets' THEN (SELECT i.code FROM items i WHERE i.id = (j ->> 'item_id')::uuid)
                       || ' / ' || (SELECT m.code FROM markets m WHERE m.id = (j ->> 'market_id')::uuid)
    WHEN 'item_uom_conversions' THEN (SELECT i.code FROM items i WHERE i.id = (j ->> 'item_id')::uuid)
                       || ' / ' || (SELECT u.code FROM uoms u WHERE u.id = (j ->> 'uom_id')::uuid)
    WHEN 'routings' THEN (SELECT i.code FROM items i WHERE i.id = (j ->> 'item_id')::uuid)
    WHEN 'routing_step_resources' THEN (SELECT r.code FROM resources r WHERE r.id = (j ->> 'resource_id')::uuid)
    WHEN 'resource_exceptions' THEN (SELECT r.code FROM resources r WHERE r.id = (j ->> 'resource_id')::uuid)
                       || ' ' || (j ->> 'reason')
    WHEN 'holidays' THEN j ->> 'date'
    WHEN 'changeover_rules' THEN
      coalesce((SELECT r.code FROM resources r WHERE r.id = (j ->> 'resource_id')::uuid), 'all machines') || ': ' ||
      CASE j ->> 'kind'
        WHEN 'same_product' THEN 'same product'
        WHEN 'same_group' THEN 'within ' || coalesce(j ->> 'from_group', 'any group')
        WHEN 'group_to_group' THEN (j ->> 'from_group') || ' → ' || (j ->> 'to_group')
        WHEN 'product_pair' THEN coalesce((SELECT i.code FROM items i WHERE i.id = (j ->> 'from_item_id')::uuid), '?') || ' → ' ||
                                 coalesce((SELECT i.code FROM items i WHERE i.id = (j ->> 'to_item_id')::uuid), '?')
        ELSE 'any product change' END
    WHEN 'campaign_rules' THEN
      coalesce((SELECT i.code FROM items i WHERE i.id = (j ->> 'item_id')::uuid), '?') || ' on ' ||
      coalesce((SELECT r.code FROM resources r WHERE r.id = (j ->> 'resource_id')::uuid), 'all machines')
    ELSE NULL END)
$$;

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

  v_tenant := CASE WHEN TG_TABLE_NAME = 'tenants' THEN (ref_j ->> 'id')::uuid ELSE (ref_j ->> 'tenant_id')::uuid END;

  INSERT INTO audit_log (tenant_id, site_id, user_id, user_name, action, entity,
                         record_id, record_label, old_values, new_values)
  VALUES (
    v_tenant,
    CASE WHEN TG_TABLE_NAME = 'sites' THEN (ref_j ->> 'id')::uuid ELSE (ref_j ->> 'site_id')::uuid END,
    cp_current_user_id(),
    coalesce(cp_setting('app.user_name'), 'system'),
    TG_OP, TG_TABLE_NAME, ref_j ->> 'id', cp_audit_label(TG_TABLE_NAME, ref_j),
    CASE WHEN o = '{}'::jsonb THEN NULL ELSE o END,
    CASE WHEN n = '{}'::jsonb THEN NULL ELSE n END
  );
  RETURN coalesce(NEW, OLD);
END $$;
