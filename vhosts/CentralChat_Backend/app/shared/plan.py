"""Plano de acao estruturado (Fase A — Decision Layer)."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.tools import iter_agent_tool_plan_specs, registered_tool_plan_kinds

_CORE_PLAN_KINDS = frozenset(
    {
        "infer",
        "transcribe",
        "synthesize",
        "host.read",
        "noop",
    }
)


class PlanStep(BaseModel):
    step_id: str = Field(..., description="Identificador estavel dentro do plano")
    kind: str = Field(
        ...,
        description=(
            "Tipo de passo: infer/transcribe/synthesize/host.read/noop ou tool.* "
            "registados em tool_registry (ex.: tool.host_summary)"
        ),
    )
    risk_hint: str = Field(default="low", description="low | medium | high")
    description: str = ""
    target: str | None = Field(default=None, description="Alvo opcional (servico, recurso)")

    @field_validator("kind")
    @classmethod
    def kind_must_be_known(cls, v: str) -> str:
        if v in _CORE_PLAN_KINDS or v in registered_tool_plan_kinds():
            return v
        raise ValueError(f"unknown plan step kind: {v!r}")

    @field_validator("risk_hint")
    @classmethod
    def risk_hint_allowed(cls, v: str) -> str:
        if v in ("low", "medium", "high"):
            return v
        raise ValueError(f"invalid risk_hint: {v!r}")


class ActionPlan(BaseModel):
    request_id: str
    schema_version: str = Field(default="1", description="Versao do contrato do plano")
    steps: list[PlanStep] = Field(default_factory=list)


def _append_registry_tool_steps(steps: list[PlanStep], start_index: int) -> int:
    """Acrescenta PlanStep por tool registada; devolve proximo indice livre."""
    n = start_index
    for plan_kind, desc, risk, target in iter_agent_tool_plan_specs():
        steps.append(
            PlanStep(
                step_id=str(n),
                kind=plan_kind,
                risk_hint=risk,
                description=desc,
                target=target,
            )
        )
        n += 1
    return n


def build_plan_text_chat(request_id: str) -> ActionPlan:
    """Fluxo actual: LLM -> (passos tool opcionais no plano) -> TTS."""
    steps: list[PlanStep] = [
        PlanStep(
            step_id="1",
            kind="infer",
            risk_hint="low",
            description="Gerar resposta via model-router/LLM",
            target="llm",
        ),
    ]
    n = _append_registry_tool_steps(steps, start_index=2)
    steps.append(
        PlanStep(
            step_id=str(n),
            kind="synthesize",
            risk_hint="low",
            description="Sintetizar audio via TTS",
            target="tts",
        ),
    )
    return ActionPlan(request_id=request_id, steps=steps)


def build_plan_voice_chat(request_id: str) -> ActionPlan:
    """Fluxo actual: STT -> LLM -> (passos tool no plano) -> TTS."""
    steps: list[PlanStep] = [
        PlanStep(
            step_id="1",
            kind="transcribe",
            risk_hint="low",
            description="Transcrever audio via STT",
            target="stt",
        ),
        PlanStep(
            step_id="2",
            kind="infer",
            risk_hint="low",
            description="Gerar resposta via model-router/LLM",
            target="llm",
        ),
    ]
    n = _append_registry_tool_steps(steps, start_index=3)
    steps.append(
        PlanStep(
            step_id=str(n),
            kind="synthesize",
            risk_hint="low",
            description="Sintetizar audio via TTS",
            target="tts",
        ),
    )
    return ActionPlan(request_id=request_id, steps=steps)
