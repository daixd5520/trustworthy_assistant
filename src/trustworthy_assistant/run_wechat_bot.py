#!/usr/bin/env python3
import sys

from trustworthy_assistant.app import build_app
from trustworthy_assistant.channels.wechat import WeChatBotRunner, load_wechat_account


def main() -> None:
    app = build_app(on_cron_event=lambda message: print(f"[cron] {message}"))
    account = load_wechat_account(app.config.root_dir, app.config.wechat_account_id)
    if account is None:
        print("错误: 未找到微信账号，请先运行 trustworthy-wechat-login")
        sys.exit(1)

    print("=" * 64)
    print("  Trustworthy Assistant - Personal WeChat Bot")
    print(f"  account_id: {account.account_id}")
    print(f"  base_url: {account.base_url}")
    print(f"  Cron jobs loaded: {len(app.cron_scheduler.list_jobs())}")
    print("=" * 64)

    runner = WeChatBotRunner(app, on_event=lambda message: print(f"[wechat] {message}"))
    runner.run_forever()


if __name__ == "__main__":
    main()
