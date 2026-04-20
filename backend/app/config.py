"""Unified configuration loaded from environment variables / .env file."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DashScope AI
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen3.6-plus"

    # Innomate API
    innomate_api_url: str = ""

    # Data directories (resolved relative to project root at runtime)
    md_raw_dir: str = "../data/raw"
    md_redacted_dir: str = "../data/redacted"
    index_dir: str = "../data/index"

    # Auth
    secret_key: str = ""
    unified_password: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480  # 8 hours

    def model_post_init(self, __context) -> None:
        """Validate critical security settings at startup."""
        if not self.secret_key or self.secret_key == "change-me-to-a-random-string":
            import secrets
            import warnings
            warnings.warn(
                "SECURITY WARNING: secret_key is not set. Using auto-generated key. "
                "This will invalidate all existing tokens on restart.",
                UserWarning,
            )
            self.secret_key = secrets.token_hex(32)
        if not self.unified_password:
            import warnings
            warnings.warn(
                "SECURITY WARNING: unified_password is not configured.",
                UserWarning,
            )

    # Dify Knowledge Base
    dify_api_key: str = ""
    dify_base_url: str = "https://api.dify.ai/v1"
    dify_dataset_id: str = ""
    dify_index_dataset_id: str = ""

    # Batch processing
    batch_concurrency: int = 3

    # Knowledge graph
    kg_embedding_model: str = "text-embedding-v4"
    kg_embedding_dim: int = 1024
    kg_embedding_batch_size: int = 10
    kg_entity_merge_threshold: float = 0.88
    kg_min_shared_entities: int = 2
    kg_max_edges_per_doc: int = 50
    kg_entity_blacklist: str = ""
    """Comma-separated entity names that should be dropped at extraction and
    query time (e.g. "本公司,领导,相关方"). Values are casefold-compared."""
    # Lightweight model used only for query-time entity extraction (NER on the
    # user question). Kept separate from dashscope_model so the heavy pipeline
    # (document-level extraction, index generation) can still use a stronger
    # model without paying the per-query latency cost.
    kg_query_model: str = "qwen3.5-flash"

    # --- Query-side NER fast path (Aho-Corasick) --------------------------
    # The ``kg_query_model`` call above dominates per-query latency. Before
    # falling back to it we try to match the question against an in-memory
    # Aho-Corasick automaton built from ``kg_entities.name`` + aliases.
    # When the automaton returns >=1 hit we use its result directly and skip
    # the LLM NER entirely (the matched ids are already canonical, so the
    # downstream embedding-based fuzzy-match step is unnecessary too).
    kg_query_use_automaton: bool = True
    """Master switch for the Aho-Corasick fast path. Set to False to go back
    to the pure LLM NER path (useful for A/B or incident fallback)."""
    kg_query_automaton_min_length: int = 2
    """Minimum surface-form length to register in the automaton. Filters
    1-char/1-digit forms that would cause catastrophic substring false
    positives in Chinese (no word boundaries). Raise to 3 if you see
    noise from 2-char person names colliding with common substrings."""

    # --- Index-rerank (topic-level second-stage filtering) ----------------
    # After the KG entity-match recall picks candidate documents, we score
    # each candidate by cosine(query_embedding, document_index_embedding)
    # to down-weight "entity is mentioned but topic is unrelated" noise.
    kg_enable_index_rerank: bool = True
    """Master switch. Set to False to fall back to pure entity-match ranking."""
    kg_index_rerank_alpha: float = 0.6
    """Weight of the normalized entity-match score in the final fused score."""
    kg_index_rerank_beta: float = 0.4
    """Weight of the index-embedding cosine similarity in the final fused score."""
    kg_index_rerank_min_score: float = 0.25
    """Documents whose cosine falls below this are dropped outright
    (guards against "entity matched but topic is clearly unrelated")."""
    kg_index_rerank_pool_multiplier: int = 2
    """Initial KG recall size is ``top_k * multiplier``, then trimmed to
    ``top_k`` after rerank. Larger values give rerank more room to re-order."""

    # Database
    database_url: str = "postgresql+psycopg2://appuser:apppassword@db:5432/ai_data_platform"

    # Prompts directory
    prompts_dir: str = str(Path(__file__).resolve().parent.parent / "prompts")

    def resolve_path(self, relative: str) -> Path:
        """Resolve a path relative to the backend/ directory."""
        base = Path(__file__).resolve().parent.parent
        return (base / relative).resolve()

    @property
    def kg_entity_blacklist_set(self) -> set[str]:
        """Parsed blacklist as a set of casefolded names for O(1) lookup."""
        return {
            s.strip().casefold()
            for s in (self.kg_entity_blacklist or "").split(",")
            if s.strip()
        }


settings = Settings()
