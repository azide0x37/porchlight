#!/bin/sh
set -eu

PROJECT="porchlight"
SRC_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT_DIR="${1:-$SRC_ROOT/systemd}"

install -d -m 0755 "$OUT_DIR"
cp "$SRC_ROOT/systemd/porchlight-ha-mqtt-bridge.service" "$OUT_DIR/"
cp "$SRC_ROOT/systemd/porchlight-ha-mqtt-bridge.timer" "$OUT_DIR/"
cp "$SRC_ROOT/systemd/porchlight-scan.service" "$OUT_DIR/"
cp "$SRC_ROOT/systemd/porchlight-scan.timer" "$OUT_DIR/"
cp "$SRC_ROOT/systemd/porchlight-discover.service" "$OUT_DIR/"
cp "$SRC_ROOT/systemd/porchlight-deep-scan.service" "$OUT_DIR/"
printf 'rendered %s systemd units to %s\n' "$PROJECT" "$OUT_DIR"
