-- Complanning Phase 4: demand and stock
-- Sales plan per site, product, market and month; stock on hand by lot and QC status;
-- items that are not stock-controlled (for example purified water made on site).

-- ---------------------------------------------------------------- sales plan (per site)
CREATE TABLE demand_lines (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  site_id     uuid NOT NULL REFERENCES sites(id),
  item_id     uuid NOT NULL REFERENCES items(id),
  market_id   uuid NOT NULL REFERENCES markets(id),
  month       date NOT NULL CHECK (extract(day FROM month) = 1),
  quantity    numeric(18, 3) NOT NULL CHECK (quantity > 0),
  due_date    date,
  notes       text,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  UNIQUE (site_id, item_id, market_id, month),
  CHECK (due_date IS NULL OR date_trunc('month', due_date)::date = month)
);
CREATE INDEX demand_lines_site_month_idx ON demand_lines (site_id, month);

-- ---------------------------------------------------------------- stock on hand (per site)
-- status: released (usable), quarantine (waiting for QC), rejected (never usable).
CREATE TABLE stock_lots (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id),
  site_id         uuid NOT NULL REFERENCES sites(id),
  item_id         uuid NOT NULL REFERENCES items(id),
  lot_no          text CHECK (lot_no IS NULL OR length(trim(lot_no)) BETWEEN 1 AND 40),
  status          text NOT NULL DEFAULT 'released' CHECK (status IN ('released', 'quarantine', 'rejected')),
  quantity        numeric(18, 3) NOT NULL CHECK (quantity >= 0),
  manufactured_on date,
  expires_on      date,
  assay_pct       numeric(7, 3) CHECK (assay_pct > 0 AND assay_pct <= 200),
  lod_pct         numeric(6, 3) CHECK (lod_pct >= 0 AND lod_pct < 100),
  notes           text,
  created_at  timestamptz NOT NULL DEFAULT now(), created_by uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  CHECK (expires_on IS NULL OR manufactured_on IS NULL OR expires_on > manufactured_on)
);
CREATE UNIQUE INDEX stock_lots_unique_idx ON stock_lots (site_id, item_id, coalesce(lot_no, ''), status);
CREATE INDEX stock_lots_item_idx ON stock_lots (site_id, item_id);

-- The date the stock figures were counted or exported from the warehouse system.
ALTER TABLE sites ADD COLUMN stock_as_of date;

-- Items the plan never runs short of, such as purified water made on site.
ALTER TABLE items ADD COLUMN not_stock_controlled boolean NOT NULL DEFAULT false;

-- ---------------------------------------------------------------- stamping, audit, RLS, grants
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['demand_lines', 'stock_lots'] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION cp_stamp()', t || '_stamp', t);
    EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION cp_audit_row()', t || '_audit', t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %I ON %I USING (cp_tenant_only(tenant_id)) WITH CHECK (cp_tenant_only(tenant_id))', t || '_tenant', t);
    EXECUTE format('REVOKE ALL ON %I FROM PUBLIC', t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO cp_app', t);
  END LOOP;
END $$;

-- Readable audit labels for the new tables; everything else falls back to the Phase 3 labels.
ALTER FUNCTION cp_audit_label(text, jsonb) RENAME TO cp_audit_label_p3;

CREATE OR REPLACE FUNCTION cp_audit_label(tbl text, j jsonb) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT CASE tbl
    WHEN 'demand_lines' THEN
      coalesce((SELECT i.code FROM items i WHERE i.id = (j ->> 'item_id')::uuid), '?') || ' / ' ||
      coalesce((SELECT m.code FROM markets m WHERE m.id = (j ->> 'market_id')::uuid), '?') || ' / ' ||
      to_char((j ->> 'month')::date, 'YYYY-MM')
    WHEN 'stock_lots' THEN
      coalesce((SELECT i.code FROM items i WHERE i.id = (j ->> 'item_id')::uuid), '?') ||
      coalesce(' lot ' || (j ->> 'lot_no'), '') || ' (' || (j ->> 'status') || ')'
    ELSE cp_audit_label_p3(tbl, j) END
$$;
