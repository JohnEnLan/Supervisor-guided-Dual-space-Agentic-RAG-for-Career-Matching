"""集中配置，从 .env 读取。其他模块只从这里拿配置，不要各处 os.getenv。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    db_pool_min: int = 2
    db_pool_max: int = 10

    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model_fast: str = "deepseek-chat"
    deepseek_model_pro: str = "deepseek-reasoner"

    qwen_api_key: str
    qwen_embed_model: str = "text-embedding-v3"
    embed_dim: int = 1024  # 必须与 schema.sql 里的 vector(N) 一致

    llm_max_concurrency: int = 5
    embed_max_concurrency: int = 8

    dual_space_enabled: bool = True
    implicit_min_cases: int = 3
    implicit_max_weight: float = 0.30
    implicit_case_top_k: int = 20

    evaluation_capability_enabled: bool = False

    max_clarification_loops: int = 1
    max_reretrieval_loops: int = 1
    max_repair_loops: int = 1


settings = Settings()  # 全局唯一实例
