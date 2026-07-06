"""
L2 — preferências locais do assistente (JSON em CENTRAL_ROOT/state).

Não misturar com policy do system-agent; não armazenar segredos.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import ASSISTANT_PREFERENCES_STORE_PATH

VERBOSITY_VALUES = frozenset({"short", "normal", "long"})
_INFERENCE_DEST_VALUES = frozenset({"local", "api"})
_TONE_HINT_MAX = 280
_LLM_MODEL_ID_MAX = 256
_AUX_DEST_VALUES = _INFERENCE_DEST_VALUES
_EMBEDDING_DEST_VALUES = _INFERENCE_DEST_VALUES
_EMBEDDING_MODEL_ID_MAX = 128
_VALID_AUTO_TIERS = frozenset({"economy", "balanced", "premium"})


def default_preferences() -> dict[str, Any]:
    return {
        "verbosity": "normal",
        "tone_hint": "",
        "inference_destination": "local",
        "llm_model_id": "",
        # Modo API: vazio + tier preenchido = Auto (pacote de política); vazio + tier vazio = default do router.
        "auto_tier": "",
        # Aux LLM (compactação/percepção/etc.) — deve poder ser diferente do chat principal.
        "aux_llm_destination": "local",
        "aux_llm_model_id": "",
        # Embeddings (memória externa pgvector) — UI escolhe; default local CPU.
        "embedding_destination": "local",
        "embedding_model_id": "",
        "default_include_long_session_memory": False,
        # Memória externa (Postgres+pgvector).
        "default_include_memory_recall": False,
        "default_include_host_context": False,
        "default_include_playbook": False,
        "default_include_capability_digest": False,
        "default_use_agent_tools": True,
        # Inference parameters
        "temperature": 0.0,
        "effort": "",
        "provider_routing": "",
        "thinking_budget": 0,
    }


def _store_path() -> Path:
    from app.shared.tenant_paths import resolve_preferences_path

    return resolve_preferences_path(ASSISTANT_PREFERENCES_STORE_PATH)


def load_preferences() -> dict[str, Any]:
    """Preferências efectivas (merge com defeitos)."""
    base = default_preferences()
    path = _store_path()
    if not path.is_file():
        return dict(base)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(base)
    if not isinstance(raw, dict):
        return dict(base)
    out = dict(base)
    for k in base:
        if k not in raw:
            continue
        v = raw[k]
        if k == "verbosity":
            if isinstance(v, str) and v in VERBOSITY_VALUES:
                out[k] = v
        elif k == "tone_hint":
            if v is None:
                out[k] = ""
            elif isinstance(v, str):
                out[k] = v.strip()[:_TONE_HINT_MAX]
        elif k == "inference_destination":
            if isinstance(v, str) and v.strip().lower() in _INFERENCE_DEST_VALUES:
                out[k] = v.strip().lower()
        elif k == "llm_model_id":
            if v is None:
                out[k] = ""
            elif isinstance(v, str):
                out[k] = v.strip()[:_LLM_MODEL_ID_MAX]
        elif k == "aux_llm_destination":
            if isinstance(v, str) and v.strip().lower() in _AUX_DEST_VALUES:
                out[k] = v.strip().lower()
        elif k == "aux_llm_model_id":
            if v is None:
                out[k] = ""
            elif isinstance(v, str):
                out[k] = v.strip()[:_LLM_MODEL_ID_MAX]
        elif k == "embedding_destination":
            if isinstance(v, str) and v.strip().lower() in _EMBEDDING_DEST_VALUES:
                out[k] = v.strip().lower()
        elif k == "embedding_model_id":
            if v is None:
                out[k] = ""
            elif isinstance(v, str):
                out[k] = v.strip()[:_EMBEDDING_MODEL_ID_MAX]
        elif k == "auto_tier":
            if v is None:
                out[k] = ""
            elif isinstance(v, str):
                s = v.strip().lower()
                out[k] = s if (not s or s in _VALID_AUTO_TIERS) else ""
        elif k == "temperature":
            if isinstance(v, (int, float)):
                t = float(v)
                out[k] = t if 0.0 <= t <= 2.0 else 0.0
        elif k == "effort":
            if isinstance(v, str):
                s = v.strip().lower()
                out[k] = s if s in ("low", "medium", "high") else ""
        elif k == "provider_routing":
            if isinstance(v, str):
                s = v.strip().lower()
                out[k] = s if s in ("cheapest", "fastest", "throughput") else ""
        elif k == "thinking_budget":
            if isinstance(v, (int, float)):
                out[k] = max(0, int(v))
        elif k.startswith("default_include") or k == "default_use_agent_tools":
            out[k] = bool(v)
    return out


def _validate_patch(patch: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Normaliza campos conhecidos; desconhecidos ignorados. Devolve (merged_delta, erro)."""
    if not isinstance(patch, dict):
        return None, "body_deve_ser_objecto_json"
    delta: dict[str, Any] = {}
    base_keys = frozenset(default_preferences().keys())
    for key, v in patch.items():
        if key not in base_keys:
            continue
        if key == "verbosity":
            if not isinstance(v, str) or v not in VERBOSITY_VALUES:
                return None, f"verbosity_invalido:{v!r}"
            delta[key] = v
        elif key == "tone_hint":
            if v is None:
                delta[key] = ""
            elif isinstance(v, str):
                delta[key] = v.strip()[:_TONE_HINT_MAX]
            else:
                return None, "tone_hint_deve_ser_string"
        elif key == "inference_destination":
            if not isinstance(v, str) or v.strip().lower() not in _INFERENCE_DEST_VALUES:
                return None, f"inference_destination_invalido:{v!r}"
            delta[key] = v.strip().lower()
        elif key == "llm_model_id":
            if v is None:
                delta[key] = ""
            elif isinstance(v, str):
                delta[key] = v.strip()[:_LLM_MODEL_ID_MAX]
            else:
                return None, "llm_model_id_deve_ser_string"
        elif key == "auto_tier":
            if v is None:
                delta[key] = ""
            elif isinstance(v, str):
                s = v.strip().lower()
                if s and s not in _VALID_AUTO_TIERS:
                    return None, f"auto_tier_invalido:{v!r}"
                delta[key] = s
            else:
                return None, "auto_tier_deve_ser_string"
        elif key == "aux_llm_destination":
            if not isinstance(v, str) or v.strip().lower() not in _AUX_DEST_VALUES:
                return None, f"aux_llm_destination_invalido:{v!r}"
            delta[key] = v.strip().lower()
        elif key == "aux_llm_model_id":
            if v is None:
                delta[key] = ""
            elif isinstance(v, str):
                delta[key] = v.strip()[:_LLM_MODEL_ID_MAX]
            else:
                return None, "aux_llm_model_id_deve_ser_string"
        elif key == "embedding_destination":
            if not isinstance(v, str) or v.strip().lower() not in _EMBEDDING_DEST_VALUES:
                return None, f"embedding_destination_invalido:{v!r}"
            delta[key] = v.strip().lower()
        elif key == "embedding_model_id":
            if v is None:
                delta[key] = ""
            elif isinstance(v, str):
                delta[key] = v.strip()[:_EMBEDDING_MODEL_ID_MAX]
            else:
                return None, "embedding_model_id_deve_ser_string"
        elif key == "temperature":
            if v is None:
                delta[key] = 0.0
            elif isinstance(v, (int, float)):
                t = float(v)
                if t < 0.0 or t > 2.0:
                    return None, "temperature_fora_do_intervalo_0_2"
                delta[key] = t
            else:
                return None, "temperature_deve_ser_numero"
        elif key == "effort":
            if v is None:
                delta[key] = ""
            elif isinstance(v, str):
                s = v.strip().lower()
                if s and s not in ("low", "medium", "high"):
                    return None, f"effort_invalido:{v!r}"
                delta[key] = s
            else:
                return None, "effort_deve_ser_string"
        elif key == "provider_routing":
            if v is None:
                delta[key] = ""
            elif isinstance(v, str):
                s = v.strip().lower()
                if s and s not in ("cheapest", "fastest", "throughput"):
                    return None, f"provider_routing_invalido:{v!r}"
                delta[key] = s
            else:
                return None, "provider_routing_deve_ser_string"
        elif key == "thinking_budget":
            if v is None:
                delta[key] = 0
            elif isinstance(v, (int, float)):
                tb = int(v)
                if tb < 0:
                    return None, "thinking_budget_negativo"
                delta[key] = tb
            else:
                return None, "thinking_budget_deve_ser_numero"
        elif key.startswith("default_include") or key == "default_use_agent_tools":
            if not isinstance(v, bool):
                return None, f"{key}_deve_ser_boolean"
            delta[key] = v
    return delta, None


def merge_preferences_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Lê, aplica delta, grava. Levanta ValueError com mensagem curta se inválido."""
    delta, err = _validate_patch(patch)
    if err:
        raise ValueError(err)
    current = load_preferences()
    current.update(delta)
    # Regras de coerência manual vs Auto
    mid_stripped = str(current.get("llm_model_id") or "").strip()
    if mid_stripped:
        current["auto_tier"] = ""
    if str(current.get("inference_destination") or "local") != "api":
        current["auto_tier"] = ""

    if str(current.get("inference_destination") or "local") == "api":
        from app.inference import validate_llm_model_id_shape

        mid = str(current.get("llm_model_id") or "").strip()

        if mid:
            if not validate_llm_model_id_shape(mid):
                raise ValueError("llm_model_id_formato_invalido")
            from app.shared.inference_governance import assert_model_allowed

            assert_model_allowed(mid)
    if str(current.get("aux_llm_destination") or "local") == "api":
        mid = str(current.get("aux_llm_model_id") or "").strip()
        if mid and not validate_llm_model_id_shape(mid):
            raise ValueError("aux_llm_model_id_formato_invalido")
        if mid:
            from app.shared.inference_governance import assert_model_allowed

            assert_model_allowed(mid)
    if str(current.get("embedding_destination") or "local") == "api":
        mid = str(current.get("embedding_model_id") or "").strip()
        if mid and not validate_llm_model_id_shape(mid):
            raise ValueError("embedding_model_id_formato_invalido")
        if mid:
            from app.shared.inference_governance import assert_model_allowed

            assert_model_allowed(mid)
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


def preferences_system_messages(prefs: dict[str, Any]) -> list[dict[str, str]]:
    """Mensagens system curtas derivadas de verbosidade / tone_hint (sem policy system-agent)."""
    lines: list[str] = []
    v = str(prefs.get("verbosity") or "normal")
    if v == "short":
        lines.append("O utilizador prefere respostas curtas e directas quando possivel.")
    elif v == "long":
        lines.append("O utilizador aceita explicacoes mais detalhadas quando forem uteis.")
    th = str(prefs.get("tone_hint") or "").strip()
    if th:
        lines.append(f"Nota de tom preferida (texto local do utilizador): {th}")
    if not lines:
        return []
    body = "[PREFERENCIAS_UTILIZADOR — ficheiro state/assistant_preferences.json]\n" + "\n".join(lines)
    return [{"role": "system", "content": body}]
