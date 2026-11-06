-- Batch number counters can restart at 1 with the first batch numbered in a new year (26001 … then 27001).
ALTER TABLE sites ADD COLUMN batch_number_yearly boolean NOT NULL DEFAULT false;
ALTER TABLE sites ADD COLUMN batch_number_year integer;          -- the year the counter belongs to
