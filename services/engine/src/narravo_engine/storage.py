import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine


class Storage:
    def __init__(self, directory: Path, *, follow_pointer: bool = True):
        self.root_directory = directory
        pointer = directory / "active-library.json"
        if follow_pointer and pointer.exists():
            library_id = json.loads(pointer.read_text())["library_id"]
            if not isinstance(library_id, str) or (
                library_id != "original" and not re.fullmatch(r"[a-f0-9]{32}", library_id)
            ):
                raise ValueError("Invalid library pointer")
            if library_id != "original":
                directory = directory / "libraries" / library_id
            if directory.is_symlink() or not (directory / "library.db").is_file():
                raise ValueError("Missing restored library")
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.path = directory / "library.db"
        self.engine: Engine = sa.create_engine(
            f"sqlite:///{self.path}", connect_args={"timeout": 10}
        )

        @sa.event.listens_for(self.engine, "connect")
        def configure(dbapi_connection: sqlite3.Connection, _: object) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
            dbapi_connection.execute("PRAGMA journal_mode=WAL")
            dbapi_connection.execute("PRAGMA synchronous=FULL")

        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        latest = ScriptDirectory.from_config(config).get_current_head()
        # Back up only when an existing database actually needs an upgrade.
        with self.engine.connect() as conn:
            exists = sa.inspect(conn).has_table("alembic_version")
            version = (
                conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
                if exists
                else None
            )
        if self.path.exists() and version != latest and exists:
            self.backup(directory / "pre-migration.db")
        with self.engine.connect() as conn:
            # sqlite3's legacy mode does not start a transaction for DDL automatically.
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            config.attributes["connection"] = conn
            try:
                command.upgrade(config, "head")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        metadata = sa.MetaData()
        metadata.reflect(bind=self.engine)
        self.tables = metadata.tables

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def backup(self, destination: Path) -> None:
        with (
            closing(sqlite3.connect(self.path)) as source,
            closing(sqlite3.connect(destination)) as target,
        ):
            source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")

    def close(self) -> None:
        self.engine.dispose()
