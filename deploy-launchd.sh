#!/usr/bin/env bash
# (Re)deploy the launchd agents that run the Jarvis OCR Service on login.
# Installs both the API service and the Redis queue worker.

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$ROOT"

AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/jarvis-ocr"

LABELS=(
    "com.jarvis.ocr.service"
    "com.jarvis.ocr.worker"
)

# Verify templates exist
for label in "${LABELS[@]}"; do
    template="$ROOT/scripts/launchd/$label.plist"
    if [[ ! -f "$template" ]]; then
        echo "Error: launchd template not found at $template"
        exit 1
    fi
done

mkdir -p "$AGENTS_DIR" "$LOG_DIR"

for label in "${LABELS[@]}"; do
    template="$ROOT/scripts/launchd/$label.plist"
    target="$AGENTS_DIR/$label.plist"

    # Materialize plist with absolute paths
    sed -e "s#__ROOT__#$ROOT#g" \
        -e "s#__USER__#$USER#g" \
        "$template" > "$target"

    echo "Installed $target"

    # Reload service using modern launchctl commands
    echo "Reloading $label..."
    launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/$(id -u)" "$target"
    launchctl enable "gui/$(id -u)/$label"
    launchctl kickstart -k "gui/$(id -u)/$label"

    echo "Ready: $label"
done

echo ""
echo "Both OCR LaunchAgents deployed."
echo "Check status: launchctl print gui/$(id -u)/com.jarvis.ocr.service"
echo "              launchctl print gui/$(id -u)/com.jarvis.ocr.worker"
echo "View logs:    tail -f $LOG_DIR/service-out.log"
echo "              tail -f $LOG_DIR/worker-out.log"
