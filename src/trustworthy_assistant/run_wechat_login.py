#!/usr/bin/env python3
import sys

from trustworthy_assistant.app import build_app
from trustworthy_assistant.channels.wechat import run_wechat_login


def main() -> None:
    app = build_app(on_cron_event=lambda message: print(f"[cron] {message}"))
    try:
        run_wechat_login(
            root_dir=app.config.root_dir,
            base_url=app.config.wechat_ilink_base_url,
            bot_type=app.config.wechat_qr_bot_type,
        )
    except KeyboardInterrupt:
        print("\n已取消微信登录")
        sys.exit(130)
    except Exception as exc:
        print(f"微信登录失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
