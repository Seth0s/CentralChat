import os
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore

    # CWD (ex.: raiz `central/`) nem sempre é `orchestrator/` — carregar sempre este `.env`.
    _ORCH_ROOT = Path(__file__).resolve().parent.parent
    _ORCH_ENV = _ORCH_ROOT / ".env"
    load_dotenv()
    if _ORCH_ENV.is_file():
        load_dotenv(_ORCH_ENV, override=True)
except Exception:
    pass

def _join_root(root: str, rel: str) -> str:
    return os.path.join(root, rel.lstrip("/"))


def _env_fallback(new_key: str, old_key: str, default: str = "") -> str:
    """Prefer `CENTRAL_*`; aceita legado `SOPHIA_*` até migração completa do `.env`."""
    v = os.getenv(new_key, "").strip()
    if v:
        return v
    return os.getenv(old_key, default).strip()


CENTRAL_ROOT = _env_fallback("CENTRAL_ROOT", "SOPHIA_ROOT")

API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8004"))

STT_SERVICE_URL = os.getenv("STT_SERVICE_URL", "").strip()
LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://127.0.0.1:8002")
MODEL_ROUTER_URL = os.getenv("MODEL_ROUTER_URL", "").strip()

# Perfil fixo do model-router em modo API (quando sem inference_routing.json)
CLOUD_ROUTER_PROFILE = os.getenv("CLOUD_ROUTER_PROFILE", "cloud_openai").strip() or "cloud_openai"

# Perfil fixo do model-router para LLM auxiliar (compactação/percepção) em modo API.
# Mantemos separado para permitir escolher Gemini sem afectar o chat principal.
AUX_CLOUD_ROUTER_PROFILE = os.getenv("AUX_CLOUD_ROUTER_PROFILE", "cloud_gemini").strip() or "cloud_gemini"

# ADR-016 — product context cap (~200k); per-model limits applied in inference_context.py
CENTRAL_CONTEXT_WINDOW_CAP = max(
    1, int(os.getenv("CENTRAL_CONTEXT_WINDOW_CAP", "200000") or "200000")
)

INFERENCE_ROUTING_PATH = os.getenv(
    "INFERENCE_ROUTING_PATH",
    _join_root(CENTRAL_ROOT, "config/inference_routing.json") if CENTRAL_ROOT else "",
).strip()

# ── CLOUD MODELS (per-user via user_cloud_models table) ──
# CLOUD_MODELS_ALLOWLIST_PATH removido (M4.5 — substituído por tabela per-user)
# CLOUD_UI_MODEL_CATALOG_MODE fixo em "full_vendor" — a allowlist per-user
# é gerida via Model Hub (UI), não por ficheiro JSON global.
# AUTO_TIER_POLICIES_PATH removido (Fase C — substituído por user_tier_profiles)

# ADR-016 — modality roles (server-side capabilities; not UI allowlist)
MODALITY_MODELS_PATH = os.getenv(
    "CENTRAL_MODALITY_MODELS_PATH",
    _join_root(CENTRAL_ROOT, "config/modality_models.json") if CENTRAL_ROOT else "",
).strip()
CENTRAL_SUMMARY_MODEL_ID = os.getenv("CENTRAL_SUMMARY_MODEL_ID", "").strip()
CENTRAL_VISION_PERCEIVE_MODEL_ID = os.getenv("CENTRAL_VISION_PERCEIVE_MODEL_ID", "").strip()
CENTRAL_AUDIO_PERCEIVE_MODEL_ID = os.getenv("CENTRAL_AUDIO_PERCEIVE_MODEL_ID", "").strip()
CENTRAL_TTS_MODEL_ID = os.getenv("CENTRAL_TTS_MODEL_ID", "").strip()
CENTRAL_WEB_RESEARCH_MODEL_ID = os.getenv("CENTRAL_WEB_RESEARCH_MODEL_ID", "").strip()
CENTRAL_WEB_RESEARCH_MODEL_ID_FAST = os.getenv("CENTRAL_WEB_RESEARCH_MODEL_ID_FAST", "").strip()
CENTRAL_WEB_RESEARCH_MODEL_ID_DEEP = os.getenv("CENTRAL_WEB_RESEARCH_MODEL_ID_DEEP", "").strip()
CENTRAL_SOCIAL_COPY_MODEL_ID = os.getenv("CENTRAL_SOCIAL_COPY_MODEL_ID", "").strip()
CENTRAL_SOCIAL_COPY_MODEL_ID_PREMIUM = os.getenv("CENTRAL_SOCIAL_COPY_MODEL_ID_PREMIUM", "").strip()
CENTRAL_IMAGE_GENERATE_MODEL_ID = os.getenv("CENTRAL_IMAGE_GENERATE_MODEL_ID", "").strip()
CENTRAL_VIDEO_PERCEIVE_MODEL_ID = os.getenv("CENTRAL_VIDEO_PERCEIVE_MODEL_ID", "").strip()
# ADR-016 §13 — video sampling (ffmpeg); full clip is not sent to the LLM
CENTRAL_VIDEO_MAX_FRAMES = max(1, min(int(os.getenv("CENTRAL_VIDEO_MAX_FRAMES", "6")), 24))
CENTRAL_VIDEO_MAX_DURATION_SEC = max(1.0, float(os.getenv("CENTRAL_VIDEO_MAX_DURATION_SEC", "30")))
CENTRAL_VIDEO_MAX_BASE64_CHARS = max(
    1024,
    int(os.getenv("CENTRAL_VIDEO_MAX_BASE64_CHARS", str(140_000_000))),
)

# ADR-016 phase 6 — modality agent tools (web research, social copy, image)
CENTRAL_MODALITY_TOOLS_ENABLED = os.getenv("CENTRAL_MODALITY_TOOLS_ENABLED", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
MODALITY_AGENT_TOOLS_PATH = os.getenv(
    "MODALITY_AGENT_TOOLS_PATH",
    _join_root(CENTRAL_ROOT, "config/modality_agent_tools.json") if CENTRAL_ROOT else "",
).strip()
CENTRAL_IMAGE_GENERATE_HITL = os.getenv("CENTRAL_IMAGE_GENERATE_HITL", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)

# ADR-016 — OpenRouter audio (TTS direct; STT via model-router multimodal)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
OPENROUTER_TTS_SPEECH_URL = os.getenv(
    "OPENROUTER_TTS_SPEECH_URL",
    "https://openrouter.ai/api/v1/audio/speech",
).strip()
OPENROUTER_TTS_VOICE = os.getenv("OPENROUTER_TTS_VOICE", "alloy").strip() or "alloy"
OPENROUTER_TTS_RESPONSE_FORMAT = os.getenv("OPENROUTER_TTS_RESPONSE_FORMAT", "mp3").strip() or "mp3"

# Pré-Fase 7 — política L8 (extract, anexos, summarização, handoff, fallback, retries)
L8_PIPELINE_POLICY_PATH = _env_fallback(
    "CENTRAL_L8_PIPELINE_POLICY_PATH",
    "L8_PIPELINE_POLICY_PATH",
    _join_root(CENTRAL_ROOT, "config/l8_pipeline_policy.json") if CENTRAL_ROOT else "",
).strip()

# CLOUD_UI_MODEL_CATALOG_MODE: sempre full_vendor (M4.5).
# A allowlist per-user é gerida via user_cloud_models (Model Hub).
CLOUD_UI_MODEL_CATALOG_MODE: str = "full_vendor"

# (UI_CLOUD_MODEL_ALLOWLIST_EDIT_ENABLED removed in M4 — replaced by per-user user_cloud_models)

# Cache do catálogo vendor no processo (paginação sem repetir upstream a cada página)
VENDOR_CATALOG_CACHE_TTL_SECONDS = max(
    5, int(os.getenv("VENDOR_CATALOG_CACHE_TTL_SECONDS", "90") or "90")
)

# Ambiente da app (CORS estrito, etc.). `production` exige `CENTRAL_CORS_ALLOW_ORIGINS` não vazio.
CENTRAL_APP_ENV = os.getenv("CENTRAL_APP_ENV", "development").strip().lower()

# Origens explícitas para CORS. Preferir `CENTRAL_CORS_ALLOW_ORIGINS`; legado `CORS_ALLOW_ORIGINS`.
_cors_raw = os.getenv("CENTRAL_CORS_ALLOW_ORIGINS", os.getenv("CORS_ALLOW_ORIGINS", "")).strip()
CORS_ALLOW_ORIGINS: list[str] = [x.strip() for x in _cors_raw.split(",") if x.strip()]
if CENTRAL_APP_ENV in ("production", "prod") and not CORS_ALLOW_ORIGINS:
    raise RuntimeError(
        "CENTRAL_APP_ENV is production but CENTRAL_CORS_ALLOW_ORIGINS (or CORS_ALLOW_ORIGINS) is empty; "
        "set a CSV of allowed browser origins."
    )

# Stream: expor `composer_segments` no evento SSE `done` (Fase 2 — alinhado a widget_feature_flags).
_raw_composer = os.getenv("CENTRAL_COMPOSER_SEGMENTS_IN_STREAM", "1").strip().lower()
COMPOSER_SEGMENTS_IN_STREAM_ENABLED = _raw_composer not in ("0", "false", "no", "n")
SYSTEM_AGENT_URL = os.getenv("SYSTEM_AGENT_URL", "http://127.0.0.1:8006").strip()
KERNEL_OBSERVER_URL = os.getenv("KERNEL_OBSERVER_URL", "http://127.0.0.1:8007").strip()
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "").strip()
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090")

DISABLE_STT = os.getenv("DISABLE_STT", "").strip().lower() in ("1", "true", "yes", "y")
DISABLE_TTS = os.getenv("DISABLE_TTS", "").strip().lower() in ("1", "true", "yes", "y")
DISABLE_LLM_SERVICE = os.getenv("DISABLE_LLM_SERVICE", "").strip().lower() in ("1", "true", "yes", "y")

# Context management / compaction
COMPACT_AFTER_MESSAGES = int(os.getenv("COMPACT_AFTER_MESSAGES", "40"))
COMPACT_AFTER_CHARS = int(os.getenv("COMPACT_AFTER_CHARS", "60000"))
COMPACT_KEEP_LAST_MESSAGES = int(os.getenv("COMPACT_KEEP_LAST_MESSAGES", "12"))
COMPACT_SUMMARY_STORE_PATH = os.getenv(
    "COMPACT_SUMMARY_STORE_PATH",
    _join_root(CENTRAL_ROOT, "state/context_summary.json") if CENTRAL_ROOT else "/tmp/central_context_summary.json",
)
# Phase 6 — token compaction (CompactionService)
CENTRAL_COMPACT_MIN_VERBATIM_TOKENS = int(os.getenv("CENTRAL_COMPACT_MIN_VERBATIM_TOKENS", "8000"))
CENTRAL_COMPACTION_SYNC_OVERFLOW_RATIO = float(os.getenv("CENTRAL_COMPACTION_SYNC_OVERFLOW_RATIO", "0.92"))
CENTRAL_COMPACTION_ASYNC_ENABLED = os.getenv("CENTRAL_COMPACTION_ASYNC_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)

# K.3 — cofre local
SECRETS_VAULT_PATH = os.getenv(
    "SECRETS_VAULT_PATH",
    _join_root(CENTRAL_ROOT, "state/secrets/vault.json") if CENTRAL_ROOT else "",
).strip()

# Encriptação em repouso para CENTRAL_ROOT/secrets/ (AES-256-GCM).
# Aceita 32 bytes em base64, hex (64 chars) ou passphrase (derivada via SHA-256).
CENTRAL_VAULT_MASTER_KEY = os.getenv("CENTRAL_VAULT_MASTER_KEY", "").strip()

# Phase 3 — secret value backend: filesystem | env | hashicorp | aws
CENTRAL_SECRET_BACKEND = os.getenv("CENTRAL_SECRET_BACKEND", "filesystem").strip().lower()
CENTRAL_HASHICORP_VAULT_ADDR = os.getenv("CENTRAL_HASHICORP_VAULT_ADDR", "").strip()
CENTRAL_HASHICORP_VAULT_TOKEN = os.getenv("CENTRAL_HASHICORP_VAULT_TOKEN", "").strip()
CENTRAL_HASHICORP_VAULT_MOUNT = os.getenv("CENTRAL_HASHICORP_VAULT_MOUNT", "secret").strip()
CENTRAL_HASHICORP_VAULT_PREFIX = os.getenv("CENTRAL_HASHICORP_VAULT_PREFIX", "centralchat").strip()
CENTRAL_HASHICORP_VAULT_NAMESPACE = os.getenv("CENTRAL_HASHICORP_VAULT_NAMESPACE", "").strip()
CENTRAL_AWS_SECRETS_REGION = os.getenv(
    "CENTRAL_AWS_SECRETS_REGION",
    os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
).strip()
CENTRAL_AWS_SECRETS_PREFIX = os.getenv("CENTRAL_AWS_SECRETS_PREFIX", "centralchat").strip()

# Memória externa (Postgres+pgvector)
MEMORY_DB_URL = os.getenv(
    "MEMORY_DB_URL",
    "postgresql://central:central@memory-db:5432/central_memory",
).strip()
MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "1").strip().lower() in ("1", "true", "yes", "y")
MEMORY_TOP_K = int(os.getenv("MEMORY_TOP_K", "8"))
MEMORY_MAX_BLOCK_CHARS = int(os.getenv("MEMORY_MAX_BLOCK_CHARS", "8000"))

# F5 — RAG de documentos (pgvector; mesmo embedding que F4 via agent_tools_embedding)
DOCUMENT_RAG_SERVER_ENABLED = os.getenv("DOCUMENT_RAG_SERVER_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
DOCUMENT_RAG_TOP_K = int(os.getenv("DOCUMENT_RAG_TOP_K", "6"))
DOCUMENT_RAG_CHUNK_CHARS = int(os.getenv("DOCUMENT_RAG_CHUNK_CHARS", "1200"))
DOCUMENT_RAG_CHUNK_OVERLAP = int(os.getenv("DOCUMENT_RAG_CHUNK_OVERLAP", "120"))
DOCUMENT_RAG_MAX_DOC_BYTES = int(os.getenv("DOCUMENT_RAG_MAX_DOC_BYTES", str(8 * 1024 * 1024)))
DOCUMENT_RAG_MAX_CHUNKS_PER_DOC = int(os.getenv("DOCUMENT_RAG_MAX_CHUNKS_PER_DOC", "400"))
DOCUMENT_RAG_PROMPT_MAX_CHARS = int(os.getenv("DOCUMENT_RAG_PROMPT_MAX_CHARS", "6000"))

# F2/A2 — workspace / canvas: memory (defeito) ou postgres (JSONB + TTL; partilhado entre réplicas)
_ws_backend = os.getenv("WORKSPACE_STORE_BACKEND", "memory").strip().lower()
WORKSPACE_STORE_BACKEND = _ws_backend if _ws_backend in ("memory", "postgres") else "memory"
WORKSPACE_PG_URL = os.getenv("WORKSPACE_PG_URL", "").strip() or MEMORY_DB_URL
WORKSPACE_SESSION_TTL_SECONDS = int(os.getenv("WORKSPACE_SESSION_TTL_SECONDS", str(86400)))

# Pre/pos-injecao (ambientacao) — ver docs/guides/ambientacao-pre-pos-injecao.md
PRE_INJECTION_ENABLED = os.getenv("PRE_INJECTION_ENABLED", "1").strip().lower() in ("1", "true", "yes", "y")
PRE_INJECTION_FILE_PATH = os.getenv("PRE_INJECTION_FILE_PATH", "").strip() or None
SESSION_MAX_MESSAGES_NO_LONG_MEMORY = int(os.getenv("SESSION_MAX_MESSAGES_NO_LONG_MEMORY", "64"))

# L0-2 — injectar digest de capacidades no system (defeito desligado; requer opt-in no pedido ou L2 + preferências)
CAPABILITY_DIGEST_IN_PROMPT_ENABLED = os.getenv(
    "CAPABILITY_DIGEST_IN_PROMPT_ENABLED", ""
).strip().lower() in ("1", "true", "yes", "y")

# Fase H: injetar agregado host quando o texto sugere pergunta metrica (defeito desligado)
HOST_CONTEXT_TEXT_TRIGGER_ENABLED = os.getenv("HOST_CONTEXT_TEXT_TRIGGER_ENABLED", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)

# ADR-017 — tenant widget catalog: cloud + client only; platform tools need legacy flag
CENTRAL_LEGACY_PLATFORM_TOOLS = os.getenv("CENTRAL_LEGACY_PLATFORM_TOOLS", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
# ADR-017-8: inject system-agent host block (Central VPS), not the tenant connector machine.
CENTRAL_INCLUDE_PLATFORM_CONTEXT = os.getenv(
    "CENTRAL_INCLUDE_PLATFORM_CONTEXT", "0"
).strip().lower() in ("1", "true", "yes", "y")
CENTRAL_LLM_APPROVAL_META_TOOL_ENABLED = os.getenv(
    "CENTRAL_LLM_APPROVAL_META_TOOL_ENABLED", "0"
).strip().lower() in ("1", "true", "yes", "y")

# ADR-017 phase 2 — connector + client_jobs (Postgres)
CENTRAL_CLIENT_JOBS_ENABLED = os.getenv("CENTRAL_CLIENT_JOBS_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
CENTRAL_CONNECTOR_AUTH_MODE = os.getenv("CENTRAL_CONNECTOR_AUTH_MODE", "jwt").strip().lower()
CENTRAL_CONNECTOR_HEARTBEAT_TTL_SECONDS = max(
    15,
    int(os.getenv("CENTRAL_CONNECTOR_HEARTBEAT_TTL_SECONDS", "90") or "90"),
)
CENTRAL_CLIENT_JOB_LEASE_SECONDS = max(
    15,
    int(os.getenv("CENTRAL_CLIENT_JOB_LEASE_SECONDS", "120") or "120"),
)
CENTRAL_CLIENT_JOB_MAX_RETRIES = max(
    0,
    int(os.getenv("CENTRAL_CLIENT_JOB_MAX_RETRIES", "3") or "3"),
)
CENTRAL_JOB_DISPATCHER_ENABLED = os.getenv("CENTRAL_JOB_DISPATCHER_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
CENTRAL_JOB_DISPATCHER_INTERVAL_SECONDS = max(
    1,
    float(os.getenv("CENTRAL_JOB_DISPATCHER_INTERVAL_SECONDS", "2") or "2"),
)
CENTRAL_JOB_DISPATCHER_BATCH_SIZE = max(
    1,
    int(os.getenv("CENTRAL_JOB_DISPATCHER_BATCH_SIZE", "32") or "32"),
)

# Fase F — agent tools (JSON + get_host_summary); requer use_agent_tools=true no pedido
AGENT_TOOLS_ENABLED = os.getenv("AGENT_TOOLS_ENABLED", "").strip().lower() in ("1", "true", "yes", "y")
AGENT_TOOLS_MAX_EXECUTIONS = int(os.getenv("AGENT_TOOLS_MAX_EXECUTIONS", "1"))

# F4 — RAG semântico do catálogo de tools (pgvector + MiniLM CPU ou hash local); desligado por defeito
AGENT_TOOLS_RAG_ENABLED = os.getenv("AGENT_TOOLS_RAG_ENABLED", "").strip().lower() in ("1", "true", "yes", "y")
AGENT_TOOLS_RAG_TOP_K = int(os.getenv("AGENT_TOOLS_RAG_TOP_K", "8"))
AGENT_TOOLS_RAG_MIN_TOOLS = int(os.getenv("AGENT_TOOLS_RAG_MIN_TOOLS", "4"))
# minilm = sentence-transformers/all-MiniLM-L6-v2 (384d); hash = embed_local_hash (sem torch; coerente ingest+query)
_rag_emb = os.getenv("AGENT_TOOLS_RAG_EMBEDDING_BACKEND", "minilm").strip().lower()
AGENT_TOOLS_RAG_EMBEDDING_BACKEND = _rag_emb if _rag_emb in ("minilm", "hash") else "minilm"
CENTRAL_EMBEDDING_DEVICE = _env_fallback("CENTRAL_EMBEDDING_DEVICE", "SOPHIA_EMBEDDING_DEVICE", "cpu").lower() or "cpu"
# B5 + exemplos estáticos do protocolo / few-shots L1 — sempre intersecção com tools registadas
AGENT_TOOLS_RAG_ALWAYS_INCLUDE_RAW = os.getenv(
    "AGENT_TOOLS_RAG_ALWAYS_INCLUDE",
    "request_shell,manage_workspace_artifact,apply_canvas_patch",
).strip()

# Fase L — fiabilidade modelo local: few-shots no historico + chamadas LLM extra se JSON invalido
AGENT_TOOLS_FEW_SHOT_ENABLED = os.getenv("AGENT_TOOLS_FEW_SHOT_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS = int(os.getenv("AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS", "1"))

# L1-3 — few-shots extra por familia (read-only / HITL / negativo); so aplica se AGENT_TOOLS_FEW_SHOT_ENABLED
AGENT_TOOLS_FEW_SHOT_FAMILIES_ENABLED = os.getenv("AGENT_TOOLS_FEW_SHOT_FAMILIES_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)

# L1-4 — re-prompt quando JSON parseia mas validate_tool_arguments falha
AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS = int(
    os.getenv("AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS", "1")
)

# L1-5 — response_format json_object no model-router (backend llama_cpp_openai); desligado por defeito
AGENT_TOOLS_JSON_MODE_ENABLED = os.getenv("AGENT_TOOLS_JSON_MODE_ENABLED", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)

ORCHESTRATOR_TIMEOUT_SECONDS = float(os.getenv("ORCHESTRATOR_TIMEOUT_SECONDS", "600"))

# Fase 5 — timeouts HTTP orquestrador → model-router (GET /config, GET /openai/models, …)
_mr_http_read_default = min(30.0, max(5.0, ORCHESTRATOR_TIMEOUT_SECONDS))
MODEL_ROUTER_HTTP_READ_TIMEOUT_SECONDS = max(
    5.0,
    min(
        120.0,
        float(
            os.getenv(
                "CENTRAL_MODEL_ROUTER_HTTP_READ_TIMEOUT_SECONDS",
                str(_mr_http_read_default),
            ).strip()
            or str(_mr_http_read_default)
        ),
    ),
)
MODEL_ROUTER_HTTP_CONNECT_TIMEOUT_SECONDS = max(
    1.0,
    min(
        30.0,
        float(os.getenv("CENTRAL_MODEL_ROUTER_HTTP_CONNECT_TIMEOUT_SECONDS", "5").strip() or "5"),
    ),
)

# OC-15 — métricas de tokens quando o backend OpenAI-compatible devolve `usage` (opt-in)
LLM_USAGE_METRICS_ENABLED = os.getenv("LLM_USAGE_METRICS_ENABLED", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)

# Labels UX / SSE (troca de modelo eco ↔ balanced)
CENTRAL_MODEL_LABEL_ECO = _env_fallback("CENTRAL_MODEL_LABEL_ECO", "SOPHIA_MODEL_LABEL_ECO", "Gemma (eco)")
CENTRAL_MODEL_LABEL_BALANCED = _env_fallback(
    "CENTRAL_MODEL_LABEL_BALANCED", "SOPHIA_MODEL_LABEL_BALANCED", "DeepSeek (balanced)"
)
PERCEPTION_MAX_IMAGE_BYTES = int(os.getenv("PERCEPTION_MAX_IMAGE_BYTES", "6000000"))

# P0-10: probes GET /health (ou paths alternativos) por serviço — timeout curto por pedido
STACK_HEALTH_PROBE_TIMEOUT = float(os.getenv("STACK_HEALTH_PROBE_TIMEOUT", "4"))
PROFILE_STORE_PATH = os.getenv(
    "PROFILE_STORE_PATH",
    _join_root(CENTRAL_ROOT, "state/profile.json") if CENTRAL_ROOT else "/tmp/central_llm_profile.json",
)

# L2 — preferências do assistente (UI + opt-in use_saved_assistant_defaults)
ASSISTANT_PREFERENCES_STORE_PATH = os.getenv(
    "ASSISTANT_PREFERENCES_STORE_PATH",
    _join_root(CENTRAL_ROOT, "state/assistant_preferences.json") if CENTRAL_ROOT else "/tmp/central_assistant_preferences.json",
)

# Multi-slot (4) — grafo de partilha de contexto (SSOT no orquestrador)
WIDGET_MULTI_SLOT_ENABLED = os.getenv("WIDGET_MULTI_SLOT_ENABLED", "").strip().lower() in ("1", "true", "yes", "y")
WIDGET_SLOT_GRAPH_STORE_PATH = os.getenv(
    "WIDGET_SLOT_GRAPH_STORE_PATH",
    _join_root(CENTRAL_ROOT, "state/widget_slot_graph.json") if CENTRAL_ROOT else "/tmp/central_widget_slot_graph.json",
).strip()


def _multislot_int(key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(str(os.getenv(key, str(default))).strip() or str(default))
    except ValueError:
        v = default
    return max(lo, min(hi, v))


# Fase 9 — limites multi-slot (UI_BACKEND_CONTRACT §10.1)
CENTRAL_MULTISLOT_DEFAULT_SLOT = _multislot_int("CENTRAL_MULTISLOT_DEFAULT_SLOT", 1, 1, 4)
CENTRAL_MULTISLOT_NEIGHBOR_MAX_MESSAGES = _multislot_int(
    "CENTRAL_MULTISLOT_NEIGHBOR_MAX_MESSAGES", 5, 0, 500
)
CENTRAL_MULTISLOT_MAX_NEIGHBOR_EDGES = _multislot_int(
    "CENTRAL_MULTISLOT_MAX_NEIGHBOR_EDGES", 2, 0, 12
)
CENTRAL_MULTISLOT_AGGREGATE_MAX_CHARS = _multislot_int(
    "CENTRAL_MULTISLOT_AGGREGATE_MAX_CHARS", 12000, 1000, 2_000_000
)
CENTRAL_MULTISLOT_FIRST_TURN_INCLUDE_NEIGHBORS = os.getenv(
    "CENTRAL_MULTISLOT_FIRST_TURN_INCLUDE_NEIGHBORS", "0"
).strip().lower() in ("1", "true", "yes", "y")

# Pré-Fase 11 — SYSTEM `.md` versionado: paths, limites e modo de reload (ver docs/ADR-014-system-prompt-versioning.md)
_ORCH_ROOT_FOR_PROMPT = Path(__file__).resolve().parent.parent
CENTRAL_SYSTEM_PROMPT_BUNDLED_PATH = os.getenv(
    "CENTRAL_SYSTEM_PROMPT_BUNDLED_PATH",
    str(_ORCH_ROOT_FOR_PROMPT / "bundled" / "system_prompt.default.md"),
).strip()
CENTRAL_SYSTEM_PROMPT_OVERLAY_PATH = os.getenv(
    "CENTRAL_SYSTEM_PROMPT_OVERLAY_PATH",
    _join_root(CENTRAL_ROOT, "state/system_prompt.md") if CENTRAL_ROOT else "",
).strip()
CENTRAL_SYSTEM_PROMPT_BUNDLED_ID = (
    os.getenv("CENTRAL_SYSTEM_PROMPT_BUNDLED_ID", "central-orchestrator").strip() or "central-orchestrator"
)
try:
    CENTRAL_SYSTEM_PROMPT_BUNDLED_VERSION = max(
        0, int(str(os.getenv("CENTRAL_SYSTEM_PROMPT_BUNDLED_VERSION", "1")).strip() or "1")
    )
except ValueError:
    CENTRAL_SYSTEM_PROMPT_BUNDLED_VERSION = 1
CENTRAL_SYSTEM_PROMPT_OVERLAY_MAX_BYTES = max(
    4096,
    int(os.getenv("CENTRAL_SYSTEM_PROMPT_OVERLAY_MAX_BYTES", "262144") or "262144"),
)
CENTRAL_SYSTEM_PROMPT_MTIME_POLL_SECONDS = max(
    5, int(os.getenv("CENTRAL_SYSTEM_PROMPT_MTIME_POLL_SECONDS", "60") or "60")
)
_raw_sp_reload = os.getenv("CENTRAL_SYSTEM_PROMPT_RELOAD_MODE", "mtime_poll").strip().lower()
CENTRAL_SYSTEM_PROMPT_RELOAD_MODE: str = (
    "startup_only" if _raw_sp_reload == "startup_only" else "mtime_poll"
)
CENTRAL_SYSTEM_PROMPT_INJECTION_ENABLED = os.getenv(
    "CENTRAL_SYSTEM_PROMPT_INJECTION_ENABLED", "1"
).strip().lower() in ("1", "true", "yes", "y")
CENTRAL_SYSTEM_PROMPT_L6_ANCHOR_ENABLED = os.getenv(
    "CENTRAL_SYSTEM_PROMPT_L6_ANCHOR_ENABLED", "1"
).strip().lower() in ("1", "true", "yes", "y")
CENTRAL_SYSTEM_PROMPT_L6_ANCHOR_MAX_CHARS = max(
    200, int(os.getenv("CENTRAL_SYSTEM_PROMPT_L6_ANCHOR_MAX_CHARS", "1200") or "1200")
)

ORCHESTRATOR_AUDIT_LOG_PATH = os.getenv(
    "ORCHESTRATOR_AUDIT_LOG_PATH",
    _join_root(CENTRAL_ROOT, "audit/orchestrator.jsonl") if CENTRAL_ROOT else "/tmp/central_orchestrator_audit.jsonl",
)

APPROVALS_STORE_PATH = os.getenv(
    "APPROVALS_STORE_PATH",
    _join_root(CENTRAL_ROOT, "state/approvals.json") if CENTRAL_ROOT else "/tmp/central_approvals.json",
)

# Policy read-only no orquestrador (K.2 dupla confirmacao)
SYSTEM_AGENT_POLICY_PATH = os.getenv(
    "SYSTEM_AGENT_POLICY_PATH",
    _join_root(CENTRAL_ROOT, "policies/system-agent.json") if CENTRAL_ROOT else "",
).strip()

# P1 Onda 1 — desktop.open_url / desktop.notify (allowlist + helper no host)
OPEN_URL_HOST_ALLOWLIST_RAW = _env_fallback("CENTRAL_OPEN_URL_HOST_ALLOWLIST", "SOPHIA_OPEN_URL_HOST_ALLOWLIST")
OPEN_URL_ALLOW_HTTP = _env_fallback("CENTRAL_OPEN_URL_ALLOW_HTTP", "SOPHIA_OPEN_URL_ALLOW_HTTP").lower() in (
    "1",
    "true",
    "yes",
    "y",
)
OPEN_URL_MAX_LEN = int(_env_fallback("CENTRAL_OPEN_URL_MAX_LEN", "SOPHIA_OPEN_URL_MAX_LEN", "2048") or "2048")
DESKTOP_NOTIFY_BODY_MAX = int(_env_fallback("CENTRAL_DESKTOP_NOTIFY_BODY_MAX", "SOPHIA_DESKTOP_NOTIFY_BODY_MAX", "512") or "512")
DESKTOP_NOTIFY_TITLE_MAX = int(_env_fallback("CENTRAL_DESKTOP_NOTIFY_TITLE_MAX", "SOPHIA_DESKTOP_NOTIFY_TITLE_MAX", "128") or "128")
DESKTOP_HELPER_PATH = _env_fallback("CENTRAL_DESKTOP_HELPER", "SOPHIA_DESKTOP_HELPER")
DESKTOP_HELPER_TIMEOUT_SEC = float(_env_fallback("CENTRAL_DESKTOP_HELPER_TIMEOUT_SEC", "SOPHIA_DESKTOP_HELPER_TIMEOUT_SEC", "15") or "15")

# P1 Onda 4 — network.endpoint.probe (SSRF: allowlist host:port obrigatória)
PROBE_ALLOWLIST_RAW = _env_fallback("CENTRAL_PROBE_ALLOWLIST", "SOPHIA_PROBE_ALLOWLIST")
PROBE_TIMEOUT_SEC = float(_env_fallback("CENTRAL_PROBE_TIMEOUT_SEC", "SOPHIA_PROBE_TIMEOUT_SEC", "3") or "3")
PROBE_HTTP_PATH_ALLOWLIST_RAW = _env_fallback("CENTRAL_PROBE_HTTP_PATH_ALLOWLIST", "SOPHIA_PROBE_HTTP_PATH_ALLOWLIST")

# P2-3 — filesystem.path.write_config (tamanho máximo do texto na fila; alinhar com FILE_WRITE_CONFIG_MAX_BYTES no agente)
WRITE_CONFIG_MAX_CONTENT_BYTES = int(
    _env_fallback("CENTRAL_WRITE_CONFIG_MAX_CONTENT_BYTES", "SOPHIA_WRITE_CONFIG_MAX_CONTENT_BYTES", "32768") or "32768"
)

# L3 — playbook supervisionado (JSON local; opt-in include_playbook no pedido)
PLAYBOOK_FEATURE_ENABLED = os.getenv("PLAYBOOK_FEATURE_ENABLED", "1").strip().lower() in ("1", "true", "yes", "y")
PLAYBOOK_STORE_PATH = os.getenv(
    "PLAYBOOK_STORE_PATH",
    _join_root(CENTRAL_ROOT, "state/playbook.json") if CENTRAL_ROOT else "/tmp/central_playbook.json",
)
PLAYBOOK_MAX_SNIPPETS_RETRIEVAL = int(os.getenv("PLAYBOOK_MAX_SNIPPETS_RETRIEVAL", "4"))
PLAYBOOK_MAX_BLOCK_CHARS = int(os.getenv("PLAYBOOK_MAX_BLOCK_CHARS", "3600"))
PLAYBOOK_FEEDBACK_LOG_MAX_EVENTS = int(os.getenv("PLAYBOOK_FEEDBACK_LOG_MAX_EVENTS", "500"))

# L3 / NEXT #7 — candidatos a promoção governada (materialização sempre humana; defeito desligado)
PLAYBOOK_GOVERNED_PROMOTION_CANDIDATES_ENABLED = os.getenv(
    "PLAYBOOK_GOVERNED_PROMOTION_CANDIDATES_ENABLED", ""
).strip().lower() in ("1", "true", "yes", "y")
PLAYBOOK_PROMOTION_CANDIDATES_PATH = os.getenv(
    "PLAYBOOK_PROMOTION_CANDIDATES_PATH",
    _join_root(CENTRAL_ROOT, "state/playbook_promotion_candidates.json") if CENTRAL_ROOT else "/tmp/central_playbook_promotion_candidates.json",
)

# shell-gateway + request_shell (porteiro)
SHELL_GATEWAY_URL = os.getenv("SHELL_GATEWAY_URL", "").strip()
SHELL_GATEWAY_TOKEN = os.getenv("SHELL_GATEWAY_TOKEN", "").strip()
SHELL_GATEWAY_HTTP_TIMEOUT = float(os.getenv("SHELL_GATEWAY_HTTP_TIMEOUT", "125"))
SHELL_GATEWAY_CONNECT_TIMEOUT = float(os.getenv("SHELL_GATEWAY_CONNECT_TIMEOUT", "8"))
SHELL_UNKNOWN_LOG_PATH = os.getenv(
    "SHELL_UNKNOWN_LOG_PATH",
    _join_root(CENTRAL_ROOT, "audit/shell_unknown.jsonl") if CENTRAL_ROOT else "/tmp/central_shell_unknown.jsonl",
).strip()
REQUEST_SHELL_SUMMARY_MIN_CHARS = int(os.getenv("REQUEST_SHELL_SUMMARY_MIN_CHARS", "8000"))
REQUEST_SHELL_SUMMARY_ENABLED = os.getenv("REQUEST_SHELL_SUMMARY_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
# cwd permitido para request_shell (prefixos absolutos, vírgulas)
SHELL_REQUEST_CWD_PREFIX_ALLOWLIST_RAW = os.getenv(
    "SHELL_REQUEST_CWD_PREFIX_ALLOWLIST",
    "/central,/tmp,/var/tmp",
).strip()

PRIMARY_AGENT_TOOLS_PATH = os.getenv("PRIMARY_AGENT_TOOLS_PATH", "").strip()

# OC-12 MVP — POST /dev/web-fetch (desligado por defeito; ver ADR-010)
WEB_FETCH_MVP_ENABLED = os.getenv("WEB_FETCH_MVP_ENABLED", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
WEB_FETCH_ALLOWLIST_HOSTS_RAW = os.getenv("WEB_FETCH_ALLOWLIST_HOSTS", "").strip()
WEB_FETCH_MAX_BYTES = int(os.getenv("WEB_FETCH_MAX_BYTES", "262144"))
WEB_FETCH_TIMEOUT_SEC = float(os.getenv("WEB_FETCH_TIMEOUT_SEC", "10"))

# Central (fork cloud): modo produto enxuto — sem dev/homelab/playbook/memória longa na superfície HTTP;
# histórico = só mensagens da sessão no payload; aprovações + /actions mantêm-se para ferramentas permitidas.
CENTRAL_FOCUS_MODE = os.getenv("CENTRAL_FOCUS_MODE", "").strip().lower() in ("1", "true", "yes", "y")

# T19: Atena meta-agent (reservado — desligado por defeito)
CENTRAL_ATENA_ENABLED = os.getenv("CENTRAL_ATENA_ENABLED", "0").strip().lower() in ("1", "true", "yes", "y")

# ContextPipeline — sistema único de contexto (substitui ContextAssembler + ContextEngine)
CONTEXT_PIPELINE_ENABLED = os.getenv("CONTEXT_PIPELINE_ENABLED", "1").strip().lower() in ("1", "true", "yes", "y")

# ContextEngine — pluggable step-based pipeline (ON by default since Onda 3).
CONTEXT_ENGINE_ENABLED = os.getenv("CONTEXT_ENGINE_ENABLED", "1").strip().lower() in ("1", "true", "yes", "y")
# Emergency rollback: set to 1 to fall back to classic pipeline (will be removed).
CONTEXT_ENGINE_DISABLED = os.getenv("CONTEXT_ENGINE_DISABLED", "").strip().lower() in ("1", "true", "yes", "y")

# Product mode — CLI-first contract (trim routes/OpenAPI, file approval gate).
# Legacy alias: MVP_MODE (deprecated env name).
_product_mode_raw = os.getenv("CENTRAL_PRODUCT_MODE", os.getenv("MVP_MODE", "0")).strip().lower()
CENTRAL_PRODUCT_MODE = _product_mode_raw in ("1", "true", "yes", "y")
# Backward-compatible alias for imports during migration.
MVP_MODE = CENTRAL_PRODUCT_MODE

# Sessões de chat persistidas (GET/POST /ui/chat-sessions + chat_session_id no assistente). Por defeito segue o modo foco.
_chat_sess_raw = os.getenv("CHAT_SESSIONS_ENABLED", "").strip().lower()
if _chat_sess_raw in ("1", "true", "yes", "y"):
    CHAT_SESSIONS_ENABLED = True
elif _chat_sess_raw in ("0", "false", "no", "n"):
    CHAT_SESSIONS_ENABLED = False
else:
    CHAT_SESSIONS_ENABLED = CENTRAL_FOCUS_MODE

CHAT_SESSIONS_STORE_PATH = os.getenv(
    "CHAT_SESSIONS_STORE_PATH",
    _join_root(CENTRAL_ROOT, "state/chat_sessions.json") if CENTRAL_ROOT else "/tmp/central_chat_sessions.json",
).strip()
CHAT_SESSIONS_MAX_SESSIONS = int(os.getenv("CHAT_SESSIONS_MAX_SESSIONS", "200"))
CHAT_SESSIONS_MAX_MESSAGES = int(os.getenv("CHAT_SESSIONS_MAX_MESSAGES", "500"))
CHAT_SESSIONS_EVENT_LOG_PATH = os.getenv(
    "CHAT_SESSIONS_EVENT_LOG_PATH",
    _join_root(CENTRAL_ROOT, "state/session_events.jsonl") if CENTRAL_ROOT else "/tmp/central_session_events.jsonl",
).strip()
CHAT_SESSIONS_LEGACY_JSON = os.getenv("CHAT_SESSIONS_LEGACY_JSON", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
CHAT_SESSIONS_EVENT_LOG_ENABLED = os.getenv("CHAT_SESSIONS_EVENT_LOG_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)

# Context system — embeddings locais (Fase 3; ver context/config.py para orçamento de tokens)
_raw_emb_backend = os.getenv("CENTRAL_EMBEDDING_BACKEND", "local").strip().lower()
CENTRAL_EMBEDDING_BACKEND = (
    _raw_emb_backend if _raw_emb_backend in ("local", "minilm", "hash") else "local"
)
CENTRAL_EMBEDDING_MODEL_ID = os.getenv("CENTRAL_EMBEDDING_MODEL_ID", "miniLM-L6-v2").strip() or "miniLM-L6-v2"

# Fase 4 — Central product pack (L0/L1) + RAG namespace product
CENTRAL_PRODUCT_PACK_ENABLED = os.getenv("CENTRAL_PRODUCT_PACK_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
CENTRAL_PRODUCT_RAG_ENABLED = os.getenv("CENTRAL_PRODUCT_RAG_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
CENTRAL_PRODUCT_RAG_TOP_K = int(os.getenv("CENTRAL_PRODUCT_RAG_TOP_K", "8"))
CENTRAL_PRODUCT_RAG_PROMPT_MAX_CHARS = int(os.getenv("CENTRAL_PRODUCT_RAG_PROMPT_MAX_CHARS", "6000"))
CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL = os.getenv("CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)

# Phase 5 — session namespace RAG (product_rag_chunks kind=session)
CENTRAL_SESSION_RAG_ENABLED = os.getenv("CENTRAL_SESSION_RAG_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
CENTRAL_SESSION_RAG_TOP_K = int(os.getenv("CENTRAL_SESSION_RAG_TOP_K", "6"))
CENTRAL_SESSION_RAG_PROMPT_MAX_CHARS = int(os.getenv("CENTRAL_SESSION_RAG_PROMPT_MAX_CHARS", "4000"))
CENTRAL_SESSION_RAG_MAX_FACTS_PER_TURN = int(os.getenv("CENTRAL_SESSION_RAG_MAX_FACTS_PER_TURN", "2"))
CENTRAL_SESSION_RAG_USE_LLM_EXTRACT = os.getenv("CENTRAL_SESSION_RAG_USE_LLM_EXTRACT", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)

# --- Fase 4 — JWT multi-tenant (claim `client_id` por defeito) ---
_raw_jwt_mode = os.getenv("CENTRAL_JWT_MODE", "off").strip().lower()
if _raw_jwt_mode == "required":
    CENTRAL_JWT_MODE: str = "required"
elif _raw_jwt_mode == "optional":
    CENTRAL_JWT_MODE = "optional"
elif _raw_jwt_mode == "hybrid":
    CENTRAL_JWT_MODE = "hybrid"
elif _raw_jwt_mode == "oidc":
    CENTRAL_JWT_MODE = "oidc"
else:
    CENTRAL_JWT_MODE = "off"

CENTRAL_JWT_SECRET = os.getenv("CENTRAL_JWT_SECRET", "").strip()
CENTRAL_JWT_ISSUER = os.getenv("CENTRAL_JWT_ISSUER", "").strip()
CENTRAL_JWT_AUDIENCE = os.getenv("CENTRAL_JWT_AUDIENCE", "").strip()
CENTRAL_JWT_CLIENT_ID_CLAIM = os.getenv("CENTRAL_JWT_CLIENT_ID_CLAIM", "client_id").strip() or "client_id"
CENTRAL_JWT_ACCESS_TTL_SECONDS = max(60, int(os.getenv("CENTRAL_JWT_ACCESS_TTL_SECONDS", "1800") or "1800"))
CENTRAL_JWT_REFRESH_TTL_SECONDS = max(
    300, int(os.getenv("CENTRAL_JWT_REFRESH_TTL_SECONDS", str(7 * 24 * 3600)) or str(7 * 24 * 3600))
)
CENTRAL_JWT_ALGORITHM = os.getenv("CENTRAL_JWT_ALGORITHM", "HS256").strip() or "HS256"

_hs256_modes = ("optional", "required", "hybrid")
if CENTRAL_JWT_MODE in _hs256_modes and not CENTRAL_JWT_SECRET:
    raise RuntimeError(
        "CENTRAL_JWT_MODE requires HS256 but CENTRAL_JWT_SECRET is empty; set a shared secret."
    )

# --- Fase B — OIDC / IdP (G7) ---
CENTRAL_OIDC_ENABLED = os.getenv("CENTRAL_OIDC_ENABLED", "0").strip().lower() in ("1", "true", "yes", "y")
CENTRAL_OIDC_ISSUER_URL = os.getenv("CENTRAL_OIDC_ISSUER_URL", "").strip().rstrip("/")
# Discovery fetch from inside Compose (ex. http://central-keycloak-dev:8080/realms/central).
CENTRAL_OIDC_DISCOVERY_BASE = os.getenv("CENTRAL_OIDC_DISCOVERY_BASE", "").strip().rstrip("/") or CENTRAL_OIDC_ISSUER_URL
# Rewrite localhost IdP URLs for server-side calls (token, JWKS); browser keeps CENTRAL_OIDC_ISSUER_URL host.
CENTRAL_OIDC_HTTP_BASE = os.getenv("CENTRAL_OIDC_HTTP_BASE", "").strip().rstrip("/")
CENTRAL_OIDC_CLIENT_ID = os.getenv("CENTRAL_OIDC_CLIENT_ID", "").strip()
CENTRAL_OIDC_CLIENT_SECRET = os.getenv("CENTRAL_OIDC_CLIENT_SECRET", "").strip()
_raw_oidc_redirects = os.getenv("CENTRAL_OIDC_REDIRECT_URIS", "").strip()
CENTRAL_OIDC_REDIRECT_URIS: list[str] = [u.strip() for u in _raw_oidc_redirects.split(",") if u.strip()]
CENTRAL_OIDC_SCOPES = os.getenv("CENTRAL_OIDC_SCOPES", "openid profile email").strip() or "openid profile email"
CENTRAL_OIDC_TENANT_CLAIM = os.getenv("CENTRAL_OIDC_TENANT_CLAIM", "").strip()
CENTRAL_OIDC_DISCOVERY_CACHE_SECONDS = max(
    60, int(os.getenv("CENTRAL_OIDC_DISCOVERY_CACHE_SECONDS", "3600") or "3600")
)
CENTRAL_OIDC_JWKS_CACHE_SECONDS = max(60, int(os.getenv("CENTRAL_OIDC_JWKS_CACHE_SECONDS", "3600") or "3600"))
CENTRAL_OIDC_CLOCK_SKEW_SECONDS = max(0, min(300, int(os.getenv("CENTRAL_OIDC_CLOCK_SKEW_SECONDS", "60") or "60")))
_raw_oidc_algs = os.getenv("CENTRAL_OIDC_ALLOWED_ALGORITHMS", "RS256,ES256").strip()
CENTRAL_OIDC_ALLOWED_ALGORITHMS: tuple[str, ...] = tuple(
    a.strip() for a in _raw_oidc_algs.split(",") if a.strip()
) or ("RS256", "ES256")
# Resource/API audience for IdP access tokens (hybrid integrations only; ADR-015).
CENTRAL_OIDC_RESOURCE_AUDIENCE = os.getenv("CENTRAL_OIDC_RESOURCE_AUDIENCE", "").strip()
_raw_oidc_strict = os.getenv("CENTRAL_OIDC_STRICT_TENANT", "").strip().lower()
if _raw_oidc_strict in ("1", "true", "yes", "y"):
    CENTRAL_OIDC_STRICT_TENANT = True
elif _raw_oidc_strict in ("0", "false", "no", "n"):
    CENTRAL_OIDC_STRICT_TENANT = False
else:
    CENTRAL_OIDC_STRICT_TENANT = CENTRAL_APP_ENV in ("production", "prod")

if CENTRAL_JWT_MODE in ("oidc", "hybrid") and not CENTRAL_OIDC_ISSUER_URL:
    raise RuntimeError("CENTRAL_JWT_MODE is oidc/hybrid but CENTRAL_OIDC_ISSUER_URL is empty.")

if CENTRAL_JWT_MODE == "oidc" and not CENTRAL_OIDC_RESOURCE_AUDIENCE:
    raise RuntimeError(
        "CENTRAL_JWT_MODE=oidc requires CENTRAL_OIDC_RESOURCE_AUDIENCE (IdP resource/API identifier)."
    )

if CENTRAL_OIDC_ENABLED:
    if not CENTRAL_OIDC_ISSUER_URL:
        raise RuntimeError("CENTRAL_OIDC_ENABLED but CENTRAL_OIDC_ISSUER_URL is empty.")
    if not CENTRAL_OIDC_CLIENT_ID or not CENTRAL_OIDC_CLIENT_SECRET:
        raise RuntimeError("CENTRAL_OIDC_ENABLED requires CENTRAL_OIDC_CLIENT_ID and CENTRAL_OIDC_CLIENT_SECRET.")
    if not CENTRAL_OIDC_REDIRECT_URIS:
        raise RuntimeError("CENTRAL_OIDC_ENABLED requires CENTRAL_OIDC_REDIRECT_URIS (CSV).")
    if "openid" not in {s.strip() for s in CENTRAL_OIDC_SCOPES.split() if s.strip()}:
        raise RuntimeError("CENTRAL_OIDC_SCOPES must include 'openid' (ADR-015).")

# --- Fase A — login credenciais (Postgres) ---
AUTH_USERS_DB_URL = os.getenv("AUTH_USERS_DB_URL", "").strip() or MEMORY_DB_URL
CENTRAL_DEFAULT_CLIENT_ID = os.getenv("CENTRAL_DEFAULT_CLIENT_ID", "default").strip() or "default"
AUTH_PASSWORD_PEPPER = os.getenv("AUTH_PASSWORD_PEPPER", "").strip()
AUTH_LOGIN_ENABLED = os.getenv("AUTH_LOGIN_ENABLED", "1").strip().lower() in ("1", "true", "yes", "y")
AUTH_LOGIN_RATE_LIMIT_PER_WINDOW = max(3, int(os.getenv("AUTH_LOGIN_RATE_LIMIT_PER_WINDOW", "10") or "10"))
AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS = max(
    30, min(3600, int(os.getenv("AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300") or "300"))
)
AUTH_LOGIN_RATE_LIMIT_MAX_KEYS = max(100, int(os.getenv("AUTH_LOGIN_RATE_LIMIT_MAX_KEYS", "2000") or "2000"))
CENTRAL_BOOTSTRAP_ADMIN_ENABLED = os.getenv("CENTRAL_BOOTSTRAP_ADMIN_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
CENTRAL_BOOTSTRAP_ADMIN_EMAIL = os.getenv("CENTRAL_BOOTSTRAP_ADMIN_EMAIL", "root@central.local").strip() or "root@central.local"
CENTRAL_BOOTSTRAP_ADMIN_PASSWORD = os.getenv("CENTRAL_BOOTSTRAP_ADMIN_PASSWORD", "changeme")
CENTRAL_BOOTSTRAP_ADMIN_DISPLAY_NAME = (
    os.getenv("CENTRAL_BOOTSTRAP_ADMIN_DISPLAY_NAME", "root").strip() or "root"
)

# --- Fase 12 — rate limit por tenant (L12 / G8) ---
CENTRAL_RATE_LIMIT_ENABLED = os.getenv("CENTRAL_RATE_LIMIT_ENABLED", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
CENTRAL_RATE_LIMIT_PER_WINDOW = max(1, int(os.getenv("CENTRAL_RATE_LIMIT_PER_WINDOW", "60") or "60"))
CENTRAL_RATE_LIMIT_WINDOW_SECONDS = max(10, min(3600, int(os.getenv("CENTRAL_RATE_LIMIT_WINDOW_SECONDS", "60") or "60")))
CENTRAL_RATE_LIMIT_MAX_TENANTS = max(100, int(os.getenv("CENTRAL_RATE_LIMIT_MAX_TENANTS", "5000") or "5000"))
CENTRAL_CONCURRENT_STREAM_LIMIT_PER_TENANT = max(1, int(os.getenv("CENTRAL_CONCURRENT_STREAM_LIMIT_PER_TENANT", "3") or "3"))
CENTRAL_CONCURRENT_STREAM_LIMIT_ENABLED = os.getenv("CENTRAL_CONCURRENT_STREAM_LIMIT_ENABLED", "0").strip().lower() in ("1", "true", "yes", "y")
CENTRAL_QUOTA_PER_TENANT_PER_HOUR = max(0, int(os.getenv("CENTRAL_QUOTA_PER_TENANT_PER_HOUR", "1000000") or "1000000"))
CENTRAL_QUOTA_ENABLED = os.getenv("CENTRAL_QUOTA_ENABLED", "0").strip().lower() in ("1", "true", "yes", "y")
CENTRAL_QUOTA_COST_PER_TOKEN_INPUT = float(os.getenv("CENTRAL_QUOTA_COST_PER_TOKEN_INPUT", "0.0") or "0.0")
CENTRAL_QUOTA_COST_PER_TOKEN_OUTPUT = float(os.getenv("CENTRAL_QUOTA_COST_PER_TOKEN_OUTPUT", "0.0") or "0.0")
CENTRAL_QUOTA_WEBHOOK_URL = os.getenv("CENTRAL_QUOTA_WEBHOOK_URL", "").strip()

# --- H2 — Enterprise ---
CENTRAL_APPROVAL_SEPARATION = os.getenv("CENTRAL_APPROVAL_SEPARATION", "0").strip().lower() in ("1", "true", "yes", "y")
CENTRAL_WRITE_MODE_DEFAULT = os.getenv("CENTRAL_WRITE_MODE_DEFAULT", "direct_write").strip().lower()
if CENTRAL_WRITE_MODE_DEFAULT not in ("direct_write", "pr_only"):
    CENTRAL_WRITE_MODE_DEFAULT = "direct_write"
CENTRAL_OIDC_ROLE_CLAIM = os.getenv("CENTRAL_OIDC_ROLE_CLAIM", "groups").strip() or "groups"
_raw_oidc_group_map = os.getenv("CENTRAL_OIDC_GROUP_ROLE_MAP", "").strip()
CENTRAL_OIDC_GROUP_ROLE_MAP: dict[str, str] = {}
if _raw_oidc_group_map:
    try:
        import json as _json

        _parsed = _json.loads(_raw_oidc_group_map)
        if isinstance(_parsed, dict):
            CENTRAL_OIDC_GROUP_ROLE_MAP = {str(k): str(v).strip().lower() for k, v in _parsed.items()}
    except (_json.JSONDecodeError, TypeError):
        pass
CENTRAL_SIEM_WEBHOOK_URLS: tuple[str, ...] = tuple(
    u.strip() for u in os.getenv("CENTRAL_SIEM_WEBHOOK_URLS", "").split(",") if u.strip()
)
CENTRAL_SIEM_HEC_TOKEN = os.getenv("CENTRAL_SIEM_HEC_TOKEN", "").strip()
CENTRAL_AUDIT_RETENTION_DAYS = max(
    30, int(os.getenv("CENTRAL_AUDIT_RETENTION_DAYS", "365") or "365")
)
CENTRAL_CLOUD_MODEL_ALLOWLIST: tuple[str, ...] = tuple(
    m.strip() for m in os.getenv("CENTRAL_CLOUD_MODEL_ALLOWLIST", "").split(",") if m.strip()
)
CENTRAL_CLOUD_MODEL_SENSITIVE_PATHS: tuple[str, ...] = tuple(
    p.strip()
    for p in os.getenv(
        "CENTRAL_CLOUD_MODEL_SENSITIVE_PATHS",
        "**/payment/**,**/cardholder/**,**/pii/**,**/secrets/**",
    ).split(",")
    if p.strip()
)
CENTRAL_DLP_TENANT_ALLOWLIST: tuple[str, ...] = tuple(
    t.strip() for t in os.getenv("CENTRAL_DLP_TENANT_ALLOWLIST", "").split(",") if t.strip()
)
CENTRAL_JSON_LOGGING = os.getenv("CENTRAL_JSON_LOGGING", "0").strip().lower() in ("1", "true", "yes", "y")
CENTRAL_ALERT_SLACK_WEBHOOK_URL = os.getenv("CENTRAL_ALERT_SLACK_WEBHOOK_URL", "").strip()
CENTRAL_ALERT_WEBHOOK_URL = os.getenv("CENTRAL_ALERT_WEBHOOK_URL", "").strip()
CENTRAL_DLP_ENABLED = os.getenv("CENTRAL_DLP_ENABLED", "0").strip().lower() in ("1", "true", "yes", "y")
CENTRAL_GITHUB_TOKEN = os.getenv("CENTRAL_GITHUB_TOKEN", "").strip()
CENTRAL_GITHUB_REPO = os.getenv("CENTRAL_GITHUB_REPO", "").strip()
CENTRAL_GITHUB_APP_ID = os.getenv("CENTRAL_GITHUB_APP_ID", "").strip()
CENTRAL_GITHUB_APP_INSTALLATION_ID = os.getenv("CENTRAL_GITHUB_APP_INSTALLATION_ID", "").strip()
CENTRAL_GITHUB_APP_PRIVATE_KEY = os.getenv("CENTRAL_GITHUB_APP_PRIVATE_KEY", "").strip()
CENTRAL_GITLAB_TOKEN = os.getenv("CENTRAL_GITLAB_TOKEN", "").strip()
CENTRAL_GITLAB_PROJECT_ID = os.getenv("CENTRAL_GITLAB_PROJECT_ID", "").strip()
CENTRAL_GITLAB_BASE_URL = os.getenv("CENTRAL_GITLAB_BASE_URL", "https://gitlab.com").strip().rstrip("/")
CENTRAL_CI_WEBHOOK_SECRET = os.getenv("CENTRAL_CI_WEBHOOK_SECRET", "").strip()
CENTRAL_QUOTA_MONTHLY_TOKENS = max(0, int(os.getenv("CENTRAL_QUOTA_MONTHLY_TOKENS", "0") or "0"))

# H3 — break-glass, data residency, air-gap
CENTRAL_BREAK_GLASS_TTL_HOURS = max(
    0.25, min(24.0, float(os.getenv("CENTRAL_BREAK_GLASS_TTL_HOURS", "1") or "1"))
)
CENTRAL_TELEMETRY_DISABLED = os.getenv("CENTRAL_TELEMETRY_DISABLED", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)
CENTRAL_DATA_RESIDENCY = os.getenv("CENTRAL_DATA_RESIDENCY", "").strip().lower() or "unset"
CENTRAL_LLM_ENDPOINT_REGION = os.getenv("CENTRAL_LLM_ENDPOINT_REGION", "").strip().lower() or "unset"
CENTRAL_AIR_GAP_MODE = os.getenv("CENTRAL_AIR_GAP_MODE", "0").strip().lower() in ("1", "true", "yes", "y")

_raw_rl_paths = os.getenv("CENTRAL_RATE_LIMIT_PATH_PREFIXES", "").strip()
if _raw_rl_paths:
    CENTRAL_RATE_LIMIT_PATH_PREFIXES: tuple[str, ...] = tuple(
        p.strip() for p in _raw_rl_paths.split(",") if p.strip()
    )
else:
    CENTRAL_RATE_LIMIT_PATH_PREFIXES = ("/assistant/text", "/assistant/text/stream")

REFRESH_REVOCATIONS_STORE_PATH = os.getenv(
    "REFRESH_REVOCATIONS_STORE_PATH",
    _join_root(CENTRAL_ROOT, "state/refresh_revocations.json") if CENTRAL_ROOT else "/tmp/central_refresh_revocations.json",
).strip()


def validate_runtime_config() -> None:
    """A3.2 — fail-fast on incoherent .env (startup)."""
    if AUTH_LOGIN_ENABLED and not (AUTH_USERS_DB_URL or MEMORY_DB_URL):
        raise RuntimeError(
            "AUTH_LOGIN_ENABLED=1 mas MEMORY_DB_URL (ou AUTH_USERS_DB_URL) em falta."
        )
    if MEMORY_ENABLED and CENTRAL_JWT_MODE in ("required", "optional") and not MEMORY_DB_URL:
        raise RuntimeError("MEMORY_DB_URL em falta com MEMORY_ENABLED e JWT activo.")
    if CENTRAL_APP_ENV in ("staging", "production", "prod") and CENTRAL_JWT_MODE == "off":
        raise RuntimeError("CENTRAL_APP_ENV=staging/production exige CENTRAL_JWT_MODE != off.")


# ADR-015 — production auth policy (after all auth env vars are defined).
# Called from server.py startup to avoid circular import with auth.py.
