#!/usr/bin/env bash
# install.sh — Install tg-send, tg-bot, and ai-review onto your PATH
#
# Usage:
#   ./install.sh                # symlink to ~/bin (created if needed)
#   ./install.sh /usr/local/bin # symlink to a specific directory
#   ./install.sh --uninstall    # remove symlinks
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$SCRIPT_DIR/bin"
TARGET="${1:-$HOME/bin}"

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

TOOLS=(tg-send tg-bot ai-review)

if [[ "${1:-}" == "--uninstall" ]]; then
    echo -e "${YELLOW}Uninstalling...${NC}"
    for tool in "${TOOLS[@]}"; do
        for dir in "$HOME/bin" "/usr/local/bin"; do
            if [[ -L "$dir/$tool" ]]; then
                rm "$dir/$tool"
                echo -e "  ${GREEN}Removed${NC} $dir/$tool"
            fi
        done
    done
    echo "Done."
    exit 0
fi

# Make scripts executable
chmod +x "$BIN_DIR"/*

# Create target dir if needed
if [[ ! -d "$TARGET" ]]; then
    echo -e "${YELLOW}Creating $TARGET${NC}"
    mkdir -p "$TARGET"
fi

# Check if target is on PATH
if [[ ":$PATH:" != *":$TARGET:"* ]]; then
    echo -e "${YELLOW}Warning: $TARGET is not on your PATH${NC}"
    echo "  Add this to your ~/.zshrc or ~/.bashrc:"
    echo "    export PATH=\"$TARGET:\$PATH\""
    echo ""
fi

# Bootstrap venvs
echo "Bootstrapping environments..."

# telegram_harness venv
if [[ ! -f "$SCRIPT_DIR/.venv/bin/tg-send" ]]; then
    echo "  Installing telegram-harness..."
    python3 -m venv "$SCRIPT_DIR/.venv"
    "$SCRIPT_DIR/.venv/bin/pip" install --quiet --upgrade pip
    "$SCRIPT_DIR/.venv/bin/pip" install --quiet -e "$SCRIPT_DIR"
fi

# review_tool venv (if available)
REVIEW_DIR="$SCRIPT_DIR/../review_tool"
if [[ -d "$REVIEW_DIR" && ! -f "$REVIEW_DIR/.venv/bin/review-tool" ]]; then
    echo "  Installing review-tool..."
    python3 -m venv "$REVIEW_DIR/.venv"
    "$REVIEW_DIR/.venv/bin/pip" install --quiet --upgrade pip
    "$REVIEW_DIR/.venv/bin/pip" install --quiet -e "$REVIEW_DIR"
fi

# Create symlinks
echo ""
echo "Installing to $TARGET:"
for tool in "${TOOLS[@]}"; do
    src="$BIN_DIR/$tool"
    dest="$TARGET/$tool"

    if [[ ! -f "$src" ]]; then
        continue
    fi

    # Skip ai-review if review_tool isn't available
    if [[ "$tool" == "ai-review" && ! -d "$REVIEW_DIR" ]]; then
        echo -e "  ${YELLOW}Skipped${NC} $tool (review_tool not found at $REVIEW_DIR)"
        continue
    fi

    if [[ -e "$dest" || -L "$dest" ]]; then
        rm "$dest"
    fi

    ln -s "$src" "$dest"
    echo -e "  ${GREEN}Installed${NC} $tool → $dest"
done

echo ""
echo -e "${GREEN}Done!${NC} You can now run from anywhere:"
echo ""
echo "  tg-send \"Hello from any directory\""
echo "  ai-review https://github.com/owner/repo/pull/42"
echo "  tg-bot start"
echo ""
echo "  Uninstall: ./install.sh --uninstall"
