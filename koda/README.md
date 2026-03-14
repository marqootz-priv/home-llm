# Koda

Koda is a Python voice assistant that runs as a persistent service on macOS. It acts as the AI brain for a Home Assistant voice pipeline: Home Assistant sends transcribed text and receives text or audio responses.

## Stack

- **Python 3.11+**
- **FastAPI** — OpenAI-compatible `POST /v1/chat/completions` for [extended_openai_conversation](https://www.home-assistant.io/integrations/openai_conversation/) in Home Assistant
- **Anthropic** — Claude (claude-sonnet-4-20250514) with tool use
- **ElevenLabs** — TTS for spoken responses
- **Web search** — Brave Search (if API key set) or DuckDuckGo (free, no key)
- **SQLite** — conversation memory
- **python-dotenv** — config and secrets

## Setup

1. **Clone the repo** (or copy the `koda` folder to your Mac Studio).

2. **Create a virtualenv and install dependencies:**
   ```bash
   cd koda
   python3 -m venv .venv
   source .venv/bin/activate   # On macOS/Linux
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env and set:
   # ANTHROPIC_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID,
   # HA_URL, HA_TOKEN (BRAVE_API_KEY optional — DuckDuckGo used if unset)
   ```

4. **Run locally to test:**
   ```bash
   python main.py
   ```
   Server listens on `http://0.0.0.0:8000`. Try:
   - `GET http://localhost:8000/health`
   - `POST http://localhost:8000/v1/chat/completions` with JSON body:
     `{"messages": [{"role": "user", "content": "Hello"}]}`

5. **Install as a persistent macOS service (launchd):**
   - Edit `com.koda.agent.plist`: set `WorkingDirectory` to the **absolute path** of the `koda` directory (e.g. `/Users/you/home-llm/koda`).
   - If you use a venv, change `ProgramArguments` to use the venv Python, e.g.:
     `<string>/Users/you/home-llm/koda/.venv/bin/python</string>`
   - Copy the plist to LaunchAgents and load it:
     ```bash
     cp com.koda.agent.plist ~/Library/LaunchAgents/
     launchctl load ~/Library/LaunchAgents/com.koda.agent.plist
     ```
   - Logs: `~/Library/Logs/koda.log`
   - Unload: `launchctl unload ~/Library/LaunchAgents/com.koda.agent.plist`

## API

- **POST /v1/chat/completions**  
  Accepts an OpenAI-style request with a `messages` array. The last user message is used as the current query. Returns an OpenAI-style JSON response with Koda’s reply in `choices[0].message.content`.

  - **Query param `?audio=true`**  
  Returns ElevenLabs MP3 audio instead of JSON (same reply, spoken).

- **GET /health**  
  Returns `{"status": "ok"}`.

## Tools (Claude)

- **control_home** — Home Assistant REST API: `get_state` and `call_service` (e.g. lights, switches).
- **search_web** — Brave (if key set) or DuckDuckGo; returns top 3 results.
- **remember** — SQLite memory: `store`, `retrieve`, `list`.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| ANTHROPIC_API_KEY | Yes | Anthropic API key |
| ELEVENLABS_API_KEY | Yes | ElevenLabs API key |
| ELEVENLABS_VOICE_ID | Yes | ElevenLabs voice ID for TTS |
| HA_URL | Yes | Home Assistant URL (e.g. http://homeassistant.local:8123) |
| HA_TOKEN | Yes | Long-lived HA access token |
| BRAVE_API_KEY | No | Brave Search API key; if unset, DuckDuckGo (free) is used |
| MEMORY_DB_PATH | No | Path to SQLite DB (default: `koda/data/koda_memory.db`) |
| CLAUDE_MODEL | No | Model name (default: claude-sonnet-4-20250514) |
