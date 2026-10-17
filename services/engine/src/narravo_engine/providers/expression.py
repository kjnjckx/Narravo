"""Conservative, opt-in expression capability for an exact provider configuration.

Checked 2026-10-17 against MiniMax's HTTP API and official MiniMax-AI TTS guide.
Only speech-2.6-hd/turbo manual happy/sad/angry controls are enabled here.
Other tags/models/providers fall back visibly; this is not an account capability probe.
"""

from .models import ProviderConfig


def expression_plan(
    config: ProviderConfig | None, requested: str, speed: float | None
) -> tuple[str, float, str]:
    supported = bool(
        config
        and config.protocol == "minimax_speech"
        and config.model in {"speech-2.6-hd", "speech-2.6-turbo"}
        and config.speech_expression
    )
    effective = requested if supported and requested in {"happy", "sad", "angry"} else "neutral"
    effective_speed = (
        (
            speed
            if speed is not None
            else {"whisper": 0.85, "gentle": 0.92, "angry": 1.08, "sad": 0.92}.get(requested, 1.0)
        )
        if supported
        else 1.0
    )
    if not supported:
        warning = "此配置未启用已核对的表达能力，回退普通语气与默认速度；保持所选音色。"
    elif effective != requested:
        warning = f"{requested} 未声明为此模型的受支持语气，回退普通语气；仅调整已支持的速度。"
    else:
        warning = "按已启用的 MiniMax 2.6 表达参数合成；账号可用性、人设遵从与听感尚需真实验收。"
    return effective, float(effective_speed), warning
