-- Production orders: manufacturing and packaging orders issued per batch from a plan, laid out by
-- company templates (logo, title, format number, numbering, header fields, material columns, signature
-- levels). Batch numbers are set by the planner on the plan and kept when the plan is re-planned.

-- Batch numbers. A site may have a pattern ({YY}{SEQ:3} ...) that fills empty numbers; the planner can
-- type or change any number. Plans keep them by item and ordinal so re-planning does not lose them.
ALTER TABLE sites ADD COLUMN batch_number_pattern text;
ALTER TABLE sites ADD COLUMN batch_number_next integer NOT NULL DEFAULT 1 CHECK (batch_number_next > 0);
ALTER TABLE plans ADD COLUMN batch_numbers jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE plan_batches ADD COLUMN lot_no text;

CREATE TABLE order_templates (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id),
  kind            text NOT NULL CHECK (kind IN ('manufacturing', 'packaging')),
  name            text NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 80),
  title           text NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 120),
  format_number   text,
  number_pattern  text NOT NULL CHECK (length(number_pattern) BETWEEN 1 AND 80),
  next_seq        integer NOT NULL DEFAULT 1 CHECK (next_seq > 0),
  orientation     text NOT NULL DEFAULT 'landscape' CHECK (orientation IN ('landscape', 'portrait')),
  logo            text,                                 -- data: URI (PNG or JPEG)
  header_columns  integer NOT NULL DEFAULT 3 CHECK (header_columns BETWEEN 1 AND 4),
  header_fields   jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{key, label}] in order
  columns         jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{key, label}] in order
  component_types jsonb NOT NULL DEFAULT '[]'::jsonb,   -- item types listed in the material table
  signatures      jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{title}] approval levels, in order
  require_esign   boolean NOT NULL DEFAULT false,
  remarks_label   text,
  remarks_lines   integer NOT NULL DEFAULT 2 CHECK (remarks_lines BETWEEN 0 AND 10),
  footer_note     text,
  is_default      boolean NOT NULL DEFAULT false,
  active          boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  CHECK (logo IS NULL OR length(logo) <= 1500000)
);
CREATE UNIQUE INDEX order_templates_default_idx ON order_templates (tenant_id, kind) WHERE is_default;

CREATE TABLE production_orders (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  site_id       uuid NOT NULL REFERENCES sites(id),
  plan_id       uuid REFERENCES plans(id) ON DELETE SET NULL,
  template_id   uuid NOT NULL REFERENCES order_templates(id),
  kind          text NOT NULL CHECK (kind IN ('manufacturing', 'packaging')),
  number        text NOT NULL,
  seq           integer,                              -- the template counter value used in the number, if any
  item_id       uuid NOT NULL REFERENCES items(id),
  ordinal       integer NOT NULL,                     -- nth batch of the item in the plan (survives re-planning)
  batch_number  text NOT NULL,
  status        text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'issued', 'cancelled')),
  revision      integer NOT NULL DEFAULT 0,
  content       jsonb,                                -- frozen document once approved or issued
  cancel_reason text,
  issued_at     timestamptz,
  issued_by     uuid,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid
);
CREATE UNIQUE INDEX production_orders_number_idx ON production_orders (tenant_id, kind, number) WHERE status <> 'cancelled';
CREATE INDEX production_orders_plan_idx ON production_orders (plan_id, item_id, ordinal);

CREATE TABLE order_signatures (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  order_id    uuid NOT NULL REFERENCES production_orders(id) ON DELETE CASCADE,
  level       integer NOT NULL CHECK (level >= 0),
  title       text NOT NULL,
  user_id     uuid NOT NULL REFERENCES users(id),
  user_name   text NOT NULL,
  meaning     text NOT NULL DEFAULT 'approved',
  signed_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (order_id, level)
);

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['order_templates', 'production_orders', 'order_signatures'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %I ON %I USING (cp_tenant_only(tenant_id)) WITH CHECK (cp_tenant_only(tenant_id))', t || '_tenant', t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO cp_app', t);
    EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION cp_audit_row()', t || '_audit', t);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['order_templates', 'production_orders'] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION cp_stamp()', t || '_stamp', t);
  END LOOP;
END $$;

-- The logo and the frozen document are large; the audit trail records that they changed, not their bytes.
CREATE OR REPLACE FUNCTION cp_audit_redacted(col text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$ SELECT col IN ('password_hash', 'logo', 'content') $$;

-- A wrong password when signing an order electronically is recorded like a failed sign-in.
CREATE OR REPLACE FUNCTION cp_audit_event(
  p_action text, p_entity text, p_record_id text, p_record_label text,
  p_details jsonb, p_tenant uuid, p_user uuid, p_user_name text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF p_action NOT IN ('LOGIN', 'LOGIN_FAILED', 'LOGOUT', 'LOCKED', 'UNLOCKED',
                      'SESSION_TIMEOUT', 'PASSWORD_CHANGED', 'PASSWORD_RESET',
                      'EXPORT', 'IMPORT', 'BOOTSTRAP', 'SAMPLE_DATA', 'SIGNATURE_FAILED') THEN
    RAISE EXCEPTION 'Unknown audit event: %', p_action;
  END IF;
  INSERT INTO audit_log (tenant_id, user_id, user_name, action, entity,
                         record_id, record_label, details)
  VALUES (p_tenant, p_user, coalesce(p_user_name, 'system'), p_action, p_entity,
          p_record_id, p_record_label, p_details);
END $$;
