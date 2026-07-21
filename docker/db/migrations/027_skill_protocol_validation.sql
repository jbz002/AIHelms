-- 027: Skill 协议合规校验（模块 S1 协议合规与生态互操作）
-- skill_versions 补协议校验结果三列：与 security_status / drift_detected 同模式
-- 草稿容错模型：errors 不阻断注册，激活时门控（activate_version 查 protocol_valid）
-- protocol_valid=false 部分索引便于治理查询「未合规版本」

ALTER TABLE aihelms.skill_versions
    ADD COLUMN IF NOT EXISTS protocol_valid BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS protocol_errors JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS last_validated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_skill_versions_protocol_valid
    ON aihelms.skill_versions(protocol_valid) WHERE protocol_valid = false;
