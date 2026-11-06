-- On time in full: the quantity of each delivery that is available to ship by its due date.
ALTER TABLE plan_demand ADD COLUMN on_time_qty numeric(18, 3);
-- Plans made before this version: a line on time was on time for its whole planned quantity.
UPDATE plan_demand SET on_time_qty = quantity WHERE on_time;
