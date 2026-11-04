-- A routing step that must run from start to end without a pause (for example wet granulation or drying):
-- the planning engine only places it where it fits completely inside one block of working time.
ALTER TABLE routing_steps ADD COLUMN uninterrupted boolean NOT NULL DEFAULT false;
