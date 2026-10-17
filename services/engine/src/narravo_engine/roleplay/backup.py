"""Roleplay backup freezing and reference validation. Never runs model requests."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .. import roleplay_models as r
from ..domain import require
from .domain import fingerprint


def clean(conn: sqlite3.Connection, include_audio: bool) -> None:
    for id_, raw in conn.execute("SELECT id,payload FROM rp_turns").fetchall():
        turn = json.loads(raw)
        config = turn.pop("config_snapshot", None)
        if config:
            turn["provider_provenance"] = {
                key: value
                for key, value in config.items()
                if key not in {"id", "name", "base_url", "has_credential", "allow_local"}
            }
        if turn["status"] == "running":
            turn.update(
                status="failed",
                error_code="UNKNOWN_OUTCOME",
                text_finished=True,
                notice="备份时轮次未完成；恢复不自动付费、续聊或发声。",
            )
        turn["speech_stopped"] = True
        for message in turn["messages"]:
            if message["status"] == "streaming":
                message["status"] = "interrupted"
                conn.execute(
                    "INSERT INTO rp_messages(id,conversation_id,payload) VALUES(?,?,?)",
                    (
                        message["revision"],
                        turn["conversation_id"],
                        json.dumps(message, ensure_ascii=False),
                    ),
                )
        for charge in turn["charges"]:
            if charge["status"] == "reserved":
                charge["status"] = "unknown"
        for item in turn["speech"]:
            if not include_audio:
                item["asset_id"] = None
                item["cache_hit"] = False
            if item["status"] in {"pending", "ready", "synthesizing"}:
                item["status"] = "stopped"
        conn.execute(
            "UPDATE rp_turns SET payload=? WHERE id=?", (json.dumps(turn, ensure_ascii=False), id_)
        )


def validate(conn: sqlite3.Connection, include_audio: bool) -> None:
    def check(condition: bool) -> None:
        require(condition, "BACKUP_REFERENCE", "备份角色/会话修订、可见范围或音频引用无效。")

    roots = {row[0]: row for row in conn.execute("SELECT * FROM rp_conversations")}
    characters = {row[0]: row for row in conn.execute("SELECT * FROM rp_characters")}
    personas: dict[str, r.Character] = {}
    for id_, character, raw in conn.execute("SELECT * FROM rp_personas"):
        value = r.Character.model_validate_json(raw)
        check(value.revision == id_ and value.id == character and character in characters)
        personas[id_] = value
    for id_, head, _ in characters.values():
        check(head in personas and personas[head].id == id_)
    snapshots: dict[str, dict[str, Any]] = {}
    messages: dict[str, r.Message] = {}
    memories: dict[str, r.Memory] = {}
    memory_scopes = {}
    for id_, conversation, raw in conn.execute("SELECT * FROM rp_messages"):
        message = r.Message.model_validate_json(raw)
        check(
            id_ == message.revision
            and message.conversation_id == conversation
            and conversation in roots
            and message.status in {"complete", "interrupted", "preset"}
        )
        check(message.sequence <= roots[conversation][2])
        messages[id_] = message
    for id_, conversation, raw in conn.execute("SELECT * FROM rp_memories"):
        memory = r.Memory.model_validate_json(raw)
        check(id_ == memory.id and conversation in roots)
        check(
            all(
                rev in messages and messages[rev].conversation_id == conversation
                for rev in memory.source_revisions
            )
        )
        memories[id_] = memory
        memory_scopes[id_] = conversation
    for id_, conversation, raw in conn.execute("SELECT * FROM rp_snapshots"):
        state = json.loads(raw)
        check(
            state["id"] == id_
            and state["conversation_id"] == conversation
            and conversation in roots
        )
        members = [r.Member.model_validate(m) for m in state["members"]]
        check(
            len({m.id for m in members}) == len(members)
            and 1 <= sum(not m.removed for m in members) <= 8
        )
        for member in members:
            check(
                member.persona_revision in personas
                and personas[member.persona_revision].id == member.character_id
                and personas[member.persona_revision].kind == "character"
            )
            check(0 <= member.joined_seq <= roots[conversation][2])
        if state["user_persona_revision"]:
            user = personas[state["user_persona_revision"]]
            check(user.id == state["user_character_id"] and user.kind == "user")
        selected = [messages[rev] for rev in state["path"]]
        check(
            all(
                m.conversation_id == conversation and m.status in {"complete", "preset"}
                for m in selected
            )
        )
        check(len({m.id for m in selected}) == len(selected))
        check(
            all(id_ in memories and memory_scopes[id_] == conversation for id_ in state["memories"])
        )
        snapshots[id_] = state
    for id_, head, _, _ in roots.values():
        check(head in snapshots and snapshots[head]["conversation_id"] == id_)
    for state in snapshots.values():
        if state["parent_id"]:
            check(
                state["parent_id"] in snapshots
                and snapshots[state["parent_id"]]["conversation_id"] == state["conversation_id"]
            )
            seen = set()
            current = state
            while current["parent_id"]:
                check(current["id"] not in seen)
                seen.add(current["id"])
                current = snapshots[current["parent_id"]]
    for message in messages.values():
        if message.input_snapshot:
            check(
                message.input_snapshot in snapshots
                and snapshots[message.input_snapshot]["conversation_id"] == message.conversation_id
            )
    assets = {row[0] for row in conn.execute("SELECT id FROM audio_assets")}
    tasks = {row[0] for row in conn.execute("SELECT id FROM tasks")}
    turn_scopes = {}
    for id_, conversation, raw in conn.execute("SELECT * FROM rp_turns"):
        data = json.loads(raw)
        require(
            "config_snapshot" not in data, "BACKUP_PRIVATE_CONFIG", "备份含未脱敏的聊天服务配置。"
        )
        turn = r.Turn.model_validate(data)
        turn_scopes[id_] = conversation
        check(
            turn.id == id_
            and turn.conversation_id == conversation
            and conversation in roots
            and turn.task_id in tasks
        )
        check(turn.status != "running" and turn.speech_stopped)
        check(
            all(
                rev in snapshots and snapshots[rev]["conversation_id"] == conversation
                for rev in [turn.base_snapshot, turn.expected_snapshot]
            )
        )
        for message in turn.messages:
            check(message.revision in messages and messages[message.revision] == message)
        for ctx in turn.contexts:
            check(
                ctx.conversation_id == conversation
                and ctx.snapshot_id in snapshots
                and snapshots[ctx.snapshot_id]["conversation_id"] == conversation
            )
            check(
                all(
                    rev in messages and messages[rev].conversation_id == conversation
                    for rev in ctx.source_revisions + ctx.trimmed_revisions
                )
            )
        for item in turn.speech:
            seg = item.segment
            check(
                seg.turn_id == id_
                and seg.conversation_id == conversation
                and seg.variant_revision in messages
            )
            message = messages[seg.variant_revision]
            check(
                seg.message_id == message.id
                and 0 <= seg.start < seg.end <= len(message.text)
                and message.text[seg.start : seg.end] == seg.text
                and fingerprint(seg.text) == seg.text_hash
            )
            check(item.status not in {"ready", "synthesizing", "pending"})
            check(item.asset_id is None or (include_audio and item.asset_id in assets))
    for _, conversation, raw in conn.execute("SELECT * FROM rp_operations"):
        data = json.loads(raw)
        result = data["result"]
        check(
            conversation in roots
            and (
                (result in turn_scopes and turn_scopes[result] == conversation)
                or (result in snapshots and snapshots[result]["conversation_id"] == conversation)
            )
        )
