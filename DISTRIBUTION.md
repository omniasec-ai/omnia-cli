# Distribution

Goal: ship a self-contained binary so users can install with:

```bash
curl https://cli.omniasec.ai | bash
```

No Python, no pip, no Docker required.

---

## How it works

Use **PyInstaller** to compile the CLI into a single executable that embeds the Python runtime:

```bash
pyinstaller --onefile --name omnia omnia/cli.py
# → dist/omnia  (~15-30 MB, no dependencies)
```

Publish one binary per platform:
- `omnia-linux-amd64`
- `omnia-linux-arm64`
- `omnia-darwin-amd64`
- `omnia-darwin-arm64`

Host them at `https://cli.omniasec.ai/releases/<version>/omnia-<os>-<arch>`.

---

## install.sh

```bash
#!/usr/bin/env bash
set -euo pipefail

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
VERSION="${OMNIA_VERSION:-latest}"
BASE="https://cli.omniasec.ai/releases"

[ "$ARCH" = "x86_64" ]  && ARCH="amd64"
[ "$ARCH" = "aarch64" ] && ARCH="arm64"

URL="$BASE/$VERSION/omnia-$OS-$ARCH"

echo "Installing omnia CLI ($OS/$ARCH)..."
curl -fsSL "$URL" -o /usr/local/bin/omnia
chmod +x /usr/local/bin/omnia
echo "Done. Run: omnia"
```

Host this file at `https://cli.omniasec.ai/install.sh`.

---

## Build pipeline (GitHub Actions)

On every release tag (`v*`), build for all platforms and upload to storage:

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags: ["v*"]

jobs:
  build:
    strategy:
      matrix:
        include:
          - os: ubuntu-latest
            target: linux-amd64
          - os: ubuntu-latest
            target: linux-arm64
            arch: aarch64
          - os: macos-latest
            target: darwin-amd64
          - os: macos-latest
            target: darwin-arm64

    runs-on: ${{ matrix.os }}

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r pyproject.toml pyinstaller

      - name: Build binary
        run: |
          pyinstaller --onefile --name omnia omnia/cli.py
          mv dist/omnia dist/omnia-${{ matrix.target }}

      - name: Upload to release
        uses: softprops/action-gh-release@v2
        with:
          files: dist/omnia-${{ matrix.target }}
```

Then a second job (or a CDN sync step) copies the release assets to the S3/R2 bucket.

---

## Storage layout

```
cli.omniasec.ai/
├── install.sh
└── releases/
    ├── latest/
    │   ├── omnia-linux-amd64
    │   ├── omnia-linux-arm64
    │   ├── omnia-darwin-amd64
    │   └── omnia-darwin-arm64
    └── v1.2.3/
        └── ...
```

`latest/` is a copy of the most recent release, updated after each publish.

---

## PyPI (optional, for Python users)

For users who prefer pip/pipx:

```bash
pipx install omnia-cli
```

Publish with:

```bash
pip install hatch twine
hatch build
twine upload dist/*
```

The `pyproject.toml` is already configured for this.
