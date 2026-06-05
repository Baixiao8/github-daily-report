#!/usr/bin/env python3
"""
GitHub Trending Daily Report → Feishu
直接抓取 github.com/trending 页面，整理三个板块推飞书卡片。
"""
import os, json, time, re, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

WEBHOOK_URL = os.environ["FEISHU_WEBHOOK"]
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime("%Y-%m-%d")
NOW_STR = datetime.now(CST).strftime("%H:%M")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

print(f"[boot] date={TODAY} now_cst={NOW_STR} dry_run={DRY_RUN}")


# ── Feishu ────────────────────────────────────────────────────────────────────

def _post(payload: dict) -> tuple[bool, str]:
    if DRY_RUN:
        print("[DRY]", json.dumps(payload, ensure_ascii=False)[:300])
        return True, "dry_run"
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(
        WEBHOOK_URL, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        body = resp.read().decode()
        return json.loads(body).get("code") == 0, body
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()}"
    except Exception as e:
        return False, str(e)


def send_text(text: str) -> bool:
    ok, msg = _post({"msg_type": "text", "content": {"text": text}})
    if not ok:
        print(f"[WARN] send_text failed: {msg[:100]}")
    return ok


def send_card(title: str, template: str, content: str) -> bool:
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


# ── GitHub Trending 抓取 ──────────────────────────────────────────────────────

class _TrendingParser(HTMLParser):
    """从 github.com/trending HTML 提取仓库信息。"""

    def __init__(self):
        super().__init__()
        self.repos: list[dict] = []
        self._cur: dict = {}
        self._in_repo_name = False
        self._in_desc = False
        self._in_lang = False
        self._in_stars_today = False
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        cls = attrs_d.get("class", "")

        if tag == "article" and "Box-row" in cls:
            self._cur = {"name": "", "desc": "", "lang": "", "stars_today": ""}
            self._depth = 0

        if tag == "h2" and ("lh-condensed" in cls or "h3" in cls):
            self._in_repo_name = True

        if tag == "p" and "col-9" in cls:
            self._in_desc = True

        if tag == "span" and attrs_d.get("itemprop") == "programmingLanguage":
            self._in_lang = True

        # 今日/本周新增星数在右侧 float span 里
        if tag == "span" and "float-sm-right" in cls:
            self._in_stars_today = True

    def handle_endtag(self, tag):
        if tag == "h2":
            self._in_repo_name = False
        if tag == "p" and self._in_desc:
            self._in_desc = False
        if tag == "span":
            self._in_lang = False
            self._in_stars_today = False
        if tag == "article" and self._cur.get("name"):
            name = re.sub(r"\s+", "", self._cur["name"]).strip("/")
            name = re.sub(r"\s*/\s*", "/", name)
            if "/" in name:
                self._cur["name"] = name
                self.repos.append(dict(self._cur))
            self._cur = {}

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_repo_name and self._cur is not None:
            self._cur["name"] += text
        if self._in_desc and self._cur is not None:
            self._cur["desc"] += text + " "
        if self._in_lang and self._cur is not None:
            self._cur["lang"] = text
        if self._in_stars_today and self._cur is not None:
            m = re.search(r"[\d,]+", text)
            if m:
                self._cur["stars_today"] = m.group()


def _fetch_trending_page(since: str) -> list[dict]:
    url = f"https://github.com/trending?since={since}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        html = resp.read().decode("utf-8", errors="replace")
        parser = _TrendingParser()
        parser.feed(html)
        repos = parser.repos
        print(f"[trending] since={since} → {len(repos)} repos")
        return repos
    except Exception as e:
        print(f"[ERROR] fetch trending since={since}: {e}")
        return []


def fetch_daily() -> list[dict]:
    return _fetch_trending_page("daily")


def fetch_weekly() -> list[dict]:
    return _fetch_trending_page("weekly")


# ── 筛选逻辑 ──────────────────────────────────────────────────────────────────

# 已经家喻户晓的项目，不放进「今日 Trending Top」
_GIANTS = {
    "react", "vue", "angular", "next.js", "svelte", "nuxt",
    "kubernetes", "docker", "tensorflow", "pytorch",
    "vscode", "linux", "nodejs", "deno", "rust", "golang",
    "django", "flask", "rails", "laravel", "spring",
    "llama", "ollama", "stable-diffusion",
}

def _is_giant(repo: dict) -> bool:
    name_lower = repo["name"].lower()
    desc_lower = repo["desc"].lower()
    return any(kw in name_lower or kw in desc_lower for kw in _GIANTS)


def _stars_int(repo: dict) -> int:
    try:
        return int(repo.get("stars_today", "0").replace(",", ""))
    except Exception:
        return 0


def select_top(daily: list[dict], n: int = 5) -> list[dict]:
    candidates = [r for r in daily if not _is_giant(r)]
    candidates.sort(key=_stars_int, reverse=True)
    return candidates[:n]


def select_new(weekly: list[dict], exclude: set, n: int = 4) -> list[dict]:
    result, seen = [], set()
    for r in weekly:
        if r["name"] in exclude or r["name"] in seen or _is_giant(r):
            continue
        seen.add(r["name"])
        result.append(r)
        if len(result) >= n:
            break
    return result


def select_tools(daily: list[dict], weekly: list[dict], exclude: set, n: int = 3) -> list[dict]:
    _TOOL_RE = re.compile(
        r"cli|command.?line|terminal|tui|self.?host|alternative|replace|"
        r"scanner|deploy|monitor|dashboard|proxy|gateway",
        re.I,
    )
    seen, result = set(), []
    for r in (daily + weekly):
        if r["name"] in exclude or r["name"] in seen:
            continue
        if _TOOL_RE.search(r["desc"] + " " + r["name"]):
            seen.add(r["name"])
            result.append(r)
        if len(result) >= n:
            break
    # 补齐
    for r in (daily + weekly):
        if len(result) >= n:
            break
        if r["name"] not in seen and r["name"] not in exclude:
            seen.add(r["name"])
            result.append(r)
    return result[:n]


# ── 描述与「为什么火」────────────────────────────────────────────────────────

_WHY_RULES = [
    (r"token|compress|llm|rag|context|prompt",  "直接优化 LLM token 成本或上下文质量"),
    (r"agent|mcp|tool.?use|copilot",            "AI agent / 工具调用方向，今年最热赛道"),
    (r"tts|speech|voice|audio",                  "语音生成赛道持续升温，开源方案稀缺"),
    (r"ocr|pdf|document|parse",                  "文档结构化是 AI pipeline 刚需"),
    (r"vtuber|live2d|anime",                     "二次元 + 本地 AI，垂直社区传播极快"),
    (r"osint|graph|cyber|security|vuln",         "安全 / 情报分析工具，填补细分空白"),
    (r"rust\b",                                   "Rust 生态扩张，性能敏感场景首选"),
    (r"terminal|cli|tui",                         "开发者工具赛道，CLI 重回主流"),
    (r"self.?host|alternative|open.?source",     "数据隐私 & 自部署需求催生替代品浪潮"),
    (r"video|image|diffusion",                    "多模态生成持续火热"),
    (r"learn|tutorial|roadmap|course",           "学习资源传播快，中文社区尤其活跃"),
]

def _why(repo: dict) -> str:
    text = (repo.get("desc", "") + " " + repo["name"]).lower()
    stars = repo.get("stars_today", "")
    suffix = f"，今日涨 {stars} 星" if stars else ""
    for pattern, reason in _WHY_RULES:
        if re.search(pattern, text):
            return reason + suffix
    return f"今日涨 {stars} 星" if stars else "社区关注度持续上升"


def fmt(repo: dict) -> str:
    name = repo["name"]
    lang = f" ({repo['lang']})" if repo.get("lang") else ""
    desc = repo.get("desc", "").strip() or "暂无描述"
    why = _why(repo)
    return (
        f"**{name}{lang}** — {desc}\n"
        f"→ {why}\n"
        f"🔗 https://github.com/{name}"
    )


# ── AI 描述增强（可选，有 GITHUB_TOKEN 时启用）────────────────────────────────

def _ai_desc(repo: dict) -> str:
    if not GITHUB_TOKEN:
        return ""
    prompt = (
        "用一句话（20-40字）介绍这个GitHub项目是什么、能做什么。"
        "要求：自然中文，无翻译腔，无引号，直接输出。\n\n"
        f"项目名：{repo['name']}\n"
        f"官方描述：{repo.get('desc') or '无'}\n"
        f"主要语言：{repo.get('lang') or '未知'}"
    )
    data = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 80, "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(
        "https://models.inference.ai.azure.com/chat/completions",
        data=data,
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        text = result["choices"][0]["message"]["content"].strip().strip('"\'「」')
        print(f"  [ai] {repo['name'].split('/')[-1]}: {text[:40]}")
        return text
    except Exception as e:
        print(f"  [ai] {repo['name']}: {e}")
        return ""


def enrich(repos: list[dict]) -> list[dict]:
    for r in repos:
        ai = _ai_desc(r)
        if ai:
            r["desc"] = ai
        if GITHUB_TOKEN:
            time.sleep(1.5)
    return repos


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    send_text(f"🤖 GitHub 日报开始拽取·{NOW_STR}")

    daily = fetch_daily()
    weekly = fetch_weekly()

    if not daily and not weekly:
        send_text("⚠️ GitHub 日报报错: 今日 & 本周 trending 均抓取失败")
        return
    if not daily:
        send_text("⚠️ GitHub 日报报错: 今日 trending 抓取失败，用本周数据代替")
        daily = weekly[:]
    if not weekly:
        weekly = daily[:]

    top = select_top(daily, 5)
    top_names = {r["name"] for r in top}

    new_repos = select_new(weekly, top_names, 4)
    new_names = {r["name"] for r in new_repos}

    tools = select_tools(daily, weekly, top_names | new_names, 3)

    enrich(top)
    enrich(new_repos)
    enrich(tools)

    cards = [
        (f"🔥 GitHub 今日 Trending Top · {TODAY}", "red",   "\n\n".join(fmt(r) for r in top)),
        (f"🆕 GitHub 本周新生 · {TODAY}",           "blue",  "\n\n".join(fmt(r) for r in new_repos)),
        (f"🛠️ GitHub 开盒即用工具 · {TODAY}",       "green", "\n\n".join(fmt(r) for r in tools)),
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
