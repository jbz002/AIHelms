-- 025: 跨实体评分 + 反馈 + 聚合缓存表（模块 06 评分反馈与使用统计）
-- entity_ratings：每用户每资源一条评分（UNIQUE 保证 upsert 语义），含可选文字反馈
-- entity_rating_stats：聚合缓存（avg_score / rating_count），列表高频读避免扫明细

CREATE TABLE IF NOT EXISTS aihelms.entity_ratings (
    id BIGSERIAL PRIMARY KEY,
    entity_type VARCHAR(32) NOT NULL,        -- mcp_server / skill（未来扩展 custom_entity / agent）
    entity_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL REFERENCES aihelms.users(id) ON DELETE CASCADE,
    score SMALLINT NOT NULL CHECK (score BETWEEN 1 AND 5),
    feedback_type VARCHAR(20) NOT NULL DEFAULT '',  -- bug / suggestion / praise / ''
    comment TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(entity_type, entity_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_ratings_entity
    ON aihelms.entity_ratings(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_ratings_user
    ON aihelms.entity_ratings(user_id);
CREATE INDEX IF NOT EXISTS idx_entity_ratings_entity_score
    ON aihelms.entity_ratings(entity_type, entity_id, score);

CREATE TRIGGER trg_entity_ratings_updated_at
    BEFORE UPDATE ON aihelms.entity_ratings
    FOR EACH ROW EXECUTE FUNCTION aihelms.update_updated_at_column();


CREATE TABLE IF NOT EXISTS aihelms.entity_rating_stats (
    entity_type VARCHAR(32) NOT NULL,
    entity_id BIGINT NOT NULL,
    avg_score NUMERIC(3,2) NOT NULL DEFAULT 0,
    rating_count INTEGER NOT NULL DEFAULT 0,
    last_rated_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_type, entity_id)
);

CREATE TRIGGER trg_entity_rating_stats_updated_at
    BEFORE UPDATE ON aihelms.entity_rating_stats
    FOR EACH ROW EXECUTE FUNCTION aihelms.update_updated_at_column();
