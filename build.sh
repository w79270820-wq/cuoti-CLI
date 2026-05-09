#!/bin/bash
# build.sh — macOS / Linux 打包脚本
set -e

echo "================================================"
echo "  错题本 打包脚本  cuoti v3.0"
echo "================================================"

# ── 检查 Python ────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[错误] 未找到 python3"
    exit 1
fi
echo "[1/4] Python 检测通过: $(python3 --version)"

# ── 安装 PyInstaller ─────────────────────────────────────────────────────────
echo "[2/4] 安装 PyInstaller..."
pip3 install pyinstaller --quiet
echo "      PyInstaller 就绪"

# ── 检查文件 ─────────────────────────────────────────────────────────────────
[ -f "app.py" ]         || { echo "[错误] 找不到 app.py"; exit 1; }
[ -f "ui/index.html" ]  || { echo "[错误] 找不到 ui/index.html"; exit 1; }
echo "[3/4] 文件检查通过"

# ── 打包 ──────────────────────────────────────────────────────────────────────
echo "[4/4] 开始打包..."

if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS: 生成 .app bundle
    pyinstaller cuoti.spec --clean --noconfirm
    echo ""
    echo "================================================"
    echo "  打包成功！"
    echo "  App 位置: dist/错题本"
    echo "================================================"
else
    # Linux
    pyinstaller cuoti.spec --clean --noconfirm
    echo ""
    echo "================================================"
    echo "  打包成功！"
    echo "  exe 位置: dist/错题本"
    echo "================================================"
fi
