#!/usr/bin/env python3
"""GitHub Trending → Feishu Daily Report"""
import json
import os
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import date, datetime, timezone, timedelta

WEBHOOK_URL  = os.environ["FEISHU_WEBHOOK"]
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
TODAY        = date.today().strftime("%Y-%m-%d")
CST          = timezone(timedelta(hours=8))
NOW_STR      = datetime.now(CST).strftime("%H:%M")

print(f"[boot] date={TODAY} now_cst={NOW_STR}")
print(f"[boot] GITHUB_TOKEN set={bool(GITHUB_TOKEN)} len={len(GITHUB_TOKEN)}")

_GH_API = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "github-daily-feishu-report/3.0",
    "X-GitHub-Api-Version": "2022-11-28",
}

_TOOL_KW = [
    "api", "cli", "tool", "gateway", "self-host", "alternative",
    "proxy", "monitor", "dashboard", "tts", "bot", "server",
    "client", "sdk", "plugin", "extension", "platform", "service",
]


# ── 中文描述生成（纯本地，无外部依赖）────────────────────────────────────────

_TOPIC_ZH: dict[str, str] = {
    "machine-learning": "机器学习", "deep-learning": "深度学习",
    "llm": "大语言模型", "ai": "AI 工具", "nlp": "自然语言处理",
    "computer-vision": "计算机视觉", "generative-ai": "生成式 AI",
    "react": "React 生态", "vue": "Vue 生态", "angular": "Angular",
    "frontend": "前端开发", "web": "Web 开发", "nextjs": "Next.js",
    "nodejs": "Node.js", "fastapi": "FastAPI", "django": "Django",
    "docker": "Docker", "kubernetes": "Kubernetes", "devops": "DevOps",
    "cli": "命令行工具", "terminal": "终端工具", "shell": "Shell 脚本",
    "database": "数据库", "sql": "SQL", "postgresql": "PostgreSQL",
    "security": "安全工具", "cryptography": "密码学",
    "ios": "iOS 开发", "android": "Android 开发", "mobile": "移动端",
    "self-hosted": "可自托管", "privacy": "隐私保护",
    "education": "编程教育", "tutorial": "教程资源",
    "awesome-list": "精选资源合集", "awesome": "精选合集",
    "api": "API 服务", "sdk": "SDK", "framework": "开发框架",
    "automation": "自动化", "workflow": "工作流",
    "game": "游戏开发", "graphics": "图形处理",
    "data-science": "数据科学", "visualization": "数据可视化",
    "chatbot": "聊天机器人", "agent": "AI Agent",
    "productivity": "效率工具", "note-taking": "笔记工具",
    "monitoring": "监控工具", "observability": "可观测性",
    "testing": "测试工具", "benchmark": "性能基准",
}

# (正则, 中文描述) — 按优先级排列，先命中先用
_DESC_PATTERNS: list[tuple[str, str]] = [
    # Awesome 合集
    (r"curated\s+(?:list|collection)",          "精选资源合集"),
    (r"awesome\s+list\s+of",                    "精选资源合集"),
    # 平替/开源替代
    (r"open.?source\s+(?:alternative|version)\s+(?:to|of)\s+([\w\s]+?)(?:[,.]|$)",
                                                "开源替代方案"),
    (r"alternative\s+to\s+([\w\s]+?)(?:[,.]|$)","开源替代方案"),
    # 助手/Agent
    (r"personal\s+AI\s+assistant",              "个人 AI 助手"),
    (r"AI\s+(?:coding\s+)?assistant",           "AI 编程助手"),
    (r"AI\s+agent",                             "AI Agent 框架"),
    # 内容生成
    (r"generate[sd]?\s+(?:\w+\s+)?video",       "AI 视频生成"),
    (r"generate[sd]?\s+(?:\w+\s+)?image",       "AI 图像生成"),
    (r"text.to.(?:speech|voice)|TTS",           "文字转语音"),
    # 工具类
    (r"workflow\s+automation",                  "工作流自动化平台"),
    (r"command.?line|CLI\s+tool",               "命令行工具"),
    (r"self.?host(?:ed|ing)?",                  "可自托管应用"),
    (r"(?:web\s+)?(?:scraping|crawler)",        "网页爬虫工具"),
    (r"(?:large\s+)?language\s+model|LLM",      "大语言模型工具"),
    (r"machine\s+learning|deep\s+learning",     "机器学习工具"),
    (r"(?:real.?time\s+)?(?:chat|messaging)",   "即时通讯工具"),
    (r"monitoring|observability",               "监控 & 可观测性"),
    (r"(?:code\s+)?(?:editor|IDE)",             "代码编辑器"),
    (r"(?:boilerplate|starter|template)",       "项目启动模板"),
    (r"(?:learn|course|curriculum|tutorial)",   "学习 & 教程"),
    (r"getting\s+(?:things?|shit)\s+done|GTD",  "GTD 效率工具"),
    (r"(?:task|todo|to-do)\s+(?:manager|app)",  "任务管理工具"),
    (r"privacy.?(?:first|focused)",             "注重隐私的"),
    (r"cross.?platform|any\s+(?:os|platform)",  "跨平台"),
]

_LANG_ZH: dict[str, str] = {
    "TypeScript": "TS", "JavaScript": "JS", "Python": "Py",
    "Rust": "Rust", "Go": "Go", "C++": "C++", "C": "C",
    "Java": "Java", "Kotlin": "Kotlin", "Swift": "Swift",
    "Ruby": "Ruby", "PHP": "PHP", "Shell": "Shell", "HTML": "HTML",
}


def _desc_hit(desc: str) -> list[str]:
    hits = []
    for pattern, zh in _DESC_PATTERNS:
        if re.search(pattern, desc, re.IGNORECASE):
            hits.append(zh)
            if len(hits) >= 2:
                break
    return hits


def _name_hint(name: str) -> str:
    """从仓库名推断类型。"""
    repo = name.split("/")[-1].lower()
    if re.search(r"^awesome-", repo):
        lang = repo.replace("awesome-", "").replace("-", "/").title()
        return f"{lang} 精选资源合集"
    if re.search(r"-(cli|tool|kit|lib|sdk|api)$", repo):
        kind = {"cli": "命令行工具", "tool": "工具", "kit": "工具包",
                "lib": "库", "sdk": "SDK", "api": "API 库"}
        suffix = re.search(r"-(cli|tool|kit|lib|sdk|api)$", repo).group(1)
        return kind.get(suffix, "开发工具")
    return ""


def make_desc(r: dict) -> str:
    raw   = r.get("description", "").strip()
    topics = r.get("topics", [])
    lang  = r.get("language", "")

    # 已是中文 → 直接用
    if raw and sum(1 for c in raw if "一" <= c <= "鿿") > 3:
        return raw

    parts: list[str] = []

    # 1. 描述模式命中
    parts.extend(_desc_hit(raw))

    # 2. Topics 词典（模式已命中 2 条则跳过）
    if len(parts) < 2:
        topic_words = [_TOPIC_ZH[t] for t in topics if t in _TOPIC_ZH]
        for tw in topic_words:
            if tw not in "".join(parts):
                parts.append(tw)
            if len(parts) >= 2:
                break

    # 3. 仓库名推断
    if len(parts) == 0:
        hint = _name_hint(r["name"])
        if hint:
            parts.append(hint)

    # 4. 兜底保留英文
    if not parts:
        return raw or "暂无描述"

    result = "，".join(dict.fromkeys(parts))   # 保序去重

    # 语言标注（内容够丰富才加）
    lang_short = _LANG_ZH.get(lang, "")
    if lang_short and len(result) >= 6 and lang_short not in result:
        result = f"[{lang_short}] {result}"

    return result


def enrich_all(repos: list[dict]) -> list[dict]:
    for r in repos:
        r["desc_zh"] = make_desc(r)
    return repos


# ── Feishu ───────────────────────────────────────────────────────────────────

def _post(payload: dict) -> tuple[bool, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        body = resp.read().decode("utf-8")
        return json.loads(body).get("code") == 0, body
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()}"
    except Exception as e:
        return False, str(e)


def send_text(text: str):
    ok, msg = _post({"msg_type": "text", "content": {"text": text}})
    if not ok:
        print(f"[WARN] send_text failed: {msg}")
    return ok


def send_card(title: str, template: str, content: str):
    ok, msg = _post({
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "elements": [{"tag": "markdown", "content": content}],
        },
    })
    if not ok:
        print(f"[ERROR] card '{title[:30]}' failed: {msg[:200]}")
    return ok


# ── GitHub 数据获取 ───────────────────────────────────────────────────────────

def _gh_search(query: str, sort: str = "stars", per_page: int = 30) -> list[dict]:
    url = (
        "https://api.github.com/search/repositories"
        f"?q={urllib.parse.quote(query)}&sort={sort}&order=desc&per_page={per_page}"
    )
    req = urllib.request.Request(url, headers=_GH_API)
    try:
        r = urllib.request.urlopen(req, timeout=20)
        data = json.loads(r.read())
        items = data.get("items", [])
        print(f"  [api] '{query[:55]}' → {len(items)} items")
        return items
    except urllib.error.HTTPError as e:
        print(f"  [api] HTTP {e.code}: {e.read().decode()[:200]}")
        return []
    except Exception as e:
        print(f"  [api] Error: {e}")
        return []


def _item_to_repo(item: dict) -> dict:
    return {
        "name":        item["full_name"],
        "description": (item.get("description") or "").strip(),
        "desc_zh":     "",   # 翻译后填入
        "language":    item.get("language") or "",
        "total_stars": item.get("stargazers_count", 0),
        "forks":       item.get("forks_count", 0),
        "created_at":  item.get("created_at", "")[:10],
        "url":         item["html_url"],
        "topics":      item.get("topics", []),
    }


def fetch_daily() -> list[dict]:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    repos, seen = [], set()

    for item in _gh_search(f"created:>{yesterday} stars:>=5", per_page=25):
        if item["full_name"] not in seen:
            seen.add(item["full_name"])
            repos.append(_item_to_repo(item))

    time.sleep(1)
    for item in _gh_search(f"pushed:>{yesterday} stars:>=500", per_page=25):
        if item["full_name"] not in seen:
            seen.add(item["full_name"])
            repos.append(_item_to_repo(item))

    repos.sort(key=lambda r: r["total_stars"], reverse=True)
    print(f"fetch_daily: {len(repos)} repos")
    return repos


def fetch_weekly() -> list[dict]:
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    repos, seen = [], set()

    for item in _gh_search(f"created:>{week_ago} stars:>=20", per_page=40):
        if item["full_name"] not in seen:
            seen.add(item["full_name"])
            repos.append(_item_to_repo(item))

    time.sleep(1)
    for item in _gh_search(f"pushed:>{week_ago} stars:100..5000", sort="updated", per_page=20):
        if item["full_name"] not in seen:
            seen.add(item["full_name"])
            repos.append(_item_to_repo(item))

    def velocity(r: dict) -> float:
        try:
            days = max((date.today() - date.fromisoformat(r["created_at"])).days, 1)
            return r["total_stars"] / days
        except Exception:
            return 0.0

    repos.sort(key=velocity, reverse=True)
    print(f"fetch_weekly: {len(repos)} repos")
    return repos


# ── 格式化 ────────────────────────────────────────────────────────────────────

def _why(r: dict) -> str:
    stars = r["total_stars"]
    created = r.get("created_at", "")

    days_old = None
    if created:
        try:
            days_old = (date.today() - date.fromisoformat(created)).days
        except Exception:
            pass

    # 新项目
    if days_old is not None and days_old <= 7:
        age = f"上线 {days_old} 天" if days_old > 0 else "今日刚上线"
        return f"{age}已获 {stars:,} 星，属于爆款新项目"

    # 老项目按体量描述
    if stars >= 100_000:
        return f"{stars // 1000}K 星，殿堂级开源项目，社区生态极成熟"
    elif stars >= 50_000:
        return f"{stars // 1000}K 星，顶级开源，有大规模生产落地案例"
    elif stars >= 10_000:
        return f"{stars:,} 星，主流项目，有稳定用户群体"
    elif stars >= 1_000:
        return f"{stars:,} 星，处于高速增长阶段"
    else:
        return f"当前 {stars:,} 星，新兴项目值得关注"


def fmt(r: dict) -> str:
    lang = f" ({r['language']})" if r["language"] else ""
    desc = r.get("desc_zh") or r.get("description") or "暂无描述"
    # 清理机器翻译可能带来的引号乱码
    desc = desc.replace("&#39;", "'").replace("&quot;", '"').replace("&amp;", "&")
    return (
        f"**{r['name']}{lang}** — {desc}\n"
        f"→ {_why(r)}\n"
        f"🔗 {r['url']}"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    send_text(f"🤖 GitHub 日报开始拽取·{NOW_STR}")

    daily  = fetch_daily()
    weekly = fetch_weekly()

    if not daily and not weekly:
        send_text("⚠️ GitHub 日报报错: GitHub API 数据全部获取失败，请检查 GITHUB_TOKEN")
        return
    if not daily:
        send_text("⚠️ GitHub 日报报错: 今日数据获取失败，用本周数据代替")
        daily = weekly[:]
    if not weekly:
        send_text("⚠️ GitHub 日报报错: 本周数据获取失败，用今日数据代替")
        weekly = daily[:]

    # ── 板块 1: 今日 Top 5 ───────────────────────────────────────────────────
    top5 = daily[:5]
    seen = {r["name"] for r in top5}
    enrich_all(top5)
    s1 = "\n\n".join(fmt(r) for r in top5)

    # ── 板块 2: 本周新生 Top 4（高日均增速）────────────────────────────────────
    new_candidates = [r for r in weekly if r["name"] not in seen]

    def velocity(r):
        try:
            days = max((date.today() - date.fromisoformat(r["created_at"])).days, 1)
            return r["total_stars"] / days
        except Exception:
            return 0.0

    new_candidates.sort(key=velocity, reverse=True)
    new4 = new_candidates[:4]
    seen |= {r["name"] for r in new4}
    enrich_all(new4)
    s2 = "\n\n".join(fmt(r) for r in new4)

    # ── 板块 3: 工具类（CLI/自托管/平替）────────────────────────────────────────
    all_pool = {r["name"]: r for r in daily + weekly}
    tools = [
        r for r in all_pool.values()
        if r["name"] not in seen
        and (
            any(kw in (r["description"] or "").lower() for kw in _TOOL_KW)
            or any(kw in r["topics"] for kw in ["cli", "tool", "self-hosted", "api"])
        )
    ]
    tools.sort(key=lambda r: r["total_stars"], reverse=True)
    tools3 = tools[:3]
    if len(tools3) < 2:
        extra = [r for r in weekly if r["name"] not in seen
                 and r["name"] not in {t["name"] for t in tools3}]
        tools3 += extra[:3 - len(tools3)]
    enrich_all(tools3)
    s3 = "\n\n".join(fmt(r) for r in tools3)

    # ── 推送三张卡片 ─────────────────────────────────────────────────────────
    cards = [
        (f"🔥 GitHub 今日 Trending Top · {TODAY}", "red",   s1),
        (f"🆕 GitHub 本周新生 · {TODAY}",           "blue",  s2),
        (f"🛠️ GitHub 开盒即用工具 · {TODAY}",       "green", s3),
    ]

    success = 0
    for i, (title, tpl, content) in enumerate(cards, 1):
        print(f"Pushing card {i}: {title}")
        ok = send_card(title, tpl, content)
        if ok:
            success += 1
        else:
            send_text(f"⚠️ GitHub 日报报错: 第 {i} 张卡片推送失败")
        if i < len(cards):
            time.sleep(2)

    send_text(f"✅ GitHub 日报 {success}/3 个板块推送完成")
    print(f"Done: {success}/3")


if __name__ == "__main__":
    main()
