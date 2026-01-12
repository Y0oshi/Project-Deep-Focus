#!/bin/bash

# Deep Focus Automated Installer
# Handles Virtual Environment and Dependencies automatically.

echo "   ___                  _____                   "
echo "  / _ \___ ___ ___     / __/___________ __ ___ "
echo " / // / -_) -_) _ \   / _// _ \/ __/ // (_-< "
echo "/____/\__/\__/ .__/  /_/  \___/\__/\_,_/___/ "
echo "            /_/                              "
echo ""
echo "[*] Deep Focus Installer initializing..."

# 1. Check Python
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
else
    echo "[!] Python 3 not found. Please install Python 3.8+."
    exit 1
fi

# 2. Setup Virtual Environment
if [ -d "venv" ]; then
    echo "[*] Virtual environment already exists."
else
    echo "[*] Creating virtual environment (venv)..."
    $PYTHON_CMD -m venv venv
fi

# 3. Activate and Install
echo "[*] Installing dependencies..."
source venv/bin/activate

# Direct installation (Modern approach, no requirements.txt needed)
pip install rich aiosqlite --upgrade

# 4. Create Launcher
echo "[*] Creating launcher..."
LAUNCHER="deepfocus"
cat > "$LAUNCHER" << 'EOF'
#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"
source "venv/bin/activate"
python3 "deep_focus.py" "$@"
EOF

chmod +x "$LAUNCHER"

# 5. Global Install
echo "[*] Attempting global installation..."
LINK_NAME="/usr/local/bin/deepfocus"
if ln -sf "$PWD/$LAUNCHER" "$LINK_NAME" 2>/dev/null; then
    echo "[+] Linked to $LINK_NAME"
else
    echo "[!] Could not write to /usr/local/bin (Permission denied)."
    echo "[*] Trying with sudo..."
    sudo ln -sf "$PWD/$LAUNCHER" "$LINK_NAME"
    if [ $? -eq 0 ]; then
        echo "[+] Successfully linked to $LINK_NAME"
    else
        echo "[!] Sudo failed. You can run locally with ./$LAUNCHER"
    fi
fi

echo ""
echo "[+] Installation Complete!"
echo "[+] You can now run Deep Focus by typing: deepfocus"
echo ""
