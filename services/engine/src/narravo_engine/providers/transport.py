import asyncio
import ipaddress
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import httpx

from .models import ProviderConfig


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


async def validate_address(config: ProviderConfig) -> None:
    host = urlsplit(config.base_url).hostname
    if not host:
        raise ProviderError("INVALID_ENDPOINT", "服务地址无效，请检查设置。")
    try:
        results = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, host, None), 5)
        addresses = [ipaddress.ip_address(item[4][0]) for item in results]
    except (OSError, ValueError, TimeoutError) as exc:
        raise ProviderError("NETWORK_ERROR", "无法解析服务地址，请检查网络和 API 地址。") from exc
    for address in addresses:
        if address.is_link_local or address.is_multicast or address.is_unspecified:
            raise ProviderError("INVALID_ENDPOINT", "此网络地址不允许用作模型服务。")
        if not address.is_global and not config.allow_local:
            raise ProviderError(
                "LOCAL_ENDPOINT_DISABLED", "这是本地或内网地址，请明确启用本地服务后再使用。"
            )


def headers(config: ProviderConfig, secret: str) -> dict[str, str]:
    result = {"Content-Type": "application/json"}
    if config.protocol == "anthropic":
        result.update({"x-api-key": secret, "anthropic-version": "2023-06-01"})
    elif config.protocol == "elevenlabs":
        result["xi-api-key"] = secret
    elif secret:
        result["Authorization"] = "Bearer " + secret
    return result


class Transport:
    def __init__(self, mock: httpx.AsyncBaseTransport | None = None):
        self.mock = mock

    @asynccontextmanager
    async def post(
        self, config: ProviderConfig, secret: str, path: str, body: dict[str, Any]
    ) -> AsyncIterator[httpx.Response]:
        if self.mock is None:
            await validate_address(config)
        try:
            async with (
                asyncio.timeout(180),
                httpx.AsyncClient(
                    transport=self.mock,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(30, connect=10, write=15, pool=5),
                ) as client,
                client.stream(
                    "POST",
                    config.base_url.rstrip("/") + path,
                    headers=headers(config, secret),
                    json=body,
                ) as response,
            ):
                status = response.status_code
                if status >= 300:
                    mapping = {
                        401: ("AUTH_FAILED", "密钥无效或已过期，请在模型设置中更新。"),
                        403: ("AUTH_FAILED", "此账号无权使用该模型或区域，请检查平台权限。"),
                        402: ("QUOTA_EXCEEDED", "账号额度不足，请检查服务平台余额。"),
                        429: ("RATE_LIMITED", "服务限流，请稍后手动重试；本次不会自动重发。"),
                        400: (
                            "INVALID_PROVIDER_PARAMETERS",
                            "模型或参数不受支持，请检查模型 ID、协议与参数开关。",
                        ),
                        404: (
                            "MODEL_NOT_FOUND",
                            "模型或接口不存在，请检查模型 ID 与 API 基础地址。",
                        ),
                    }
                    code, message = mapping.get(
                        status, ("PROVIDER_ERROR", "服务拒绝请求，请检查配置并稍后手动重试。")
                    )
                    if 300 <= status < 400:
                        code, message = (
                            "REDIRECT_BLOCKED",
                            "服务返回重定向。请核实并直接配置最终地址，不会转发密钥。",
                        )
                    raise ProviderError(code, message)
                yield response
        except (httpx.TransportError, TimeoutError) as exc:
            # A POST may already have reached the service. Never replay on restart or timeout.
            raise ProviderError(
                "UNKNOWN_OUTCOME",
                "网络中断或超时，远端可能已处理并计费。已收到的内容会保留，请检查后决定是否重试。",
            ) from exc


async def bounded_body(response: httpx.Response, maximum: int) -> bytes:
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) > maximum:
            raise ProviderError("RESPONSE_TOO_LARGE", "服务返回内容超过限制，请缩短输入或输出。")
    return bytes(data)


async def sse(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    import json

    total = 0
    buffer = ""
    async for chunk in response.aiter_text():
        total += len(chunk.encode("utf-8"))
        if total > 4 * 1024 * 1024:
            raise ProviderError("RESPONSE_TOO_LARGE", "模型响应过长，已停止接收。")
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.rstrip("\r")
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                yield {"_done": True}
                return
            try:
                value = json.loads(payload)
            except ValueError as exc:
                raise ProviderError(
                    "INVALID_RESPONSE", "模型返回的流式格式无效，请检查所选协议。"
                ) from exc
            if not isinstance(value, dict):
                raise ProviderError("INVALID_RESPONSE", "模型响应格式无效。")
            yield value
    if buffer.strip():
        raise ProviderError("UNKNOWN_OUTCOME", "流式响应意外结束，远端计费状态未知。")
