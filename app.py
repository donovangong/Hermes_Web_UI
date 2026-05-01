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

HOST = os.environ.get("HERMES_UI_HOST", "127.0.0.1")
PORT = int(os.environ.get("HERMES_UI_PORT", "8765"))


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
        title = row["title"] or short_text(row["first_user_message"], 48) or row["id"]
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
        "title": session["title"] or session["id"],
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
        ["chat", "--quiet", "--yolo", "--query", "请只回复：新对话已创建"],
        timeout=300,
    )
    matches = re.findall(r"\b\d{8}_\d{6}_[a-f0-9]+\b", out)
    session_id = matches[-1] if matches else None
    if not session_id:
        sessions = get_sessions("")
        session_id = sessions[0]["id"] if sessions else None
    return ok, out, session_id


def decode_attachment(filename: str, data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def build_message_with_attachments(message: str, files: list[dict]) -> str:
    if not files:
        return message
    parts = [message, "", "以下是我随消息附上的文件内容，请一起参考："]
    for index, item in enumerate(files, start=1):
        filename = item["filename"]
        content = decode_attachment(filename, item["data"])
        parts.append(
            f"\n--- 附件 {index}: {filename} ---\n"
            f"```text\n{content}\n```\n"
            f"--- 附件 {index} 结束 ---"
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
            ok, out, session_id = create_new_session()
            session = get_session(session_id) if session_id else None
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
            if len(files) > 5:
                return error(self, "最多只能添加 5 个附件", 400)
            for item in files:
                if len(item["data"]) > 1024 * 1024:
                    return error(self, f"附件过大：{item['filename']}，单个文件最多 1MB", 400)
            if not get_session(session_id):
                return error(self, "Session not found", 404)
            final_message = build_message_with_attachments(message, files)
            ok, out = send_chat_message(session_id, final_message)
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
