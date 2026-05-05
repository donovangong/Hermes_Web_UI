# Hermes UI MVP Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a lightweight local UI to browse and manage Hermes sessions.

**Architecture:** Start with a dependency-free Python HTTP server that reads Hermes SQLite session data and serves a static HTML/CSS/JS frontend. Use Hermes CLI commands for rename/delete to avoid guessing internal write semantics.

**Tech Stack:** Python stdlib `http.server`, SQLite, vanilla HTML/CSS/JS.

---

### Task 1: Create project scaffold

**Objective:** Create a runnable local web project under `/opt/hermes-agent-web`.

**Files:**
- Create: `app.py`
- Create: `static/index.html`
- Create: `static/styles.css`
- Create: `static/app.js`
- Create: `README.md`
- Create: `.gitignore`

**Verification:**
Run `python -m py_compile app.py`.
Expected: exit code 0.

### Task 2: Add session list API

**Objective:** Read sessions from `$HOME/.hermes/state.db` and expose `/api/sessions`.

**Files:**
- Modify: `app.py`

**Verification:**
Run server, then `curl http://127.0.0.1:8765/api/sessions`.
Expected: JSON with `ok: true` and a `sessions` array.

### Task 3: Add session detail API

**Objective:** Show messages for one session via `/api/sessions/<id>`.

**Files:**
- Modify: `app.py`

**Verification:**
Open a session in the UI.
Expected: right panel shows metadata and ordered messages.

### Task 4: Add management actions

**Objective:** Support rename and delete through Hermes CLI.

**Files:**
- Modify: `app.py`
- Modify: `static/app.js`

**Verification:**
Use UI rename on a test session.
Expected: `hermes sessions list` shows new title.

### Task 5: Improve UX

**Objective:** Add keyboard shortcuts, safer delete UX, and optional export button.

**Files:**
- Modify: `static/index.html`
- Modify: `static/styles.css`
- Modify: `static/app.js`

**Verification:**
Manual browser check.
Expected: search, select, copy, rename, delete all work clearly.
