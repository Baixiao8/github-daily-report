#!/usr/bin/env python3
"""
AI 日报主入口
用法:
  python3 scripts/run.py           # 正常运行（有去重）
  python3 scripts/run.py --reset   # 清空今日状态后重跑
  python3 scripts/run.py --check   # 只查看今日推送状态
"""
import sys, json, datetime, os
sys.path.insert(0, os.path.dirname(__file__))

from fetchers import fetch_all
from generator import generate_all
from feishu_push import push_all, load_state, save_state, push_text, pending_sections, SECTION_ORDER

TODAY = datetime.date.today().isoformat()

def main():
    if '--check' in sys.argv:
        state   = load_state()
        pushed  = state.get('pushed', [])
        pending = [s for s in SECTION_ORDER if s not in pushed]
        print(json.dumps({'date': TODAY, 'pushed': pushed, 'pending': pending,
                          'all_done': not pending}, ensure_ascii=False, indent=2))
        return

    if '--reset' in sys.argv:
        save_state({'date': TODAY, 'pushed': []})
        print(f'[RESET] 今日 {TODAY} 状态已清空')

    pending = pending_sections()
    if not pending:
        print(f'[SKIP] 今日 {TODAY} 已全部推送，退出。强制重跑: python3 scripts/run.py --reset')
        return

    print(f'[START] 待推板块: {pending}')

    try:
        raw = fetch_all()
    except Exception as e:
        msg = f'⚠️ AI 日报数据抓取失败: {e}'
        print(msg); push_text(msg); sys.exit(1)

    try:
        contents = generate_all(raw)
    except Exception as e:
        msg = f'⚠️ AI 日报内容生成失败: {e}'
        print(msg); push_text(msg); sys.exit(1)

    ok = push_all(contents)
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
