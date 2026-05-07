#!/bin/bash
set -e  # Exit immediately if a command exits with a non-zero status

# Config
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_VERSION="3.13"
REQUIREMENTS_FILE="$ROOT_DIR/requirements.txt"

# Detect Python 3.13
PYTHON_BIN=""
if command -v "python${PYTHON_VERSION}" >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v "python${PYTHON_VERSION}")"
elif command -v "python3.${PYTHON_VERSION#3.}" >/dev/null 2>&1; then
    # Same as python3.13 when PYTHON_VERSION=3.13
    PYTHON_BIN="$(command -v "python3.${PYTHON_VERSION#3.}")"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "Python ${PYTHON_VERSION} not found."
    echo "On Raspberry Pi OS, install it (if available) and venv support, e.g.:"
    echo "  sudo apt update && sudo apt install -y python${PYTHON_VERSION} python${PYTHON_VERSION}-venv"
    exit 1
fi

PYVER="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [ "$PYVER" != "$PYTHON_VERSION" ]; then
    echo "Expected Python ${PYTHON_VERSION}, but found ${PYVER} at: ${PYTHON_BIN}"
    echo "Please install/use Python ${PYTHON_VERSION} (python${PYTHON_VERSION}) on this machine."
    exit 1
fi
echo "Using Python ${PYTHON_VERSION} at: $PYTHON_BIN"

# Create virtual environment (if needed)
if [ -d "$VENV_DIR" ]; then
    echo "Virtual environment already exists at $VENV_DIR (skipping creation)"
else
    echo "Creating virtual environment at $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# Detect OS type for activation path
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    ACTIVATE_SCRIPT="$VENV_DIR/Scripts/activate"
else
    ACTIVATE_SCRIPT="$VENV_DIR/bin/activate"
fi

if [ ! -f "$ACTIVATE_SCRIPT" ]; then
    echo "Activation script not found at $ACTIVATE_SCRIPT"
    exit 1
fi

# Activate environment
source "$ACTIVATE_SCRIPT"

# Upgrade pip & install requirements
echo "Upgrading pip..."
python -m pip install --upgrade pip setuptools wheel

if [ -f "$REQUIREMENTS_FILE" ]; then
    echo "Installing packages from $REQUIREMENTS_FILE"
    pip install -r "$REQUIREMENTS_FILE"
else
    echo "No requirements.txt found at $REQUIREMENTS_FILE"
fi

# Summary
echo ""
echo "Done"