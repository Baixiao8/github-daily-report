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


# ── 翻译 ─────────────────────────────────────────────────────────────────────

# 保护不该被翻译的技术词汇（翻译前替换为占位符，翻译后还原）
_TECH_TERMS = [
    (r"\brepo(sitory)?\b", "XREPOX"),
    (r"\bfork\b",          "XFORKX"),
    (r"\bpull request\b",  "XPRX"),
    (r"\bcommit\b",        "XCOMMITX"),
    (r"\bworkflow\b",      "XWORKFLOWX"),
    (r"\bpipeline\b",      "XPIPELINEX"),
    (r"\bDocker\b",        "XDOCKERX"),
    (r"\bKubernetes\b",    "XKUBERNETESX"),
    (r"\bLLM\b",           "XLLMX"),
    (r"\bAI\b",            "XAIX"),
    (r"\bAPI\b",           "XAPIX"),
    (r"\bCLI\b",           "XCLIX"),
    (r"\bSDK\b",           "XSDKX"),
    (r"\bGPU\b",           "XGPUX"),
]

def _protect(text: str) -> tuple[str, dict]:
    mapping = {}
    for pattern, placeholder in _TECH_TERMS:
        found = re.findall(pattern, text, re.IGNORECASE)
        if found:
            original = re.search(pattern, text, re.IGNORECASE).group(0)
            mapping[placeholder] = original
            text = re.sub(pattern, placeholder, text, flags=re.IGNORECASE)
    return text, mapping

def _restore(text: str, mapping: dict) -> str:
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text

def translate(text: str) -> str:
    """把英文描述翻译成中文，保护技术词，失败则保留原文。"""
    if not text or len(text) < 4:
        return text or "暂无描述"
    if sum(1 for c in text if "一" <= c <= "鿿") > 4:
        return text  # 已是中文

    protected, mapping = _protect(text)
    url = (
        "https://api.mymemory.translated.net/get"
        f"?q={urllib.parse.quote(protected[:450])}&langpair=en|zh-CN"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "github-daily-report/3.0"})

    for attempt in range(2):
        try:
            r = urllib.request.urlopen(req, timeout=10)
            data = json.loads(r.read())
            result = data.get("responseData", {}).get("translatedText", "")
            quota_ok = data.get("quotaFinished", False) is False
            if not quota_ok:
                print("  [translate] quota finished, skipping rest")
                return text
            if result and result != result.upper() and result.upper() != text.upper():
                return _restore(result, mapping)
        except Exception as e:
            print(f"  [translate] attempt {attempt+1} error: {e}")
            if attempt == 0:
                time.sleep(3)
    return text


def fetch_readme_summary(full_name: str) -> str:
    """抓 README 首段有效内容，作为描述补充。"""
    url = f"https://api.github.com/repos/{full_name}/readme"
    req = urllib.request.Request(
        url, headers={**_GH_API, "Accept": "application/vnd.github.raw"}
    )
    try:
        r = urllib.request.urlopen(req, timeout=10)
        content = r.read().decode("utf-8", errors="replace")
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith(("#", "!", "<", ">", "---", "```", "<!--")):
                continue
            # 跳过纯徽章行（[![...](...)）
            if re.match(r"^\[?!\[", line):
                continue
            # 清理 Markdown 标记
            line = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", line)
            line = re.sub(r"[*_`~]+", "", line)
            line = re.sub(r"\s+", " ", line).strip()
            if len(line) > 25:
                return line[:220]
    except Exception as e:
        print(f"  [readme] {full_name}: {e}")
    return ""


def translate_all(repos: list[dict]) -> list[dict]:
    """批量翻译，间隔 1.2s 避免触发限速。描述过短时先抓 README 补充。"""
    print(f"  Enriching & translating {len(repos)} repos...")
    for r in repos:
        raw = r.get("description", "").strip()

        # 描述太短或太模糊 → 先抓 README 第一段
        if len(raw) < 30:
            readme = fetch_readme_summary(r["name"])
            if readme:
                raw = readme
                print(f"    [readme] {r['name']}: got {len(raw)} chars")
            time.sleep(0.5)

        r["desc_zh"] = translate(raw)
        time.sleep(1.2)
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
    translate_all(top5)
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
    translate_all(new4)
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
    translate_all(tools3)
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
