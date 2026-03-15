# Ensemble TTS

Home Assistant TTS that sends text to your Ensemble server (`/v1/audio/speech`) and returns MP3. Use it in the voice assistant pipeline so replies use the same voices (Matilda/Leon) as the Mac server.

## Installation

1. Copy this folder to your Home Assistant config:
   - From this repo: `home-assistant/custom_components/ensemble_tts/`
   - To: `config/custom_components/ensemble_tts/`
   - Or run: `./home-assistant/install-ensemble-tts.sh` (from repo root, copies via SSH).

2. Restart Home Assistant.

## Configuration (choose one)

### Option A: Add via UI (recommended — shows in pipeline dropdown)

1. **Settings → Devices & services → Add integration**
2. Search for **Ensemble TTS**, add it.
3. Enter **Base URL** (e.g. `http://10.50.3.21:8000`). No trailing slash.
4. Finish. A TTS entity is created and will appear in the voice assistant pipeline editor.

### Option B: configuration.yaml (legacy)

```yaml
tts:
  - platform: ensemble_tts
    base_url: "http://YOUR_MAC_IP:8000"
```

Replace `YOUR_MAC_IP` with the IP of the Mac running Ensemble. Reload TTS or restart HA.

**Note:** With yaml only, the engine may not appear in the pipeline dropdown in some setups. Use Option A if you need it listed there.

## Use in Assist

1. **Settings → Voice assistants** → open your pipeline (e.g. Ensemble).
2. Under **Text-to-speech**, select **Ensemble TTS** (or the entity `tts.ensemble_tts`).
3. Save.

Pipeline flow: STT → Conversation (Extended OpenAI → Mac `/v1/chat/completions`) → TTS (Ensemble TTS → Mac `/v1/audio/speech`).

## Removing a stuck integration

If the Ensemble TTS integration won’t delete from the UI (e.g. after a failed config flow):

1. **Stop Home Assistant** (or make a backup of the file below).
2. **Edit** `config/.storage/core.config_entries` (e.g. with the File Editor add-on or over SSH).
3. **Remove** the entry whose `"domain"` is `"ensemble_tts"`: in the `"data"` → `"entries"` array, delete that single JSON object (the one containing `"domain": "ensemble_tts"`). Keep the rest of the array and the file structure valid.
4. **Save** the file and **restart** Home Assistant.

After that, the integration will be gone and you can add it again.

## Requirements

- Ensemble server running on the Mac and reachable from HA at `base_url`.
- No extra Python requirements; Home Assistant provides `aiohttp`.
