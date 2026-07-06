import json
from pathlib import Path

from app.config import PROFILE_STORE_PATH

DEFAULT_PROFILE = "B"

# Perfil do model-router (`POST /infer` `profile`) para cada cartão A/B/C da UI.
# Ver `model-router` config `profiles` (eco | balanced | quality).
_UI_TO_ROUTER_PROFILE: dict[str, str] = {
    "A": "eco",
    "B": "balanced",
    "C": "quality",
}

PROFILES: dict[str, dict[str, str | int]] = {
    "A": {
        "label": "Eco",
        "description": "Menor uso de GPU e consumo, com resposta mais lenta.",
        "n_gpu_layers": 30,
        "ctx_size": 4096,
        "threads": 8,
    },
    "B": {
        "label": "Equilibrado",
        "description": "Equilibrio entre latencia e uso de GPU.",
        "n_gpu_layers": 40,
        "ctx_size": 4096,
        "threads": 8,
    },
    "C": {
        "label": "Performance",
        "description": "Mais rapidez, com maior uso de GPU.",
        "n_gpu_layers": 60,
        "ctx_size": 8192,
        "threads": 8,
    },
}


def _store_path() -> Path:
    return Path(PROFILE_STORE_PATH)


def router_profile_for_ui_profile(ui_id: str) -> str:
    """
    Mapeia o perfil da dashboard (A/B/C) para o nome de perfil do model-router.
    Valores inválidos caem em `balanced`.
    """
    key = (ui_id or "").strip().upper()
    return _UI_TO_ROUTER_PROFILE.get(key, "balanced")


def router_profile_for_agent_tools(router_profile: str) -> str:
    """
    O perfil `eco` (Gemma) não deve decidir JSON de agent tools; forçar `balanced`.
    O mesmo para `local_eco` quando existir na config do router.
    """
    key = (router_profile or "").strip().lower()
    if key in ("eco", "local_eco"):
        return "balanced"
    return router_profile


def get_active_profile() -> str:
    path = _store_path()
    if not path.exists():
        return DEFAULT_PROFILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        selected = str(data.get("active_profile", DEFAULT_PROFILE))
        return selected if selected in PROFILES else DEFAULT_PROFILE
    except (OSError, json.JSONDecodeError):
        return DEFAULT_PROFILE


def set_active_profile(profile_id: str) -> str:
    if profile_id not in PROFILES:
        raise ValueError(f"Perfil invalido: {profile_id}")

    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"active_profile": profile_id}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return profile_id
