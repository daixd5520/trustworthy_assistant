from __future__ import annotations

import base64
import json
import secrets
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

try:
    import qrcode
except ImportError:  # pragma: no cover - optional dependency at runtime
    qrcode = None


DEFAULT_LOGIN_TIMEOUT_SECONDS = 480
ACTIVE_LOGIN_TTL_SECONDS = 5 * 60
QR_LONG_POLL_TIMEOUT_SECONDS = 35
LONG_POLL_TIMEOUT_SECONDS = 35
API_TIMEOUT_SECONDS = 15
MAX_QR_REFRESH_COUNT = 3
MESSAGE_TYPE_USER = 1
MESSAGE_TYPE_BOT = 2
MESSAGE_ITEM_TEXT = 1
MESSAGE_ITEM_VOICE = 3


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else f"{url}/"


def _normalize_account_id(value: str) -> str:
    raw = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in (value or "").strip())
    return raw or "default"


def _wechat_uin() -> str:
    return base64.b64encode(str(secrets.randbits(32)).encode("utf-8")).decode("utf-8")


def _state_dir(root_dir: Path) -> Path:
    return root_dir / ".wechat_personal"


def _accounts_dir(root_dir: Path) -> Path:
    path = _state_dir(root_dir) / "accounts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sync_dir(root_dir: Path) -> Path:
    path = _state_dir(root_dir) / "sync"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(slots=True)
class WeChatAccount:
    account_id: str
    token: str
    base_url: str
    user_id: str = ""
    saved_at: str = ""


@dataclass(slots=True)
class IncomingWeChatMessage:
    sender_id: str
    text: str
    context_token: str
    message_id: str
    received_at: str
    raw: dict[str, Any]


def list_wechat_accounts(root_dir: Path) -> list[WeChatAccount]:
    accounts: list[WeChatAccount] = []
    for file_path in sorted(_accounts_dir(root_dir).glob("*.json")):
        try:
            parsed = json.loads(file_path.read_text(encoding="utf-8"))
            accounts.append(WeChatAccount(**parsed))
        except Exception:
            continue
    return accounts


def save_wechat_account(root_dir: Path, account: WeChatAccount) -> WeChatAccount:
    file_path = _accounts_dir(root_dir) / f"{_normalize_account_id(account.account_id)}.json"
    payload = asdict(account)
    if not payload["saved_at"]:
        payload["saved_at"] = _utcnow()
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return WeChatAccount(**payload)


def load_wechat_account(root_dir: Path, account_id: str | None = None) -> WeChatAccount | None:
    accounts = list_wechat_accounts(root_dir)
    if not accounts:
        return None
    if account_id:
        for account in accounts:
            if account.account_id == account_id:
                return account
        return None
    accounts.sort(key=lambda item: item.saved_at or "", reverse=True)
    return accounts[0]


def _context_token_path(root_dir: Path, account_id: str) -> Path:
    return _accounts_dir(root_dir) / f"{_normalize_account_id(account_id)}.context_tokens.json"


def load_context_tokens(root_dir: Path, account_id: str) -> dict[str, str]:
    path = _context_token_path(root_dir, account_id)
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(user_id).strip(): str(token).strip()
        for user_id, token in parsed.items()
        if str(user_id).strip() and str(token).strip()
    }


def persist_context_token(root_dir: Path, account_id: str, user_id: str, token: str) -> None:
    user_id = str(user_id).strip()
    token = str(token).strip()
    if not user_id or not token:
        return
    tokens = load_context_tokens(root_dir, account_id)
    if tokens.get(user_id) == token:
        return
    tokens[user_id] = token
    path = _context_token_path(root_dir, account_id)
    path.write_text(json.dumps(tokens, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sync_buffer_path(root_dir: Path, account_id: str) -> Path:
    return _sync_dir(root_dir) / f"{_normalize_account_id(account_id)}.txt"


def load_sync_buffer(root_dir: Path, account_id: str) -> str:
    path = _sync_buffer_path(root_dir, account_id)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_sync_buffer(root_dir: Path, account_id: str, value: str) -> None:
    _sync_buffer_path(root_dir, account_id).write_text(str(value or ""), encoding="utf-8")


def normalize_incoming_message(message: dict[str, Any]) -> IncomingWeChatMessage | None:
    if not isinstance(message, dict):
        return None
    message_type = int(message.get("message_type") or 0)
    if message_type == MESSAGE_TYPE_BOT:
        return None
    if message_type not in {0, MESSAGE_TYPE_USER}:
        return None
    sender_id = str(message.get("from_user_id") or "").strip()
    if not sender_id:
        return None
    text = _text_from_item_list(message.get("item_list"))
    if not text:
        return None
    context_token = str(message.get("context_token") or "").strip()
    message_id = str(message.get("message_id") or "").strip()
    create_ms = int(message.get("create_time_ms") or 0)
    if create_ms <= 0:
        create_ms = int(message.get("create_time") or 0) * 1000
    received_at = (
        datetime.fromtimestamp(create_ms / 1000, tz=timezone.utc).isoformat()
        if create_ms > 0
        else _utcnow()
    )
    return IncomingWeChatMessage(
        sender_id=sender_id,
        text=text,
        context_token=context_token,
        message_id=message_id,
        received_at=received_at,
        raw=message,
    )


def _text_from_item_list(item_list: Any) -> str:
    if not isinstance(item_list, list):
        return ""
    for item in item_list:
        item_type = int((item or {}).get("type") or 0)
        if item_type == MESSAGE_ITEM_TEXT:
            text = str(((item or {}).get("text_item") or {}).get("text") or "").strip()
            if text:
                return text
        if item_type == MESSAGE_ITEM_VOICE:
            text = str(((item or {}).get("voice_item") or {}).get("text") or "").strip()
            if text:
                return text
    return ""


class ILinkWeChatClient:
    def __init__(self, base_url: str, timeout: float = API_TIMEOUT_SECONDS) -> None:
        self.base_url = _ensure_trailing_slash(base_url)
        self.client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def _headers(self, token: str | None, body: str | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": _wechat_uin(),
        }
        if body is not None:
            headers["Content-Length"] = str(len(body.encode("utf-8")))
        if token:
            headers["Authorization"] = f"Bearer {token.strip()}"
        return headers

    def fetch_qr_code(self, bot_type: str) -> dict[str, Any]:
        response = self.client.get(f"{self.base_url}ilink/bot/get_bot_qrcode", params={"bot_type": bot_type})
        response.raise_for_status()
        return response.json()

    def poll_qr_status(self, qrcode_token: str, timeout: float = QR_LONG_POLL_TIMEOUT_SECONDS) -> dict[str, Any]:
        response = self.client.get(
            f"{self.base_url}ilink/bot/get_qrcode_status",
            params={"qrcode": qrcode_token},
            headers={"iLink-App-ClientVersion": "1"},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_updates(self, token: str, get_updates_buf: str = "", timeout: float = LONG_POLL_TIMEOUT_SECONDS) -> dict[str, Any]:
        payload = json.dumps({"get_updates_buf": get_updates_buf, "base_info": {"channel_version": "trustworthy_assistant/1.0"}})
        try:
            response = self.client.post(
                f"{self.base_url}ilink/bot/getupdates",
                content=payload,
                headers=self._headers(token, payload),
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        except httpx.ReadTimeout:
            return {"ret": 0, "msgs": [], "get_updates_buf": get_updates_buf}

    def send_text(self, token: str, to_user_id: str, text: str, context_token: str) -> dict[str, Any]:
        payload = json.dumps(
            {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user_id,
                    "client_id": f"ta-{secrets.token_hex(8)}",
                    "message_type": 2,
                    "message_state": 2,
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                    "context_token": context_token,
                },
                "base_info": {"channel_version": "trustworthy_assistant/1.0"},
            }
        )
        response = self.client.post(
            f"{self.base_url}ilink/bot/sendmessage",
            content=payload,
            headers=self._headers(token, payload),
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        parsed = response.json()
        if int(parsed.get("ret") or 0) != 0:
            raise RuntimeError(
                f"sendMessage ret={parsed.get('ret')} errcode={parsed.get('errcode')} errmsg={parsed.get('errmsg')}"
            )
        return parsed


def _print_qr_code(url: str) -> None:
    if qrcode is None:
        print(url)
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    try:
        qr.print_ascii(invert=True)
    except Exception:
        print(url)


def run_wechat_login(root_dir: Path, base_url: str, bot_type: str = "3", timeout_seconds: int = DEFAULT_LOGIN_TIMEOUT_SECONDS) -> WeChatAccount:
    client = ILinkWeChatClient(base_url=base_url)
    try:
        qr_response = client.fetch_qr_code(bot_type)
        started_at = time.time()
        refresh_count = 1
        qrcode_token = str(qr_response.get("qrcode") or "").strip()
        qr_content = str(qr_response.get("qrcode_img_content") or "").strip()
        if not qrcode_token or not qr_content:
            raise RuntimeError("二维码接口返回缺少 qrcode 或 qrcode_img_content")
        print("请使用微信扫码绑定:\n")
        _print_qr_code(qr_content)
        print("\n如果终端里二维码不清晰，可直接打开这个链接扫码：")
        print(qr_content)
        print("\n等待扫码结果...\n")
        scanned_printed = False
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if time.time() - started_at > ACTIVE_LOGIN_TTL_SECONDS:
                qr_response = client.fetch_qr_code(bot_type)
                qrcode_token = str(qr_response.get("qrcode") or "").strip()
                qr_content = str(qr_response.get("qrcode_img_content") or "").strip()
                started_at = time.time()
                scanned_printed = False
                refresh_count += 1
                if refresh_count > MAX_QR_REFRESH_COUNT:
                    raise RuntimeError("二维码过期次数过多，请重新执行登录")
                print(f"\n二维码已过期，正在刷新 ({refresh_count}/{MAX_QR_REFRESH_COUNT})\n")
                _print_qr_code(qr_content)
            status = client.poll_qr_status(qrcode_token)
            state = str(status.get("status") or "").strip().lower()
            if state == "wait":
                print(".", end="", flush=True)
                continue
            if state == "scaned":
                if not scanned_printed:
                    print("\n已扫码，请在微信中确认授权...")
                    scanned_printed = True
                continue
            if state == "expired":
                qr_response = client.fetch_qr_code(bot_type)
                qrcode_token = str(qr_response.get("qrcode") or "").strip()
                qr_content = str(qr_response.get("qrcode_img_content") or "").strip()
                started_at = time.time()
                scanned_printed = False
                refresh_count += 1
                if refresh_count > MAX_QR_REFRESH_COUNT:
                    raise RuntimeError("二维码过期次数过多，请重新执行登录")
                print(f"\n二维码已过期，正在刷新 ({refresh_count}/{MAX_QR_REFRESH_COUNT})\n")
                _print_qr_code(qr_content)
                continue
            if state == "confirmed":
                account_id = str(status.get("ilink_bot_id") or "").strip()
                token = str(status.get("bot_token") or "").strip()
                resolved_base_url = str(status.get("baseurl") or base_url).strip()
                user_id = str(status.get("ilink_user_id") or "").strip()
                if not account_id or not token:
                    raise RuntimeError("登录成功但缺少 account_id 或 token")
                account = save_wechat_account(
                    root_dir,
                    WeChatAccount(
                        account_id=account_id,
                        token=token,
                        base_url=resolved_base_url,
                        user_id=user_id,
                        saved_at=_utcnow(),
                    ),
                )
                print("\n绑定成功")
                print(f"account_id: {account.account_id}")
                print(f"user_id: {account.user_id or '(unknown)'}")
                print(f"base_url: {account.base_url}")
                return account
        raise RuntimeError("登录超时，请重新运行登录命令")
    finally:
        client.close()


class WeChatBotRunner:
    def __init__(self, app, on_event=None) -> None:
        self.app = app
        self.config = app.config
        self.on_event = on_event or (lambda _message: None)
        self._seen: set[str] = set()

    def run_forever(self) -> None:
        account = load_wechat_account(self.config.root_dir, self.config.wechat_account_id)
        if account is None:
            raise RuntimeError("未找到微信账号，请先运行 trustworthy-wechat-login")
        context_tokens = load_context_tokens(self.config.root_dir, account.account_id)
        sync_buffer = load_sync_buffer(self.config.root_dir, account.account_id)
        client = ILinkWeChatClient(account.base_url)
        self.on_event(f"using account {account.account_id}")
        self.app.cron_scheduler.start()
        try:
            while True:
                updates = client.get_updates(account.token, get_updates_buf=sync_buffer)
                sync_buffer = str(updates.get("get_updates_buf") or sync_buffer)
                save_sync_buffer(self.config.root_dir, account.account_id, sync_buffer)
                messages = updates.get("msgs") or []
                for message in messages:
                    inbound = normalize_incoming_message(message)
                    if inbound is None:
                        continue
                    dedup_key = "|".join(
                        [
                            inbound.sender_id,
                            inbound.message_id,
                            str((message or {}).get("seq") or ""),
                            inbound.received_at,
                        ]
                    )
                    if dedup_key in self._seen:
                        continue
                    self._seen.add(dedup_key)
                    if len(self._seen) > 2048:
                        self._seen = set(list(self._seen)[-1024:])
                    if inbound.context_token:
                        persist_context_token(self.config.root_dir, account.account_id, inbound.sender_id, inbound.context_token)
                        context_tokens[inbound.sender_id] = inbound.context_token
                    self.on_event(f"recv {inbound.sender_id}: {inbound.text[:80]}")
                    agent = self.app.agent_registry.get(self.app.agent_registry.default_agent_id)
                    result = self.app.turn_processor.process_turn(
                        inbound.text,
                        agent=agent,
                        channel="wechat",
                        user_id=inbound.sender_id,
                    )
                    reply = (result.assistant_text or "").strip()
                    if result.errors:
                        reply = f"处理消息时出错: {'; '.join(result.errors)}"
                    if not reply:
                        continue
                    context_token = inbound.context_token or context_tokens.get(inbound.sender_id, "")
                    if not context_token:
                        self.on_event(f"skip reply for {inbound.sender_id}: missing context_token")
                        continue
                    client.send_text(account.token, inbound.sender_id, reply, context_token)
                    self.on_event(f"sent reply to {inbound.sender_id}")
        except KeyboardInterrupt:
            self.on_event("stopped by user")
        finally:
            self.app.cron_scheduler.stop()
            client.close()
            sys.stdout.flush()
