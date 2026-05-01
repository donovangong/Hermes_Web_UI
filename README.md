# Hermes Web UI

A lightweight local web interface for browsing and continuing Hermes Agent sessions from a browser.

<p align="center">
  <img src="images/dashboard.png" alt="Dashboard screenshot" width="700">
</p>

This project is intentionally simple:

- Python standard library backend
- SQLite read access to Hermes session state
- Vanilla HTML/CSS/JavaScript frontend
- No external runtime dependencies

## Features

- Browse Hermes sessions in a left sidebar
- Search sessions by title, ID, model, and message content
- View conversations in a ChatGPT-like user/assistant layout
- Continue an existing Hermes session from the browser
- Create a new Hermes session from the browser
- Rename and delete sessions
- Attach up to 5 local text/code files and send them with a message
- Copy `hermes --resume <session_id>` command

## Requirements

- Linux/macOS/WSL environment
- Python 3.10+
- Hermes Agent CLI installed and configured
- Access to the Hermes state database, usually:

```text
~/.hermes/state.db
```

## Run

```bash
cd Hermes_Web_UI
python app.py
```

Default address:

```text
http://127.0.0.1:8765
```

To access from another machine on your local network or from a host browser into a VM:

```bash
HERMES_UI_HOST=0.0.0.0 HERMES_UI_PORT=8765 python app.py
```

Then open:

```text
http://<vm-or-server-ip>:8765
```

## Configuration

Optional environment variables:

```bash
HERMES_UI_HOST=127.0.0.1
HERMES_UI_PORT=8765
HERMES_HOME=~/.hermes
HERMES_STATE_DB=~/.hermes/state.db
HERMES_SESSION_DIR=~/.hermes/sessions
```

## Security notes

This app can read your Hermes sessions and can send prompts through your Hermes CLI.

Do not expose it directly to the public internet without authentication, HTTPS, and access control.

Recommended for development:

- Keep `HERMES_UI_HOST=127.0.0.1`, or
- Use SSH port forwarding, or
- Put it behind Nginx with Basic Auth / SSO if you need remote access.

Do not commit any of the following:

- `.env`
- API keys
- `~/.hermes/state.db`
- `~/.hermes/sessions/`
- logs
- uploaded files

## GitHub checklist

```bash
git init
git add .
git commit -m "feat: initial Hermes Web UI"
git branch -M main
git remote add origin git@github.com:<your-user>/<your-repo>.git
git push -u origin main
```

## License

Add your preferred license before publishing, for example MIT.
