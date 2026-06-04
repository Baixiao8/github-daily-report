"""
数据抓取模块
覆盖: GitHub / HackerNews / HuggingFace / arXiv / Papers with Code / RSS 全源
"""
import re, time, calendar, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests, feedparser
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    )
}

def _get(url, timeout=20):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f'[FETCH] {url[:80]} => {e}')
        return None


# ── 1. GitHub Trending (AI 优先) ──────────────────────────

AI_KEYWORDS = {
    'ai', 'ml', 'llm', 'gpt', 'claude', 'agent', 'neural', 'diffusion',
    'transformer', 'embedding', 'rag', 'inference', 'model', 'dataset',
    'training', 'fine-tun', 'langchain', 'openai', 'anthropic', 'gemini',
    'copilot', 'chatbot', 'nlp', 'vision', 'multimodal', 'stable-diffusion',
    'huggingface', 'pytorch', 'tensorflow', 'jax', 'cuda', 'vector',
}

def _is_ai_related(name, desc):
    text = (name + ' ' + desc).lower()
    return any(kw in text for kw in AI_KEYWORDS)

def fetch_github_trending(since='daily'):
    results = []
    for lang in ['', 'python', 'typescript', 'rust']:
        url = f'https://github.com/trending/{lang}?since={since}'
        r = _get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, 'html.parser')
        for article in soup.select('article.Box-row'):
            try:
                name_tag = article.select_one('h2 a')
                if not name_tag:
                    continue
                full_name = name_tag.get('href', '').strip('/')
                desc_tag = article.select_one('p')
                description = desc_tag.get_text(strip=True) if desc_tag else ''
                lang_tag = article.select_one('[itemprop="programmingLanguage"]')
                language = lang_tag.get_text(strip=True) if lang_tag else ''
                stars_today_tag = article.select_one('.float-sm-right')
                stars_today = stars_today_tag.get_text(strip=True) if stars_today_tag else ''
                link_tags = article.select('a.Link--muted')
                total_stars = link_tags[0].get_text(strip=True) if link_tags else ''
                entry = {
                    'name': full_name,
                    'url': f'https://github.com/{full_name}',
                    'description': description,
                    'language': language,
                    'stars_today': stars_today,
                    'total_stars': total_stars,
                    'ai_related': _is_ai_related(full_name, description),
                }
                if not any(x['name'] == full_name for x in results):
                    results.append(entry)
            except Exception:
                continue
        time.sleep(1)
    # AI 相关排前，其余补充
    ai = [r for r in results if r['ai_related']]
    others = [r for r in results if not r['ai_related']]
    return (ai + others)[:25]


# ── 2. HackerNews AI (Algolia API) ───────────────────────

def fetch_hackernews_ai(hours_back=24, min_points=15):
    cutoff = int((datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp())
    queries = ['AI agent', 'LLM', 'large language model', 'machine learning', 'artificial intelligence']
    seen = {}
    for q in queries:
        url = (
            f'https://hn.algolia.com/api/v1/search?tags=story'
            f'&query={requests.utils.quote(q)}'
            f'&numericFilters=created_at_i>{cutoff},points>{min_points}'
            f'&hitsPerPage=10'
        )
        r = _get(url)
        if not r:
            continue
        try:
            for hit in r.json().get('hits', []):
                oid = hit.get('objectID')
                if oid and oid not in seen:
                    seen[oid] = {
                        'title': hit.get('title', ''),
                        'url': hit.get('url') or f"https://news.ycombinator.com/item?id={oid}",
                        'points': hit.get('points', 0),
                        'comments': hit.get('num_comments', 0),
                        'hn_url': f"https://news.ycombinator.com/item?id={oid}",
                    }
        except Exception as e:
            print(f'[HN] {e}')
        time.sleep(0.5)
    return sorted(seen.values(), key=lambda x: x['points'], reverse=True)[:12]


# ── 3. HuggingFace Daily Papers ───────────────────────────

def fetch_huggingface_papers():
    r = _get('https://huggingface.co/papers')
    if not r:
        return []
    soup = BeautifulSoup(r.text, 'html.parser')
    papers = []
    for item in soup.select('article')[:12]:
        try:
            title_tag = item.select_one('h3') or item.select_one('h2')
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            link_tag = item.select_one('a[href*="/papers/"]')
            if not link_tag:
                continue
            href = link_tag.get('href', '')
            url = f'https://huggingface.co{href}' if href.startswith('/') else href
            desc_tag = item.select_one('p')
            description = desc_tag.get_text(strip=True)[:400] if desc_tag else ''
            papers.append({'title': title, 'url': url, 'description': description})
        except Exception:
            continue
    return papers[:8]


# ── 4. arXiv API ──────────────────────────────────────────

def fetch_arxiv_papers(max_results=20):
    url = (
        'https://export.arxiv.org/api/query'
        '?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL+OR+cat:cs.CV'
        '&sortBy=submittedDate&sortOrder=descending'
        f'&max_results={max_results}'
    )
    r = _get(url)
    if not r:
        return []
    try:
        root = ET.fromstring(r.content)
        ns = {'a': 'http://www.w3.org/2005/Atom'}
        papers = []
        for entry in root.findall('a:entry', ns):
            title = entry.find('a:title', ns)
            summary = entry.find('a:summary', ns)
            link = entry.find('a:id', ns)
            authors = entry.findall('a:author', ns)
            published = entry.find('a:published', ns)
            if title is None:
                continue
            names = [
                a.find('a:name', ns).text for a in authors[:3]
                if a.find('a:name', ns) is not None
            ]
            papers.append({
                'title': title.text.strip().replace('\n', ' '),
                'summary': (summary.text or '').strip()[:400].replace('\n', ' '),
                'url': (link.text or '').strip(),
                'published': (published.text or '')[:10],
                'authors': ', '.join(names),
            })
        return papers[:12]
    except Exception as e:
        print(f'[arXiv] {e}')
        return []


# ── 5. Papers with Code (热门论文 + 代码) ─────────────────

def fetch_papers_with_code():
    r = _get('https://paperswithcode.com/api/v1/papers/?ordering=-github_stars&items_per_page=10')
    if not r:
        return []
    try:
        items = r.json().get('results', [])
        return [{
            'title': item.get('title', ''),
            'url': f"https://paperswithcode.com{item.get('url_abs', '')}",
            'abstract': (item.get('abstract') or '')[:400],
            'github_stars': item.get('github_stars') or 0,
            'published': (item.get('published') or '')[:10],
        } for item in items[:8]]
    except Exception as e:
        print(f'[PwC] {e}')
        return []


# ── 6. Product Hunt AI ────────────────────────────────────

def fetch_producthunt_ai():
    r = _get('https://www.producthunt.com/topics/artificial-intelligence')
    if not r:
        return []
    soup = BeautifulSoup(r.text, 'html.parser')
    products = []
    for item in soup.select('[data-test="post-item"]')[:10]:
        try:
            name_tag = item.select_one('h3, [class*="title"]')
            if not name_tag:
                continue
            name = name_tag.get_text(strip=True)
            desc_tag = item.select_one('p, [class*="tagline"]')
            description = desc_tag.get_text(strip=True) if desc_tag else ''
            link_tag = item.select_one('a[href*="/posts/"]')
            if not link_tag:
                continue
            href = link_tag.get('href', '')
            url = f'https://www.producthunt.com{href}' if href.startswith('/') else href
            products.append({'name': name, 'description': description, 'url': url})
        except Exception:
            continue
    return products[:6]


# ── 7. RSS 全源 ────────────────────────────────────────────

RSS_SOURCES = {
    # 行业媒体
    'VentureBeat AI':     'https://venturebeat.com/ai/feed/',
    'MIT Tech Review':    'https://www.technologyreview.com/feed/',
    'The Verge AI':       'https://www.theverge.com/ai-artificial-intelligence/rss/index.xml',
    'Wired AI':           'https://www.wired.com/feed/tag/artificial-intelligence/rss',
    # 大厂一手来源
    'OpenAI':             'https://openai.com/blog/rss.xml',
    'Anthropic':          'https://www.anthropic.com/news/rss',
    'Google AI':          'https://blog.research.google/feeds/posts/default?alt=rss',
    'DeepMind':           'https://deepmind.google/blog/rss.xml',
    'Meta AI':            'https://ai.meta.com/blog/rss/',
    'Microsoft Research': 'https://www.microsoft.com/en-us/research/feed/',
    'Mistral AI':         'https://mistral.ai/news/rss',
    'HuggingFace Blog':   'https://huggingface.co/blog/feed.xml',
    # Newsletter (Twitter 精华聚合)
    'Import AI':          'https://importai.substack.com/feed',
    'TLDR AI':            'https://tldr.tech/ai/rss',
    'The Batch':          'https://read.deeplearning.ai/the-batch/rss/',
    'Ahead of AI':        'https://magazine.sebastianraschka.com/feed',
    "Ben's Bites":        'https://www.bensbites.com/rss',
    'AlphaSignal':        'https://alphasignal.ai/rss',
    # 学术机构
    'BAIR Blog':          'https://bair.berkeley.edu/blog/feed.xml',
    'Stanford HAI':       'https://hai.stanford.edu/news/rss.xml',
    # 中文媒体
    '机器之心':            'https://www.jiqizhixin.com/rss',
    '量子位':              'https://www.qbitai.com/feed',
    '36氪 AI':            'https://36kr.com/feed',
    '新智元':              'https://www.xinzhi.com/rss',
}

def fetch_rss_news(hours_back=36):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    items = []
    for source, feed_url in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    ts = calendar.timegm(entry.published_parsed)
                    published = datetime.fromtimestamp(ts, tz=timezone.utc)
                if published and published < cutoff:
                    continue
                summary = ''
                if hasattr(entry, 'summary'):
                    summary = BeautifulSoup(entry.summary, 'html.parser').get_text()[:400]
                items.append({
                    'source': source,
                    'title': getattr(entry, 'title', ''),
                    'url': getattr(entry, 'link', ''),
                    'summary': summary,
                    'published': published.strftime('%Y-%m-%d %H:%M') if published else '',
                })
        except Exception as e:
            print(f'[RSS] {source}: {e}')
    return items


# ── 汇总入口 ──────────────────────────────────────────────

def fetch_all():
    results = {}
    tasks = [
        ('github',      lambda: fetch_github_trending()),
        ('hackernews',  lambda: fetch_hackernews_ai()),
        ('hf_papers',   lambda: fetch_huggingface_papers()),
        ('arxiv',       lambda: fetch_arxiv_papers()),
        ('pwc',         lambda: fetch_papers_with_code()),
        ('producthunt', lambda: fetch_producthunt_ai()),
        ('rss',         lambda: fetch_rss_news()),
    ]
    for key, fn in tasks:
        print(f'[FETCH] {key}...')
        try:
            data = fn()
            results[key] = data
            print(f'  => {len(data)} items')
        except Exception as e:
            print(f'  => ERROR: {e}')
            results[key] = []
    return results
