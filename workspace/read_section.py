with open('/Users/bytedance/Documents/trae/trustworthy_assistant/src/trustworthy_assistant/runtime/cron.py') as f:
    lines = f.readlines()
for i, line in enumerate(lines[279:298], start=280):
    print(f'{i}: {repr(line)}')