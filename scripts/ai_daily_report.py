#!/usr/bin/env python3
"""AI Daily Report → Feishu
Sources: AI lab blogs + arXiv + HN + researcher newsletters + Karpathy GitHub
"""
import json, os, re, time, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone, timedelta

WEBHOOK_URL  = os.environ["FEISHU_WEBHOOK"]
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
TODAY        = date.today().strftime("%Y-%m-%d")
CST          = timezone(timedelta(hours=8))
NOW_STR      = datetime.now(CST).strftime("%H:%M")

print(f"[boot] {TODAY} {NOW_STR} token_len={len(GITHUB_TOKEN)}")

# ── RSS 数据源 ────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    # AI 实验室官方博客
    ("Anthropic",       "https://www.anthropic.com/rss.xml"),
    ("OpenAI",          "https://openai.com/news/rss/"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("HuggingFace",     "https://huggingface.co/blog/feed.xml"),
    ("Mistral AI",      "https://mistral.ai/news/rss.xml"),
    ("Meta AI",         "https://ai.meta.com/blog/rss/"),
    # 研究 / 论文
    ("arXiv NLP",       "https://arxiv.org/rss/cs.CL"),
    ("arXiv ML",        "https://arxiv.org/rss/cs.LG"),
    ("HF Daily Papers", "https://huggingface.co/papers/rss"),
    # 行业新闻
    ("TechCrunch AI",   "https://techcrunch.com/tag/artificial-intelligence/feed/"),
    ("VentureBeat AI",  "https://venturebeat.com/category/ai/feed/"),
    ("Hacker News",     "https://news.ycombinator.com/rss"),
    # 研究员 newsletter
    ("Import AI",       "https://importai.substack.com/feed"),
    ("The Batch",       "https://www.deeplearning.ai/the-batch/feed/"),
    ("Interconnects",   "https://www.interconnects.ai/feed"),
]

# Hacker News 需要关键词过滤（不是所有帖子都是 AI）
_AI_KW = {
    "ai", "gpt", "llm", "claude", "gemini", "llama", "openai", "anthropic",
    "deepmind", "mistral", "neural", "transformer", "diffusion", "chatgpt",
    "machine learning", "deep learning", "language model", "foundation model",
    "hugging face", "midjourney", "stable diffusion", "rlhf", "agent",
}

def _is_ai(title: str, summary: str = "") -> bool:
    text = (title + " " + summary).lower()
    return any(kw in text for kw in _AI_KW)


# ── RSS 解析 ──────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_rss(name: str, url: str, max_items: int = 20) -> list[dict]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "AI-Daily-Report/1.0",
        "Accept": "application/rss+xml, application/atom+xml, */*",
    })
    try:
        r = urllib.request.urlopen(req, timeout=15)
        raw = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [rss] {name}: {e}")
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  [rss] {name} parse error: {e}")
        return []

    items = []
    atom_ns = "http://www.w3.org/2005/Atom"
    channel = root.find("channel")

    if channel is not None:  # RSS 2.0
        for item in channel.findall("item")[:max_items]:
            title = item.findtext("title", "").strip()
            link  = item.findtext("link", "").strip()
            desc  = _clean(item.findtext("description", ""))[:350]
            if title and link:
                items.append({"source": name, "title": title, "link": link, "summary": desc})
    else:  # Atom
        for entry in root.findall(f"{{{atom_ns}}}entry")[:max_items]:
            title   = entry.findtext(f"{{{atom_ns}}}title", "").strip()
            link_el = entry.find(f"{{{atom_ns}}}link")
            link    = link_el.get("href", "") if link_el is not None else ""
            summary = _clean(
                entry.findtext(f"{{{atom_ns}}}summary", "") or
                entry.findtext(f"{{{atom_ns}}}content", "")
            )[:350]
            if title and link:
                items.append({"source": name, "title": title, "link": link, "summary": summary})

    # Hacker News 过滤非 AI 内容
    if name == "Hacker News":
        items = [i for i in items if _is_ai(i["title"], i.get("summary", ""))]

    print(f"  [rss] {name}: {len(items)} items")
    return items


# ── Karpathy GitHub 活动 ──────────────────────────────────────────────────────

def fetch_karpathy() -> list[dict]:
    GH_H = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "AI-Daily-Report/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    req = urllib.request.Request(
        "https://api.github.com/users/karpathy/events/public?per_page=15",
        headers=GH_H,
    )
    items = []
    try:
        r   = urllib.request.urlopen(req, timeout=10)
        evs = json.loads(r.read())
        cutoff = (date.today() - timedelta(days=2)).isoformat()
        for ev in evs:
            if ev.get("created_at", "") < cutoff:
                continue
            etype = ev.get("type", "")
            repo  = ev.get("repo", {}).get("name", "")
            if etype == "CreateEvent" and ev["payload"].get("ref_type") == "repository":
                desc = ev["payload"].get("description", "")
                items.append({
                    "source": "Karpathy GitHub",
                    "title":  f"Karpathy 新建仓库: {repo}",
                    "link":   f"https://github.com/{repo}",
                    "summary": desc or "Andrej Karpathy 的新项目",
                })
            elif etype == "PushEvent":
                commits = ev["payload"].get("commits", [])
                if commits:
                    msg = commits[0].get("message", "")
                    items.append({
                        "source": "Karpathy GitHub",
                        "title":  f"Karpathy 更新 {repo}",
                        "link":   f"https://github.com/{repo}",
                        "summary": msg[:200],
                    })
    except Exception as e:
        print(f"  [github] karpathy: {e}")
    if items:
        print(f"  [github] karpathy: {len(items)} events")
    return items


# ── 去重 ──────────────────────────────────────────────────────────────────────

def dedup(items: list[dict]) -> list[dict]:
    seen_url, seen_title = set(), set()
    out = []
    for item in items:
        url   = item.get("link", "").split("?")[0].rstrip("/")
        tkey  = re.sub(r"\W+", "", item.get("title", "").lower())[:60]
        if (url and url in seen_url) or (tkey and tkey in seen_title):
            continue
        if url:   seen_url.add(url)
        if tkey:  seen_title.add(tkey)
        out.append(item)
    return out


# ── AI 整理（去重 + 分类 + 摘要，一次调用）────────────────────────────────────

def ai_organize(items: list[dict]) -> dict | None:
    listing = "\n".join(
        f"[{i+1}] [{x['source']}] {x['title']}\n    {x.get('summary','')[:120]}\n    {x['link']}"
        for i, x in enumerate(items[:50])
    )

    prompt = f"""你是 AI 领域资深编辑。从以下 {min(len(items),50)} 条内容中，整理「今日 AI 日报」，分三个板块，每板块选 3-4 条。

规则：
- 同一条新闻只出现在一个板块（跨板块去重）
- 板块1「模型动态」：新模型/API 发布、产品更新、重要 benchmark
- 板块2「研究进展」：论文突破、开源项目、研究员观点/newsletter 要点
- 板块3「行业动态」：融资、收购、公司战略、行业政策
- 每条写 1-2 句中文摘要，自然流畅，无翻译腔，无引号
- 只返回 JSON，不要任何其他文字

格式：
{{"model": [{{"title":"中文标题","summary":"摘要","link":"URL","source":"来源"}},...], "research":[...], "industry":[...]}}

内容列表：
{listing}"""

    data = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1800,
        "temperature": 0.2,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://models.inference.ai.azure.com/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=40)
        body = json.loads(resp.read())
        raw  = body["choices"][0]["message"]["content"].strip()
        raw  = re.sub(r"^```json\s*", "", raw)
        raw  = re.sub(r"\s*```$",     "", raw)
        return json.loads(raw)
    except Exception as e:
        print(f"  [ai] organize: {e}")
        return None


# ── 知识卡片（每日深度概念解读）─────────────────────────────────────────────────

def ai_knowledge_card(items: list[dict], sections: dict) -> dict | None:
    listing = "\n".join(
        f"[{i+1}] [{x['source']}] {x['title']}"
        for i, x in enumerate(items[:50])
    )

    already_covered = "\n".join(
        f"- {x['title']}"
        for x in (
            sections.get("model", []) +
            sections.get("research", []) +
            sections.get("industry", [])
        )
    )

    prompt = f"""你是 AI 领域科普作者。从以下今日新闻中，挑选 1 个最值得深入了解的技术概念或事件，写一张「知识卡片」。

要求：
- 挑有学习价值的概念（优先技术原理、新方法、新范式，而非纯商业新闻）
- 不能选已在日报中出现的内容（见下方「已覆盖」列表）
- 用自然中文，无翻译腔，面向有一定技术背景的读者
- 只返回 JSON，不要任何其他文字

已覆盖（不要重复）：
{already_covered}

格式：
{{"concept":"概念名称","what":"是什么（2-3句，说清楚定义和背景）","why":"为什么重要（1-2句）","analogy":"一个帮助理解的类比（1-2句）","takeaway":"一句话记住它"}}

今日新闻列表：
{listing}"""

    data = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600,
        "temperature": 0.3,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://models.inference.ai.azure.com/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=40)
        body = json.loads(resp.read())
        raw  = body["choices"][0]["message"]["content"].strip()
        raw  = re.sub(r"^```json\s*", "", raw)
        raw  = re.sub(r"\s*```$",     "", raw)
        return json.loads(raw)
    except Exception as e:
        print(f"  [ai] knowledge_card: {e}")
        return None


def fmt_knowledge(card: dict) -> str:
    return (
        f"**{card['concept']}**\n\n"
        f"{card['what']}\n\n"
        f"**💡 为什么重要**\n{card['why']}\n\n"
        f"**🎯 一个类比**\n{card['analogy']}\n\n"
        f"**📌 一句话记住它**\n{card['takeaway']}"
    )


# ── Feishu ────────────────────────────────────────────────────────────────────

def _post(payload: dict) -> tuple[bool, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req  = urllib.request.Request(
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
    if not ok: print(f"[WARN] send_text: {msg}")
    return ok


def send_card(title: str, template: str, content: str):
    ok, msg = _post({
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": template},
            "elements": [{"tag": "markdown", "content": content}],
        },
    })
    if not ok: print(f"[ERROR] card: {msg[:150]}")
    return ok


def fmt(item: dict) -> str:
    src = f" `{item['source']}`" if item.get("source") else ""
    return (
        f"**{item['title']}**{src}\n"
        f"{item.get('summary', '')}\n"
        f"🔗 {item['link']}"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    send_text(f"🤖 AI 日报开始拽取·{NOW_STR}（via GitHub Actions）")

    all_items = []
    for name, url in RSS_FEEDS:
        all_items.extend(fetch_rss(name, url))
        time.sleep(0.4)

    all_items.extend(fetch_karpathy())

    print(f"Raw items: {len(all_items)}")
    all_items = dedup(all_items)
    print(f"After dedup: {len(all_items)}")

    if not all_items:
        send_text("⚠️ AI 日报报错: 所有数据源均获取失败（GitHub Actions）")
        return

    sections = ai_organize(all_items)
    if not sections:
        send_text("⚠️ AI 日报报错: AI 内容整理失败（GitHub Actions）")
        return

    cards = [
        (f"🚀 AI 模型动态 · {TODAY}", "red",   sections.get("model",    [])),
        (f"📄 AI 研究进展 · {TODAY}", "blue",   sections.get("research", [])),
        (f"🏭 AI 行业动态 · {TODAY}", "green",  sections.get("industry", [])),
    ]

    success = 0
    for i, (title, tpl, items) in enumerate(cards, 1):
        if not items:
            send_text(f"⚠️ AI 日报: 板块{i}「{title}」无内容，跳过（GitHub Actions）")
            continue
        content = "\n\n".join(fmt(x) for x in items)
        content += "\n\n_via GitHub Actions_"
        ok = send_card(title, tpl, content)
        if ok:
            success += 1
        else:
            send_text(f"⚠️ AI 日报报错: 第 {i} 张卡片推送失败（GitHub Actions）")
        if i < len(cards):
            time.sleep(2)

    # 第 4 张：知识卡片
    time.sleep(2)
    kcard = ai_knowledge_card(all_items, sections)
    if kcard:
        content = fmt_knowledge(kcard) + "\n\n_via GitHub Actions_"
        ok = send_card(f"🧠 今日知识卡片 · {TODAY}", "turquoise", content)
        if ok:
            success += 1
        else:
            send_text("⚠️ AI 日报报错: 知识卡片推送失败（GitHub Actions）")
    else:
        send_text("⚠️ AI 日报: 知识卡片生成失败，跳过（GitHub Actions）")

    send_text(f"✅ AI 日报 {success}/4 个板块推送完成（GitHub Actions）")
    print(f"Done: {success}/4")


if __name__ == "__main__":
    main()
