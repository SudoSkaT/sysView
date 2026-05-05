#!/usr/bin/env bash
# sysview install script
# Installs sysview to /usr/local/bin/sysview (or ~/bin/sysview without root)
# Supports: Linux, macOS, WSL

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRY="$SCRIPT_DIR/main.py"
MIN_PYTHON_MINOR=10

# ── Checks ────────────────────────────────────────────────────────────────────

check_python() {
    local py
    for candidate in python3 python; do
        if command -v "$candidate" &>/dev/null; then
            local ver
            ver=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
            if [[ "$ver" -ge "$MIN_PYTHON_MINOR" ]]; then
                echo "$candidate"
                return
            fi
        fi
    done
    echo "ERROR: Python 3.${MIN_PYTHON_MINOR}+ not found." >&2
    exit 1
}

check_psutil() {
    local py="$1"
    if ! "$py" -c "import psutil" &>/dev/null; then
        echo "psutil not found. Attempting installation..."
        "$py" -m pip install --quiet psutil || {
            echo "ERROR: Could not install psutil. Run: pip install psutil" >&2
            exit 1
        }
    fi
}

# ── Install ───────────────────────────────────────────────────────────────────

PY=$(check_python)
echo "Python: $($PY --version)"
check_psutil "$PY"
echo "psutil: OK"

# Determine install directory
if [[ $EUID -eq 0 ]]; then
    INSTALL_DIR="/usr/local/bin"
else
    INSTALL_DIR="$HOME/.local/bin"
    mkdir -p "$INSTALL_DIR"
fi

WRAPPER="$INSTALL_DIR/sysview"

cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
exec $PY $ENTRY "\$@"
EOF

chmod +x "$WRAPPER"

echo ""
echo "Installed: $WRAPPER"
echo ""
echo "Usage:"
echo "  sysview                  # interactive TUI"
echo "  sysview --cli            # one-shot snapshot"
echo "  sysview --free           # memory relief"
echo "  sysview --help           # all options"

# Warn if install dir is not in PATH
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo ""
    echo "NOTE: $INSTALL_DIR is not in your PATH."
    echo "Add this to your shell profile:"
    echo "  export PATH=\"$INSTALL_DIR:\$PATH\""
fi