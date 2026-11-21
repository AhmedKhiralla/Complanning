-- Bought materials each planned batch uses, and the material stock the plan started from (for the plan simulation).
CREATE TABLE plan_batch_materials (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  uuid NOT NULL REFERENCES tenants(id),
  plan_id    uuid NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  batch_id   uuid NOT NULL REFERENCES plan_batches(id) ON DELETE CASCADE,
  item_id    uuid NOT NULL REFERENCES items(id),
  quantity   numeric(18, 3) NOT NULL
);
CREATE INDEX plan_batch_materials_plan_idx ON plan_batch_materials (plan_id);
ALTER TABLE plan_batch_materials ENABLE ROW LEVEL SECURITY;
CREATE POLICY plan_batch_materials_tenant ON plan_batch_materials USING (cp_tenant_only(tenant_id)) WITH CHECK (cp_tenant_only(tenant_id));
REVOKE ALL ON plan_batch_materials FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON plan_batch_materials TO cp_app;

-- {item_id: {released, quarantine, quarantine_ready, arrival, unlimited}} for the materials the plan uses.
ALTER TABLE plans ADD COLUMN material_pools jsonb;
