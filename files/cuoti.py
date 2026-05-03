#!/usr/bin/env python3
"""
cuoti — 行测错题本 CLI  v2.0
新增：艾宾浩斯间隔复习 + Anki 牌组导出
用法: python cuoti.py --help
"""

import sqlite3
import argparse
import datetime
import os
import json
import zipfile
import hashlib
import time
import random
import tempfile

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cuoti.db")

MODULES     = ["言语理解", "数量关系", "判断推理", "常识判断", "资料分析"]
ERROR_TYPES = ["粗心大意", "知识盲区", "思路错误", "时间不够"]

# 艾宾浩斯复习间隔（天数），按复习轮次索引
# 规律：1→2→4→7→15→30→60 天
REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30, 60]

# ── ANSI 颜色 ──────────────────────────────────────────────────────────────
RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
RED   = "\033[91m"; GREEN= "\033[92m"; YELLOW="\033[93m"
BLUE  = "\033[94m"; CYAN = "\033[96m"; WHITE ="\033[97m"

def c(text, color): return f"{color}{text}{RESET}"
def bold(text):     return f"{BOLD}{text}{RESET}"
def dim(text):      return f"{DIM}{text}{RESET}"

MODULE_COLORS = {
    "言语理解": BLUE, "数量关系": RED,
    "判断推理": CYAN, "常识判断": GREEN, "资料分析": YELLOW,
}
ERROR_COLORS = {
    "粗心大意": YELLOW, "知识盲区": RED,
    "思路错误": CYAN,   "时间不够": GREEN,
}
RATING_COLORS = {
    "完全掌握": GREEN, "基本掌握": CYAN,
    "模糊记得": YELLOW, "完全不会": RED,
}

# ── 数据库 & 自动迁移 ──────────────────────────────────────────────────────
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
            interval    INTEGER NOT NULL,
            FOREIGN KEY(question_id) REFERENCES questions(id)
        )
    """)

    # 迁移旧数据库：平滑添加新字段
    existing = {row[1] for row in conn.execute("PRAGMA table_info(questions)")}
    for col, defn in [
        ("review_count",  "INTEGER DEFAULT 0"),
        ("last_reviewed", "TEXT DEFAULT NULL"),
        ("next_review",   "TEXT DEFAULT NULL"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {col} {defn}")

    conn.commit()
    return conn

# ── 日期工具 ───────────────────────────────────────────────────────────────
def today_str() -> str:
    return datetime.date.today().isoformat()

def days_until(date_str: str) -> int:
    if not date_str:
        return 9999
    return (datetime.date.fromisoformat(date_str) - datetime.date.today()).days

def next_interval_days(review_count: int) -> int:
    idx = min(review_count, len(REVIEW_INTERVALS) - 1)
    return REVIEW_INTERVALS[idx]

def urgency_label(days: int) -> str:
    if days < 0:  return c(f"逾期{-days}天", RED)
    if days == 0: return c("今天到期", YELLOW)
    if days <= 2: return c(f"{days}天后", CYAN)
    return dim(f"{days}天后")

# ── 工具函数 ───────────────────────────────────────────────────────────────
def pick(prompt, options, colors=None):
    print(f"\n{bold(prompt)}")
    for i, opt in enumerate(options, 1):
        color = colors.get(opt, WHITE) if colors else WHITE
        print(f"  {dim(str(i)+'.')} {c(opt, color)}")
    while True:
        try:
            val = input(f"  {dim('输入序号')} > ").strip()
            idx = int(val) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except (ValueError, KeyboardInterrupt):
            pass
        print(f"  {c('请输入有效序号', RED)}")

def hr(width=60):
    print(c("─" * width, DIM))

def bar_chart(data: dict, title="", width=30, color_map=None):
    if not data: return
    max_val = max(data.values()) or 1
    total   = sum(data.values()) or 1
    print(f"\n  {bold(title)}")
    for label, val in sorted(data.items(), key=lambda x: -x[1]):
        bar_len = int(val / max_val * width)
        color   = color_map.get(label, WHITE) if color_map else WHITE
        bar     = c("█" * bar_len, color) + dim("░" * (width - bar_len))
        pct     = f"{val/total*100:.0f}%"
        print(f"  {label.ljust(6)}  {bar}  {c(str(val)+'题', WHITE)} {dim(pct)}")

def review_progress_bar(count: int) -> str:
    total = len(REVIEW_INTERVALS)
    filled = min(count, total)
    return c("▓" * filled, BLUE) + dim("░" * (total - filled)) + f"  {dim(str(filled)+'/'+str(total)+'轮')}"

# ── 命令：add ──────────────────────────────────────────────────────────────
def cmd_add(args):
    print(f"\n{bold('  ＋ 添加错题')}")
    hr()
    module     = pick("科目模块", MODULES, MODULE_COLORS)
    error_type = pick("错误原因", ERROR_TYPES, ERROR_COLORS)

    print(f"\n{bold('题目内容')} {dim('(回车确认；多行模式输入 END 结束)')}")
    lines = []
    while True:
        line = input("  > ")
        if line.strip() == "END": break
        lines.append(line)
        if not args.multiline: break
    content = "\n".join(lines).strip()
    if not content:
        print(c("题目内容不能为空", RED)); return

    wrong_ans  = input(f"\n{bold('你的答案')} {dim('(可留空)')} > ").strip().upper()
    right_ans  = input(f"{bold('正确答案')} {dim('(可留空)')} > ").strip().upper()
    analysis   = input(f"{bold('解析笔记')} {dim('(可留空)')} > ").strip()
    source     = input(f"{bold('题目来源')} {dim('如2023国考行测第12题，可留空')} > ").strip()
    tags_input = input(f"{bold('知识点标签')} {dim('逗号分隔，如: 主旨题,转折关系')} > ").strip()

    next_review = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

    conn = get_conn()
    conn.execute("""
        INSERT INTO questions
        (module,error_type,tags,content,wrong_ans,right_ans,analysis,source,
         created_at,review_count,next_review)
        VALUES (?,?,?,?,?,?,?,?,?,0,?)
    """, (module, error_type, tags_input, content, wrong_ans, right_ans,
          analysis, source,
          datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), next_review))
    conn.commit()
    conn.close()
    print(f"\n  {c('✓ 错题已记录', GREEN)}  首次复习时间：{c(next_review, CYAN)}\n")

# ── 命令：due ──────────────────────────────────────────────────────────────
def cmd_due(args):
    conn = get_conn()
    t = today_str()
    rows = conn.execute("""
        SELECT * FROM questions
        WHERE next_review IS NOT NULL AND next_review <= ?
        ORDER BY next_review ASC, review_count ASC
    """, (t,)).fetchall()
    conn.close()

    overdue   = [r for r in rows if r["next_review"] < t]
    due_today = [r for r in rows if r["next_review"] == t]

    print(f"\n  {bold('今日复习任务')}")
    hr()
    print(f"  今天到期  {c(str(len(due_today)), YELLOW)} 题")
    if overdue:
        print(f"  已逾期    {c(str(len(overdue)), RED)} 题  {dim('请优先处理！')}")

    if not rows:
        print(f"\n  {c('✓ 今日无待复习题目，继续刷题！', GREEN)}\n")
        return

    print()
    for row in overdue + due_today:
        days = days_until(row["next_review"])
        mod_color = MODULE_COLORS.get(row["module"], WHITE)
        preview   = row["content"].replace("\n", " ")[:52]
        if len(row["content"]) > 52: preview += "…"

        print(f"  {dim('#'+str(row['id']).zfill(4))}  "
              f"{c('['+row['module']+']', mod_color)}  "
              f"{urgency_label(days)}  "
              f"{dim('第'+str(row['review_count']+1)+'轮')}")
        print(f"         {preview}")
        if row["tags"]:
            tags = " ".join(f"#{t.strip()}" for t in row["tags"].split(",") if t.strip())
            print(f"         {dim(tags)}")
        print()

    print(f"  {dim('用  python cuoti.py review <ID>  开始复习')}\n")

# ── 命令：review ───────────────────────────────────────────────────────────
def cmd_review(args):
    conn = get_conn()
    row  = conn.execute("SELECT * FROM questions WHERE id=?", (args.id,)).fetchone()
    if not row:
        print(c(f"\n  找不到 ID={args.id}\n", RED)); conn.close(); return

    mod_color = MODULE_COLORS.get(row["module"], WHITE)
    print(f"\n  {bold('复习')}  {dim('#'+str(row['id']).zfill(4))}  {c('['+row['module']+']', mod_color)}")
    hr()
    for line in row["content"].split("\n"):
        print(f"  {line}")
    print()

    # 先给用户思考时间，再显示答案
    input(f"  {dim('回车查看答案...')}")

    if row["wrong_ans"] or row["right_ans"]:
        print(f"\n  {c('你当时选了', RED)} {row['wrong_ans'] or '?'}   "
              f"{c('正确答案', GREEN)} {row['right_ans'] or '?'}")
    if row["analysis"]:
        print(f"\n  {dim(row['analysis'])}")

    # 评分
    ratings = ["完全掌握", "基本掌握", "模糊记得", "完全不会"]
    print(f"\n{bold('  掌握程度？')}")
    for i, r in enumerate(ratings, 1):
        hint = ["间隔×1.5加速", "按计划推进", "间隔减半", "重置从头来"][i-1]
        print(f"  {dim(str(i)+'.')} {c(r, RATING_COLORS[r])}  {dim(hint)}")

    rating = "基本掌握"
    try:
        val = input(f"  {dim('输入序号')} > ").strip()
        idx = int(val) - 1
        if 0 <= idx < len(ratings):
            rating = ratings[idx]
    except (ValueError, KeyboardInterrupt):
        pass

    # 根据评分计算下次间隔
    new_count = row["review_count"] + 1
    interval  = next_interval_days(new_count)

    if rating == "完全不会":
        interval  = 1
        new_count = 0
    elif rating == "模糊记得":
        interval  = max(1, interval // 2)
    elif rating == "完全掌握" and new_count > 3:
        interval  = int(interval * 1.5)

    now_str    = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    fully_done = (new_count >= len(REVIEW_INTERVALS)
                  and rating in ("完全掌握", "基本掌握"))
    next_dt    = None if fully_done else (
        datetime.date.today() + datetime.timedelta(days=interval)
    ).isoformat()

    conn.execute("""
        UPDATE questions
        SET reviewed=1, review_count=?, last_reviewed=?, next_review=?
        WHERE id=?
    """, (new_count, now_str, next_dt, args.id))
    conn.execute("""
        INSERT INTO review_log (question_id, reviewed_at, rating, interval)
        VALUES (?,?,?,?)
    """, (args.id, now_str, rating, interval))
    conn.commit()
    conn.close()

    print(f"\n  {c('✓', GREEN)} {c(rating, RATING_COLORS[rating])}", end="")
    if fully_done:
        print(f"\n  {c('🎉 此题已完成全部复习轮次，进入长期记忆！', GREEN)}")
    else:
        print(f"\n  下次复习  {c(next_dt, CYAN)}  {dim('('+str(interval)+'天后)')}")
        print(f"  进度      {review_progress_bar(new_count)}")
    print()

# ── 命令：list ─────────────────────────────────────────────────────────────
def cmd_list(args):
    conn   = get_conn()
    query  = "SELECT * FROM questions WHERE 1=1"
    params = []
    if args.module:
        query += " AND module=?"; params.append(args.module)
    if args.error_type:
        query += " AND error_type=?"; params.append(args.error_type)
    if args.tag:
        query += " AND tags LIKE ?"; params.append(f"%{args.tag}%")
    if args.unreviewed:
        query += " AND (reviewed=0 OR next_review IS NOT NULL)"
    query += " ORDER BY created_at DESC"
    if args.limit:
        query += f" LIMIT {args.limit}"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        print(c("\n  暂无记录\n", DIM)); return

    print(f"\n  {bold('错题列表')}  {dim(f'共 {len(rows)} 条')}\n")
    for row in rows:
        mod_color = MODULE_COLORS.get(row["module"], WHITE)
        err_color = ERROR_COLORS.get(row["error_type"], WHITE)

        if row["next_review"]:
            days   = days_until(row["next_review"])
            status = urgency_label(days)
            rounds = dim(f"第{row['review_count']+1}轮")
        elif row["reviewed"]:
            status = c("✓ 记熟了", GREEN)
            rounds = dim(f"共{row['review_count']}轮")
        else:
            status = dim("未开始")
            rounds = ""

        print(f"  {dim('#'+str(row['id']).zfill(4))}  "
              f"{c('['+row['module']+']', mod_color)}  "
              f"{c(row['error_type'], err_color)}  "
              f"{status}  {rounds}  {dim(row['created_at'][:10])}")
        preview = row["content"].replace("\n", " ")[:55]
        if len(row["content"]) > 55: preview += "…"
        print(f"         {preview}")
        if row["source"]:
            print(f"         {dim('来源: '+row['source'])}")
        if row["tags"]:
            print(f"         {dim(' '.join('#'+t.strip() for t in row['tags'].split(',') if t.strip()))}")
        print()

# ── 命令：show ─────────────────────────────────────────────────────────────
def cmd_show(args):
    conn = get_conn()
    row  = conn.execute("SELECT * FROM questions WHERE id=?", (args.id,)).fetchone()
    logs = conn.execute(
        "SELECT * FROM review_log WHERE question_id=? ORDER BY reviewed_at",
        (args.id,)
    ).fetchall()
    conn.close()

    if not row:
        print(c(f"\n  找不到 ID={args.id}\n", RED)); return

    mod_color = MODULE_COLORS.get(row["module"], WHITE)
    err_color = ERROR_COLORS.get(row["error_type"], WHITE)

    print(f"\n  {bold('错题详情')}  {dim('#'+str(row['id']).zfill(4))}")
    hr()
    print(f"  科目      {c(row['module'], mod_color)}")
    print(f"  错误原因  {c(row['error_type'], err_color)}")
    if row["source"]:  print(f"  来源      {row['source']}")
    if row["tags"]:    print(f"  标签      {dim(row['tags'])}")
    print(f"  记录时间  {dim(row['created_at'])}")

    if row["next_review"]:
        days = days_until(row["next_review"])
        print(f"  下次复习  {urgency_label(days)}  {dim('('+row['next_review']+')')}")
        print(f"  复习进度  {review_progress_bar(row['review_count'])}")
    elif row["reviewed"]:
        print(f"  复习状态  {c('✓ 已完成全部轮次，长期记忆', GREEN)}")

    hr()
    print(f"\n  {bold('题目')}\n")
    for line in row["content"].split("\n"):
        print(f"  {line}")
    if row["wrong_ans"] or row["right_ans"]:
        print(f"\n  {c('你的答案', RED)} {row['wrong_ans'] or '-'}   "
              f"{c('正确答案', GREEN)} {row['right_ans'] or '-'}")
    if row["analysis"]:
        print(f"\n  {bold('解析笔记')}\n  {row['analysis']}")

    if logs:
        print(f"\n  {bold('复习历史')}")
        for i, log in enumerate(logs, 1):
            rc = RATING_COLORS.get(log["rating"], WHITE)
            print(f"  第{i}次  {dim(log['reviewed_at'][:10])}  "
                  f"{c(log['rating'], rc)}  {dim('→ '+str(log['interval'])+'天后')}")
    print()

# ── 命令：stats ────────────────────────────────────────────────────────────
def cmd_stats(args):
    conn  = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    memorized = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE next_review IS NULL AND reviewed=1"
    ).fetchone()[0]
    due_cnt = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE next_review<=?", (today_str(),)
    ).fetchone()[0]
    overdue = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE next_review<? AND next_review IS NOT NULL",
        (today_str(),)
    ).fetchone()[0]
    week_ago = (datetime.datetime.now()-datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    recent   = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE created_at>=?", (week_ago,)
    ).fetchone()[0]
    rev_total = conn.execute("SELECT COUNT(*) FROM review_log").fetchone()[0]
    mod_rows  = conn.execute(
        "SELECT module, COUNT(*) n FROM questions GROUP BY module ORDER BY n DESC"
    ).fetchall()
    err_rows  = conn.execute(
        "SELECT error_type, COUNT(*) n FROM questions GROUP BY error_type ORDER BY n DESC"
    ).fetchall()
    conn.close()

    print(f"\n  {bold('备考数据统计')}")
    hr()
    print(f"  总错题数   {bold(c(str(total), CYAN))} 题")
    print(f"  已记熟     {bold(c(str(memorized), GREEN))} 题  {dim('(完成全部复习轮次)')}")
    print(f"  今日待复习 {bold(c(str(due_cnt), YELLOW))} 题"
          + (f"  {c('其中逾期'+str(overdue)+'题', RED)}" if overdue else ""))
    print(f"  累计复习   {bold(str(rev_total))} 次")
    print(f"  近7天新增  {bold(str(recent))} 题")

    bar_chart({r["module"]: r["n"] for r in mod_rows},
              "按科目分布", color_map=MODULE_COLORS)
    bar_chart({r["error_type"]: r["n"] for r in err_rows},
              "按错误原因", color_map=ERROR_COLORS)

    if mod_rows:
        weakest = mod_rows[0]["module"]
        print(f"\n  {c('⚠ 重点攻克', YELLOW)}  "
              f"{c(weakest, MODULE_COLORS.get(weakest, WHITE))} {dim('（错题最多的模块）')}\n")

# ── 命令：export（Markdown）────────────────────────────────────────────────
def cmd_export(args):
    conn   = get_conn()
    query  = "SELECT * FROM questions WHERE 1=1"
    params = []
    if args.module:
        query += " AND module=?"; params.append(args.module)
    if args.unreviewed:
        query += " AND reviewed=0"
    rows = conn.execute(query + " ORDER BY module, created_at", params).fetchall()
    conn.close()

    if not rows:
        print(c("\n  没有符合条件的错题\n", DIM)); return

    out_path = args.output or f"错题本_{datetime.datetime.now().strftime('%Y%m%d')}.md"
    lines = [
        "# 行测错题本\n",
        f"> 导出时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}  共 {len(rows)} 题\n",
    ]
    cur_mod = None
    for row in rows:
        if row["module"] != cur_mod:
            cur_mod = row["module"]
            lines.append(f"\n## {cur_mod}\n")
        done   = not row["next_review"] and row["reviewed"]
        status = "✅" if done else "⬜"
        lines.append(f"### {status} #{row['id']:04d} {row['error_type']}")
        if row["source"]: lines.append(f"**来源**：{row['source']}")
        if row["tags"]:
            lines.append("**标签**：" + " ".join(f"`{t.strip()}`"
                for t in row["tags"].split(",") if t.strip()))
        if row["next_review"]:
            lines.append(f"**下次复习**：{row['next_review']}  "
                         f"**进度**：{row['review_count']}/{len(REVIEW_INTERVALS)}轮")
        lines.append(f"\n{row['content']}\n")
        if row["wrong_ans"] or row["right_ans"]:
            lines.append(f"- 我的答案：**{row['wrong_ans'] or '?'}**  "
                         f"正确答案：**{row['right_ans'] or '?'}**")
        if row["analysis"]:
            lines.append(f"\n> {row['analysis']}")
        lines.append("\n---\n")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n  {c('✓ 已导出', GREEN)} → {bold(out_path)}  {dim(str(len(rows))+'题')}\n")

# ── Anki .apkg 生成（纯标准库）────────────────────────────────────────────
ANKI_CSS = """
.card{font-family:"PingFang SC","Noto Sans CJK SC",Arial,sans-serif;
  font-size:17px;line-height:1.7;color:#1a1a1a;max-width:640px;
  margin:0 auto;padding:16px}
.mod{display:inline-block;padding:2px 10px;border-radius:12px;
  font-size:13px;margin-bottom:10px}
.言语理解{background:#dbeafe;color:#1e40af}
.数量关系{background:#fee2e2;color:#991b1b}
.判断推理{background:#ccfbf1;color:#134e4a}
.常识判断{background:#dcfce7;color:#14532d}
.资料分析{background:#fef9c3;color:#713f12}
.q{background:#f8fafc;border-left:3px solid #6366f1;
  padding:12px 16px;border-radius:0 8px 8px 0;margin:12px 0;
  white-space:pre-wrap}
.ans{background:#f0fdf4;border:1px solid #86efac;
  border-radius:8px;padding:12px 16px;margin:12px 0}
.wrong{color:#dc2626}.right{color:#16a34a}
.note{background:#fffbeb;border-left:3px solid #f59e0b;
  padding:10px 14px;border-radius:0 6px 6px 0;
  font-size:15px;color:#78350f;margin:10px 0}
.tags span{background:#e0e7ff;color:#3730a3;padding:2px 8px;
  border-radius:8px;font-size:12px;margin-right:4px}
.err{background:#f3f4f6;color:#374151;padding:2px 8px;
  border-radius:8px;font-size:13px}
.src{font-size:13px;color:#6b7280;margin-top:8px}
hr{border:none;border-top:1px solid #e5e7eb;margin:14px 0}
""".strip()

def make_front(row) -> str:
    src = f'<div class="src">📌 {row["source"]}</div>' if row["source"] else ""
    content = row["content"].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return (f'<div class="card">'
            f'<span class="mod {row["module"]}">{row["module"]}</span>'
            f'<div class="q">{content}</div>{src}</div>')

def make_back(row) -> str:
    ans = ""
    if row["wrong_ans"] or row["right_ans"]:
        ans = (f'<div class="ans">'
               f'<span class="wrong">✗ 你选了：{row["wrong_ans"] or "?"}</span>'
               f'&emsp;<span class="right">✓ 正确：{row["right_ans"] or "?"}</span>'
               f'</div>')
    note = ""
    if row["analysis"]:
        txt = row["analysis"].replace("&","&amp;").replace("<","&lt;")
        note = f'<div class="note">💡 {txt}</div>'
    tags = ""
    if row["tags"]:
        inner = "".join(f'<span>{t.strip()}</span>'
                        for t in row["tags"].split(",") if t.strip())
        tags = f'<div class="tags" style="margin-top:8px">{inner}</div>'
    err = f'<span class="err">{row["error_type"]}</span>'
    return (f'<div class="card">{{{{FrontSide}}}}<hr>'
            f'{ans}{note}'
            f'<div style="margin-top:8px">{err}{tags}</div></div>')

def build_anki_package(rows, deck_name="行测错题本", out_path=None) -> str:
    if not out_path:
        out_path = f"行测错题_{datetime.datetime.now().strftime('%Y%m%d')}.apkg"

    now_ts   = int(time.time())
    deck_id  = random.randint(10**9, 9*10**9)
    model_id = random.randint(10**9, 9*10**9)

    model_def = {str(model_id): {
        "id": model_id, "name": "行测错题", "type": 0, "mod": now_ts,
        "usn": -1, "sortf": 0, "did": deck_id,
        "tmpls": [{"name":"正→背","ord":0,
                   "qfmt":"{{正面}}","afmt":"{{背面}}",
                   "bqfmt":"","bafmt":"","did":None,"bfont":"","bsize":0}],
        "flds": [
            {"name":"正面","ord":0,"sticky":False,"rtl":False,"font":"Arial","size":20,"media":[]},
            {"name":"背面","ord":1,"sticky":False,"rtl":False,"font":"Arial","size":20,"media":[]},
        ],
        "css": ANKI_CSS,
        "latexPre":"\\documentclass[12pt]{article}\n\\begin{document}\n",
        "latexPost":"\\end{document}","vers":[],"tags":[],
    }}
    deck_def = {str(deck_id): {
        "id":deck_id,"name":deck_name,"desc":"由 cuoti CLI 生成","mod":now_ts,
        "usn":-1,"conf":1,"extendNew":0,"extendRev":50,
        "collapsed":False,"browserCollapsed":False,"dyn":0,
        "newToday":[0,0],"revToday":[0,0],"lrnToday":[0,0],"timeToday":[0,0],
    }}
    conf_def = {"1":{
        "id":1,"name":"Default","replayq":True,
        "lapse":{"delays":[10],"leechAction":0,"leechFails":8,"minInt":1,"mult":0},
        "rev":{"bury":False,"ease4":1.3,"fuzz":0.05,"ivlFct":1,"maxIvl":36500,"minSpace":1,"perDay":100},
        "new":{"bury":False,"delays":[1,10],"initialFactor":2500,"ints":[1,4,7],"order":1,"perDay":20,"separate":True},
        "maxTaken":60,"timer":0,"autoplay":True,"mod":0,"usn":0,"dyn":False,
    }}

    with tempfile.NamedTemporaryFile(suffix=".anki2", delete=False) as tmp:
        db_path = tmp.name

    db = sqlite3.connect(db_path)
    db.executescript("""
        CREATE TABLE col(id INTEGER PRIMARY KEY,crt INTEGER NOT NULL,
          mod INTEGER NOT NULL,scm INTEGER NOT NULL,ver INTEGER NOT NULL,
          dty INTEGER NOT NULL,usn INTEGER NOT NULL,ls INTEGER NOT NULL,
          conf TEXT NOT NULL,models TEXT NOT NULL,decks TEXT NOT NULL,
          dconf TEXT NOT NULL,tags TEXT NOT NULL);
        CREATE TABLE notes(id INTEGER PRIMARY KEY,guid TEXT NOT NULL,
          mid INTEGER NOT NULL,mod INTEGER NOT NULL,usn INTEGER NOT NULL,
          tags TEXT NOT NULL,flds TEXT NOT NULL,sfld TEXT NOT NULL,
          csum INTEGER NOT NULL,flags INTEGER NOT NULL,data TEXT NOT NULL);
        CREATE TABLE cards(id INTEGER PRIMARY KEY,nid INTEGER NOT NULL,
          did INTEGER NOT NULL,ord INTEGER NOT NULL,mod INTEGER NOT NULL,
          usn INTEGER NOT NULL,type INTEGER NOT NULL,queue INTEGER NOT NULL,
          due INTEGER NOT NULL,ivl INTEGER NOT NULL,factor INTEGER NOT NULL,
          reps INTEGER NOT NULL,lapses INTEGER NOT NULL,left INTEGER NOT NULL,
          odue INTEGER NOT NULL,odid INTEGER NOT NULL,flags INTEGER NOT NULL,
          data TEXT NOT NULL);
        CREATE TABLE revlog(id INTEGER PRIMARY KEY,cid INTEGER NOT NULL,
          usn INTEGER NOT NULL,ease INTEGER NOT NULL,ivl INTEGER NOT NULL,
          lastIvl INTEGER NOT NULL,factor INTEGER NOT NULL,time INTEGER NOT NULL,
          type INTEGER NOT NULL);
        CREATE TABLE graves(usn INTEGER NOT NULL,oid INTEGER NOT NULL,
          type INTEGER NOT NULL);
    """)

    col_conf = json.dumps({
        "activeDecks":[deck_id],"curDeck":deck_id,"newSpread":0,
        "collapseTime":1200,"timeLim":0,"estTimes":True,"dueCounts":True,
        "curModel":str(model_id),"nextPos":1,"sortType":"noteFld",
        "sortBackwards":False,"addToCur":True,
    })
    db.execute("INSERT INTO col VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        1, now_ts, now_ts, now_ts*1000, 11, 0, 0, 0,
        col_conf, json.dumps(model_def), json.dumps(deck_def), json.dumps(conf_def),
        json.dumps({}),
    ))

    for i, row in enumerate(rows):
        note_id = now_ts * 1000 + i
        card_id = note_id + 1
        front   = make_front(row)
        back    = make_back(row)
        flds    = front + "\x1f" + back
        guid    = hashlib.sha1(f"{note_id}{row['content']}".encode()).hexdigest()[:10]
        csum    = int(hashlib.sha1(front.encode()).hexdigest()[:8], 16)
        tags    = " " + " ".join(
            t.strip() for t in (row["tags"] or "").split(",") if t.strip()
        ) + " "

        db.execute("INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            note_id, guid, model_id, now_ts, -1, tags, flds, front[:80], csum, 0, "",
        ))
        db.execute("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            card_id, note_id, deck_id, 0, now_ts, -1,
            0, 0, i+1, 0, 0, 0, 0, 0, 0, 0, 0, "",
        ))

    db.commit(); db.close()

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, "collection.anki2")
        zf.writestr("media", json.dumps({}))

    os.unlink(db_path)
    return out_path

def cmd_anki(args):
    conn   = get_conn()
    query  = "SELECT * FROM questions WHERE 1=1"
    params = []
    if args.module:
        query += " AND module=?"; params.append(args.module)
    if args.unreviewed:
        query += " AND (reviewed=0 OR next_review IS NOT NULL)"
    if args.tag:
        query += " AND tags LIKE ?"; params.append(f"%{args.tag}%")
    rows = conn.execute(query + " ORDER BY module, created_at", params).fetchall()
    conn.close()

    if not rows:
        print(c("\n  没有符合条件的错题\n", DIM)); return

    deck_name = args.deck or "行测错题本"
    out_path  = args.output or f"行测错题_{datetime.datetime.now().strftime('%Y%m%d')}.apkg"

    print(f"\n  {dim('正在生成 Anki 牌组...')}")
    result = build_anki_package(list(rows), deck_name=deck_name, out_path=out_path)
    size_kb = os.path.getsize(result) // 1024
    print(f"  {c('✓ Anki 牌组已生成', GREEN)} → {bold(result)}")
    print(f"  {dim(str(len(rows))+' 张卡片  '+str(size_kb)+'KB')}")
    print(f"\n  {dim('导入：打开 Anki → 文件 → 导入 → 选择此 .apkg 文件')}\n")

# ── 命令：delete ───────────────────────────────────────────────────────────
def cmd_delete(args):
    conn = get_conn()
    row  = conn.execute("SELECT id, content FROM questions WHERE id=?", (args.id,)).fetchone()
    if not row:
        print(c(f"\n  找不到 ID={args.id}\n", RED)); conn.close(); return
    preview = row["content"][:40].replace("\n", " ")
    confirm = input(f"\n  确认删除 #{args.id:04d}「{preview}」? {dim('(y/N)')} > ")
    if confirm.strip().lower() == "y":
        conn.execute("DELETE FROM questions WHERE id=?", (args.id,))
        conn.execute("DELETE FROM review_log WHERE question_id=?", (args.id,))
        conn.commit()
        print(c(f"\n  ✓ 已删除 #{args.id:04d}\n", GREEN))
    else:
        print(dim("\n  已取消\n"))
    conn.close()

# ── 主程序 ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="cuoti",
        description="cuoti — 行测错题本 CLI v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
命令速查:
  add                     添加错题（交互式引导）
  due                     今日待复习清单
  review <id>             复习一道题（评分 + 艾宾浩斯调度）
  list                    查看错题列表
  list -m 言语理解          按模块筛选
  list -e 知识盲区          按错误类型筛选
  list -t 主旨题            按标签搜索
  list --unreviewed        只看待复习的
  show <id>               查看详情和复习历史
  stats                   统计与弱点分析
  export                  导出 Markdown（含复习进度）
  anki                    导出 Anki .apkg 牌组
  anki -m 数量关系         只导出某科目
  anki -t 主旨题           只导出某标签
  anki -o file.apkg       自定义文件名
  delete <id>             删除错题
        """
    )
    sub = parser.add_subparsers(dest="command", metavar="命令")

    p_add = sub.add_parser("add", help="添加一道错题")
    p_add.add_argument("--multiline", "-ml", action="store_true", help="多行输入（END结束）")

    sub.add_parser("due", help="今日待复习清单")

    p_rev = sub.add_parser("review", help="复习一道题（自动艾宾浩斯调度）")
    p_rev.add_argument("id", type=int)

    p_list = sub.add_parser("list", help="查看错题列表")
    p_list.add_argument("-m", "--module",     help="按科目筛选")
    p_list.add_argument("-e", "--error-type", dest="error_type")
    p_list.add_argument("-t", "--tag",        help="按知识点标签搜索")
    p_list.add_argument("-n", "--limit",      type=int)
    p_list.add_argument("--unreviewed",       action="store_true")

    p_show = sub.add_parser("show", help="查看错题详情和复习历史")
    p_show.add_argument("id", type=int)

    sub.add_parser("stats", help="统计与弱点分析")

    p_exp = sub.add_parser("export", help="导出为 Markdown")
    p_exp.add_argument("-m", "--module"); p_exp.add_argument("--unreviewed", action="store_true")
    p_exp.add_argument("-o", "--output")

    p_anki = sub.add_parser("anki", help="导出为 Anki .apkg 牌组")
    p_anki.add_argument("-m", "--module")
    p_anki.add_argument("-t", "--tag")
    p_anki.add_argument("--unreviewed", action="store_true")
    p_anki.add_argument("-d", "--deck",   default="行测错题本")
    p_anki.add_argument("-o", "--output")

    p_del = sub.add_parser("delete", help="删除一道错题")
    p_del.add_argument("id", type=int)

    args = parser.parse_args()

    banner = (f"\n  {bold(c('错题本', CYAN))} "
              f"{dim('cuoti v2.0 · 间隔复习 + Anki 导出')}\n")

    dispatch = {
        "add":cmd_add,"due":cmd_due,"review":cmd_review,
        "list":cmd_list,"show":cmd_show,"stats":cmd_stats,
        "export":cmd_export,"anki":cmd_anki,"delete":cmd_delete,
    }

    if args.command in dispatch:
        print(banner)
        dispatch[args.command](args)
    else:
        print(banner)
        parser.print_help()

if __name__ == "__main__":
    main()
