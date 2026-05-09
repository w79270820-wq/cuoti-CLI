#!/usr/bin/env python3
"""
cuoti 桌面版 — 行测错题本
依赖: pip install pywebview
用法: python app.py
      python app.py --browser   # 在默认浏览器打开（无需 pywebview）
"""

import sqlite3
import datetime
import os
import sys
import json
import base64
import tempfile
import threading
import webbrowser
import http.server
import urllib.parse
import urllib.error

try:
    from cuoti import (
        SUPPORTED_EXTS,
        call_claude_vision,
        call_deepseek_structurer,
        extract_text_with_paddleocr,
    )
except Exception:
    SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    call_claude_vision = None
    call_deepseek_structurer = None
    extract_text_with_paddleocr = None

# ── 路径解析（兼容开发模式 和 PyInstaller 打包模式）─────────────────────────
# PyInstaller 打包后：
#   sys.frozen = True
#   sys._MEIPASS = 只读 bundle 临时目录（存放 ui/ 等资源）
#   sys.executable = exe 所在目录（可读写，存放 cuoti.db）
if getattr(sys, "frozen", False):
    _BUNDLE_DIR = sys._MEIPASS                           # 资源目录（只读）
    _DATA_DIR   = os.path.dirname(sys.executable)        # exe 同级目录（可读写）
else:
    _BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    _DATA_DIR   = _BUNDLE_DIR

BASE_DIR = _DATA_DIR
DB_FILE  = os.path.join(_DATA_DIR,   "cuoti.db")
UI_FILE  = os.path.join(_BUNDLE_DIR, "ui", "index.html")
REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30, 60]

# ── DB ─────────────────────────────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            module        TEXT NOT NULL,
            error_type    TEXT NOT NULL,
            tags          TEXT DEFAULT '',
            content       TEXT NOT NULL,
            wrong_ans     TEXT DEFAULT '',
            right_ans     TEXT DEFAULT '',
            analysis      TEXT DEFAULT '',
            source        TEXT DEFAULT '',
            reviewed      INTEGER DEFAULT 0,
            created_at    TEXT NOT NULL,
            review_count  INTEGER DEFAULT 0,
            last_reviewed TEXT DEFAULT NULL,
            next_review   TEXT DEFAULT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS review_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            reviewed_at TEXT NOT NULL,
            rating      TEXT NOT NULL,
            interval    INTEGER NOT NULL
        )
    """)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(questions)")}
    for col, defn in [
        ("review_count",  "INTEGER DEFAULT 0"),
        ("last_reviewed", "TEXT DEFAULT NULL"),
        ("next_review",   "TEXT DEFAULT NULL"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {col} {defn}")
    conn.commit()
    return conn

def today():
    return datetime.date.today().isoformat()

def row_dict(row):
    return {k: row[k] for k in row.keys()}

# ── Python API（暴露给 JavaScript）─────────────────────────────────────────
class CuotiAPI:

    def get_questions(self, filters=None):
        filters = filters or {}
        conn  = get_conn()
        query = "SELECT * FROM questions WHERE 1=1"
        params = []
        if filters.get("module"):
            query += " AND module=?"; params.append(filters["module"])
        if filters.get("error_type"):
            query += " AND error_type=?"; params.append(filters["error_type"])
        if filters.get("tag"):
            query += " AND tags LIKE ?"; params.append(f"%{filters['tag']}%")
        if filters.get("unreviewed"):
            query += " AND (reviewed=0 OR next_review IS NOT NULL)"
        if filters.get("due"):
            query += " AND next_review IS NOT NULL AND next_review<=?"; params.append(today())
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [row_dict(r) for r in rows]

    def add_question(self, data):
        conn = get_conn()
        next_review = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        cur = conn.execute("""
            INSERT INTO questions
            (module,error_type,tags,content,wrong_ans,right_ans,analysis,source,
             created_at,review_count,next_review)
            VALUES (?,?,?,?,?,?,?,?,?,0,?)
        """, (
            data.get("module",""), data.get("error_type",""),
            data.get("tags",""),   data.get("content",""),
            data.get("wrong_ans","").upper(), data.get("right_ans","").upper(),
            data.get("analysis",""), data.get("source",""),
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            next_review,
        ))
        new_id = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM questions WHERE id=?", (new_id,)).fetchone()
        conn.close()
        return row_dict(row)

    def recognize_image(self, data):
        """识别截图并返回可写入表单的错题字段。"""
        tmp_path = None
        try:
            provider, api_key = self._resolve_ocr_provider(data or {})
            image_name = (data or {}).get("image_name") or "screenshot.png"
            image_data = (data or {}).get("image_data") or ""
            if not image_data:
                return {"ok": False, "error": "没有收到图片数据"}

            if "," in image_data and image_data.lower().startswith("data:"):
                image_data = image_data.split(",", 1)[1]

            ext = os.path.splitext(image_name)[1].lower() or ".png"
            if ext not in SUPPORTED_EXTS:
                return {"ok": False, "error": f"不支持的图片格式 {ext}，请使用 PNG/JPG/WEBP"}

            try:
                raw = base64.b64decode(image_data)
            except Exception:
                return {"ok": False, "error": "图片数据解析失败，请重新选择截图"}

            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
                f.write(raw)
                tmp_path = f.name

            if provider == "anthropic":
                if call_claude_vision is None:
                    return {"ok": False, "error": "当前程序缺少 Claude Vision OCR 模块"}
                result = call_claude_vision(tmp_path, api_key)
            elif provider == "deepseek":
                if extract_text_with_paddleocr is None or call_deepseek_structurer is None:
                    return {"ok": False, "error": "当前程序缺少本地 OCR + DeepSeek 模块"}
                ocr_text = extract_text_with_paddleocr(tmp_path)
                result = call_deepseek_structurer(ocr_text, api_key)
                result["_ocr_text_length"] = len(ocr_text)
            else:
                return {"ok": False, "error": f"未知 OCR 模式：{provider}"}

            return {"ok": True, "provider": provider, "data": result}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return {"ok": False, "error": f"API 请求失败 {e.code}: {body[:240]}"}
        except urllib.error.URLError as e:
            return {"ok": False, "error": f"网络错误：{e.reason}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _resolve_ocr_provider(self, data):
        provider = data.get("provider") or "auto"
        api_key = (data.get("api_key") or "").strip()

        if provider == "auto":
            if os.environ.get("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif os.environ.get("DEEPSEEK_API_KEY"):
                provider = "deepseek"
            elif api_key:
                provider = "anthropic"
            else:
                raise RuntimeError("请先设置 ANTHROPIC_API_KEY 或 DEEPSEEK_API_KEY，或在界面中选择模式并临时输入 API Key")

        if provider == "anthropic":
            key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
            if not key:
                raise RuntimeError("Claude 视觉模式需要 ANTHROPIC_API_KEY")
        elif provider == "deepseek":
            key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
            if not key:
                raise RuntimeError("DeepSeek 模式需要 DEEPSEEK_API_KEY，并需安装本地 OCR")
        else:
            raise RuntimeError(f"未知 OCR 模式：{provider}")

        return provider, key

    def review_question(self, question_id, rating):
        conn = get_conn()
        row  = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        if not row:
            conn.close(); return None

        new_count = row["review_count"] + 1
        interval  = REVIEW_INTERVALS[min(new_count, len(REVIEW_INTERVALS) - 1)]

        if rating == "完全不会":
            interval = 1; new_count = 0
        elif rating == "模糊记得":
            interval = max(1, interval // 2)
        elif rating == "完全掌握" and new_count > 3:
            interval = int(interval * 1.5)

        now_str    = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        fully_done = new_count >= len(REVIEW_INTERVALS) and rating != "完全不会"
        next_dt    = None if fully_done else (
            datetime.date.today() + datetime.timedelta(days=interval)
        ).isoformat()

        conn.execute("""
            UPDATE questions SET reviewed=1,review_count=?,last_reviewed=?,next_review=?
            WHERE id=?
        """, (new_count, now_str, next_dt, question_id))
        conn.execute(
            "INSERT INTO review_log (question_id,reviewed_at,rating,interval) VALUES (?,?,?,?)",
            (question_id, now_str, rating, interval)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        conn.close()
        return row_dict(row)

    def delete_question(self, question_id):
        conn = get_conn()
        conn.execute("DELETE FROM questions WHERE id=?", (question_id,))
        conn.execute("DELETE FROM review_log WHERE question_id=?", (question_id,))
        conn.commit(); conn.close()
        return True

    def get_stats(self):
        conn = get_conn()
        t = today()
        week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")

        total      = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        memorized  = conn.execute("SELECT COUNT(*) FROM questions WHERE next_review IS NULL AND reviewed=1").fetchone()[0]
        due_count  = conn.execute("SELECT COUNT(*) FROM questions WHERE next_review<=?", (t,)).fetchone()[0]
        overdue    = conn.execute("SELECT COUNT(*) FROM questions WHERE next_review<? AND next_review IS NOT NULL", (t,)).fetchone()[0]
        recent     = conn.execute("SELECT COUNT(*) FROM questions WHERE created_at>=?", (week_ago,)).fetchone()[0]
        rev_total  = conn.execute("SELECT COUNT(*) FROM review_log").fetchone()[0]

        by_module = [
            {"name": r[0], "value": r[1]}
            for r in conn.execute(
                "SELECT module,COUNT(*) n FROM questions GROUP BY module ORDER BY n DESC"
            ).fetchall()
        ]
        by_error = [
            {"name": r[0], "value": r[1]}
            for r in conn.execute(
                "SELECT error_type,COUNT(*) n FROM questions GROUP BY error_type ORDER BY n DESC"
            ).fetchall()
        ]
        review_dist = [
            {"name": f"第{i+1}轮", "value": conn.execute(
                "SELECT COUNT(*) FROM questions WHERE review_count=?", (i,)
            ).fetchone()[0]}
            for i in range(len(REVIEW_INTERVALS))
        ]
        conn.close()
        return {
            "total": total, "memorized": memorized, "due": due_count,
            "overdue": overdue, "recent": recent, "reviews": rev_total,
            "by_module": by_module, "by_error": by_error,
            "review_dist": review_dist,
        }

    def open_in_browser(self):
        """从 pywebview 内触发：在系统默认浏览器也打开当前 UI"""
        webbrowser.open("http://localhost:7417")
        return True

# ── 浏览器模式（--browser 参数）───────────────────────────────────────────
class BrowserHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # 静态文件（ui/index.html）在 _BUNDLE_DIR（PyInstaller 解压目录）
        # 数据库（cuoti.db）在 _DATA_DIR（exe 同级目录）
        super().__init__(*args, directory=_BUNDLE_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "":
            self.path = "/ui/index.html"
        if parsed.path.startswith("/api/"):
            self._handle_api("GET", parsed)
            return
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        self._handle_api("POST", parsed)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        self._handle_api("DELETE", parsed)

    def _handle_api(self, method, parsed):
        api  = CuotiAPI()
        path = parsed.path
        body = {}
        if self.headers.get("Content-Length"):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))

        result = None
        if path == "/api/questions" and method == "GET":
            qs_  = urllib.parse.parse_qs(parsed.query)
            filt = {k: v[0] for k, v in qs_.items()}
            for b in ("unreviewed", "due"):
                filt[b] = filt.get(b) == "true"
            result = api.get_questions(filt)
        elif path == "/api/questions" and method == "POST":
            result = api.add_question(body)
        elif path == "/api/ocr" and method == "POST":
            result = api.recognize_image(body)
        elif path.startswith("/api/questions/") and method == "DELETE":
            qid = int(path.split("/")[-1])
            result = api.delete_question(qid)
        elif path.endswith("/review") and method == "POST":
            qid = int(path.split("/")[-2])
            result = api.review_question(qid, body.get("rating",""))
        elif path == "/api/stats" and method == "GET":
            result = api.get_stats()

        if result is not None:
            payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", len(payload))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *args): pass  # 静音日志

PORT = 7417

def find_free_port():
    """如果 7417 被占用，自动找一个空闲端口"""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def run_browser_mode(silent=False):
    global PORT
    # 尝试默认端口，否则自动换端口
    import socket
    try:
        test = socket.socket()
        test.bind(("127.0.0.1", PORT))
        test.close()
    except OSError:
        PORT = find_free_port()

    server = http.server.HTTPServer(("127.0.0.1", PORT), BrowserHandler)
    url    = f"http://localhost:{PORT}"

    if not silent:
        # 清屏 + 状态面板
        os.system("cls" if sys.platform == "win32" else "clear")
        print("=" * 48)
        print("  错题本  —  行测备考工具  cuoti v3.0")
        print("=" * 48)
        print(f"\n  ✓ 服务已启动")
        print(f"  ✓ 地址：{url}")
        print(f"  ✓ 数据库：{DB_FILE}")
        print(f"\n  浏览器即将自动打开...")
        print(f"\n  关闭此窗口即可退出程序")
        print("-" * 48)

    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  已退出")

# ── 入口 ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    is_frozen = getattr(sys, "frozen", False)

    # exe 双击启动：默认浏览器模式（最可靠，无需 pywebview）
    # 开发模式：传 --browser 强制浏览器模式，否则尝试 pywebview
    if is_frozen or "--browser" in sys.argv or "-b" in sys.argv:
        run_browser_mode()
        sys.exit(0)

    try:
        import webview
    except ImportError:
        print("\n  未找到 pywebview，自动切换到浏览器模式")
        print("  安装原生窗口版：pip install pywebview\n")
        run_browser_mode()
        sys.exit(0)

    if not os.path.exists(UI_FILE):
        print(f"  找不到 UI 文件：{UI_FILE}，切换到浏览器模式")
        run_browser_mode()
        sys.exit(0)

    api    = CuotiAPI()
    window = webview.create_window(
        "错题本 — 行测备考",
        UI_FILE,
        js_api=api,
        width=980,
        height=720,
        min_size=(800, 600),
        background_color="#ffffff",
    )
    webview.start(debug="--debug" in sys.argv)
