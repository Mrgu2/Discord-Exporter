"""Durable, append-preserving Discord message archive.

Network access and credentials deliberately live outside this module. A failed
collection may leave useful pages in the archive, but never advances its cursor.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote_plus, urlsplit, urlunsplit


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def iso_time(value: Any = None) -> str:
    return (parse_time(value) or datetime.now(timezone.utc)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _id(value: Any) -> str | None:
    return str(value) if value is not None and value != "" else None


def _snowflake_time(message_id: str) -> str | None:
    try:
        milliseconds = (int(message_id) >> 22) + 1420070400000
        return iso_time(datetime.fromtimestamp(milliseconds / 1000, timezone.utc))
    except (ValueError, OverflowError, OSError):
        return None


def _attachment_url_for_hash(value: str) -> str:
    """Ignore only expiring Discord attachment signatures, not media identity."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if parts.scheme != "https" or parts.hostname not in {
        "cdn.discordapp.com", "media.discordapp.net", "cdn.discordapp.net"
    } or not parts.path.startswith("/attachments/"):
        return value
    # Preserve all non-signature query fields byte-for-byte and in order. In
    # particular, external URLs, image transforms, paths and filenames retain
    # their normal versioning behavior.
    fields = parts.query.split("&")
    retained = [field for field in fields if unquote_plus(field.partition("=")[0]) not in {"ex","is","hm"}]
    if len(retained) == len(fields):
        return value
    return urlunsplit((parts.scheme,parts.netloc,parts.path,"&".join(retained),parts.fragment))


def _attachments_for_hash(value: Any) -> Any:
    if isinstance(value,list):
        return [_attachments_for_hash(item) for item in value]
    if isinstance(value,dict):
        return {key:(_attachment_url_for_hash(item) if key in {"url","proxy_url","proxyUrl"} and isinstance(item,str)
            else _attachments_for_hash(item)) for key,item in value.items()}
    return value


def normalize_message(raw: dict[str, Any], channel_id: str, *, source: str = "discord_api") -> dict[str, Any]:
    """Accept both Discord API and DiscordChatExporter JSON message objects."""
    message_id = _id(raw.get("id") or raw.get("messageId"))
    if not message_id:
        raise ValueError("A message must have an id")
    author = raw.get("author") or {}
    reference = raw.get("message_reference") or raw.get("reference") or {}
    nested = raw.get("referenced_message") or raw.get("referencedMessage")
    reply_id = _id(reference.get("message_id") or reference.get("messageId"))
    if not reply_id and isinstance(nested, dict):
        reply_id = _id(nested.get("id"))
    channel = _id(raw.get("channel_id") or raw.get("channelId")) or str(channel_id)
    timestamp = raw.get("timestamp") or raw.get("created_at")
    edited = raw.get("edited_timestamp") or raw.get("timestampEdited") or raw.get("edited_at")
    thread = raw.get("thread") or {}
    normalized = {
        "channel_id": channel,
        "message_id": message_id,
        "author_id": _id(author.get("id") or raw.get("author_id")),
        "author_name": author.get("global_name") or author.get("nickname") or author.get("name") or author.get("username") or "",
        "content": raw.get("content") or "",
        "created_at": iso_time(timestamp) if timestamp else _snowflake_time(message_id),
        "edited_at": iso_time(edited) if edited else None,
        "reply_to_message_id": reply_id,
        "reply_to_channel_id": _id(reference.get("channel_id") or reference.get("channelId")) or (channel if reply_id else None),
        "thread_id": _id(raw.get("thread_id") or raw.get("threadId") or thread.get("id")),
        "message_type": str(raw.get("type", "Default")),
        "attachments": raw.get("attachments") or [],
        "embeds": raw.get("embeds") or [],
        "stickers": raw.get("sticker_items") or raw.get("stickers") or [],
        "source": source,
    }
    # Only message substance creates a new version. Reactions and API/DCE field
    # naming differences must not manufacture text edits.
    substance = {key: normalized[key] for key in (
        "content", "edited_at", "reply_to_message_id", "reply_to_channel_id", "attachments", "embeds", "stickers"
    )}
    for key in ("attachments","embeds","stickers"):
        substance[key] = _attachments_for_hash(substance[key])
    normalized["version_hash"] = hashlib.sha256(_json(substance).encode("utf-8")).hexdigest()
    return normalized


class ArchiveStore:
    """Thread-safe SQLite archive. IDs are strings, and raw source objects survive."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._create_schema()
        self._summary_cache = None

    def change_token(self) -> tuple[int, int]:
        """Cheap invalidation for local writes and commits by other connections."""
        with self._lock:
            return self.conn.total_changes, self.conn.execute("PRAGMA data_version").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    @contextmanager
    def _transaction(self):
        with self._lock:
            with self.conn:
                yield self.conn

    def _create_schema(self) -> None:
        with self._transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id TEXT PRIMARY KEY, name TEXT, guild_id TEXT,
                    cursor TEXT, last_success_at TEXT, last_attempt_at TEXT,
                    last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL REFERENCES channels(channel_id),
                    trigger TEXT NOT NULL, source TEXT NOT NULL,
                    status TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT,
                    cursor_before TEXT, cursor_after TEXT, error TEXT,
                    message_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS messages (
                    channel_id TEXT NOT NULL REFERENCES channels(channel_id),
                    message_id TEXT NOT NULL, author_id TEXT, author_name TEXT,
                    content TEXT NOT NULL, created_at TEXT, edited_at TEXT,
                    reply_to_message_id TEXT, reply_to_channel_id TEXT, thread_id TEXT,
                    message_type TEXT, raw_json TEXT NOT NULL,
                    normalized_json TEXT NOT NULL, version_hash TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                    last_direct_seen_at TEXT, source TEXT NOT NULL,
                    is_reference_snapshot INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (channel_id, message_id)
                );
                CREATE TABLE IF NOT EXISTS message_versions (
                    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    version_hash TEXT NOT NULL, captured_at TEXT NOT NULL,
                    source TEXT NOT NULL, is_reference_snapshot INTEGER NOT NULL,
                    raw_json TEXT NOT NULL, normalized_json TEXT NOT NULL,
                    UNIQUE(channel_id, message_id, version_hash),
                    FOREIGN KEY(channel_id, message_id) REFERENCES messages(channel_id, message_id)
                );
                CREATE TABLE IF NOT EXISTS run_messages (
                    run_id INTEGER NOT NULL REFERENCES runs(run_id),
                    channel_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    is_reference_snapshot INTEGER NOT NULL DEFAULT 0,
                    version_hash TEXT,
                    PRIMARY KEY(run_id, channel_id, message_id),
                    FOREIGN KEY(channel_id, message_id) REFERENCES messages(channel_id, message_id)
                );
                CREATE TABLE IF NOT EXISTS coverage_gaps (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL REFERENCES channels(channel_id),
                    started_at TEXT NOT NULL, ended_at TEXT, detected_at TEXT NOT NULL,
                    kind TEXT NOT NULL, reason TEXT NOT NULL,
                    UNIQUE(channel_id, started_at, kind)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_author ON messages(author_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_messages_reply ON messages(reply_to_channel_id, reply_to_message_id);
                CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(channel_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_runs_channel ON runs(channel_id, run_id);
                CREATE INDEX IF NOT EXISTS idx_run_messages_message_run
                    ON run_messages(channel_id, message_id, run_id);
            """)
            # Additive migration keeps archives created by an earlier build.
            run_columns = {row["name"] for row in db.execute("PRAGMA table_info(run_messages)")}
            if "version_hash" not in run_columns:
                db.execute("ALTER TABLE run_messages ADD COLUMN version_hash TEXT")

    def _ensure_channel(self, db, channel_id: str, *, now: str, name: str | None = None, guild_id: str | None = None):
        db.execute("""INSERT INTO channels(channel_id,name,guild_id,created_at,updated_at)
            VALUES(?,?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET
            name=COALESCE(excluded.name,channels.name), guild_id=COALESCE(excluded.guild_id,channels.guild_id),
            updated_at=excluded.updated_at""", (str(channel_id), name, guild_id, now, now))

    def ensure_channel(self, channel_id: str, name: str | None = None, guild_id: str | None = None):
        with self._transaction() as db:
            self._ensure_channel(db, str(channel_id), now=utc_now(), name=name, guild_id=guild_id)

    def start_run(self, channel_id: str, trigger: str = "manual", source: str = "discord_api", started_at: Any = None) -> int:
        now = iso_time(started_at)
        with self._transaction() as db:
            self._ensure_channel(db, str(channel_id), now=now)
            channel = db.execute("SELECT cursor FROM channels WHERE channel_id=?", (str(channel_id),)).fetchone()
            result = db.execute("""INSERT INTO runs(channel_id,trigger,source,status,started_at,cursor_before)
                VALUES(?,?,?,'running',?,?)""", (str(channel_id), trigger, source, now, channel["cursor"]))
            db.execute("UPDATE channels SET last_attempt_at=?,updated_at=? WHERE channel_id=?", (now, now, str(channel_id)))
            return int(result.lastrowid)

    def ingest_messages(self, channel_id: str, messages: Iterable[dict[str, Any]], run_id: int | None = None,
                        source: str = "discord_api", observed_at: Any = None) -> dict[str, int]:
        now = iso_time(observed_at)
        stats = {"seen": 0, "inserted": 0, "versions_added": 0, "reference_snapshots": 0}
        with self._transaction() as db:
            self._ensure_channel(db, str(channel_id), now=now)
            if run_id is not None:
                run = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if not run or run["channel_id"] != str(channel_id) or run["status"] != "running":
                    raise ValueError("run_id must identify a running run for this channel")
            visited: set[tuple[str, str, bool, str]] = set()

            def ingest(raw: dict[str, Any], default_channel: str, snapshot: bool = False):
                normalized = normalize_message(raw, default_channel, source=source)
                channel, message = normalized["channel_id"], normalized["message_id"]
                marker = (channel, message, snapshot, normalized["version_hash"])
                if marker in visited:
                    return
                visited.add(marker)
                self._ensure_channel(db, channel, now=now)
                previous = db.execute("SELECT * FROM messages WHERE channel_id=? AND message_id=?", (channel, message)).fetchone()
                if previous and normalized["version_hash"] != previous["version_hash"]:
                    # Older archives hashed complete signed URLs. Re-evaluate
                    # their untouched raw object under the current rules and
                    # retain its established hash if only signatures changed.
                    # This avoids a one-time false edit and keeps prior runs'
                    # version references valid without a schema/data migration.
                    previous_semantic = normalize_message(json.loads(previous["raw_json"]),channel,source=previous["source"])
                    if previous_semantic["version_hash"] == normalized["version_hash"]:
                        normalized["version_hash"] = previous["version_hash"]
                stats["reference_snapshots" if snapshot else "seen"] += 1
                stats["inserted"] += int(previous is None)
                raw_json, normalized_json = _json(raw), _json(normalized)
                # A quoted snapshot can add a historical version but must not
                # replace a message obtained directly from its own channel.
                replace_current = previous is None or not snapshot or bool(previous["is_reference_snapshot"])
                if previous and replace_current:
                    old_time = parse_time(previous["edited_at"] or previous["created_at"])
                    new_time = parse_time(normalized["edited_at"] or normalized["created_at"])
                    if old_time and new_time and new_time < old_time:
                        replace_current = False
                if previous is None:
                    db.execute("""INSERT INTO messages(channel_id,message_id,author_id,author_name,content,created_at,
                        edited_at,reply_to_message_id,reply_to_channel_id,thread_id,message_type,raw_json,normalized_json,
                        version_hash,first_seen_at,last_seen_at,last_direct_seen_at,source,is_reference_snapshot)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        channel,message,normalized["author_id"],normalized["author_name"],normalized["content"],
                        normalized["created_at"],normalized["edited_at"],normalized["reply_to_message_id"],
                        normalized["reply_to_channel_id"],normalized["thread_id"],normalized["message_type"],raw_json,
                        normalized_json,normalized["version_hash"],now,now,None if snapshot else now,source,int(snapshot)))
                elif replace_current:
                    db.execute("""UPDATE messages SET author_id=?,author_name=?,content=?,created_at=?,edited_at=?,
                        reply_to_message_id=?,reply_to_channel_id=?,thread_id=?,message_type=?,raw_json=?,normalized_json=?,
                        version_hash=?,last_seen_at=?,last_direct_seen_at=COALESCE(?,last_direct_seen_at),source=?,
                        is_reference_snapshot=? WHERE channel_id=? AND message_id=?""", (
                        normalized["author_id"],normalized["author_name"],normalized["content"],normalized["created_at"],
                        normalized["edited_at"],normalized["reply_to_message_id"],normalized["reply_to_channel_id"],
                        normalized["thread_id"],normalized["message_type"],raw_json,normalized_json,
                        normalized["version_hash"],now,None if snapshot else now,source,int(snapshot),channel,message))
                else:
                    db.execute("UPDATE messages SET last_seen_at=? WHERE channel_id=? AND message_id=?", (now,channel,message))
                inserted = db.execute("""INSERT OR IGNORE INTO message_versions(channel_id,message_id,version_hash,
                    captured_at,source,is_reference_snapshot,raw_json,normalized_json) VALUES(?,?,?,?,?,?,?,?)""",
                    (channel,message,normalized["version_hash"],now,source,int(snapshot),raw_json,normalized_json))
                stats["versions_added"] += int(inserted.rowcount > 0)
                if run_id is not None:
                    db.execute("""INSERT INTO run_messages(run_id,channel_id,message_id,is_reference_snapshot,version_hash)
                        VALUES(?,?,?,?,?) ON CONFLICT(run_id,channel_id,message_id) DO UPDATE SET
                        version_hash=CASE WHEN excluded.is_reference_snapshot=0 OR run_messages.is_reference_snapshot=1
                            THEN excluded.version_hash ELSE run_messages.version_hash END,
                        is_reference_snapshot=MIN(run_messages.is_reference_snapshot,excluded.is_reference_snapshot)""",
                        (run_id,channel,message,int(snapshot),normalized["version_hash"]))
                nested = raw.get("referenced_message") or raw.get("referencedMessage")
                if isinstance(nested, dict) and nested.get("id"):
                    ingest(nested, normalized["reply_to_channel_id"] or channel, True)

            for raw in messages:
                if not isinstance(raw, dict):
                    raise ValueError("Message objects must be dictionaries")
                ingest(raw, str(channel_id))
            if run_id is not None:
                db.execute("""UPDATE runs SET message_count=(SELECT COUNT(*) FROM run_messages
                    WHERE run_id=? AND is_reference_snapshot=0) WHERE run_id=?""", (run_id, run_id))
        return stats

    @staticmethod
    def _max_cursor(old: str | None, new: str | None) -> str | None:
        if not new:
            return old
        if not old:
            return str(new)
        try:
            return str(max(int(old), int(new)))
        except ValueError:
            return str(new)

    def finish_run(self, run_id: int, success: bool, error: str | None = None, cursor: str | None = None,
                   ended_at: Any = None, retention_hours: float = 48) -> dict[str, Any]:
        now = iso_time(ended_at)
        with self._transaction() as db:
            run = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not run:
                raise ValueError("Unknown run_id")
            if run["status"] != "running":
                raise ValueError("Run is already finalized")
            channel = db.execute("SELECT * FROM channels WHERE channel_id=?", (run["channel_id"],)).fetchone()
            new_cursor = channel["cursor"]
            if success:
                if cursor is None:
                    ids = db.execute("""SELECT message_id FROM run_messages WHERE run_id=?
                        AND channel_id=? AND is_reference_snapshot=0""", (run_id, run["channel_id"])).fetchall()
                    cursor = max((row["message_id"] for row in ids), key=lambda value: int(value) if value.isdigit() else -1, default=None)
                new_cursor = self._max_cursor(channel["cursor"], _id(cursor))
                last_success = parse_time(channel["last_success_at"])
                current_time = parse_time(now)
                if last_success and current_time - last_success >= timedelta(hours=retention_hours):
                    db.execute("""INSERT OR IGNORE INTO coverage_gaps(channel_id,started_at,ended_at,detected_at,kind,reason)
                        VALUES(?,?,?,?,?,?)""", (run["channel_id"],channel["last_success_at"],now,now,
                        "possible_retention_loss","Successful collections were farther apart than the configured retention window; missing messages are possible, not proven."))
                db.execute("""UPDATE channels SET cursor=?,last_success_at=?,last_error=NULL,updated_at=?
                    WHERE channel_id=?""", (new_cursor,now,now,run["channel_id"]))
            else:
                db.execute("UPDATE channels SET last_error=?,updated_at=? WHERE channel_id=?", (error or "Collection failed",now,run["channel_id"]))
            db.execute("UPDATE runs SET status=?,completed_at=?,cursor_after=?,error=? WHERE run_id=?",
                ("success" if success else "failed",now,new_cursor,None if success else (error or "Collection failed"),run_id))
        return self.get_run(run_id)

    def recover_interrupted_runs(self, error: str = "Process stopped before collection completed") -> int:
        """Mark interrupted attempts failed; no cursor is advanced on restart."""
        with self._lock:
            ids = [row["run_id"] for row in self.conn.execute("SELECT run_id FROM runs WHERE status='running'")]
        for run_id in ids:
            self.finish_run(run_id, False, error)
        return len(ids)

    def _message_dict(self, row) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        normalized = json.loads(result.pop("normalized_json"))
        result["raw"] = json.loads(result.pop("raw_json"))
        for key in ("attachments", "embeds", "stickers"):
            result[key] = normalized[key]
        result["id"] = result["message_id"]
        result["is_reference_snapshot"] = bool(result["is_reference_snapshot"])
        if "version_count" not in result:
            result["version_count"] = self.conn.execute("SELECT COUNT(*) FROM message_versions WHERE channel_id=? AND message_id=?",
                (result["channel_id"],result["message_id"])).fetchone()[0]
        return result

    def get_message(self, channel_id: str, message_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._message_dict(self.conn.execute("SELECT * FROM messages WHERE channel_id=? AND message_id=?",
                (str(channel_id),str(message_id))).fetchone())

    def get_versions(self, channel_id: str, message_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM message_versions WHERE channel_id=? AND message_id=? ORDER BY version_id",
                (str(channel_id),str(message_id))).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["raw"] = json.loads(item.pop("raw_json"))
                item["normalized"] = json.loads(item.pop("normalized_json"))
                item["is_reference_snapshot"] = bool(item["is_reference_snapshot"])
                result.append(item)
            return result

    def list_messages(self, channel_id: str | None = None, author_id: str | None = None,
                      run_id: int | None = None, since: Any = None, until: Any = None,
                      limit: int | None = None, include_snapshots: bool = True,
                      as_of_run_id: int | None = None) -> list[dict[str, Any]]:
        clauses, args = [], []
        for column, value in (("m.channel_id",channel_id),("m.author_id",author_id)):
            if value is not None:
                clauses.append(column+"=?")
                args.append(str(value))
        if run_id is not None:
            clauses.append("EXISTS(SELECT 1 FROM run_messages r WHERE r.channel_id=m.channel_id AND r.message_id=m.message_id AND r.run_id=?)")
            args.append(run_id)
        if as_of_run_id is not None:
            clauses.append("EXISTS(SELECT 1 FROM run_messages r WHERE r.channel_id=m.channel_id AND r.message_id=m.message_id AND r.run_id<=?)")
            args.append(as_of_run_id)
        if since is not None:
            clauses.append("m.created_at>=?")
            args.append(iso_time(since))
        if until is not None:
            clauses.append("m.created_at<=?")
            args.append(iso_time(until))
        if not include_snapshots:
            clauses.append("m.is_reference_snapshot=0")
        query = """SELECT m.*,(SELECT COUNT(*) FROM message_versions vc
            WHERE vc.channel_id=m.channel_id AND vc.message_id=m.message_id) AS version_count
            FROM messages m""" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY m.created_at,LENGTH(m.message_id),m.message_id"
        if limit is not None:
            query += " LIMIT ?"
            args.append(int(limit))
        with self._lock:
            result = [self._message_dict(row) for row in self.conn.execute(query,args).fetchall()]
            selected_run = run_id if run_id is not None else as_of_run_id
            if selected_run is not None:
                for message in result:
                    operator = "=" if run_id is not None else "<="
                    observed = self.conn.execute(f"""SELECT r.version_hash,r.is_reference_snapshot,v.raw_json,v.normalized_json,v.source
                        FROM run_messages r LEFT JOIN message_versions v ON v.channel_id=r.channel_id
                        AND v.message_id=r.message_id AND v.version_hash=r.version_hash
                        WHERE r.channel_id=? AND r.message_id=? AND r.run_id{operator}?
                        ORDER BY r.run_id DESC LIMIT 1""", (message["channel_id"],message["message_id"],selected_run)).fetchone()
                    if observed and observed["normalized_json"]:
                        current_hash = message["version_hash"]
                        message.update(json.loads(observed["normalized_json"]))
                        message["raw"] = json.loads(observed["raw_json"])
                        message["source"] = observed["source"]
                        message["is_reference_snapshot"] = bool(observed["is_reference_snapshot"])
                        message["current_version_hash"] = current_hash
                        message["as_of_run_id"] = selected_run
            if not include_snapshots:
                result = [message for message in result if not message["is_reference_snapshot"]]
            return result

    def list_run_changes(self, run_id: int, *, author_id: str | None = None,
                         channel_id: str | None = None, since: Any = None,
                         until: Any = None) -> list[dict[str, Any]]:
        """Return new/edited direct messages against this channel's last success.

        Collection rounds deliberately overlap for reliability. Observation in
        a round is therefore different from a new contribution in that round.
        Failed attempts never establish a manuscript baseline, even if their
        partial pages already saved a message or an edit.
        """
        with self._lock:
            run = self.get_run(run_id)
            if not run:
                raise ValueError("Unknown run_id")
            if channel_id is not None and str(channel_id) != run["channel_id"]:
                return []
            previous = self.conn.execute("""SELECT run_id FROM runs WHERE channel_id=?
                AND status='success' AND run_id<? ORDER BY run_id DESC LIMIT 1""",
                (run["channel_id"],run_id)).fetchone()
            baseline_run_id = previous["run_id"] if previous else None
            baseline = {}
            if baseline_run_id is not None:
                baseline = {row["message_id"]:row["version_hash"] for row in self.conn.execute("""
                    SELECT message_id,version_hash FROM run_messages WHERE run_id=?
                    AND channel_id=? AND is_reference_snapshot=0""", (baseline_run_id,run["channel_id"]))}
            messages = self.list_messages(channel_id=run["channel_id"],author_id=author_id,
                run_id=run_id,since=since,until=until,include_snapshots=False)
            result = []
            for message in messages:
                old_hash = baseline.get(message["message_id"])
                if old_hash is not None and old_hash == message["version_hash"]:
                    continue
                message["change_type"] = "edited" if message["message_id"] in baseline else "new"
                message["baseline_run_id"] = baseline_run_id
                result.append(message)
            return result

    def list_channels(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self.conn.execute("SELECT * FROM channels ORDER BY channel_id")]

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            return dict(row) if row else None

    def list_runs(self, channel_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            if channel_id is None:
                rows = self.conn.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT ?", (limit,))
            else:
                rows = self.conn.execute("SELECT * FROM runs WHERE channel_id=? ORDER BY run_id DESC LIMIT ?", (str(channel_id),limit))
            return [dict(row) for row in rows]

    def get_cursor(self, channel_id: str) -> str | None:
        with self._lock:
            row = self.conn.execute("SELECT cursor FROM channels WHERE channel_id=?", (str(channel_id),)).fetchone()
            return row["cursor"] if row else None

    def channel_status(self, channel_id: str, now: Any = None, retention_hours: float = 48,
                       expected_interval_hours: float = 6) -> dict[str, Any]:
        current_time = parse_time(now) or datetime.now(timezone.utc)
        with self._lock:
            row = self.conn.execute("SELECT * FROM channels WHERE channel_id=?", (str(channel_id),)).fetchone()
            status = dict(row) if row else {"channel_id":str(channel_id),"cursor":None,"last_success_at":None,"last_attempt_at":None,"last_error":None}
            latest = self.conn.execute("SELECT * FROM runs WHERE channel_id=? ORDER BY run_id DESC LIMIT 1", (str(channel_id),)).fetchone()
            count = self.conn.execute("SELECT COUNT(*) FROM messages WHERE channel_id=?", (str(channel_id),)).fetchone()[0]
            gaps = [dict(item) for item in self.conn.execute("SELECT * FROM coverage_gaps WHERE channel_id=? ORDER BY gap_id", (str(channel_id),))]
        last_success = parse_time(status["last_success_at"])
        elapsed = max(0.0,(current_time-last_success).total_seconds()) if last_success else None
        if elapsed is None:
            coverage = "never_synced"
        elif elapsed >= retention_hours*3600:
            coverage = "retention_at_risk"
        elif elapsed > expected_interval_hours*3600:
            coverage = "overdue"
        else:
            coverage = "healthy"
        status.update({"message_count":count,"latest_run":dict(latest) if latest else None,
            "hours_since_success":round(elapsed/3600,3) if elapsed is not None else None,
            "coverage_status":coverage,"coverage_gaps":gaps,
            "retention_hours":retention_hours,"expected_interval_hours":expected_interval_hours,
            "offline_hours":round(elapsed/3600,3) if elapsed is not None else None,
            "offline_hours_basis":"time_since_last_successful_collection; network outage itself is not observed"})
        return status

    get_channel_status = channel_status

    def summary(self) -> dict[str, Any]:
        with self._lock:
            token = self.change_token()
            if not self.conn.in_transaction and self._summary_cache is not None and self._summary_cache[0] == token:
                cached = self._summary_cache[1]
                return {**cached,"runs_by_status":dict(cached["runs_by_status"])}
            message_count = self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            version_count = self.conn.execute("SELECT COUNT(*) FROM message_versions").fetchone()[0]
            snapshot_count = self.conn.execute("SELECT COUNT(*) FROM messages WHERE is_reference_snapshot=1").fetchone()[0]
            run_counts = {row["status"]:row["count"] for row in self.conn.execute("SELECT status,COUNT(*) AS count FROM runs GROUP BY status")}
            gap_count = self.conn.execute("SELECT COUNT(*) FROM coverage_gaps").fetchone()[0]
            channel_count = self.conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
            result = {"message_count":message_count,"version_count":version_count,"reference_snapshot_count":snapshot_count,
                "channel_count":channel_count,"run_count":sum(run_counts.values()),"runs_by_status":run_counts,
                "coverage_gap_count":gap_count}
            # The token is captured before reading: a concurrent external commit
            # invalidates this entry on the next call rather than being missed.
            # Never retain an uncommitted view: total_changes does not rewind
            # when SQLite rolls a transaction back.
            self._summary_cache = None if self.conn.in_transaction else (token,result)
            return {**result,"runs_by_status":dict(run_counts)}

    stats = summary

    def record_gap(self, channel_id: str, started_at: Any, ended_at: Any = None,
                   reason: str = "Possible missing history", kind: str = "possible_missing_history") -> None:
        now = utc_now()
        with self._transaction() as db:
            self._ensure_channel(db,str(channel_id),now=now)
            db.execute("""INSERT OR IGNORE INTO coverage_gaps(channel_id,started_at,ended_at,detected_at,kind,reason)
                VALUES(?,?,?,?,?,?)""", (str(channel_id),iso_time(started_at),iso_time(ended_at) if ended_at else None,now,kind,reason))

    def import_dce(self, document: str | Path | dict[str, Any], *, channel_id: str | None = None) -> dict[str, Any]:
        if isinstance(document,(str,Path)):
            with Path(document).open(encoding="utf-8-sig") as handle:
                document = json.load(handle)
        if not isinstance(document,dict) or not isinstance(document.get("messages"),list):
            raise ValueError("A DiscordChatExporter JSON object with a messages list is required")
        channel = document.get("channel") or {}
        chosen_channel = _id(channel_id or channel.get("id"))
        if not chosen_channel:
            raise ValueError("DCE export channel id is missing")
        guild = document.get("guild") or {}
        self.ensure_channel(chosen_channel,channel.get("name"),_id(guild.get("id")))
        run_id = self.start_run(chosen_channel,trigger="import",source="dce")
        try:
            stats = self.ingest_messages(chosen_channel,document["messages"],run_id,source="dce")
            # Importing an offline file must not claim the live channel was just
            # checked or move the live collection cursor.
            with self._transaction() as db:
                db.execute("UPDATE runs SET status='success',completed_at=?,cursor_after=cursor_before WHERE run_id=?", (utc_now(),run_id))
            return {"run_id":run_id,"channel_id":chosen_channel,**stats}
        except Exception as exc:
            self.finish_run(run_id,False,str(exc))
            raise
