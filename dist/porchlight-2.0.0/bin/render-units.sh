#!/bin/sh
set -eu

PROJECT="porchlight"
SRC_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT_DIR="${1:-$SRC_ROOT/systemd}"

install -d -m 0755 "$OUT_DIR"
cp "$SRC_ROOT"/systemd/porchlight-*.service "$OUT_DIR/"
cp "$SRC_ROOT"/systemd/porchlight-*.timer "$OUT_DIR/"
cp "$SRC_ROOT"/systemd/porchlight-*.path "$OUT_DIR/"
printf 'rendered %s systemd units to %s\n' "$PROJECT" "$OUT_DIR"
