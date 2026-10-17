"""Test-only HTTP transport. Never imported or bundled by the desktop application."""
import asyncio
import io
import json
import wave

import httpx

from narravo_engine.providers.transport import Transport


class ChatStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        events = [
            {"model": "fixture-model-v1", "choices": [{"delta": {"content": "你好😀。"}}]},
            {"choices": [{"delta": {"content": "灯塔的灯还亮着，我们慢慢说。"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 40, "completion_tokens": 20}},
        ]
        for index, event in enumerate(events):
            if index == 1:
                await asyncio.sleep(1.2)
            yield ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
        yield b"data: [DONE]\n\n"


def respond(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith('/chat/completions'):
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        if "chat_scoped" in system:
            if system.startswith("只输出一个 JSON"):
                public = json.loads(system.split("\n", 1)[1])["public_members"]
                queue = [member["member_id"] for member in public[:3]]
                value = {"choices": [{"delta": {"content": json.dumps(queue)}}]}
                return httpx.Response(200, content=("data: " + json.dumps(value) + "\n\ndata: [DONE]\n\n").encode(), headers={"content-type": "text/event-stream"})
            return httpx.Response(200, stream=ChatStream(), headers={"content-type": "text/event-stream"})
        payload = {"model":"fixture-model-v1","choices":[{"delta":{"content":"国王发现王冠失踪了。😀"}}]}
        usage = {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":50,"completion_tokens":12}}
        return httpx.Response(200,content=('data: '+json.dumps(payload,ensure_ascii=False)+'\n\ndata: '+json.dumps(usage)+'\n\ndata: [DONE]\n\n').encode(),headers={'content-type':'text/event-stream'})
    if request.url.path.endswith('/audio/speech'):
        output=io.BytesIO()
        with wave.open(output,'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(24000);audio.writeframes(b'\x00\x00'*4800)
        return httpx.Response(200,content=output.getvalue(),headers={'content-type':'audio/wav'})
    return httpx.Response(404,json={'error':'unconfigured test path'})


original_init=Transport.__init__
def mock_init(self, mock=None):
    original_init(self,httpx.MockTransport(respond))
Transport.__init__=mock_init

from narravo_engine.__main__ import main
main()
