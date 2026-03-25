#!/bin/bash
#
# CAM - Collective Agent Memory
# One-line installer: curl -fsSL https://raw.githubusercontent.com/julianfleck/collective-agent-memory/main/install.sh | bash
#
# Options:
#   -v    Verbose output (show full pip/uv output)
#
set -e

REPO="julianfleck/collective-agent-memory"
VERBOSE=false

# Parse arguments
while getopts "v" opt; do
    case $opt in
        v) VERBOSE=true ;;
        *) ;;
    esac
done

echo "CAM - Collective Agent Memory"
echo "============================="
echo

# Check for HF_TOKEN
if [ -z "$HF_TOKEN" ] && [ -z "$HUGGING_FACE_HUB_TOKEN" ]; then
    echo "[tip] Set HF_TOKEN for faster model downloads:"
    echo "      export HF_TOKEN=hf_xxx"
    echo "      (Get token from huggingface.co/settings/tokens)"
    echo
fi

# =============================================================================
# Dependency checks
# =============================================================================

check_python() {
    if command -v python3 &>/dev/null; then
        PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

        if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
            echo "[ok] Python $PY_VERSION"
            return 0
        fi
    fi

    echo "[error] Python 3.10+ required"
    exit 1
}

check_git() {
    if command -v git &>/dev/null; then
        echo "[ok] git"
        return 0
    fi
    echo "[error] git required"
    exit 1
}

# =============================================================================
# Installation
# =============================================================================

install_cam() {
    echo
    echo "Installing CAM..."

    local GIT_URL="git+https://github.com/$REPO.git"

    if $VERBOSE; then
        # Verbose: show full output
        if command -v uv &>/dev/null; then
            echo "[info] Using uv"
            uv tool install --force "$GIT_URL"
        elif command -v pipx &>/dev/null; then
            echo "[info] Using pipx"
            pipx install --force "$GIT_URL"
        elif command -v pip3 &>/dev/null; then
            echo "[info] Using pip3"
            pip3 install --user --force-reinstall --no-cache-dir "$GIT_URL"
        else
            echo "[info] Using pip"
            pip install --user --force-reinstall --no-cache-dir "$GIT_URL"
        fi
    else
        # Quiet: show only last few lines
        if command -v uv &>/dev/null; then
            uv tool install --force "$GIT_URL" 2>&1 | tail -3
        elif command -v pipx &>/dev/null; then
            pipx install --force "$GIT_URL" 2>&1 | tail -3
        elif command -v pip3 &>/dev/null; then
            pip3 install --user --force-reinstall --no-cache-dir --quiet "$GIT_URL" 2>&1 | tail -3
        else
            pip install --user --force-reinstall --no-cache-dir --quiet "$GIT_URL" 2>&1 | tail -3
        fi
    fi

    # Show installed version
    local CAM_VERSION
    CAM_VERSION=$(cam --version 2>/dev/null || echo "unknown")
    echo "[ok] CAM $CAM_VERSION installed"
}

# =============================================================================
# Main
# =============================================================================

main() {
    # Check dependencies
    check_python
    check_git

    # Install CAM
    install_cam

    # Find cam binary
    CAM_BIN=$(which cam 2>/dev/null || echo "$HOME/.local/bin/cam")

    if [ ! -x "$CAM_BIN" ]; then
        echo
        echo "[warning] cam not found in PATH"
        echo "Add to your shell profile:"
        echo '  export PATH="$HOME/.local/bin:$PATH"'
        echo
        echo "Then run: cam init"
        exit 0
    fi

    # Run interactive setup (or non-interactive if piped)
    echo
    if [ -t 0 ]; then
        "$CAM_BIN" init
    else
        # Stdin is not a terminal (curl | bash), use defaults
        "$CAM_BIN" init -y
    fi
}

main "$@"
