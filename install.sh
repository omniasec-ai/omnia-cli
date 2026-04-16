#!/usr/bin/env bash
set -euo pipefail

REPO="omniasec-ai/omnia-cli"
BINARY_NAME="omnia"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"

# ── Detect OS and architecture ────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Linux)  os="linux" ;;
  Darwin) os="macos" ;;
  *)
    echo "Unsupported OS: $OS"
    exit 1
    ;;
esac

case "$ARCH" in
  x86_64)          arch="amd64" ;;
  arm64 | aarch64) arch="arm64" ;;
  *)
    echo "Unsupported architecture: $ARCH"
    exit 1
    ;;
esac

ASSET="${BINARY_NAME}-${os}-${arch}"

# ── Auth header (optional, needed for private repos) ─────────────────────────
AUTH_HEADER=""
if [ -n "${GITHUB_TOKEN:-}" ]; then
  AUTH_HEADER="Authorization: token ${GITHUB_TOKEN}"
fi

_curl() {
  if [ -n "$AUTH_HEADER" ]; then
    curl -fsSL -H "$AUTH_HEADER" "$@"
  else
    curl -fsSL "$@"
  fi
}

# ── Resolve latest release tag ────────────────────────────────────────────────
echo "Fetching latest release..."
TAG=$(_curl "https://api.github.com/repos/${REPO}/releases/latest" \
  | grep '"tag_name"' \
  | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')

if [ -z "$TAG" ]; then
  echo "Could not determine latest release tag."
  exit 1
fi

echo "Latest version: $TAG"

DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${TAG}/${ASSET}"

# ── Download ──────────────────────────────────────────────────────────────────
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "Downloading $ASSET..."
ASSET_ID=$(_curl "https://api.github.com/repos/${REPO}/releases/latest" \
  | grep -A1 "\"${ASSET}\"" | grep '"id"' | grep -o '[0-9]*' | head -1)

if [ -n "$ASSET_ID" ] && [ -n "$AUTH_HEADER" ]; then
  curl -fsSL -L -H "$AUTH_HEADER" -H "Accept: application/octet-stream" \
    "https://api.github.com/repos/${REPO}/releases/assets/${ASSET_ID}" \
    -o "$TMP_DIR/$BINARY_NAME"
else
  curl -fsSL -L "$DOWNLOAD_URL" -o "$TMP_DIR/$BINARY_NAME"
fi
chmod +x "$TMP_DIR/$BINARY_NAME"

# ── Install ───────────────────────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR"
mv "$TMP_DIR/$BINARY_NAME" "$INSTALL_DIR/$BINARY_NAME"

echo ""
echo "omnia installed to $INSTALL_DIR/$BINARY_NAME"

# ── PATH ──────────────────────────────────────────────────────────────────────
if ! echo "$PATH" | grep -q "$INSTALL_DIR"; then
  SHELL_RC=""
  if [ -n "${ZSH_VERSION:-}" ] || [ "$(basename "${SHELL:-}")" = "zsh" ]; then
    SHELL_RC="$HOME/.zshrc"
  elif [ -n "${BASH_VERSION:-}" ] || [ "$(basename "${SHELL:-}")" = "bash" ]; then
    SHELL_RC="$HOME/.bashrc"
  fi

  if [ -n "$SHELL_RC" ]; then
    echo "" >> "$SHELL_RC"
    echo "export PATH=\"$INSTALL_DIR:\$PATH\"" >> "$SHELL_RC"
    export PATH="$INSTALL_DIR:$PATH"
    echo "Added $INSTALL_DIR to PATH in $SHELL_RC"
  fi
fi

echo ""
exec "$INSTALL_DIR/$BINARY_NAME"
