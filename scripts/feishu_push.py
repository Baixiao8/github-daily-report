"""
飞书推送模块 — 带去重，每推成功一个板块立即写入 state.json
"""
import json, os, datetime, time, urllib.request, urllib.error

WEBHOOK    = os.environ.get('FEISHU_WEBHOOK', '')
STATE_FILE = os.path.join(os.path.dirname(__file__), '..', 'state.json')
TODAY      = datetime.date.today().isoformat()

SECTION_ORDER = ['github_ai', 'ai_news', 'ai_apps', 'ai_research']

SECTION_META = {
    'github_ai':   {'title': f'🔥 GitHub AI 热榜 · {TODAY}',      'template': 'red'},
    'ai_news':     {'title': f'📰 全球 AI 资讯 · {TODAY}',         'template': 'blue'},
    'ai_apps':     {'title': f'🛠️ 开箱即用 AI 应用 · {TODAY}',    'template': 'green'},
    'ai_research': {'title': f'🔬 AI 研究速递 · {TODAY}',          'template': 'purple'},
}

# ── 状态管理 ──────────────────────────────────────────────

def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            s = json.load(f)
        if s.get('date') == TODAY:
            return s
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {'date': TODAY, 'pushed': []}

def save_state(state: dict):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def pending_sections() -> list:
    return [s for s in SECTION_ORDER if s not in load_state().get('pushed', [])]

# ── HTTP 推送 ─────────────────────────────────────────────

def _post(payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req  = urllib.request.Request(
        WEBHOOK, data=data,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {'code': e.code, 'msg': e.read().decode()}
    except Exception as e:
        return {'code': -1, 'msg': str(e)}

def push_text(text: str) -> dict:
    return _post({'msg_type': 'text', 'content': {'text': text}})

def push_card(section_id: str, content: str) -> dict:
    meta = SECTION_META[section_id]
    return _post({
        'msg_type': 'interactive',
        'card': {
            'config': {'wide_screen_mode': True},
            'header': {
                'title': {'tag': 'plain_text', 'content': meta['title']},
                'template': meta['template'],
            },
            'elements': [{'tag': 'markdown', 'content': content}],
        },
    })

# ── 主推送流程 ────────────────────────────────────────────

def push_all(contents: dict) -> bool:
    state   = load_state()
    pushed  = state.get('pushed', [])
    pending = [s for s in SECTION_ORDER if s not in pushed]

    if not pending:
        print(f'[SKIP] 今日 {TODAY} 四个板块均已推送')
        return True

    print(f'[INFO] 待推: {pending}')
    push_text(f'🤖 GitHub & AI 日报开始推送 · {TODAY}')

    for sid in pending:
        if sid not in contents:
            print(f'[WARN] {sid} 内容缺失，跳过')
            continue
        result = push_card(sid, contents[sid])
        if result.get('code') == 0:
            pushed.append(sid)
            state['pushed'] = pushed
            save_state(state)
            print(f'[OK]  {sid} ✓')
        else:
            msg = str(result.get('msg', result))[:120]
            print(f'[ERR] {sid} 失败: {msg}')
            push_text(f'⚠️ AI 日报推送失败 [{sid}]: {msg}')
            return False
        time.sleep(2)

    if set(state.get('pushed', [])) == set(SECTION_ORDER):
        push_text('✅ GitHub & AI 日报 4 个板块推送完成')
        print('[DONE] 全部完成')
    return True
