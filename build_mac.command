#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "请在 macOS 上运行这个脚本。"
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv-mac-build}"
DIST_DIR="${DIST_DIR:-dist_mac}"
BUILD_DIR="${BUILD_DIR:-build_mac}"
APP_NAME="${APP_NAME:-douban_record_export_mac}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "未找到 ${PYTHON_BIN}，请先安装 Python 3。"
  exit 1
fi

"$PYTHON_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  app.py

APP_PATH="$(pwd)/${DIST_DIR}/${APP_NAME}.app"
echo ""
echo "构建完成：${APP_PATH}"
open "$DIST_DIR"
