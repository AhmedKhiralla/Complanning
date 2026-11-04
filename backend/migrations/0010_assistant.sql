-- AI assistant: usage counters per user and day, for the daily limit and the cost overview.
-- Questions and answers themselves are not stored.
CREATE TABLE ai_usage (
  tenant_id          uuid NOT NULL REFERENCES tenants(id),
  user_id            uuid NOT NULL REFERENCES users(id),
  day                date NOT NULL,
  questions          integer NOT NULL DEFAULT 0,
  prompt_tokens      bigint NOT NULL DEFAULT 0,
  completion_tokens  bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day)
);
ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_usage_tenant ON ai_usage USING (cp_tenant_only(tenant_id)) WITH CHECK (cp_tenant_only(tenant_id));
REVOKE ALL ON ai_usage FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON ai_usage TO cp_app;
