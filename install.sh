#!/bin/bash
#
# CAM - Collective Agent Memory
# One-line installer: curl -fsSL https://raw.githubusercontent.com/julianfleck/collective-agent-memory/main/install.sh | bash
#
set -e

REPO="julianfleck/collective-agent-memory"

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

    if command -v uv &>/dev/null; then
        uv tool install --force "git+https://github.com/$REPO.git" 2>&1 | tail -3
    elif command -v pipx &>/dev/null; then
        pipx install --force "git+https://github.com/$REPO.git" 2>&1 | tail -3
    elif command -v pip3 &>/dev/null; then
        pip3 install --user --force-reinstall --quiet "git+https://github.com/$REPO.git" 2>&1 | tail -3
    else
        pip install --user --force-reinstall --quiet "git+https://github.com/$REPO.git" 2>&1 | tail -3
    fi

    echo "[ok] CAM installed"
}

install_qmd() {
    if command -v qmd &>/dev/null; then
        echo "[ok] qmd already installed"
        return 0
    fi

    echo "Installing qmd..."
    if command -v npm &>/dev/null; then
        npm install -g @tobilu/qmd 2>&1 | tail -2
    elif command -v bun &>/dev/null; then
        bun install -g @tobilu/qmd 2>&1 | tail -2
    else
        echo "[--] npm/bun not found, skipping qmd"
        echo "     Install Node.js from: https://nodejs.org/"
        return 1
    fi
    echo "[ok] qmd installed"
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

    # Install qmd (optional)
    if command -v npm &>/dev/null || command -v bun &>/dev/null; then
        install_qmd
    else
        echo
        echo "[--] npm/bun not found (qmd search engine won't be installed)"
        echo "     Install Node.js from: https://nodejs.org/"
    fi

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
