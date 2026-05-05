#!/usr/bin/env python3
"""Hermes UI - small local dashboard for managing Hermes sessions.

No external Python dependencies. Run:
    python app.py
then open http://127.0.0.1:8765
"""

from __future__ import annotations

import cgi
import json
import mimetypes
import os
import re
import sqlite3
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
DB_PATH = Path(os.environ.get("HERMES_STATE_DB", HERMES_HOME / "state.db")).expanduser()
SESSION_JSON_DIR = Path(os.environ.get("HERMES_SESSION_DIR", HERMES_HOME / "sessions")).expanduser()
UPLOAD_ROOT = Path(os.environ.get("HERMES_UI_UPLOAD_ROOT", ROOT / "uploads")).expanduser()

HOST = os.environ.get("HERMES_UI_HOST", "127.0.0.1")
PORT = int(os.environ.get("HERMES_UI_PORT", "8765"))

NEW_SESSION_TITLE = "new session"
NEW_SESSION_TITLE_PREFIX = "new_session_"
NEW_SESSION_SEED_PROMPT = "Reply exactly in English and do not translate: New conversation created"
TITLE_MAX_LENGTH = 64
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def json_response(handler: BaseHTTPRequestHandler, payload, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def error(handler: BaseHTTPRequestHandler, message: str, status: int = 400) -> None:
    json_response(handler, {"ok": False, "error": message}, status)


def iso_from_epoch(value):
    if value is None:
        return None
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value)))
    except Exception:
        return None


def short_text(value: str | None, limit: int = 180) -> str:
    if not value:
        return ""
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def clean_title_source(value: str | None) -> str:
    """Normalize a user message before deriving an automatic session title."""
    if not value:
        return ""
    text = str(value)
    for attachment_marker in ("以下是我随消息附上的文件内容", "用户上传了以下附件", "[attachments]"):
        if attachment_marker in text:
            text = text.split(attachment_marker, 1)[0]
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"https?://\S+", " ", text)
    text = " ".join(text.split())
    return text.strip(" -_.,，。;；:：!?！？、/\\|")


def first_clause(value: str, limit: int = 32) -> str:
    text = clean_title_source(value)
    if not text:
        return ""
    pieces = re.split(r"(?<=[。！？!?；;\.])\s+|[\n\r]+|[。！？!?；;]", text)
    clause = next((piece.strip() for piece in pieces if piece.strip()), text)
    return short_text(clause, limit)


def build_auto_title(second_user_message: str, third_user_message: str) -> str:
    """Build one fixed title from the visible 2nd and 3rd user messages."""
    parts = [part for part in (first_clause(second_user_message), first_clause(third_user_message)) if part]
    if not parts:
        return NEW_SESSION_TITLE
    title = " / ".join(parts)
    return short_text(title, TITLE_MAX_LENGTH) or NEW_SESSION_TITLE


def is_new_session_placeholder(title: str | None) -> bool:
    text = (title or "").strip()
    return not text or text == NEW_SESSION_TITLE or text.startswith(NEW_SESSION_TITLE_PREFIX)


def build_initial_session_title(session_id: str | None) -> str:
    """Build a unique, readable placeholder title for a just-created session."""
    now = time.strftime("%Y%m%d%H%M%S", time.localtime())
    if not session_id:
        return f"{NEW_SESSION_TITLE_PREFIX}{now}"
    match = re.match(r"^(\d{8})_(\d{6})_([A-Za-z0-9]+)$", session_id)
    if match:
        stamp = f"{match.group(1)}{match.group(2)}"
        suffix = match.group(3)[:6]
        return f"{NEW_SESSION_TITLE_PREFIX}{stamp}_{suffix}"
    safe_id = re.sub(r"[^A-Za-z0-9]+", "", session_id)[-6:]
    return f"{NEW_SESSION_TITLE_PREFIX}{now}_{safe_id}" if safe_id else f"{NEW_SESSION_TITLE_PREFIX}{now}"


def make_unique_title(conn: sqlite3.Connection, title: str, session_id: str) -> str:
    candidate = short_text(title, TITLE_MAX_LENGTH)
    if not candidate:
        candidate = build_initial_session_title(session_id)
    base = candidate
    counter = 2
    while conn.execute(
        "SELECT 1 FROM sessions WHERE title = ? AND id != ? LIMIT 1",
        (candidate, session_id),
    ).fetchone():
        suffix = f"_{counter}"
        candidate = short_text(base, TITLE_MAX_LENGTH - len(suffix)) + suffix
        counter += 1
    return candidate


def set_session_title(session_id: str, title: str) -> str:
    with db() as conn:
        unique_title = make_unique_title(conn, title, session_id)
        conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (unique_title, session_id))
        conn.commit()
        return unique_title


def visible_user_messages(conn: sqlite3.Connection, session_id: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT content
        FROM messages
        WHERE session_id = ? AND role = 'user' AND content IS NOT NULL
        ORDER BY timestamp ASC, id ASC
        """,
        (session_id,),
    ).fetchall()
    messages = []
    for row in rows:
        content = (row["content"] or "").strip()
        if not content or content == NEW_SESSION_SEED_PROMPT:
            continue
        messages.append(content)
    return messages


def maybe_generate_session_title(session_id: str) -> str | None:
    """Generate the title once when visible user message #4 arrives.

    The trigger is the 4th visible user message, but the title content is still
    based only on visible user messages #2 and #3.
    """
    with db() as conn:
        row = conn.execute("SELECT title FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        current_title = (row["title"] or "").strip()
        if not is_new_session_placeholder(current_title):
            return current_title
        user_messages = visible_user_messages(conn, session_id)
        if len(user_messages) < 4:
            return current_title or NEW_SESSION_TITLE
        title = make_unique_title(conn, build_auto_title(user_messages[1], user_messages[2]), session_id)
        conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))
        conn.commit()
        return title


def get_sessions(query: str = "") -> list[dict]:
    if not DB_PATH.exists():
        return []
    q = f"%{query.strip()}%"
    sql = """
        SELECT
            s.id,
            s.title,
            s.source,
            s.model,
            s.started_at,
            COALESCE(s.ended_at, s.started_at) AS last_active,
            s.message_count,
            s.tool_call_count,
            s.input_tokens,
            s.output_tokens,
            (
              SELECT content FROM messages m
              WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
              ORDER BY m.timestamp ASC LIMIT 1
            ) AS first_user_message,
            (
              SELECT content FROM messages m
              WHERE m.session_id = s.id AND m.content IS NOT NULL
              ORDER BY m.timestamp DESC LIMIT 1
            ) AS last_message
        FROM sessions s
        WHERE (? = '' OR s.id LIKE ? OR COALESCE(s.title, '') LIKE ? OR COALESCE(s.model, '') LIKE ? OR EXISTS (
            SELECT 1 FROM messages m
            WHERE m.session_id = s.id AND COALESCE(m.content, '') LIKE ?
        ))
        ORDER BY last_active DESC
        LIMIT 200
    """
    with db() as conn:
        rows = conn.execute(sql, (query.strip(), q, q, q, q)).fetchall()
    result = []
    for row in rows:
        title = row["title"] or NEW_SESSION_TITLE
        result.append(
            {
                "id": row["id"],
                "title": title,
                "source": row["source"],
                "model": row["model"],
                "started_at": iso_from_epoch(row["started_at"]),
                "last_active": iso_from_epoch(row["last_active"]),
                "message_count": row["message_count"],
                "tool_call_count": row["tool_call_count"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "preview": short_text(row["first_user_message"] or row["last_message"]),
                "resume_command": f"hermes --resume {row['id']}",
            }
        )
    return result


def get_session(session_id: str) -> dict | None:
    with db() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            return None
        messages = conn.execute(
            """
            SELECT id, role, content, tool_name, timestamp, finish_reason
            FROM messages
            WHERE session_id = ?
            ORDER BY timestamp ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
    return {
        "id": session["id"],
        "title": session["title"] or NEW_SESSION_TITLE,
        "source": session["source"],
        "model": session["model"],
        "started_at": iso_from_epoch(session["started_at"]),
        "ended_at": iso_from_epoch(session["ended_at"]),
        "message_count": session["message_count"],
        "tool_call_count": session["tool_call_count"],
        "tokens": {
            "input": session["input_tokens"],
            "output": session["output_tokens"],
            "cache_read": session["cache_read_tokens"],
            "cache_write": session["cache_write_tokens"],
            "reasoning": session["reasoning_tokens"],
        },
        "resume_command": f"hermes --resume {session_id}",
        "json_path": str(SESSION_JSON_DIR / f"session_{session_id}.json"),
        "messages": [
            {
                "id": m["id"],
                "role": m["role"],
                "content": m["content"] or "",
                "tool_name": m["tool_name"],
                "timestamp": iso_from_epoch(m["timestamp"]),
                "finish_reason": m["finish_reason"],
            }
            for m in messages
        ],
    }


def run_hermes_command(args: list[str], timeout: int = 20) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["hermes", *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            cwd=str(Path.home()),
        )
        return proc.returncode == 0, proc.stdout.strip()
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        return False, f"Hermes command timed out after {timeout}s.\n{output}".strip()
    except Exception as exc:
        return False, str(exc)


def send_chat_message(session_id: str, message: str) -> tuple[bool, str]:
    # -Q keeps stdout quieter for web use. --yolo avoids a headless browser request
    # getting stuck on terminal approval prompts.
    return run_hermes_command(
        ["chat", "--resume", session_id, "--quiet", "--yolo", "--query", message],
        timeout=600,
    )


def create_new_session() -> tuple[bool, str, str | None]:
    ok, out = run_hermes_command(
        ["chat", "--quiet", "--yolo", "--query", NEW_SESSION_SEED_PROMPT],
        timeout=300,
    )
    matches = re.findall(r"\b\d{8}_\d{6}_[a-f0-9]+\b", out)
    session_id = matches[-1] if matches else None
    if not session_id:
        sessions = get_sessions("")
        session_id = sessions[0]["id"] if sessions else None
    if ok and session_id:
        set_session_title(session_id, build_initial_session_title(session_id))
    return ok, out, session_id


def safe_filename(filename: str) -> str:
    name = Path(filename or "attachment").name.strip()
    name = re.sub(r"[^A-Za-z0-9._()\-\u4e00-\u9fff ]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:160] or "attachment"


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def append_attachment_metadata(session_dir: Path, records: list[dict]) -> None:
    metadata_path = session_dir / "attachments.json"
    existing = []
    if metadata_path.exists():
        try:
            existing = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except (OSError, json.JSONDecodeError):
            existing = []
    metadata_path.write_text(json.dumps(existing + records, ensure_ascii=False, indent=2), encoding="utf-8")


def save_uploaded_attachments(session_id: str, files: list[dict]) -> list[dict]:
    if not files:
        return []
    session_dir = UPLOAD_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    uploaded_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    records = []
    for index, item in enumerate(files, start=1):
        original_name = item["filename"]
        data = item["data"]
        clean_name = safe_filename(original_name)
        saved_name = f"{stamp}_{index:02d}_{clean_name}"
        path = session_dir / saved_name
        counter = 2
        while path.exists():
            saved_name = f"{stamp}_{index:02d}_{counter}_{clean_name}"
            path = session_dir / saved_name
            counter += 1
        path.write_bytes(data)
        records.append(
            {
                "original_name": original_name,
                "saved_name": saved_name,
                "path": str(path),
                "size": len(data),
                "size_display": format_bytes(len(data)),
                "uploaded_at": uploaded_at,
            }
        )
    append_attachment_metadata(session_dir, records)
    return records


def build_message_with_attachment_paths(message: str, attachments: list[dict]) -> str:
    if not attachments:
        return message
    parts = [message, "", "[attachments]"]
    for index, item in enumerate(attachments, start=1):
        parts.append(
            f"{index}. {item['original_name']}\n"
            f"path: {item['path']}\n"
            f"size: {item['size_display']}\n"
            f"uploaded_at: {item['uploaded_at']}"
        )
    return "\n".join(parts)


def parse_post_payload(handler: BaseHTTPRequestHandler) -> tuple[dict, list[dict]]:
    content_type = handler.headers.get("Content-Type", "")
    length = int(handler.headers.get("Content-Length", "0"))

    if content_type.startswith("multipart/form-data"):
        form = cgi.FieldStorage(
            fp=handler.rfile,
            headers=handler.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(length),
            },
            keep_blank_values=True,
        )
        payload = {}
        files = []
        for key in form.keys():
            values = form[key]
            if not isinstance(values, list):
                values = [values]
            for field in values:
                if field.filename:
                    data = field.file.read()
                    files.append({"filename": Path(field.filename).name, "data": data})
                else:
                    payload[key] = field.value
        return payload, files

    raw = handler.rfile.read(length).decode("utf-8") if length else "{}"
    try:
        return json.loads(raw or "{}"), []
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/health":
            return json_response(self, {"ok": True, "db": str(DB_PATH), "db_exists": DB_PATH.exists()})
        if path == "/api/sessions":
            query = parse_qs(parsed.query).get("q", [""])[0]
            return json_response(self, {"ok": True, "sessions": get_sessions(query)})
        if path.startswith("/api/sessions/"):
            session_id = path.rsplit("/", 1)[-1]
            session = get_session(session_id)
            if not session:
                return error(self, "Session not found", 404)
            return json_response(self, {"ok": True, "session": session})
        self.serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            payload, files = parse_post_payload(self)
        except ValueError as exc:
            return error(self, str(exc), 400)

        if path == "/api/sessions/new":
            try:
                ok, out, session_id = create_new_session()
                session = get_session(session_id) if session_id else None
            except Exception as exc:
                return error(self, str(exc), 500)
            return json_response(
                self,
                {"ok": ok and bool(session), "output": out, "session": session},
                200 if ok and session else 500,
            )

        if path.startswith("/api/sessions/") and path.endswith("/rename"):
            session_id = path.split("/")[3]
            title = str(payload.get("title", "")).strip()
            if not title:
                return error(self, "Title is required")
            ok, out = run_hermes_command(["sessions", "rename", session_id, title])
            return json_response(self, {"ok": ok, "output": out}, 200 if ok else 500)

        if path.startswith("/api/sessions/") and path.endswith("/delete"):
            session_id = path.split("/")[3]
            ok, out = run_hermes_command(["sessions", "delete", "--yes", session_id])
            return json_response(self, {"ok": ok, "output": out}, 200 if ok else 500)

        if path.startswith("/api/sessions/") and path.endswith("/chat"):
            session_id = path.split("/")[3]
            message = str(payload.get("message", "")).strip()
            if not message and not files:
                return error(self, "Message or attachment is required")
            if len(files) > MAX_ATTACHMENTS:
                return error(self, f"最多只能添加 {MAX_ATTACHMENTS} 个附件", 400)
            for item in files:
                if len(item["data"]) > MAX_ATTACHMENT_BYTES:
                    return error(self, f"附件过大：{item['filename']}，单个文件最多 {format_bytes(MAX_ATTACHMENT_BYTES)}", 400)
            if not get_session(session_id):
                return error(self, "Session not found", 404)
            attachments = save_uploaded_attachments(session_id, files)
            final_message = build_message_with_attachment_paths(message, attachments)
            ok, out = send_chat_message(session_id, final_message)
            maybe_generate_session_title(session_id)
            session = get_session(session_id)
            return json_response(
                self,
                {"ok": ok, "output": out, "session": session},
                200 if ok else 500,
            )

        return error(self, "Unknown endpoint", 404)

    def serve_static(self, path: str) -> None:
        if path in ("", "/"):
            file_path = STATIC / "index.html"
        else:
            file_path = (STATIC / path.lstrip("/")).resolve()
            if STATIC.resolve() not in file_path.parents and file_path != STATIC.resolve():
                return error(self, "Forbidden", 403)
        if not file_path.exists() or not file_path.is_file():
            return error(self, "Not found", 404)
        body = file_path.read_bytes()
        ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    if not DB_PATH.exists():
        print(f"Warning: Hermes state DB not found: {DB_PATH}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Hermes UI running: http://{HOST}:{PORT}")
    print(f"Using DB: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
