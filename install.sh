#!/usr/bin/env bash
# NoLabel - Automated macOS Corner Label & Watermark Removal
# Installation Script

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"

echo "=========================================="
echo " NoLabel Installation"
echo "=========================================="
echo "Installing from: $REPO_DIR"

# 1. Hardware Checks
echo "[*] Verifying Hardware Requirements..."

ARCH=$(uname -m)
if [ "$ARCH" != "arm64" ]; then
    echo "[!] Error: NoLabel requires an Apple Silicon (M-series) Mac."
    echo "    Intel Macs and other hardware are not supported."
    exit 1
fi

MEM_BYTES=$(sysctl -n hw.memsize)
MEM_GB=$((MEM_BYTES / 1024 / 1024 / 1024))
if [ "$MEM_GB" -lt 8 ]; then
    echo "[!] Error: NoLabel requires a minimum of 8GB RAM. Detected: ${MEM_GB}GB."
    exit 1
fi
echo "[✓] Hardware checks passed: Apple Silicon with ${MEM_GB}GB RAM."

# 2. Check Dependencies
if ! command -v python3 &> /dev/null; then
    echo "[!] python3 is required. Please install it (e.g. brew install python3)."
    exit 1
fi

if ! command -v swiftc &> /dev/null; then
    echo "[!] swiftc (Xcode Command Line Tools) is required."
    echo "[!] Run: xcode-select --install"
    exit 1
fi

# 3. Setup Python Virtual Environment
echo "[*] Setting up Python virtual environment..."
cd "$REPO_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
echo "[*] Installing Python dependencies..."
pip install -r requirements.txt

# 4. Compile Swift Vision Tool
echo "[*] Compiling Swift Vision binary (macOS native)..."
swiftc -O -o bin/nolabel_vision scripts/nolabel_vision.swift -framework Vision -framework CoreImage -framework Foundation
echo "[✓] Swift compilation successful."

# 5. Link CLI Tool
echo "[*] Linking CLI tool to $BIN_DIR..."
mkdir -p "$BIN_DIR"
ln -sf "$REPO_DIR/bin/nolabel" "$BIN_DIR/nolabel"
chmod +x "$REPO_DIR/bin/nolabel"

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "[!] Note: $BIN_DIR is not in your PATH."
    echo "    Consider adding it to your ~/.zshrc or ~/.bash_profile:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# 6. Setup Quick Action (Finder Service)
echo "[*] Installing macOS Quick Action..."
SERVICES_DIR="$HOME/Library/Services"
mkdir -p "$SERVICES_DIR"
# Remove existing if any
rm -rf "$SERVICES_DIR/Remove Corner Label.workflow"
cp -R "$REPO_DIR/quick_action/Remove Corner Label.workflow" "$SERVICES_DIR/"
# Note: Finder might take a few seconds to pick up the new Quick Action.
echo "[✓] Quick Action installed."

# 7. Install Launchd Service (Folder Watcher)
echo "[*] Installing background Folder Watcher daemon..."
"$BIN_DIR/nolabel" install-service

echo ""
echo "=========================================="
echo " Installation Complete! "
echo "=========================================="
echo ""
echo "Quick Action: Right-click any PDF, PNG, JPG, Keynote, or PPTX -> Quick Actions -> Remove Corner Label"
echo "Folder Watcher: Drop files into ~/Documents/Label-Cleaner and they will be auto-processed."
echo "CLI Usage: nolabel process <file.pdf>"
echo ""
echo "Try running 'nolabel status' to verify everything is running!"
