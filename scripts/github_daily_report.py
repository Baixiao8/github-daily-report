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

# Topic 标签 → 中文领域词
_TOPIC_ZH: dict[str, str] = {
    "machine-learning": "机器学习", "deep-learning": "深度学习",
    "llm": "大语言模型", "ai": "AI", "nlp": "自然语言处理",
    "computer-vision": "计算机视觉", "generative-ai": "生成式AI",
    "react": "React", "vue": "Vue", "angular": "Angular",
    "frontend": "前端", "web": "Web", "nextjs": "Next.js",
    "nodejs": "Node.js", "fastapi": "FastAPI", "django": "Django",
    "docker": "Docker", "kubernetes": "Kubernetes", "devops": "DevOps",
    "cli": "命令行工具", "terminal": "终端", "shell": "Shell",
    "database": "数据库", "sql": "SQL", "postgresql": "PostgreSQL",
    "security": "安全", "cryptography": "密码学",
    "ios": "iOS", "android": "Android", "mobile": "移动端",
    "rust": "Rust", "golang": "Go", "python": "Python",
    "self-hosted": "可自托管", "open-source": "开源",
    "education": "编程教育", "tutorial": "教程",
    "api": "API", "sdk": "SDK", "framework": "框架",
    "automation": "自动化", "workflow": "工作流",
    "game": "游戏", "graphics": "图形", "simulation": "仿真",
    "data-science": "数据科学", "visualization": "数据可视化",
    "chatbot": "聊天机器人", "agent": "AI Agent",
    "productivity": "效率工具", "note-taking": "笔记",
}

# 描述关键词 → 中文功能摘要
_DESC_PATTERNS: list[tuple[str, str]] = [
    (r"alternative to ([^,.]+)",        r"替代 \1 的开源方案"),
    (r"open.?source (?:version|alternative) (?:of|to) ([^,.]+)", r"\1 的开源替代"),
    (r"self.?host",                      "可自托管部署"),
    (r"command.?line|CLI tool",          "命令行工具"),
    (r"machine learning|deep learning",  "机器学习框架"),
    (r"large language model|LLM",        "大语言模型相关"),
    (r"generate[sd]? (?:video|image|audio)", "AI 内容生成"),
    (r"text.to.speech|TTS",              "文字转语音"),
    (r"code (?:editor|assistant|agent)", "AI 编程辅助"),
    (r"workflow automation",             "工作流自动化平台"),
    (r"real.time",                       "实时"),
    (r"privacy.first|privacy.focused",   "隐私优先"),
    (r"(?:learn|teach|course|tutorial)", "学习/教程资源"),
    (r"monitoring|observability",        "监控与可观测性"),
    (r"starter|boilerplate|template",    "快速启动模板"),
]

# 语言 → 中文标注
_LANG_ZH: dict[str, str] = {
    "TypeScript": "TS", "JavaScript": "JS", "Python": "Python",
    "Rust": "Rust", "Go": "Go", "C++": "C++", "C": "C",
    "Java": "Java", "Kotlin": "Kotlin", "Swift": "Swift",
    "Ruby": "Ruby", "PHP": "PHP", "Shell": "Shell", "HTML": "HTML",
}


def _extract_pattern(desc: str) -> str:
    for pattern, replacement in _DESC_PATTERNS:
        m = re.search(pattern, desc, re.IGNORECASE)
        if m:
            try:
                return re.sub(pattern, replacement, m.group(0), flags=re.IGNORECASE)
            except Exception:
                return replacement
    return ""


def make_desc(r: dict) -> str:
    """用仓库元数据直接生成中文描述，无需外部服务。"""
    raw_desc  = r.get("description", "").strip()
    topics    = r.get("topics", [])
    lang      = r.get("language", "")

    # 原描述已是中文 → 直接用
    if raw_desc and sum(1 for c in raw_desc if "一" <= c <= "鿿") > 3:
        return raw_desc

    parts: list[str] = []

    # 1. 从描述里提取关键功能模式
    if raw_desc:
        pattern_hit = _extract_pattern(raw_desc)
        if pattern_hit:
            parts.append(pattern_hit)

    # 2. Topics → 领域词
    topic_hits = [_TOPIC_ZH[t] for t in topics if t in _TOPIC_ZH][:3]
    if topic_hits:
        parts.append("·".join(topic_hits))

    # 3. 实在没信息 → 保留英文原描述（总比空着强）
    if not parts:
        return raw_desc or "暂无描述"

    # 去重：topics 里和 pattern 里说的同一件事不重复
    if len(parts) > 1:
        seen_words: set[str] = set(parts[0].split("·"))
        deduped = [parts[0]]
        for p in parts[1:]:
            words = set(p.split("·"))
            if not words & seen_words:   # 没有重叠词才加入
                deduped.append(p)
                seen_words |= words
        parts = deduped

    result = "，".join(parts)

    # 加语言标注
    lang_short = _LANG_ZH.get(lang, "")
    if lang_short and lang_short not in result:
        result = f"[{lang_short}] {result}"

    return result


def enrich_all(repos: list[dict]) -> list[dict]:
    """为每个仓库生成中文描述，无外部调用。"""
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
