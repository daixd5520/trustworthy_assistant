#!/usr/bin/env python3
import sys
import uvicorn
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from trustworthy_assistant.app import build_app
from trustworthy_assistant.channels.wecom import create_wecom_app


def main():
    app = build_app()
    
    if not app.config.wecom_corp_id or not app.config.wecom_agent_id or not app.config.wecom_secret:
        print("错误: 请配置 WECOM_CORP_ID, WECOM_AGENT_ID, WECOM_SECRET 环境变量")
        sys.exit(1)
    
    fastapi_app = create_wecom_app(app)
    
    print("=" * 64)
    print("  Trustworthy Assistant - WeCom Bot")
    print(f"  监听地址: http://0.0.0.0:8000")
    print(f"  Webhook 地址: http://<your-domain>/wecom/webhook")
    print("=" * 64)
    
    uvicorn.run(
        fastapi_app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )


if __name__ == "__main__":
    main()
