#!/usr/bin/env python3
"""GitHub Trending → Feishu Daily Report"""
import json
import os
import re
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timezone, timedelta

WEBHOOK_URL = os.environ["FEISHU_WEBHOOK"]
TODAY = date.today().strftime("%Y-%m-%d")
CST = timezone(timedelta(hours=8))
NOW_STR = datetime.now(CST).strftime("%H:%M")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


# ── Feishu helpers ──────────────────────────────────────────────────────────

def _post(payload: dict) -> tuple[bool, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        body = resp.read().decode("utf-8")
        obj = json.loads(body)
        return obj.get("code") == 0, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, str(e)


def send_text(text: str) -> bool:
    ok, msg = _post({"msg_type": "text", "content": {"text": text}})
    if not ok:
        print(f"[WARN] send_text failed: {msg}")
    return ok


def send_card(title: str, template: str, content: str) -> bool:
    ok, msg = _post(
        {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": template,
                },
                "elements": [{"tag": "markdown", "content": content}],
            },
        }
    )
    if not ok:
        print(f"[ERROR] send_card failed: {msg[:300]}")
    return ok


# ── GitHub Trending scraper ─────────────────────────────────────────────────

def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_trending(since: str) -> list[dict]:
    url = f"https://github.com/trending?since={since}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[ERROR] fetch_trending({since}): {e}")
        return []

    repos = []
    # Each repo lives inside <article class="Box-row">
    for art in re.findall(
        r'<article[^>]*class="[^"]*Box-row[^"]*"[^>]*>(.*?)</article>',
        html,
        re.DOTALL,
    ):
        # owner/repo from <h2><a href="/owner/repo">
        link = re.search(r'<h2[^>]*>\s*<a\s+href="/([^/"]+/[^"]+)"', art)
        if not link:
            continue
        full_name = link.group(1).strip().rstrip("/")
        if full_name.count("/") != 1:
            continue

        # description
        desc_m = re.search(
            r'<p[^>]*class="[^"]*col-9[^"]*"[^>]*>(.*?)</p>', art, re.DOTALL
        )
        description = _clean(desc_m.group(1)) if desc_m else ""

        # language
        lang_m = re.search(r'itemprop="programmingLanguage"[^>]*>\s*([^<]+)', art)
        language = lang_m.group(1).strip() if lang_m else ""

        # stars this period (e.g. "1,234 stars today" or "1,234 stars this week")
        period_m = re.search(
            r'([\d,]+)\s+stars?\s+(?:today|this week)', art, re.IGNORECASE
        )
        stars_period = int(period_m.group(1).replace(",", "")) if period_m else 0

        # total stars
        total_m = re.search(
            r'href="/[^"]+/stargazers"[^>]*>.*?<svg[^>]*>.*?</svg>\s*([\d,]+)',
            art,
            re.DOTALL,
        )
        total_stars = int(total_m.group(1).replace(",", "")) if total_m else 0

        repos.append(
            {
                "name": full_name,
                "description": description,
                "language": language,
                "stars_period": stars_period,
                "total_stars": total_stars,
                "url": f"https://github.com/{full_name}",
            }
        )

    print(f"  fetched {len(repos)} repos (since={since})")
    return repos


# ── Content formatter ───────────────────────────────────────────────────────

_TOOL_KEYWORDS = [
    "api", "cli", "tool", "gateway", "self-host", "alternative",
    "proxy", "monitor", "dashboard", "tts", "bot", "server",
    "client", "sdk", "plugin", "extension", "agent",
]


def _why_trending(r: dict, since: str) -> str:
    period_label = "今日" if since == "daily" else "本周"
    stars = r["stars_period"]
    total = r["total_stars"]

    if stars > 3000:
        heat = f"{period_label}爆涨 {stars:,} 星"
    elif stars > 1000:
        heat = f"{period_label}新增 {stars:,} 星"
    elif stars:
        heat = f"{period_label}新增 {stars:,} 星"
    else:
        heat = "持续受关注"

    if total and stars and total > 0:
        ratio = stars / total
        if ratio > 0.4:
            note = "，极新项目一出手就引爆"
        elif ratio > 0.15:
            note = "，近期才进入大众视野"
        else:
            note = ""
    else:
        note = ""

    return f"{heat}{note}"


def fmt(r: dict, since: str = "daily") -> str:
    lang = f" ({r['language']})" if r["language"] else ""
    desc = r["description"] or "暂无描述"
    why = _why_trending(r, since)
    return (
        f"**{r['name']}{lang}** — {desc}\n"
        f"→ {why}\n"
        f"🔗 {r['url']}"
    )


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    send_text(f"🤖 GitHub 日报开始拽取·{NOW_STR}")

    print("Fetching GitHub trending...")
    daily = fetch_trending("daily")
    weekly = fetch_trending("weekly")

    if not daily:
        send_text("⚠️ GitHub 日报报错: 今日 trending 获取失败，用本周数据代替")
        daily = weekly[:]

    if not weekly:
        send_text("⚠️ GitHub 日报报错: 本周 trending 获取失败，用今日数据代替")
        weekly = daily[:]

    if not daily and not weekly:
        send_text("⚠️ GitHub 日报报错: 数据全部获取失败，终止推送")
        return

    # ── Section 1: 今日 Trending Top (5 条) ─────────────────────────────────
    top5 = daily[:5]
    seen = {r["name"] for r in top5}
    s1 = "\n\n".join(fmt(r, "daily") for r in top5)

    # ── Section 2: 本周新生 (4 条，偏好高增速小众项目) ───────────────────────
    new_candidates = [r for r in weekly if r["name"] not in seen]
    # 按「本周星/总星」比例排序，比例越高说明越新/越爆
    new_candidates.sort(
        key=lambda r: r["stars_period"] / max(r["total_stars"], 100),
        reverse=True,
    )
    new4 = new_candidates[:4]
    seen |= {r["name"] for r in new4}
    s2 = "\n\n".join(fmt(r, "weekly") for r in new4)

    # ── Section 3: 开盒即用工具 (3 条) ──────────────────────────────────────
    all_pool = {r["name"]: r for r in daily + weekly}
    tool_candidates = [
        r for r in all_pool.values()
        if r["name"] not in seen
        and any(kw in (r["description"] or "").lower() for kw in _TOOL_KEYWORDS)
    ]
    tool_candidates.sort(key=lambda r: r["stars_period"], reverse=True)
    tools = tool_candidates[:3]
    # fallback: 不够 2 条就从 weekly 里随便补
    if len(tools) < 2:
        extra = [r for r in weekly if r["name"] not in seen and r["name"] not in {t["name"] for t in tools}]
        tools += extra[: 3 - len(tools)]
    s3 = "\n\n".join(fmt(r, "weekly") for r in tools)

    # ── Push three cards ─────────────────────────────────────────────────────
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
            send_text(f"⚠️ GitHub 日报报错: 第 {i} 个板块「{title}」推送失败")
        if i < len(cards):
            time.sleep(2)

    send_text(f"✅ GitHub 日报 {success}/3 个板块推送完成")
    print(f"Done: {success}/3 cards sent.")


if __name__ == "__main__":
    main()
