-- A routing step that runs together with the previous step on its own machines (for example a cartoner connected to a
-- blister machine): the planning engine books both machines for the same time instead of one after the other.
ALTER TABLE routing_steps ADD COLUMN with_previous boolean NOT NULL DEFAULT false;
