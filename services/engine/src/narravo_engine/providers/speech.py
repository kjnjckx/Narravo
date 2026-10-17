import io
import json
import wave
from typing import Any, Literal

from mutagen.mp3 import MP3

from .models import ProviderConfig
from .transport import ProviderError, Transport, bounded_body


def split_text(text: str, maximum: int = 280) -> list[tuple[int, int, str]]:
    result = []
    start = 0
    while start < len(text):
        end = min(start + maximum, len(text))
        if end < len(text):
            boundary = max(
                (text.rfind(mark, start + maximum // 2, end) for mark in "。！？；\n"), default=-1
            )
            if boundary >= 0:
                end = boundary + 1
        result.append((start, end, text[start:end]))
        start = end
    return result


def validate_audio(raw: bytes) -> tuple[str, Literal["audio/wav", "audio/mpeg"], float]:
    if len(raw) > 8 * 1024 * 1024:
        raise ProviderError("AUDIO_TOO_LARGE", "单段音频超过缓存读取上限，请缩短分段。")
    try:
        if raw.startswith(b"RIFF") and raw[8:12] == b"WAVE":
            with wave.open(io.BytesIO(raw)) as audio:
                frames, rate = audio.getnframes(), audio.getframerate()
                expected = frames * audio.getnchannels() * audio.getsampwidth()
                if frames < 1 or rate < 8000 or len(audio.readframes(frames)) != expected:
                    raise ValueError("invalid wave")
                return "wav", "audio/wav", frames / rate
        probe: Any = MP3
        info = probe(io.BytesIO(raw)).info
        if info is None or info.length <= 0:
            raise ValueError("empty mp3")
        return "mp3", "audio/mpeg", float(info.length)
    except Exception as exc:
        raise ProviderError(
            "INVALID_AUDIO", "语音返回的音频文件不完整或格式不受支持，未加入播放列表。"
        ) from exc


async def synthesize(
    config: ProviderConfig,
    secret: str,
    text: str,
    transport: Transport,
    expression: tuple[str, float] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    if config.protocol == "minimax_speech":
        path = "/t2a_v2"
        body: dict[str, Any] = {
            "model": config.model,
            "text": text,
            "stream": False,
            "output_format": "hex",
            "voice_setting": {"voice_id": config.voice, "speed": 1, "vol": 1, "pitch": 0},
            "audio_setting": {"sample_rate": 24000, "format": "wav", "channel": 1},
        }
    elif config.protocol == "elevenlabs":
        path = "/text-to-speech/" + config.voice
        body = {"model_id": config.model, "text": text}
    else:
        path = "/audio/speech"
        body = {
            "model": config.model,
            "voice": config.voice,
            "input": text,
            "response_format": "wav",
        }
    if expression is not None:
        emotion, speed = expression
        if (
            config.protocol != "minimax_speech"
            or not config.speech_expression
            or config.model not in {"speech-2.6-hd", "speech-2.6-turbo"}
            or emotion not in {"neutral", "happy", "sad", "angry"}
            or not 0.5 <= speed <= 2
        ):
            raise ProviderError(
                "UNSUPPORTED_EXPRESSION", "所选表达参数不受此配置支持，请使用普通语气。"
            )
        body["voice_setting"]["speed"] = speed
        if emotion != "neutral":
            body["voice_setting"]["emotion"] = emotion
    async with transport.post(config, secret, path, body) as response:
        raw = await bounded_body(response, 12 * 1024 * 1024)
    if config.protocol == "minimax_speech":
        try:
            payload = json.loads(raw)
            code = payload.get("base_resp", {}).get("status_code", 0)
            if code:
                mapping = {1004: "AUTH_FAILED", 1008: "QUOTA_EXCEEDED", 1002: "RATE_LIMITED"}
                raise ProviderError(
                    mapping.get(code, "PROVIDER_ERROR"),
                    "MiniMax 拒绝了合成，请检查密钥、额度、模型和音色权限。",
                )
            raw = bytes.fromhex(payload["data"]["audio"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ProviderError(
                "INVALID_RESPONSE", "MiniMax 没有返回合法音频，请检查模型与音色。"
            ) from exc
    return raw, {"input_characters": len(text)}
