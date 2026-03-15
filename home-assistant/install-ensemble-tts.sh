#!/usr/bin/env bash
# Copy Ensemble TTS custom component to Home Assistant via SSH.
# Run from repo root:  ./home-assistant/install-ensemble-tts.sh
# Uses marqootz@homeassistant.local; installs to /config via sudo.
# (Uses ssh + tee because sftp may not be available on the add-on.)

set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE="${1:-marqootz@homeassistant.local}"
DEST="/config/custom_components/ensemble_tts"
SRC="$REPO_ROOT/home-assistant/custom_components/ensemble_tts"

echo "Creating $DEST on $REMOTE..."
ssh "$REMOTE" "sudo mkdir -p $DEST $DEST/translations"

echo "Copying files..."
for f in manifest.json const.py __init__.py config_flow.py tts.py README.md; do
  ssh "$REMOTE" "sudo tee $DEST/$f" < "$SRC/$f" > /dev/null
done
if [ -f "$SRC/translations/en.json" ]; then
  ssh "$REMOTE" "sudo tee $DEST/translations/en.json" < "$SRC/translations/en.json" > /dev/null
fi

echo "Done. Restart Home Assistant or reload the TTS integration."
