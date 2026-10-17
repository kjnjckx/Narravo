"""Opt-in native UI fixture: loopback SSE + test tone, no secrets or cloud calls.

Run with the engine virtualenv, --data-dir pointing to a NEW empty test directory.
The tone proves audio transport/playback only; it is not speech or a quality sample.
"""

import argparse
import io
import json
import math
import struct
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from narravo_engine import roleplay_models as r
from narravo_engine.domain import Domain
from narravo_engine.providers.models import NetworkSet, ProviderConfig, ProviderSave
from narravo_engine.storage import Storage


def tone() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(
            b"".join(
                struct.pack("<h", round(1200 * math.sin(i * 2 * math.pi * 440 / 24000)))
                for i in range(14400)
            )
        )
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None:
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length < 256 * 1024:
            self.send_error(413)
            return
        data = json.loads(self.rfile.read(length))
        if self.path == "/v1/audio/speech":
            raw = tone()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        system = data["messages"][0]["content"]
        content = [
            "你好，这是原生测试。",
            "文字仍在生成，前一句已经可以播放。",
            "这只是本地替身，未调用真实模型。",
        ]
        if system.startswith("只输出一个 JSON"):
            public = json.loads(system.split("\n", 1)[1])["public_members"]
            content = [json.dumps([m["member_id"] for m in public[:3]])]
        try:
            for index, text in enumerate(content):
                if index:
                    time.sleep(1.2)
                event = {"model": "native-fixture-v1", "choices": [{"delta": {"content": text}}]}
                self.wfile.write(
                    ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
                )
                self.wfile.flush()
            event = {
                "usage": {"prompt_tokens": 40, "completion_tokens": 24},
                "choices": [{"delta": {}, "finish_reason": "stop"}],
            }
            self.wfile.write(("data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n").encode())
        except (BrokenPipeError, ConnectionResetError):
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=1438)
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    if list(args.data_dir.iterdir()):
        raise SystemExit(
            "Fixture requires a new empty directory; existing data will not be changed."
        )
    domain = Domain(Storage(args.data_dir))
    for kind, id_, protocol in [
        ("llm", "a" * 32, "openai_chat"),
        ("tts", "b" * 32, "openai_speech"),
    ]:
        config = ProviderConfig(
            id=id_,
            name="原生本地替身 " + kind,
            kind=kind,
            protocol=protocol,
            base_url=f"http://127.0.0.1:{args.port}/v1",
            model="native-fixture",
            voice="fixture-voice",
            allow_local=True,
            requires_key=False,
            max_output_tokens=128,
        )
        domain.providers.save(ProviderSave(config=config), False)
    domain.providers.network_set(NetworkSet(enabled=True))
    chars = [
        domain.roleplay.character_save(
            r.CharacterSave(
                persona=r.Persona(
                    name=name,
                    introduction="虚构的本地验收角色",
                    personality="温和",
                    voice=r.Voice(config_id="b" * 32, voice="fixture-voice"),
                )
            )
        )
        for name in ["灯塔守望者", "旅人", "纸鸢"]
    ]
    domain.roleplay.create(
        r.ChatCreate(title="原生单聊验收", character_ids=[chars[0].id], scene="本地测试灯塔")
    )
    domain.roleplay.create(r.ChatCreate(title="原生群聊验收", character_ids=[c.id for c in chars]))
    domain.db.close()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("Native fixture ready; loopback only, no cloud or keychain.", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
