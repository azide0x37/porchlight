#!/bin/sh
set -eu

if command -v systemctl >/dev/null 2>&1; then
  exec systemctl start porchlight-scan.service
fi

exec /opt/porchlight/current/bin/porchlight-scan --apply --mode scan
