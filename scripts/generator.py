"""
内容生成模块 — Claude API 把原始数据生成中文飞书卡片
"""
import os, json
import anthropic

CLIENT = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
MODEL  = 'claude-haiku-4-5-20251001'

def _ask(prompt: str, max_tokens: int = 1400) -> str:
    msg = CLIENT.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system="""你是 AI 资讯编辑，把原始数据整理成简洁的中文飞书卡片内容。

格式规则：
- 每条加粗项目/文章名，一句话说清核心价值，说人话不翻译腔
- 说明为什么重要（1-2句），末尾 🔗 URL
- 条目间空一行，每板块 4-5 条，宁缺毋滥
- 不用弯引号，不用代码块，不加多余 emoji""",
        messages=[{'role': 'user', 'content': prompt}],
    )
    return msg.content[0].text.strip()


def gen_github(data: list) -> str:
    return _ask(f"""
GitHub 今日 Trending 数据如下，筛 4-5 个 AI 相关优质项目（跳过纯 Web 框架/管理工具）。

每条格式：
**owner/repo (语言)** — 一句话功能
→ 今天为什么火（结合 stars_today 数据）
🔗 URL

数据：
{json.dumps(data[:20], ensure_ascii=False)}
""")


def gen_news(hn: list, rss: list) -> str:
    return _ask(f"""
综合 HackerNews 和 RSS 多源数据，挑 4-5 条今日最重要 AI 新闻。
优先：模型发布、重大研究突破、行业政策、重要融资。
同一事件只保留最权威来源。

每条格式：
**标题** — 一句话说清这件事
→ 为什么重要（1-2句）
🔗 URL

HackerNews：
{json.dumps(hn[:8], ensure_ascii=False)}

RSS 多源（含大厂博客/Newsletter/中文媒体）：
{json.dumps(rss[:25], ensure_ascii=False)}
""", max_tokens=1500)


def gen_apps(ph: list, github: list) -> str:
    return _ask(f"""
从 Product Hunt AI 热门 + GitHub Trending 工具类项目里，挑 3-4 个真正「开箱即用」的 AI 应用。
标准：安装简单、有 UI 或 CLI、普通用户/开发者能直接上手。
排除：需大量配置的框架、纯学术工具。

每条格式：
**产品名 (类型)** — 一句话功能
→ 亮点，比同类好在哪
🔗 URL

Product Hunt：
{json.dumps(ph[:6], ensure_ascii=False)}

GitHub 工具类：
{json.dumps([r for r in github[:15] if r.get('ai_related')], ensure_ascii=False)}
""", max_tokens=1000)


def gen_research(arxiv: list, hf: list, pwc: list) -> str:
    return _ask(f"""
综合 arXiv、HuggingFace Papers、Papers with Code，挑 4-5 篇今日最值得关注的 AI 研究。
优先：有实用价值的新方法、刷新 benchmark、影响工程实践的发现。
避开：高度垂直小领域、无代码实现的纯理论。

每条格式：
**论文标题（中文意译）** — 一句话核心贡献
→ 为什么值得关注，对实践有什么影响
🔗 URL

arXiv：
{json.dumps(arxiv[:10], ensure_ascii=False)}

HuggingFace Papers：
{json.dumps(hf[:8], ensure_ascii=False)}

Papers with Code：
{json.dumps(pwc[:6], ensure_ascii=False)}
""", max_tokens=1400)


def generate_all(raw: dict) -> dict:
    sections = {
        'github_ai':   ('GitHub AI 热榜',   lambda: gen_github(raw['github'])),
        'ai_news':     ('全球 AI 资讯',      lambda: gen_news(raw['hackernews'], raw['rss'])),
        'ai_apps':     ('开箱即用 AI 应用',  lambda: gen_apps(raw['producthunt'], raw['github'])),
        'ai_research': ('AI 研究速递',       lambda: gen_research(raw['arxiv'], raw['hf_papers'], raw['pwc'])),
    }
    results = {}
    for sid, (label, fn) in sections.items():
        print(f'[GEN] {label}...')
        try:
            results[sid] = fn()
        except Exception as e:
            print(f'[GEN] {label} 失败: {e}')
            results[sid] = f'内容生成失败: {e}'
    return results
