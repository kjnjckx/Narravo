from __future__ import annotations

import base64
import copy
import hashlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from charset_normalizer import from_bytes
from pydantic import BaseModel
from sqlalchemy import Connection

from . import contracts as c
from .storage import Storage


def uid() -> str:
    return uuid4().hex


def count(text: str) -> int:
    return sum(not char.isspace() for char in text)


class DomainError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise DomainError(code, message)


class Domain:
    def __init__(self, storage: Storage):
        self.db = storage
        from .providers.service import ProviderService

        self.providers = ProviderService(self)
        from .roleplay.domain import RoleplayService

        self.roleplay = RoleplayService(self)
        from .files import FileService

        self.files = FileService(self)

    def insert(self, conn: Connection, table: str, **values: Any) -> None:
        conn.execute(self.db.tables[table].insert().values(**values))

    def row(self, conn: Connection, table: str, row_id: str) -> dict[str, Any]:
        target = self.db.tables[table]
        row = conn.execute(sa.select(target).where(target.c.id == row_id)).mappings().first()
        require(row is not None, "NOT_FOUND", "内容不存在，请返回作品库重新打开。")
        return dict(row) if row is not None else {}

    def update(self, conn: Connection, table: str, row_id: str, **values: Any) -> None:
        target = self.db.tables[table]
        conn.execute(target.update().where(target.c.id == row_id).values(**values))

    def state(
        self, conn: Connection, branch_id: str, expected: str | None = None
    ) -> dict[str, Any]:
        branch = self.row(conn, "branches", branch_id)
        require(
            expected is None or branch["head"] == expected,
            "REVISION_CONFLICT",
            "正文、章节或设定已发生变化。请保留当前输入，重新打开最新版本后再操作。",
        )
        return copy.deepcopy(self.row(conn, "snapshots", branch["head"]))

    def workspace(self, conn: Connection, branch_id: str) -> c.Workspace:
        branch = self.row(conn, "branches", branch_id)
        book = self.row(conn, "books", branch["book_id"])
        snapshot = self.state(conn, branch_id)
        branches = self.db.tables["branches"]
        siblings = conn.execute(
            sa.select(branches).where(branches.c.book_id == book["id"])
        ).mappings()
        return c.Workspace(
            book_id=book["id"],
            title=book["title"],
            origin_type=book["origin_type"],
            branch_id=branch_id,
            snapshot_id=snapshot["id"],
            planning_revision=snapshot["planning_id"],
            branches=[
                c.BranchInfo(id=b["id"], name=b["name"], parent_id=b["parent_id"]) for b in siblings
            ],
            chapters=[c.ChapterMeta(**ch) for ch in snapshot["chapters"]],
            planning=self.row(conn, "planning", snapshot["planning_id"])["payload"],
            word_count=sum(ch["word_count"] for ch in snapshot["chapters"]),
        )

    def commit_snapshot(
        self, conn: Connection, branch_id: str, state: dict[str, Any]
    ) -> c.Workspace:
        old_id = state["id"]
        state["id"] = uid()
        state["parent_id"] = old_id
        self.insert(conn, "snapshots", **state)
        self.update(conn, "branches", branch_id, head=state["id"])
        self.update(conn, "books", state["book_id"], updated_at=datetime.now(UTC).isoformat())
        return self.workspace(conn, branch_id)

    def new_chapter(
        self, conn: Connection, title: str, text: str = "", source: str = "manual"
    ) -> dict[str, Any]:
        revision = uid()
        self.insert(conn, "revisions", id=revision, text=text, source=source)
        return {
            "id": uid(),
            "title": title,
            "status": "draft",
            "revision": revision,
            "anchor": uid(),
            "word_count": count(text),
        }

    def create(
        self,
        conn: Connection,
        title: str,
        chapters: list[dict[str, Any]],
        source_asset_id: str | None = None,
        source_hash: str | None = None,
    ) -> c.Workspace:
        book_id, branch_id, snapshot_id, planning_id = uid(), uid(), uid(), uid()
        self.insert(
            conn,
            "books",
            id=book_id,
            title=title.strip() or "未命名作品",
            origin_type="imported" if source_asset_id else "original",
            source_asset_id=source_asset_id,
            source_hash=source_hash,
            import_status="confirmed" if source_asset_id else "not_applicable",
            updated_at=datetime.now(UTC).isoformat(),
        )
        self.insert(conn, "planning", id=planning_id, payload=[])
        self.insert(
            conn,
            "snapshots",
            id=snapshot_id,
            book_id=book_id,
            parent_id=None,
            planning_id=planning_id,
            chapters=chapters,
        )
        self.insert(
            conn,
            "branches",
            id=branch_id,
            book_id=book_id,
            name="主线",
            parent_id=None,
            head=snapshot_id,
        )
        return self.workspace(conn, branch_id)

    def health(self, _: c.Empty) -> c.Health:
        state = self.providers.provider_list(None)
        return c.Health(
            provider="configured" if state.providers else "unconfigured",
            external_enabled=state.external_enabled,
        )

    def book_list(self, _: c.Empty) -> c.Library:
        with self.db.transaction() as conn:
            books = conn.execute(
                sa.select(self.db.tables["books"]).order_by(
                    self.db.tables["books"].c.updated_at.desc()
                )
            ).mappings()
            summaries = []
            for book in books:
                branches = self.db.tables["branches"]
                main = conn.execute(
                    sa.select(branches.c.id).where(
                        branches.c.book_id == book["id"], branches.c.parent_id.is_(None)
                    )
                ).scalar_one()
                workspace = self.workspace(conn, main)
                summaries.append(
                    c.BookSummary(
                        book_id=book["id"],
                        title=book["title"],
                        origin_type=book["origin_type"],
                        branch_id=main,
                        word_count=workspace.word_count,
                        chapter_count=len(workspace.chapters),
                        updated_at=book["updated_at"],
                    )
                )
            return c.Library(books=summaries)

    def book_create(self, p: c.BookCreate) -> c.Workspace:
        with self.db.transaction() as conn:
            return self.create(conn, p.title, [self.new_chapter(conn, "第一章")])

    def branch_get(self, p: c.BranchTarget) -> c.Workspace:
        with self.db.transaction() as conn:
            return self.workspace(conn, p.branch_id)

    def branch_fork(self, p: c.BranchFork) -> c.Workspace:
        with self.db.transaction() as conn:
            state = self.state(conn, p.branch_id, p.expected_snapshot)
            branch_id = uid()
            self.insert(
                conn,
                "branches",
                id=branch_id,
                book_id=state["book_id"],
                name=p.name,
                parent_id=p.branch_id,
                head=state["id"],
            )
            return self.workspace(conn, branch_id)

    def branch_history(self, p: c.BranchTarget) -> c.History:
        with self.db.transaction() as conn:
            state = self.state(conn, p.branch_id)
            entries = []
            for _ in range(30):
                entries.append(
                    c.HistoryEntry(
                        snapshot_id=state["id"],
                        word_count=sum(ch["word_count"] for ch in state["chapters"]),
                        chapter_count=len(state["chapters"]),
                        planning_count=len(
                            self.row(conn, "planning", state["planning_id"])["payload"]
                        ),
                    )
                )
                if state["parent_id"] is None:
                    break
                state = self.row(conn, "snapshots", state["parent_id"])
            return c.History(entries=entries)

    def branch_restore(self, p: c.RestoreSnapshot) -> c.Workspace:
        with self.db.transaction() as conn:
            current = self.state(conn, p.branch_id, p.expected_snapshot)
            target = current
            while target["id"] != p.snapshot_id:
                require(
                    target["parent_id"] is not None,
                    "INVALID_ARGUMENT",
                    "只能恢复当前分支历史中的版本。",
                )
                target = self.row(conn, "snapshots", target["parent_id"])
            # Restoration is a new child snapshot, retaining both the target and current history.
            current["chapters"] = copy.deepcopy(target["chapters"])
            current["planning_id"] = target["planning_id"]
            return self.commit_snapshot(conn, p.branch_id, current)

    @staticmethod
    def chapter(state: dict[str, Any], chapter_id: str) -> dict[str, Any]:
        chapters: list[dict[str, Any]] = state["chapters"]
        chapter = next((ch for ch in chapters if ch["id"] == chapter_id), None)
        require(chapter is not None, "NOT_FOUND", "当前分支没有此章节，请重新选择。")
        return chapter or {}

    def chapter_get(self, p: c.ChapterTarget) -> c.ChapterText:
        with self.db.transaction() as conn:
            chapter = self.chapter(self.state(conn, p.branch_id), p.chapter_id)
            return c.ChapterText(
                chapter_id=p.chapter_id,
                revision=chapter["revision"],
                anchor=chapter["anchor"],
                text=self.row(conn, "revisions", chapter["revision"])["text"],
            )

    def chapter_save(self, p: c.ChapterSave) -> c.Workspace:
        with self.db.transaction() as conn:
            state = self.state(conn, p.branch_id, p.expected_snapshot)
            chapter = self.chapter(state, p.chapter_id)
            if self.row(conn, "revisions", chapter["revision"])["text"] == p.text:
                return self.workspace(conn, p.branch_id)
            revision = uid()
            self.insert(conn, "revisions", id=revision, text=p.text, source="manual")
            chapter.update(revision=revision, word_count=count(p.text))
            return self.commit_snapshot(conn, p.branch_id, state)

    def chapter_create(self, p: c.ChapterCreate) -> c.Workspace:
        with self.db.transaction() as conn:
            state = self.state(conn, p.branch_id, p.expected_snapshot)
            state["chapters"].append(self.new_chapter(conn, p.title.strip() or "新章节"))
            return self.commit_snapshot(conn, p.branch_id, state)

    def chapter_update(self, p: c.ChapterUpdate) -> c.Workspace:
        with self.db.transaction() as conn:
            state = self.state(conn, p.branch_id, p.expected_snapshot)
            self.chapter(state, p.chapter_id).update(title=p.title, status=p.status)
            return self.commit_snapshot(conn, p.branch_id, state)

    def chapter_reorder(self, p: c.ChapterReorder) -> c.Workspace:
        with self.db.transaction() as conn:
            state = self.state(conn, p.branch_id, p.expected_snapshot)
            ids = [ch["id"] for ch in state["chapters"]]
            require(
                len(p.ordered_ids) == len(ids) and set(p.ordered_ids) == set(ids),
                "INVALID_ARGUMENT",
                "章节顺序必须包含全部章节且不可重复。",
            )
            state["chapters"] = [self.chapter(state, id_) for id_ in p.ordered_ids]
            return self.commit_snapshot(conn, p.branch_id, state)

    def chapter_remove(self, p: c.ChapterRemove) -> c.Workspace:
        with self.db.transaction() as conn:
            state = self.state(conn, p.branch_id, p.expected_snapshot)
            self.chapter(state, p.chapter_id)
            require(len(state["chapters"]) > 1, "INVALID_ARGUMENT", "请至少保留一个章节。")
            # Retained in immutable snapshots. A deleted disclosure anchor remains unresolved/hidden.
            state["chapters"] = [ch for ch in state["chapters"] if ch["id"] != p.chapter_id]
            return self.commit_snapshot(conn, p.branch_id, state)

    def planning_save(self, p: c.PlanningSave) -> c.Workspace:
        require(
            len({entry.id for entry in p.entries}) == len(p.entries),
            "INVALID_ARTIFACT",
            "设定 ID 不可重复。",
        )
        with self.db.transaction() as conn:
            state = self.state(conn, p.branch_id, p.expected_snapshot)
            for entry in p.entries:
                if entry.visible_from:
                    self.chapter(state, entry.visible_from)
                require(
                    entry.kind != "outline" or entry.context_role == "planned_event",
                    "INVALID_ARTIFACT",
                    "大纲必须标记为未来计划。",
                )
            planning_id = uid()
            self.insert(
                conn,
                "planning",
                id=planning_id,
                payload=[entry.model_dump() for entry in p.entries],
            )
            state["planning_id"] = planning_id
            return self.commit_snapshot(conn, p.branch_id, state)

    def context(
        self, conn: Connection, p: c.ContextRequest, limit: int = 16384, reserve: int = 2048
    ) -> c.ContextPreview:
        state = self.state(conn, p.branch_id)
        current = self.chapter(state, p.chapter_id)
        current_text = self.row(conn, "revisions", current["revision"])["text"]
        require(p.offset <= len(current_text), "INVALID_ANCHOR", "光标位置已失效，请重新选择位置。")
        ids = [ch["id"] for ch in state["chapters"]]
        position = ids.index(p.chapter_id)
        missing, body = [], []
        for chapter in state["chapters"][:position]:
            text = self.row(conn, "revisions", chapter["revision"])["text"]
            if not text.strip():
                missing.append(chapter["id"])
            else:
                body.append(text)
        body.append(current_text[: p.offset])
        if p.context_policy == "full_rewrite":
            require(
                bool(p.rewrite_chapter_ids),
                "CONTEXT_POLICY_VIOLATION",
                "完整改写需要明确选择正文范围。",
            )
            require(
                set(p.rewrite_chapter_ids).issubset(ids),
                "CONTEXT_POLICY_VIOLATION",
                "改写范围包含不存在的章节。",
            )
            body = [
                self.row(conn, "revisions", ch["revision"])["text"]
                for ch in state["chapters"]
                if ch["id"] in p.rewrite_chapter_ids
            ]
        planning = self.row(conn, "planning", state["planning_id"])["payload"]
        require(
            set(p.selected_planning_ids).issubset({e["id"] for e in planning}),
            "DANGLING_REFERENCE",
            "选中的设定已失效。",
        )
        selected = []
        for entry in planning:
            if entry["id"] not in p.selected_planning_ids:
                continue
            visible = entry["visible_from"] in ids and ids.index(entry["visible_from"]) < position
            if p.context_policy == "reader_safe" and (
                entry["author_only"] or entry["context_role"] == "planned_event" or not visible
            ):
                continue
            selected.append(c.PlanningEntry(**entry))
        text = "\n\n".join(body)
        # Conservative estimate and an explicit hard stop; never silently drop required settings.
        estimate = len(text) + sum(len(e.text) + len(e.title) + 100 for e in selected)
        require(
            estimate + reserve + 512 <= limit,
            "CONTEXT_BUDGET_EXCEEDED",
            "上下文超过配置上限，请缩小范围或减少所选设定。",
        )
        return c.ContextPreview(
            context_policy=p.context_policy,
            preceding_text=text,
            planning=selected,
            missing_chapter_ids=missing,
            estimated_tokens=estimate,
            warning="作者规划仅供写作参考，包含的秘密可能发送给模型；计划事件尚未发生。"
            if selected
            else "仅使用当前位置之前的已保存正文；缺失章节不会补成历史。",
        )

    def writing_preview_context(self, p: c.ContextRequest) -> c.ContextPreview:
        from .providers.models import ProviderTarget

        config = (
            self.providers.provider_get(ProviderTarget(config_id=p.config_id))
            if p.config_id
            else None
        )
        with self.db.transaction() as conn:
            return self.context(
                conn,
                p,
                config.context_limit if config else 16384,
                config.max_output_tokens if config else 2048,
            )

    def writing_generate(self, p: c.Generate) -> c.Task:
        require(bool(p.intent.strip()), "EMPTY_INTENT", "先写一句本次创作意图，再开始生成。")
        with self.db.transaction() as conn:
            state = self.state(conn, p.branch_id, p.expected_snapshot)
            context = self.context(conn, p)
            chapter = self.chapter(state, p.chapter_id)
            generation_id, task_id = uid(), uid()
            # Deterministic local fixture. Never represents a model's actual writing quality.
            candidate = f"【本地演示候选】\n{p.intent.strip()}\n\n窗外的雨渐渐停了。她合上手中的笔记，在空白的一页写下了新的日期。那个尚未得到回答的问题，再一次浮现在眼前。\n\n“从这里开始吧。”她轻声说。"
            self.insert(
                conn,
                "generations",
                id=generation_id,
                payload={
                    "id": generation_id,
                    "artifact_kind": "prose",
                    "candidate_revision": uid(),
                    "text": candidate,
                    "accepted": False,
                    "branch_id": p.branch_id,
                    "base_snapshot": state["id"],
                    "chapter_id": p.chapter_id,
                    "anchor": chapter["anchor"],
                    "offset": p.offset,
                    "context": context.model_dump(),
                    "provider": "demo",
                    "accepted_ranges": [],
                },
            )
            task = c.Task(task_id=task_id, status="running", seq=0)
            self.insert(
                conn,
                "tasks",
                id=task_id,
                payload={**task.model_dump(), "generation_id": generation_id, "emitted": 0},
            )
            return task

    def generation(self, payload: dict[str, Any], text: str | None = None) -> c.Generation:
        return c.Generation(
            id=payload["id"],
            artifact_kind="prose",
            candidate_revision=payload["candidate_revision"],
            text=payload["text"] if text is None else text,
            accepted=payload["accepted"],
        )

    def task_list(self, _: c.Empty) -> c.TaskList:
        result = []
        with self.db.transaction() as conn:
            tasks = (
                conn.execute(
                    sa.select(self.db.tables["tasks"])
                    .order_by(sa.literal_column("rowid").desc())
                    .limit(20)
                )
                .mappings()
                .all()
            )
            for task in tasks:
                data = task["payload"]
                if data.get("generation_id"):
                    target = self.row(conn, "generations", data["generation_id"])["payload"]
                elif data.get("kind") == "narration" and data.get("audio"):
                    target = data["audio"]
                else:
                    continue
                branch = self.row(conn, "branches", target["branch_id"])
                book = self.row(conn, "books", branch["book_id"])
                result.append(
                    c.TaskSummary(
                        task_id=task["id"],
                        status=data["status"],
                        branch_id=branch["id"],
                        chapter_id=target["chapter_id"],
                        title=book["title"],
                        kind=data.get("kind", "writing"),
                    )
                )
        return c.TaskList(tasks=result)

    def task_get(self, p: c.TaskTarget) -> c.Task:
        with self.db.transaction() as conn:
            data = self.row(conn, "tasks", p.task_id)["payload"]
            generation = (
                self.row(conn, "generations", data["generation_id"])["payload"]
                if data.get("generation_id")
                else None
            )
            return c.Task(
                task_id=p.task_id,
                status=data["status"],
                seq=data["seq"],
                error_code=data.get("error_code"),
                kind=data.get("kind", "writing"),
                message=data.get("message"),
                usage=data.get("usage"),
                audio=data.get("audio"),
                generation=self.generation(generation, generation["text"][: data["emitted"]])
                if generation
                else None,
            )

    def task_cancel(self, p: c.TaskTarget) -> c.Task:
        self.providers.cancel(p.task_id)
        with self.db.transaction() as conn:
            data = self.row(conn, "tasks", p.task_id)["payload"]
            if data["status"] == "running":
                data.update(status="cancelled", error_code="CANCELLED", seq=data["seq"] + 1)
                self.update(conn, "tasks", p.task_id, payload=data)
        return self.task_get(p)

    def tick(self) -> list[dict[str, Any]]:
        events = []
        with self.db.transaction() as conn:
            tasks = conn.execute(sa.select(self.db.tables["tasks"])).mappings().all()
            for task in tasks:
                data = task["payload"]
                if data["status"] != "running" or data.get("remote"):
                    continue
                generation = self.row(conn, "generations", data["generation_id"])["payload"]
                previous = data["emitted"]
                data["emitted"] = min(previous + 8, len(generation["text"]))
                data["seq"] += 1
                if data["emitted"] == len(generation["text"]):
                    data["status"] = "completed"
                self.update(conn, "tasks", task["id"], payload=data)
                events.append(
                    {
                        "jsonrpc": "2.0",
                        "schema_version": 1,
                        "method": "generation.delta",
                        "params": {
                            "task_id": task["id"],
                            "seq": data["seq"],
                            "delta": generation["text"][previous : data["emitted"]],
                            "status": data["status"],
                        },
                    }
                )
        return events

    def recover(self) -> None:
        # Only the deterministic provider exists. Its emitted checkpoint is safe to continue.
        # Real remote adapters must use UNKNOWN_OUTCOME instead of replaying requests.
        self.tick()

    def writing_accept(self, p: c.Accept) -> c.Workspace:
        with self.db.transaction() as conn:
            generation = self.row(conn, "generations", p.generation_id)["payload"]
            decisions = self.db.tables["decisions"]
            existing = (
                conn.execute(sa.select(decisions).where(decisions.c.id == p.idempotency_key))
                .mappings()
                .first()
            )
            if existing:
                require(
                    existing["generation_id"] == p.generation_id
                    and existing["payload"]["request"] == p.model_dump(),
                    "IDEMPOTENCY_CONFLICT",
                    "此接纳标识已用于其他内容，请使用新的操作。",
                )
                return self.workspace(conn, generation["branch_id"])
            require(
                p.candidate_revision == generation["candidate_revision"],
                "REVISION_CONFLICT",
                "候选版本已变化，请重新检查。",
            )
            require(
                0 <= p.start < p.end <= len(generation["text"]),
                "INVALID_ANCHOR",
                "候选选择范围无效。",
            )
            ranges = generation["accepted_ranges"]
            require(
                not any(p.start < end and p.end > start for start, end in ranges),
                "ALREADY_ACCEPTED",
                "这段候选已有接纳记录，请勿重复插入。",
            )
            tasks = conn.execute(sa.select(self.db.tables["tasks"])).mappings().all()
            task = next(
                t["payload"] for t in tasks if t["payload"]["generation_id"] == p.generation_id
            )
            require(
                task["status"] in {"completed", "cancelled", "failed"} and p.end <= task["emitted"],
                "INVALID_STATE",
                "请先停止生成并检查候选内容。",
            )
            state = self.state(conn, generation["branch_id"], p.expected_snapshot)
            require(
                state["id"] == generation["base_snapshot"],
                "REVISION_CONFLICT",
                "生成后正文或规划已经改变，请保留候选并重新生成。",
            )
            chapter = self.chapter(state, generation["chapter_id"])
            require(
                chapter["anchor"] == generation["anchor"],
                "REVISION_CONFLICT",
                "原始段落锚点已失效。",
            )
            text = self.row(conn, "revisions", chapter["revision"])["text"]
            offset = generation["offset"]
            new_text = text[:offset] + p.edited_text + text[offset:]
            revision = uid()
            self.insert(conn, "revisions", id=revision, text=new_text, source="accepted_generation")
            chapter.update(revision=revision, word_count=count(new_text))
            result = self.commit_snapshot(conn, generation["branch_id"], state)
            self.insert(
                conn,
                "decisions",
                id=p.idempotency_key,
                generation_id=p.generation_id,
                payload={
                    "request": p.model_dump(),
                    "target_revision": revision,
                    "target_snapshot": result.snapshot_id,
                },
            )
            generation["accepted_ranges"].append([p.start, p.end])
            generation["accepted"] = True
            # Allow another disjoint selection only atop this exact acceptance result.
            generation["base_snapshot"] = result.snapshot_id
            generation["offset"] = offset + len(p.edited_text)
            self.update(conn, "generations", p.generation_id, payload=generation)
            return result

    def book_preview_import(self, p: c.PreviewImport) -> c.ImportPreview:
        require(
            Path(p.filename).suffix.lower() == ".txt",
            "UNSUPPORTED_FORMAT",
            "EPUB/PDF 请通过文件处理任务导入。",
        )
        try:
            raw = base64.b64decode(p.content_b64, validate=True)
        except ValueError as exc:
            raise DomainError("INVALID_ARGUMENT", "文件数据无效，请重新选择。") from exc
        require(
            len(raw) <= 10 * 1024 * 1024,
            "FILE_TOO_LARGE",
            "当前 TXT 导入上限为 10 MiB，请拆分文件。",
        )
        warnings = []
        encoding: str = p.encoding
        if encoding == "auto":
            if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                encoding = "utf-16"
            else:
                try:
                    raw.decode("utf-8-sig")
                    encoding = "utf-8"
                except UnicodeDecodeError:
                    best = from_bytes(raw).best()
                    encoding = best.encoding if best else "gb18030"
                    warnings.append("自动识别的编码可能不准确，请检查预览；乱码时重新选择编码。")
        try:
            text = raw.decode("utf-8-sig" if encoding == "utf-8" else encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            raise DomainError(
                "ENCODING_UNCERTAIN", "无法按此编码读取，请选择其他编码后重试。"
            ) from exc
        require(bool(text.strip()), "EMPTY_DOCUMENT", "文件没有可导入正文，请选择其他文件。")
        # Keep original bytes and line start byte locators; normalized text never replaces source.
        lines = text.splitlines(keepends=True)
        sections: list[dict[str, Any]] = []
        title, start_byte, cursor = "正文", 0, 0
        found_heading = False
        buffer: list[str] = []
        for line in lines:
            if re.match(
                r"^\s*(第[零一二三四五六七八九十百千万两\d]+[章回节卷].{0,60}|chapter\s+\d+.{0,60})\s*$",
                line,
                re.IGNORECASE,
            ):
                if buffer or found_heading:
                    sections.append(
                        {
                            "title": title,
                            "text": "".join(buffer).replace("\r\n", "\n"),
                            "byte_start": start_byte,
                            "byte_end": cursor,
                        }
                    )
                title, buffer, start_byte = line.strip(), [], cursor
                found_heading = True
            else:
                buffer.append(line)
            # Use an incremental encoder below for accurate BOM handling.
            cursor += len(
                line.encode(
                    "utf-8"
                    if encoding in {"utf-8", "utf-8-sig"}
                    else "utf-16-le"
                    if encoding == "utf-16" and raw.startswith(b"\xff\xfe")
                    else "utf-16-be"
                    if encoding == "utf-16"
                    else encoding
                )
            )
        if buffer or found_heading or not sections:
            sections.append(
                {
                    "title": title,
                    "text": "".join(buffer).replace("\r\n", "\n"),
                    "byte_start": start_byte,
                    "byte_end": cursor,
                }
            )
        bom = 3 if raw.startswith(b"\xef\xbb\xbf") else 2 if encoding == "utf-16" else 0
        for section in sections:
            section["byte_start"] += bom
            section["byte_end"] += bom
        return self.persist_import(p.filename, raw, encoding, sections, warnings)

    def persist_import(
        self,
        filename: str,
        raw: bytes,
        encoding: str,
        sections: list[dict[str, Any]],
        warnings: list[str],
        omitted_pages: list[int] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> c.ImportPreview:
        import_id = uid()
        asset_dir = self.db.directory / "sources"
        asset_dir.mkdir(exist_ok=True)
        digest = hashlib.sha256(raw).hexdigest()
        asset = asset_dir / digest
        if asset.exists():
            require(
                hashlib.sha256(asset.read_bytes()).hexdigest() == digest,
                "SOURCE_CORRUPT",
                "原文件副本校验失败，请保留源文件并检查磁盘。",
            )
        else:
            temporary = asset_dir / (digest + "." + uid() + ".tmp")
            with temporary.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(asset)
        with self.db.transaction() as conn:
            self.insert(
                conn,
                "imports",
                id=import_id,
                payload={
                    "filename": filename,
                    "encoding": encoding,
                    "source_hash": digest,
                    "chapters": sections,
                    "book_branch": None,
                    "omitted_pages": omitted_pages or [],
                    "metadata": metadata or {},
                    "warnings": warnings,
                },
            )
        return c.ImportPreview(
            import_id=import_id,
            filename=filename,
            encoding=encoding,
            warnings=warnings,
            chapters=[s["title"] for s in sections],
            sample=sections[0]["text"][:600],
            omitted_pages=omitted_pages or [],
            metadata=metadata or {},
        )

    def book_confirm_import(self, p: c.ConfirmImport) -> c.Workspace:
        with self.db.transaction() as conn:
            preview = self.row(conn, "imports", p.import_id)["payload"]
            if preview["book_branch"]:
                return self.workspace(conn, preview["book_branch"])
            require(
                not preview.get("omitted_pages") or p.accept_incomplete,
                "INCOMPLETE_IMPORT",
                "存在遗漏页面，请明确勾选接受不完整导入。",
            )
            chapters = [
                self.new_chapter(conn, section["title"], section["text"], "imported")
                for section in preview["chapters"]
            ]
            for chapter, section in zip(chapters, preview["chapters"], strict=True):
                # Source mapping belongs to the immutable import manifest, referenced by chapter ID.
                section["chapter_id"] = chapter["id"]
            result = self.create(conn, p.title, chapters, p.import_id, preview["source_hash"])
            preview["book_branch"] = result.branch_id
            self.update(conn, "imports", p.import_id, payload=preview)
            return result

    def book_export(self, p: c.Export) -> c.ExportResult:
        with self.db.transaction() as conn:
            state = self.state(conn, p.branch_id)
            book = self.row(conn, "books", state["book_id"])
            pieces = []
            for chapter in state["chapters"]:
                text = self.row(conn, "revisions", chapter["revision"])["text"]
                pieces.append(
                    ("## " if p.format == "md" else "") + chapter["title"] + "\n\n" + text
                )
            filename = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", book["title"]) + "." + p.format
            return c.ExportResult(filename=filename, content="\n\n".join(pieces))

    def dispatch(
        self,
        method: str,
        params: dict[str, Any],
        secret: str = "",
        credential_present: bool = False,
        credential_endpoint: str = "",
    ) -> BaseModel:
        require(
            not self.files.activating or method in {"file.get", "file.cancel", "system.health"},
            "LIBRARY_SWITCHING",
            "正在切换书库，请稍后再操作。",
        )
        require(method in c.METHODS, "METHOD_NOT_FOUND", "此功能尚未实现，请更新应用后重试。")
        model, _ = c.METHODS[method]
        parsed = model.model_validate(params)
        if method in {
            "provider.test",
            "narration.synthesize",
            "roleplay.send",
            "roleplay.synthesize",
        } or (method == "writing.generate" and params.get("provider") == "configured"):
            from .providers.models import ProviderTarget

            configured = self.providers.provider_get(
                ProviderTarget(config_id=params.get("config_id", ""))
            )
            require(
                credential_endpoint == configured.base_url,
                "PROVIDER_CHANGED",
                "模型地址已变化，请重新检查发送目标后操作。",
            )
        if method in {"roleplay.send", "roleplay.synthesize"}:
            handler_remote: Any = getattr(self.roleplay, method.split(".")[1])
            remote_result: BaseModel = handler_remote(parsed, secret)
            return remote_result
        if method == "provider.save":
            return self.providers.save(parsed, credential_present)  # type: ignore[arg-type]
        if method == "provider.test":
            return self.providers.start_test(parsed, secret)  # type: ignore[arg-type]
        if method == "narration.synthesize":
            return self.providers.start_narration(parsed, secret)  # type: ignore[arg-type]
        if method == "writing.generate" and params.get("provider") == "configured":
            return self.providers.start_writing(parsed, secret)  # type: ignore[arg-type]
        if method.startswith("roleplay."):
            handler: Any = getattr(self.roleplay, method.split(".")[1])
        elif method.startswith(("file.", "backup.")):
            handler = getattr(self.files, method.replace(".", "_"))
        elif method.startswith(("provider.", "network.", "audio.")):
            handler = getattr(self.providers, method.replace(".", "_"))
        else:
            handler = (
                getattr(self, method.replace(".", "_"))
                if method != "system.health"
                else self.health
            )
        result: BaseModel = handler(parsed)
        return result
