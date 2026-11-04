-- Complanning 0.7: every company setting and item field now changes planning.
-- Assay basis: whether a material's certificate reports assay on the substance as received or on the dried substance
-- (then the lot's loss on drying is taken into account too).
ALTER TABLE items ADD COLUMN assay_basis text NOT NULL DEFAULT 'as_is' CHECK (assay_basis IN ('as_is', 'dried'));

-- Standard costs are kept in one currency per company.
ALTER TABLE tenants ADD COLUMN cost_currency char(3) NOT NULL DEFAULT 'EGP' CHECK (cost_currency ~ '^[A-Z]{3}$');

-- Planned batches carry their expiry (end of production + shelf life) and their material cost.
ALTER TABLE plan_batches ADD COLUMN expires_on date;
ALTER TABLE plan_batches ADD COLUMN material_cost numeric(18, 2);

-- Deliveries rounded to full shippers keep the quantity before rounding for reference.
ALTER TABLE plan_demand ADD COLUMN before_rounding numeric(18, 3);
