# Hermes Agent Web MVP Implementation Plan

**Goal:** Build a lightweight local browser UI to browse and continue Hermes Agent sessions.

**Architecture:** Python standard-library HTTP server reads Hermes SQLite session data and serves a static HTML/CSS/JS frontend. Session management actions use Hermes CLI commands instead of directly mutating private Hermes internals.

**Tech Stack:** Python stdlib `http.server`, SQLite, vanilla HTML/CSS/JS.

## Implemented MVP

1. Project scaffold
   - `app.py`
   - `static/index.html`
   - `static/styles.css`
   - `static/app.js`
   - `README.md`
   - `.gitignore`

2. Session list API
   - `GET /api/sessions`
   - Optional query parameter: `q`

3. Session detail API
   - `GET /api/sessions/<session_id>`

4. Management actions
   - `POST /api/sessions/new`
   - `POST /api/sessions/<session_id>/chat`
   - `POST /api/sessions/<session_id>/rename`
   - `POST /api/sessions/<session_id>/delete`

5. Browser UX
   - Left sidebar session list
   - Search
   - New chat button
   - ChatGPT-like user/assistant conversation view
   - Bottom composer
   - Up to 5 text/code attachments sent together with the message
   - Auto-scroll to latest message

## Next steps

- Add authentication before remote/public deployment
- Add streaming responses instead of waiting for the Hermes CLI process to finish
- Add export button
- Add session tags/folders
- Add proper packaging, for example `hermes-web-ui` command
