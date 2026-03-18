# Ensemble

Multi-agent voice assistant for Home Assistant. Two AI collaborators — **Matilda** (operator/executor) and **Leon** (navigator/explorer) — deliberate and respond to Mark in a three-way conversation.

## Agents

| Agent    | Role       | Domain | Voice   |
|----------|------------|--------|---------|
| Matilda  | Operator   | Home control, scheduling, weather, execution | ElevenLabs female |
| Leon     | Navigator  | Research, design, UX, coding, synthesis      | ElevenLabs male   |

Shared domains (health, creative projects, travel, news) trigger **deliberation**: both agents respond in sequence, then one produces the final answer.

## Stack

- Python 3.11+
- FastAPI — OpenAI-compatible `POST /v1/chat/completions`
- Anthropic (claude-sonnet-4-20250514) — tool use for both agents
- ElevenLabs — per-agent voice; fallback to pyttsx3 on failure
- Web search: Brave (if API key set) or DuckDuckGo (free); SQLite memory; Home Assistant REST API

## Setup

1. **Clone the repo** (or copy the `ensemble` folder to your Mac Studio).

2. **Create a virtualenv and install dependencies:**
   ```bash
   cd ensemble
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set:
   - `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`
   - `MATILDA_VOICE_ID`, `LEON_VOICE_ID` (from [ElevenLabs Voice Library](https://elevenlabs.io/voice-library))
   - `HA_URL`, `HA_TOKEN` (`BRAVE_API_KEY` optional — DuckDuckGo used if unset)

4. **Run locally:**
   ```bash
   python main.py
   ```
   Server runs at `http://0.0.0.0:8000` (or `ENSEMBLE_PORT`).

5. **In Home Assistant:** Point **extended_openai_conversation** (or compatible) at `http://<mac-studio-ip>:8000/v1`.

6. **Install as a persistent macOS service:**
   - Edit `com.ensemble.plist`: set `WorkingDirectory` to the **absolute path** of the `ensemble` directory.
   - Optionally set `ProgramArguments` to your venv Python, e.g. `<string>/Users/you/ensemble/.venv/bin/python</string>` and `<string>main.py</string>`.
   - Load env from `.env` by sourcing it in a wrapper script, or set `EnvironmentVariables` in the plist for each var.
   ```bash
   cp com.ensemble.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.ensemble.plist
   ```
   Logs: `~/Library/Logs/ensemble.log`.

7. **Seed memory (optional):** Edit `data/seed_mark_profile.json` with `seed_memories` (key/value pairs). On startup the app loads these into the shared memory store with `speaker=system`. You can also run `python load_seed_memory.py` once to load or refresh.

## API

- **POST /v1/chat/completions**  
  Body: OpenAI-style `messages` array. Last user message = Mark’s input.  
  - **?audio=true** — Returns concatenated MP3 (Matilda + Leon in order, with 400ms silence between).  
  - **?turns=true** — Response JSON includes a `turns` array: `[{ "agent": "matilda"|"leon", "text": "..." }]`.

- **GET /health**  
  Returns `{"status": "ok"}`.

- **WebSocket /ws/state**  
  Subscribers receive JSON state after each turn: `active_agent`, `deliberating`, `awaiting_mark`, `topic`. For future use (e.g. USB serial bridge to AtomS3R / Leon's face device).

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| ANTHROPIC_API_KEY | Yes | Anthropic API key |
| ELEVENLABS_API_KEY | Yes | ElevenLabs API key |
| MATILDA_VOICE_ID | Yes | ElevenLabs voice ID for Matilda |
| LEON_VOICE_ID | Yes | ElevenLabs voice ID for Leon |
| HA_URL | Yes | Home Assistant URL (e.g. http://homeassistant.local:8123) |
| HA_TOKEN | Yes | Long-lived HA access token |
| BRAVE_API_KEY | No | Brave Search API key; if unset, DuckDuckGo (free) is used |
| ENSEMBLE_PORT | No | Port (default 8000) |
| MEMORY_DB_PATH | No | SQLite path (default: ensemble/data/ensemble_memory.db) |
| CLAUDE_MODEL | No | Model (default: claude-sonnet-4-20250514) |

## Error handling

- Tool failures: agents acknowledge in speech and do not crash.
- HA unreachable: Matilda reports plainly and can retry.
- Search failure: Leon notes it and continues from context.
- ElevenLabs failure: fallback to system TTS (pyttsx3) with degraded voice.
- Exceptions are logged to `ensemble.log` with traceback.
