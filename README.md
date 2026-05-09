# CuotiPilot

一个面向行测备考的本地错题本应用。它把错题录入、截图 OCR、艾宾浩斯复习、弱点统计和 Anki 导出放在同一个轻量工具里，适合日常刷题后快速沉淀错题。

> 推荐仓库名：`CuotiPilot`

## 功能亮点

- **桌面 / 浏览器双模式**：可直接运行本地 Web UI，也可通过 PyInstaller 打包为 Windows 可执行文件。
- **手动录入错题**：支持科目、错误原因、题干、答案、解析、来源和标签。
- **截图 OCR 导入**：支持选择图片文件，也支持直接粘贴剪贴板图片。
- **双 OCR 模式**：
  - Claude 视觉模式：图片直接交给 Claude Vision 识别并整理字段。
  - 本地 OCR + DeepSeek 模式：先用本地 OCR 提取文字，再由 DeepSeek 整理为结构化错题。
- **艾宾浩斯复习调度**：按 `1 -> 2 -> 4 -> 7 -> 15 -> 30 -> 60` 天安排复习。
- **今日待复习**：自动列出到期和逾期错题。
- **错题库筛选**：按科目、错误原因、标签和关键词检索。
- **数据统计**：查看总错题数、今日待复习、已记熟、本周新增、模块分布和错误原因分布。
- **导出能力**：CLI 支持 Markdown 导出和 Anki `.apkg` 牌组导出。
- **本地数据优先**：题库默认保存在本地 SQLite 数据库 `cuoti.db`。

## 项目预览

核心页面包括：

- 今日任务：集中处理当天需要复习的错题。
- 错题库：筛选、搜索和查看历史错题。
- 添加错题：手动输入或截图 OCR 导入。
- 数据统计：查看错题分布和复习进度。

截图 OCR 导入支持两种方式：

1. 选择本地图片文件。
2. 截图后直接在 OCR 页面粘贴图片。

识别完成后，系统会自动把题干、答案、解析、来源、科目和标签填入表单。用户确认并选择错误原因后再保存入库。

## 目录结构

```text
.
├── app.py              # 桌面 / 浏览器 UI 后端入口
├── cuoti.py            # CLI 入口、OCR 逻辑、导出逻辑
├── ui/
│   └── index.html      # 单页前端界面
├── requirements.txt    # 基础依赖说明
├── cuoti.spec          # PyInstaller 打包配置
├── build.ps1           # Windows PowerShell 打包脚本
├── build.bat           # Windows 批处理打包脚本
├── build.sh            # macOS / Linux 打包脚本
└── cuoti.db            # 本地 SQLite 数据库
```

## 环境要求

- Python 3.10+
- Windows / macOS / Linux
- 可选：Anthropic API Key
- 可选：DeepSeek API Key
- 可选：本地 OCR 依赖 `rapidocr-onnxruntime` 或 `paddleocr`

## 安装

克隆仓库后进入项目目录：

```bash
git clone https://github.com/your-name/CuotiPilot.git
cd CuotiPilot
```

安装基础依赖：

```bash
python -m pip install -r requirements.txt
```

如果要使用 DeepSeek OCR 模式，推荐额外安装轻量本地 OCR：

```bash
python -m pip install rapidocr-onnxruntime
```

也可以选择 PaddleOCR：

```bash
python -m pip install paddleocr
```

## 运行应用

推荐浏览器模式：

```bash
python app.py --browser
```

应用启动后会打开本地地址：

```text
http://localhost:7417
```

如果端口被占用，程序会自动选择空闲端口。

也可以直接运行：

```bash
python app.py
```

在安装了 `pywebview` 的环境中，程序会尝试以桌面窗口方式打开。

## OCR 配置

### Claude 视觉模式

Claude 视觉模式会把图片直接发送给 Anthropic API，由 Claude 完成图片识别和字段整理。

PowerShell：

```powershell
$env:ANTHROPIC_API_KEY="sk-ant-..."
python app.py --browser
```

持久保存到当前 Windows 用户环境变量：

```powershell
[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "sk-ant-...", "User")
```

### 本地 OCR + DeepSeek 模式

DeepSeek 当前用于整理 OCR 文本，不直接识别图片。流程是：

```text
图片 -> 本地 OCR -> 题目文本 -> DeepSeek -> 结构化错题字段
```

PowerShell：

```powershell
python -m pip install rapidocr-onnxruntime
$env:DEEPSEEK_API_KEY="sk-..."
python app.py --browser
```

持久保存到当前 Windows 用户环境变量：

```powershell
[Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "sk-...", "User")
```

### UI 中使用 OCR

1. 打开应用。
2. 进入 `添加错题`。
3. 切换到 `截图 OCR 导入`。
4. 选择识别模式：
   - `自动选择`
   - `Claude 视觉`
   - `本地 OCR + DeepSeek`
5. 选择图片文件，或截图后直接粘贴图片。
6. 点击 `识别并填入表单`。
7. 核对识别结果，选择错误原因。
8. 保存错题。

## CLI 用法

除了图形界面，项目也保留了命令行入口：

```bash
python cuoti.py --help
```

常用命令：

```bash
python cuoti.py add
python cuoti.py list
python cuoti.py due
python cuoti.py stats
python cuoti.py export
python cuoti.py anki
```

命令行 OCR：

```bash
python cuoti.py ocr screenshot.png
python cuoti.py ocr screenshot.png --provider deepseek
```

导出 Anki：

```bash
python cuoti.py anki
python cuoti.py anki -m 数量关系
python cuoti.py anki -t 主旨题
python cuoti.py anki -o my_deck.apkg
```

## 打包

Windows PowerShell：

```powershell
.\build.ps1
```

Windows CMD：

```bat
build.bat
```

macOS / Linux：

```bash
bash build.sh
```

打包产物默认生成在 `dist/` 目录。

## 数据说明

默认数据库文件为：

```text
cuoti.db
```

开发模式下，数据库位于项目根目录。

打包为 exe 后，数据库位于 exe 同级目录，便于用户迁移和备份。

建议定期备份 `cuoti.db`。

## 上传 GitHub 前建议

建议不要上传这些文件：

```text
__pycache__/
build/
dist/
*.pyc
```

如果 `cuoti.db` 中已经有个人错题数据，也建议不要公开上传。

不要把 API Key 写入代码或提交到仓库。推荐使用环境变量：

```text
ANTHROPIC_API_KEY
DEEPSEEK_API_KEY
```

## 常见问题

### DeepSeek API Key 可以直接识别图片吗？

当前实现中不直接把图片发给 DeepSeek。DeepSeek 模式使用本地 OCR 先提取图片文字，再调用 DeepSeek 整理字段。

### 为什么 OCR 识别后还要手动确认？

错题截图的排版、答案标记、解析区域可能不稳定。应用选择先填入表单，再由用户确认保存，避免错误数据直接入库。

### PaddleOCR 安装失败怎么办？

可以使用更轻量的 RapidOCR：

```bash
python -m pip install rapidocr-onnxruntime
```

当前代码会优先尝试 PaddleOCR；如果未安装 PaddleOCR，会自动回退到 RapidOCR。

### 端口 7417 被占用怎么办？

程序会自动寻找空闲端口。前端 API 地址会跟随当前页面地址，不需要手动修改。

## 许可证

如果计划开源，建议补充一个许可证文件，例如 MIT License。

