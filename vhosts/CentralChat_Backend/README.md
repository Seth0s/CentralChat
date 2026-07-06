# Orchestrator (Central)

Serviço de orquestração do assistente: contexto, inferência via **model-router** (OpenRouter), ferramentas de agente e voz.

## Objetivo

- Expor endpoints unificados para o assistente (texto, stream SSE, voz).
- **Inferência LLM e multimodal:** `MODEL_ROUTER_URL` → serviço `model-router` (OpenRouter).
- **Voz (ADR-016):** STT e TTS na nuvem — **não** são necessários contentores STT/TTS locais num deploy novo.

## Arquitetura de voz (ADR-016)

| Capacidade | Caminho preferido | Env principal |
|------------|-------------------|---------------|
| **STT** (áudio → texto) | Model-router, papel `audio_perceive` (`call_model_router_raw_messages`) | `CENTRAL_AUDIO_PERCEIVE_MODEL_ID`, `MODEL_ROUTER_URL` |
| **TTS** (texto → áudio) | OpenRouter `POST /api/v1/audio/speech` no orquestrador | `CENTRAL_TTS_MODEL_ID`, `OPENROUTER_API_KEY` |
| Legado | Microserviços `STT_SERVICE_URL` / `TTS_SERVICE_URL` | **Deprecated** — fallback com warning nos logs |

### Vídeo (ADR-016 §13)

1. Anexo `kind=video`, MIME `video/mp4` ou `video/webm` (base64).
2. **ffmpeg** no servidor extrai até `CENTRAL_VIDEO_MAX_FRAMES` JPEGs (cap de duração `CENTRAL_VIDEO_MAX_DURATION_SEC`).
3. Cada frame → `vision_perceive`; agregação textual → `video_perceive`.
4. O ficheiro de vídeo integral **não** é enviado ao LLM.

**Stack Docker mínima** (`central/docker-compose.yml`): `model-router` + `orchestrator` + UI. Variáveis `DISABLE_STT` / `DISABLE_TTS` vêm `true` por defeito; para activar voz, ver [docs/guides/ENV_FILES.md](../docs/guides/ENV_FILES.md) (secção ADR-016).

Documentação completa: [ADR-016-model-routing-policy.md](../docs/ADR-016-model-routing-policy.md) · [ADR-016-IMPLEMENTATION-PLAN.md](../docs/ADR-016-IMPLEMENTATION-PLAN.md).

## Requisitos

- Python 3.12+
- **Model-router** em execução (`MODEL_ROUTER_URL`, p.ex. `http://127.0.0.1:8005`)
- Para voz: `OPENROUTER_API_KEY` no orquestrador (ou vault) + IDs em `modality_models.json` / env `CENTRAL_*_MODEL_ID`

## Setup

```bash
cd /caminho/para/central/orchestrator
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Opcional — testes I+ (property-based Hypothesis); a CI do repo instala também.
pip install -r requirements-dev.txt
cp .env.example .env   # ajustar MODEL_ROUTER_URL; voz: ver secção Voz no .env.example
```

## Rodar API

```bash
cd /caminho/para/central/orchestrator
source .venv/bin/activate
uvicorn app.server:app --host 127.0.0.1 --port 8004 --reload
```

Fábrica da aplicação (Fase 1): `from app.server import create_app` — útil para testes isolados. Re-export: `uvicorn app.application:app` (equivalente ao alvo acima).

## Endpoints

Contrato completo com a UI (HTTP + SSE): [../docs/UI_BACKEND_CONTRACT.md](../docs/UI_BACKEND_CONTRACT.md).

- `GET /health`
- `GET /config` — inclui `modality_models` (papéis servidor, read-only)
- `GET /ui/inference_catalog`
- `POST /assistant/text` / `POST /assistant/text/stream`
- `POST /assistant/voice` — requer STT/TTS activos (OpenRouter ou legado)

## Testes

```bash
curl "http://127.0.0.1:8004/health"
curl "http://127.0.0.1:8004/config" | jq '.modality_models.roles[:3]'
```

```bash
curl -X POST "http://127.0.0.1:8004/assistant/text" \
  -H "Content-Type: application/json" \
  -d '{"text":"Ola, me responda em uma frase curta."}'
```

Voz (com `DISABLE_STT=0`, `DISABLE_TTS=0`, `OPENROUTER_API_KEY` e modelos ADR-016 definidos):

```bash
curl -X POST "http://127.0.0.1:8004/assistant/voice" \
  -F "file=@/caminho/para/o/teu_audio.wav"
```

Testes automatizados: `PYTHONPATH=. python -m pytest tests/test_openrouter_audio.py -q`

## Execução no cliente (ADR-017)

Deploy **tenant** (widget): inferência e HITL no orquestrador; shell e ficheiros no **connector** local.

| Env | Defeito | Efeito |
|-----|---------|--------|
| `CENTRAL_LEGACY_PLATFORM_TOOLS` | `0` | Sem tools VPS (`list_processes`, `grep_workspace`, …) no catálogo LLM |
| `CENTRAL_INCLUDE_PLATFORM_CONTEXT` | `0` | Sem bloco `[FACTUAL_HOST_CONTEXT]` da VPS no prompt |

Homelab: `CENTRAL_LEGACY_PLATFORM_TOOLS=1` + `SYSTEM_AGENT_URL` / `SHELL_GATEWAY_URL` no `.env`. Código legado: `app/old_tools/`. Connector: [../connector/README.md](../connector/README.md).
