#!/bin/sh
set -eu

PROJECT="porchlight"
CONFIG_DIR="${CONFIG_DIR:-/etc/$PROJECT}"
CURRENT_LINK="/opt/$PROJECT/current"
MANIFEST_FILE="${UPDATE_MANIFEST_FILE:-$CONFIG_DIR/update-manifest.json}"

json_field() {
  key="$1"
  file="$2"
  sed -n "s/.*\"$key\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" "$file" | head -n 1
}

if [ ! -f "$MANIFEST_FILE" ]; then
  printf '%s\n' "No update manifest at $MANIFEST_FILE; nothing to do."
  exit 0
fi

version=$(json_field version "$MANIFEST_FILE")
archive=$(json_field artifact_url "$MANIFEST_FILE")
if [ -z "$archive" ]; then
  archive=$(json_field archive "$MANIFEST_FILE")
fi
sha256=$(json_field sha256 "$MANIFEST_FILE")

if [ -z "$version" ] || [ -z "$archive" ] || [ -z "$sha256" ]; then
  printf '%s\n' "update manifest must include version, artifact_url/archive, and sha256" >&2
  exit 1
fi

tmp_dir=$(mktemp -d)
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

case "$archive" in
  http://*|https://*)
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL "$archive" -o "$tmp_dir/porchlight.tar.gz"
    else
      printf '%s\n' "curl is required for remote update archives" >&2
      exit 1
    fi
    ;;
  *)
    cp "$archive" "$tmp_dir/porchlight.tar.gz"
    ;;
esac

if command -v sha256sum >/dev/null 2>&1; then
  actual=$(sha256sum "$tmp_dir/porchlight.tar.gz" | awk '{print $1}')
else
  actual=$(shasum -a 256 "$tmp_dir/porchlight.tar.gz" | awk '{print $1}')
fi
if [ "$actual" != "$sha256" ]; then
  printf '%s\n' "sha256 mismatch: expected $sha256 got $actual" >&2
  exit 1
fi

previous=""
if [ -L "$CURRENT_LINK" ] || [ -e "$CURRENT_LINK" ]; then
  previous=$(readlink "$CURRENT_LINK" || true)
fi

tar -xzf "$tmp_dir/porchlight.tar.gz" -C "$tmp_dir"
release_root="$tmp_dir/porchlight-$version"
if [ ! -d "$release_root" ]; then
  printf '%s\n' "archive must contain porchlight-$version/" >&2
  exit 1
fi

MUSTER_ROOT="" "$release_root/bin/install.sh"

if ! /opt/$PROJECT/current/bin/doctor.sh; then
  if [ -n "$previous" ]; then
    ln -sfn "$previous" "$CURRENT_LINK"
  fi
  printf '%s\n' "update failed health check; rolled back" >&2
  exit 1
fi

printf 'updated %s to %s\n' "$PROJECT" "$version"
