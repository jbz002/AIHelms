from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库连接（可直接设置 DATABASE_URL，或由下面的变量拼接）
    database_url: str = ""
    postgres_user: str = "aihelms"
    postgres_password: str = "aihelms"
    postgres_db: str = "aihelms"
    db_host: str = "localhost"
    db_port: int = 5432

    # Redis 连接（可直接设置 REDIS_URL，或由下面的变量拼接）
    redis_url: str = ""
    redis_password: str = "aihelms"
    redis_host: str = "localhost"
    redis_port: int = 6379

    # LiteLLM（可直接设置 LITELLM_URL，或由下面的变量拼接）
    litellm_url: str = ""
    litellm_host: str = "localhost"
    litellm_port: int = 4000
    litellm_master_key: str = ""
    # 对外暴露给用户客户端的 LiteLLM 地址
    # （自动由 NGINX_SERVER_NAME + LITELLM_PORT 拼接）
    litellm_public_url: str = ""
    nginx_server_name: str = "localhost"
    web_port: int = 80
    # 平台对外访问地址（自动由 NGINX_SERVER_NAME + WEB_PORT 拼接），
    # 用于生成 skill 下载链接等
    platform_public_url: str = ""

    # 日志
    log_level: str = "INFO"
    log_dir: str = "/logs"

    # 应用
    secret_key: str = ""
    access_token_expire_minutes: int = 60 * 24
    super_admin_password: str = ""

    # 成本计算
    usd_to_cny_rate: float = 7.0  # LiteLLM spend(美元) → 人民币汇率

    # Gunicorn
    gunicorn_workers: int = 0
    gunicorn_timeout: int = 120
    gunicorn_keepalive: int = 5
    gunicorn_max_requests: int = 1000
    gunicorn_max_requests_jitter: int = 50
    gunicorn_loglevel: str = "info"

    # Celery
    celery_worker_concurrency: int = 0
    celery_loglevel: str = "info"
    celery_prefetch_multiplier: int = 1

    # 文件存储（开发：项目根 ../data；生产容器内：/data）
    data_dir: str = "../data"
    skills_storage_dir: str = ""
    uploads_storage_dir: str = ""
    exports_storage_dir: str = ""

    # 时区（LiteLLM 容器时区，用于日志同步时区转换）
    timezone: str = "Asia/Shanghai"

    # 管理员日志保留天数
    audit_log_retention_days: int = 180

    # 一致性保障（S6）
    idempotency_ttl_hours: int = 24  # 幂等键保留时长（小时）
    idempotency_path_prefixes: str = (
        "/api/v1/ratings,/api/v1/resource-applications"  # 启用幂等的路径前缀（逗号分隔，仅 JSON 写接口）
    )
    storage_compensation_max_retries: int = 5  # 孤儿文件删除补偿最大重试次数
    distributed_lock_default_ttl: int = 30  # 分布式锁默认 TTL（秒）

    # Skill 包物理校验（S5）
    skills_package_max_file_size_mb: int = 10  # 单文件解压后上限（MB）
    skills_package_max_total_size_mb: int = 100  # 总包上限（MB，压缩与解压均校验）
    skills_package_max_file_count: int = 500  # 包内文件数上限
    # 扩展名白名单：留空走模块默认；非空则整体替换（逗号分隔）
    skills_package_allowed_extensions: str = ""

    # AI Policies
    ai_policies_scanner_url: str = "http://127.0.0.1:8010"
    ai_policies_timeout_seconds: int = 600
    # AI Policies S2（多 analyzer + 策略 + Verdict）
    ai_policies_signatures_path: str = "security_rules/signatures.yaml"
    ai_policies_default_policy: str = "balanced"  # strict | balanced | permissive
    ai_policies_regex_enabled: bool = True
    ai_policies_llm_consensus_runs: int = 1  # 全局兜底，被 settings 表 / preset 覆盖
    ai_policies_llm_consensus_timeout_seconds: int = 180

    # SSRF 校验
    ssrf_allowed_hosts: str = ""  # MCP 内网白名单域名（逗号分隔）
    ssrf_allowed_cidrs: str = ""  # MCP 内网白名单 CIDR（逗号分隔）
    ssrf_skill_url_domains: str = ""  # Skill URL 注册允许的仓库域名白名单

    # 内置 Skills 开箱即用（S8）
    builtin_skills_enabled: bool = True  # 总开关：关闭后不读 manifest 不同步
    builtin_skills_manifest_path: str = (
        "apps/builtin_skills/manifest.json"  # 相对仓库根
    )
    builtin_skills_allowed_domains: str = ""  # 远程 url 模式源域名白名单（逗号分隔）
    builtin_skills_sync_on_startup: bool = True  # 启动时异步同步一次

    # Crawl4AI 网页抓取
    crawl4ai_enabled: bool = True
    crawl_timeout: int = 30  # 单页抓取超时（秒）

    # docs-mcp-server（API文档管理）
    # REST API + SSE 事件流均在 worker 容器
    docs_mcp_server_url: str = "http://localhost:8080"
    docs_mcp_server_web_url: str = "http://localhost:8080"
    docs_mcp_worker_port: int = 8080
    docs_mcp_server_port: int = 6280
    docs_mcp_web_port: int = 6281

    # docling-serve（文档格式转换：PDF/DOCX/PPTX 等 → Markdown）
    docling_serve_url: str = "http://localhost:5001"
    docling_serve_port: int = 5001
    docling_convert_timeout: int = 60  # 单文件转换超时（秒）

    # LLM 调用日志同步与清理
    llm_log_sync_interval_minutes: int = 5
    llm_log_retention_days: int = 0  # 0 = 不清理

    @model_validator(mode="after")
    def build_urls(self) -> "Settings":
        if not self.database_url:
            self.database_url = (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.db_host}:{self.db_port}/{self.postgres_db}"
            )
        if not self.redis_url:
            self.redis_url = (
                f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
            )
        if not self.litellm_url:
            self.litellm_url = f"http://{self.litellm_host}:{self.litellm_port}"
        if not self.litellm_public_url:
            # 用 NGINX_SERVER_NAME + LITELLM_PORT 拼接对外 LiteLLM 地址
            host = (
                self.nginx_server_name.split()[0]
                if self.nginx_server_name
                else "localhost"
            )
            self.litellm_public_url = f"http://{host}:{self.litellm_port}"
        if not self.platform_public_url:
            host = (
                self.nginx_server_name.split()[0]
                if self.nginx_server_name
                else "localhost"
            )
            port_suffix = "" if self.web_port == 80 else f":{self.web_port}"
            self.platform_public_url = f"http://{host}{port_suffix}"
        if not self.skills_storage_dir:
            self.skills_storage_dir = f"{self.data_dir}/skills"
        if not self.uploads_storage_dir:
            self.uploads_storage_dir = f"{self.data_dir}/uploads"
        if not self.exports_storage_dir:
            self.exports_storage_dir = f"{self.data_dir}/exports"
        return self

    class Config:
        env_file = str(
            __import__("pathlib").Path(__file__).resolve().parent.parent.parent / ".env"
        )
        extra = "ignore"


settings = Settings()
