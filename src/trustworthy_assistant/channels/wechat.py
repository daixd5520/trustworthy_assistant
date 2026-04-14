from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

try:
    import qrcode
except ImportError:  # pragma: no cover - optional dependency at runtime
    qrcode = None

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as _padding

    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


DEFAULT_LOGIN_TIMEOUT_SECONDS = 480
ACTIVE_LOGIN_TTL_SECONDS = 5 * 60
QR_LONG_POLL_TIMEOUT_SECONDS = 35
LONG_POLL_TIMEOUT_SECONDS = 35
API_TIMEOUT_SECONDS = 15
CDN_TIMEOUT_SECONDS = 30
CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
MAX_QR_REFRESH_COUNT = 3
MESSAGE_TYPE_USER = 1
MESSAGE_TYPE_BOT = 2
MESSAGE_ITEM_TEXT = 1
MESSAGE_ITEM_IMAGE = 2
MESSAGE_ITEM_VOICE = 3
MESSAGE_ITEM_FILE = 4
MESSAGE_ITEM_VIDEO = 5
UPLOAD_MEDIA_IMAGE = 1
UPLOAD_MEDIA_VIDEO = 2
UPLOAD_MEDIA_FILE = 3
MAX_FILE_SIZE = 20 * 1024 * 1024

_MIME_BY_EXT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip",
    ".html": "text/html",
}


def _get_mime_type(file_path: str | Path) -> str:
    ext = Path(file_path).suffix.lower()
    return _MIME_BY_EXT.get(ext, "application/octet-stream")


def _classify_media_type(file_path: str | Path) -> int:
    mime = _get_mime_type(file_path)
    if mime.startswith("image/"):
        return UPLOAD_MEDIA_IMAGE
    if mime.startswith("video/"):
        return UPLOAD_MEDIA_VIDEO
    return UPLOAD_MEDIA_FILE


def _split_text_for_delivery(text: str, soft_limit: int = 110, hard_limit: int = 220) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    if "```" in raw:
        return [raw]

    def _hard_split(chunk: str) -> list[str]:
        return [chunk[i:i + hard_limit] for i in range(0, len(chunk), hard_limit) if chunk[i:i + hard_limit]]

    chunks: list[str] = []
    paragraphs = [part.strip() for part in raw.replace("\r\n", "\n").split("\n\n") if part.strip()]
    for paragraph in paragraphs:
        if len(paragraph) <= hard_limit:
            sentences = [
                item.strip() for item in re.split(r"(?<=[。！？!?；;])\s*", paragraph) if item.strip()
            ]
        else:
            sentences = []
            for line in paragraph.splitlines():
                line = line.strip()
                if not line:
                    continue
                if len(line) > hard_limit:
                    sentences.extend(_hard_split(line))
                else:
                    sentences.append(line)
        current = ""
        for sentence in sentences or [paragraph]:
            candidate = sentence if not current else f"{current}\n{sentence}" if sentence.startswith(("- ", "* ")) else f"{current} {sentence}"
            if current and len(candidate) > soft_limit:
                chunks.append(current.strip())
                current = sentence
            else:
                current = candidate
            if len(current) > hard_limit:
                chunks.extend(_hard_split(current))
                current = ""
        if current.strip():
            chunks.append(current.strip())
    return chunks or [raw]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _debug_emit(hypothesis_id: str, location: str, msg: str, data: dict[str, Any] | None = None, trace_id: str = "") -> None:
    payload = {
        "sessionId": "wechat-quote-dup",
        "runId": "pre-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "msg": f"[DEBUG] {msg}",
        "data": data or {},
    }
    if trace_id:
        payload["traceId"] = trace_id
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                "http://127.0.0.1:7778/event",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            ),
            timeout=1.5,
        ).read()
    except Exception:
        pass


def _ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else f"{url}/"


def _normalize_account_id(value: str) -> str:
    raw = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in (value or "").strip())
    return raw or "default"


def _wechat_uin() -> str:
    return base64.b64encode(str(secrets.randbits(32)).encode("utf-8")).decode("utf-8")


def _aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    if not _HAS_CRYPTO:
        raise RuntimeError("cryptography package is required for file upload. Install with: pip install cryptography")
    padder = _padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _aes_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    if not _HAS_CRYPTO:
        raise RuntimeError("cryptography package is required for media download. Install with: pip install cryptography")
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = _padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def _aes_ecb_padded_size(plaintext_size: int) -> int:
    return ((plaintext_size + 1 + 15) // 16) * 16


@dataclass(slots=True)
class UploadedFileInfo:
    filekey: str
    download_encrypted_query_param: str
    aeskey_hex: str
    file_size: int
    file_size_ciphertext: int


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


def _incoming_media_dir(root_dir: Path, account_id: str) -> Path:
    path = _state_dir(root_dir) / "incoming" / _normalize_account_id(account_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _lock_dir(root_dir: Path) -> Path:
    path = _state_dir(root_dir) / "locks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _instance_lock_path(root_dir: Path, account_id: str) -> Path:
    return _lock_dir(root_dir) / f"{_normalize_account_id(account_id)}.lock"


@dataclass(slots=True)
class WeChatAccount:
    account_id: str
    token: str
    base_url: str
    user_id: str = ""
    saved_at: str = ""


@dataclass(slots=True)
class IncomingWeChatReference:
    text: str = ""
    sender_id: str = ""
    message_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class IncomingWeChatImage:
    encrypt_query_param: str
    aes_key_b64: str
    file_name: str = ""
    mime_type: str = ""
    local_path: str = ""
    is_quoted: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class IncomingWeChatMessage:
    sender_id: str
    text: str
    context_token: str
    message_id: str
    received_at: str
    raw: dict[str, Any]
    quoted: IncomingWeChatReference | None = None
    images: list[IncomingWeChatImage] = field(default_factory=list)


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
    item_list = message.get("item_list")
    text = _text_from_item_list(item_list)
    quoted = _extract_reference_from_item_list(item_list)
    images = _extract_images_from_item_list(item_list)
    if not text and quoted is None and not images:
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
        quoted=quoted,
        images=images,
        raw=message,
    )


def _text_from_item_list(item_list: Any) -> str:
    if not isinstance(item_list, list):
        return ""
    texts: list[str] = []
    for item in item_list:
        item_type = int((item or {}).get("type") or 0)
        if item_type == MESSAGE_ITEM_TEXT:
            text = str(((item or {}).get("text_item") or {}).get("text") or "").strip()
            if text:
                texts.append(text)
        if item_type == MESSAGE_ITEM_VOICE:
            text = str(((item or {}).get("voice_item") or {}).get("text") or "").strip()
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def _text_from_message_item(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    item_type = int(item.get("type") or 0)
    if item_type == MESSAGE_ITEM_TEXT:
        return str((item.get("text_item") or {}).get("text") or "").strip()
    if item_type == MESSAGE_ITEM_VOICE:
        return str((item.get("voice_item") or {}).get("text") or "").strip()
    item_list = item.get("item_list")
    if isinstance(item_list, list):
        return _text_from_item_list(item_list)
    return ""


def _reference_payload_from_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    containers = [
        item,
        item.get("text_item"),
        item.get("voice_item"),
        item.get("image_item"),
        item.get("file_item"),
        item.get("video_item"),
    ]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in ("ref_msg", "refer_msg", "quote_msg", "quoted_msg", "reply_msg", "reference"):
            value = container.get(key)
            if isinstance(value, dict):
                return value
    return None


def _extract_reference_from_item_list(item_list: Any) -> IncomingWeChatReference | None:
    if not isinstance(item_list, list):
        return None
    for item in item_list:
        ref = _reference_payload_from_item(item)
        if ref is None:
            continue
        ref_item = ref.get("message_item")
        text = _text_from_message_item(ref_item)
        if not text:
            text = _text_from_item_list(ref.get("item_list"))
        if not text:
            candidates = [
                ref.get("text"),
                ref.get("content"),
                ref.get("title"),
                ref.get("summary"),
                ref.get("desc"),
                ref.get("digest"),
                ref.get("message"),
                ref.get("reply_content"),
            ]
            text = next((str(value).strip() for value in candidates if str(value or "").strip()), "")
        return IncomingWeChatReference(
            text=text,
            sender_id=str(ref.get("from_user_id") or ref.get("sender_id") or "").strip(),
            message_id=str(ref.get("message_id") or ref.get("msg_id") or "").strip(),
            raw=ref,
        )
    return None


def _append_image_from_item(images: list[IncomingWeChatImage], item: Any, *, is_quoted: bool) -> None:
    if int((item or {}).get("type") or 0) != MESSAGE_ITEM_IMAGE:
        return
    image_item = (item or {}).get("image_item") or {}
    media = image_item.get("media") or {}
    encrypt_query_param = str(media.get("encrypt_query_param") or image_item.get("encrypt_query_param") or "").strip()
    aes_key_b64 = str(
        image_item.get("aeskey")
        or media.get("aes_key")
        or image_item.get("aes_key")
        or ""
    ).strip()
    if not encrypt_query_param or not aes_key_b64:
        return
    images.append(
        IncomingWeChatImage(
            encrypt_query_param=encrypt_query_param,
            aes_key_b64=aes_key_b64,
            file_name=str(image_item.get("file_name") or image_item.get("name") or "").strip(),
            mime_type=str(image_item.get("mime_type") or image_item.get("content_type") or "").strip(),
            is_quoted=is_quoted,
            raw=image_item if isinstance(image_item, dict) else {},
        )
    )


def _extract_images_from_item_list(item_list: Any) -> list[IncomingWeChatImage]:
    if not isinstance(item_list, list):
        return []
    images: list[IncomingWeChatImage] = []
    for item in item_list:
        _append_image_from_item(images, item, is_quoted=False)
        ref = _reference_payload_from_item(item)
        if not isinstance(ref, dict):
            continue
        ref_item = ref.get("message_item")
        if isinstance(ref_item, dict):
            _append_image_from_item(images, ref_item, is_quoted=True)
    return images


def _guess_image_media_type(image_bytes: bytes, fallback: str = "") -> tuple[str, str]:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", ".gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if image_bytes.startswith(b"BM"):
        return "image/bmp", ".bmp"
    if fallback.startswith("image/"):
        ext = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
        }.get(fallback, "")
        return fallback, ext
    return fallback, ""


def _build_user_facing_error_reply(errors: list[str]) -> str:
    combined = " | ".join((item or "").strip() for item in errors if (item or "").strip())
    lowered = combined.lower()
    if any(marker in lowered for marker in ("error code 500", "unknown error 520", "internal server error", "server error", "gateway", "overloaded")):
        return "抱歉，刚刚请求模型服务时临时失败了。请稍后再试一次。"
    if any(marker in lowered for marker in ("timeout", "timed out", "connection reset", "network")):
        return "抱歉，刚刚和模型服务通信超时了。请稍后再试一次。"
    return "抱歉，刚刚处理这条消息时出了点问题。请稍后再试一次。"


def _decode_wechat_aes_key(raw_value: str) -> bytes:
    text = (raw_value or "").strip()
    if not text:
        raise ValueError("Missing AES key")
    candidates: list[bytes] = []
    if all(ch in "0123456789abcdefABCDEF" for ch in text) and len(text) in {32, 48, 64}:
        try:
            candidates.append(bytes.fromhex(text))
        except ValueError:
            pass
    try:
        decoded = base64.b64decode(text)
        candidates.append(decoded)
        try:
            decoded_text = decoded.decode("ascii")
        except UnicodeDecodeError:
            decoded_text = ""
        if decoded_text and all(ch in "0123456789abcdefABCDEF" for ch in decoded_text) and len(decoded_text) in {32, 48, 64}:
            try:
                candidates.append(bytes.fromhex(decoded_text))
            except ValueError:
                pass
    except (binascii.Error, ValueError):
        pass
    for candidate in candidates:
        if len(candidate) in {16, 24, 32}:
            return candidate
    raise ValueError(f"Unsupported AES key format (len={len(text)})")


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
                    "item_list": [{"type": MESSAGE_ITEM_TEXT, "text_item": {"text": text}}],
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

    def get_upload_url(
        self,
        token: str,
        filekey: str,
        media_type: int,
        to_user_id: str,
        rawsize: int,
        rawfilemd5: str,
        filesize: int,
        aeskey_hex: str,
    ) -> dict[str, Any]:
        payload = json.dumps({
            "filekey": filekey,
            "media_type": media_type,
            "to_user_id": to_user_id,
            "rawsize": rawsize,
            "rawfilemd5": rawfilemd5,
            "filesize": filesize,
            "no_need_thumb": True,
            "aeskey": aeskey_hex,
            "base_info": {"channel_version": "trustworthy_assistant/1.0"},
        })
        response = self.client.post(
            f"{self.base_url}ilink/bot/getuploadurl",
            content=payload,
            headers=self._headers(token, payload),
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def upload_to_cdn(self, upload_url: str, ciphertext: bytes) -> str:
        response = self.client.post(
            upload_url,
            content=ciphertext,
            headers={"Content-Type": "application/octet-stream"},
            timeout=CDN_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        download_param = response.headers.get("x-encrypted-param", "")
        if not download_param:
            raise RuntimeError(f"CDN upload response missing x-encrypted-param header, status={response.status_code}")
        return download_param

    def download_cdn_media(self, encrypt_query_param: str) -> bytes:
        url = f"{_ensure_trailing_slash(CDN_BASE_URL)}download?encrypted_query_param={_url_encode(encrypt_query_param)}"
        response = self.client.get(url, timeout=CDN_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.content

    def upload_file(
        self,
        token: str,
        file_path: str | Path,
        to_user_id: str,
        media_type: int = UPLOAD_MEDIA_FILE,
    ) -> UploadedFileInfo:
        path = Path(file_path)
        plaintext = path.read_bytes()
        rawsize = len(plaintext)
        rawfilemd5 = hashlib.md5(plaintext).hexdigest()
        aeskey = os.urandom(16)
        filekey = secrets.token_hex(16)
        filesize = _aes_ecb_padded_size(rawsize)
        trace_id = f"wxsend-{filekey[:8]}"
        # #region debug-point F1:upload-file-start
        _debug_emit("F1", "wechat.py:upload_file", "prepare wechat file upload", {
            "file_name": path.name,
            "media_type": media_type,
            "to_user_id": to_user_id,
            "rawsize": rawsize,
            "ciphertext_size": filesize,
            "rawfilemd5": rawfilemd5,
        }, trace_id=trace_id)
        # #endregion
        upload_resp = self.get_upload_url(
            token=token,
            filekey=filekey,
            media_type=media_type,
            to_user_id=to_user_id,
            rawsize=rawsize,
            rawfilemd5=rawfilemd5,
            filesize=filesize,
            aeskey_hex=aeskey.hex(),
        )
        # #region debug-point F2:get-upload-url
        _debug_emit("F2", "wechat.py:upload_file", "wechat getuploadurl response", {
            "file_name": path.name,
            "media_type": media_type,
            "response_keys": sorted(list(upload_resp.keys()))[:20],
            "ret": upload_resp.get("ret"),
            "errcode": upload_resp.get("errcode"),
            "errmsg": str(upload_resp.get("errmsg") or "")[:240],
            "has_upload_param": bool(upload_resp.get("upload_param")),
            "has_upload_full_url": bool(upload_resp.get("upload_full_url")),
        }, trace_id=trace_id)
        # #endregion
        upload_param = str(upload_resp.get("upload_param") or "")
        upload_full_url = str(upload_resp.get("upload_full_url") or "")
        if upload_full_url:
            upload_url = upload_full_url
        elif upload_param:
            upload_url = (
                f"{_ensure_trailing_slash(CDN_BASE_URL)}upload"
                f"?encrypted_query_param={_url_encode(upload_param)}&filekey={_url_encode(filekey)}"
            )
        else:
            raise RuntimeError(f"getUploadUrl returned no upload target: {upload_resp}")
        ciphertext = _aes_ecb_encrypt(plaintext, aeskey)
        download_param = self.upload_to_cdn(upload_url, ciphertext)
        # #region debug-point F3:upload-file-complete
        _debug_emit("F3", "wechat.py:upload_file", "wechat file upload completed", {
            "file_name": path.name,
            "media_type": media_type,
            "download_param_len": len(download_param),
            "download_param_preview": download_param[:80],
        }, trace_id=trace_id)
        # #endregion
        return UploadedFileInfo(
            filekey=filekey,
            download_encrypted_query_param=download_param,
            aeskey_hex=aeskey.hex(),
            file_size=rawsize,
            file_size_ciphertext=filesize,
        )

    def send_image(self, token: str, to_user_id: str, uploaded: UploadedFileInfo, context_token: str, caption: str = "") -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if caption:
            items.append({"type": MESSAGE_ITEM_TEXT, "text_item": {"text": caption}})
        aes_key_b64 = base64.b64encode(bytes.fromhex(uploaded.aeskey_hex)).decode("utf-8")
        items.append({
            "type": MESSAGE_ITEM_IMAGE,
            "image_item": {
                "media": {
                    "encrypt_query_param": uploaded.download_encrypted_query_param,
                    "aes_key": aes_key_b64,
                    "encrypt_type": 1,
                },
                "aeskey": uploaded.aeskey_hex,
                "mid_size": uploaded.file_size_ciphertext,
                "hd_size": uploaded.file_size_ciphertext,
            },
        })
        return self._send_items(token, to_user_id, items, context_token)

    def send_video(self, token: str, to_user_id: str, uploaded: UploadedFileInfo, context_token: str, caption: str = "") -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if caption:
            items.append({"type": MESSAGE_ITEM_TEXT, "text_item": {"text": caption}})
        aes_key_b64 = base64.b64encode(bytes.fromhex(uploaded.aeskey_hex)).decode("utf-8")
        items.append({
            "type": MESSAGE_ITEM_VIDEO,
            "video_item": {
                "media": {
                    "encrypt_query_param": uploaded.download_encrypted_query_param,
                    "aes_key": aes_key_b64,
                    "encrypt_type": 1,
                },
                "video_size": uploaded.file_size_ciphertext,
            },
        })
        return self._send_items(token, to_user_id, items, context_token)

    def send_file(self, token: str, to_user_id: str, file_name: str, uploaded: UploadedFileInfo, context_token: str, caption: str = "") -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if caption:
            items.append({"type": MESSAGE_ITEM_TEXT, "text_item": {"text": caption}})
        aes_key_b64 = base64.b64encode(bytes.fromhex(uploaded.aeskey_hex)).decode("utf-8")
        items.append({
            "type": MESSAGE_ITEM_FILE,
            "file_item": {
                "media": {
                    "encrypt_query_param": uploaded.download_encrypted_query_param,
                    "aes_key": aes_key_b64,
                    "encrypt_type": 1,
                },
                "file_name": file_name,
                "len": str(uploaded.file_size),
            },
        })
        # #region debug-point F4:send-file-payload
        _debug_emit("F4", "wechat.py:send_file", "wechat file item payload", {
            "to_user_id": to_user_id,
            "file_name": file_name,
            "context_token_len": len(context_token or ""),
            "item_count": len(items),
            "file_item_keys": sorted(list(((items[-1].get("file_item") or {}).keys()))),
            "media_keys": sorted(list((((items[-1].get("file_item") or {}).get("media") or {}).keys()))),
            "file_len": str(uploaded.file_size),
            "ciphertext_size": uploaded.file_size_ciphertext,
        }, trace_id=f"wxfile-{uploaded.filekey[:8]}")
        # #endregion
        return self._send_items(token, to_user_id, items, context_token)

    def _send_items(self, token: str, to_user_id: str, items: list[dict[str, Any]], context_token: str) -> dict[str, Any]:
        payload = json.dumps({
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": f"ta-{secrets.token_hex(8)}",
                "message_type": 2,
                "message_state": 2,
                "item_list": items,
                "context_token": context_token,
            },
            "base_info": {"channel_version": "trustworthy_assistant/1.0"},
        })
        trace_id = f"wxitems-{secrets.token_hex(4)}"
        # #region debug-point F5:send-items-request
        _debug_emit("F5", "wechat.py:_send_items", "wechat send items request", {
            "to_user_id": to_user_id,
            "context_token_len": len(context_token or ""),
            "item_types": [item.get("type") for item in items],
            "payload_len": len(payload),
            "file_item_keys": sorted(list((((items[-1].get("file_item") or {}).keys())))) if items and items[-1].get("type") == MESSAGE_ITEM_FILE else [],
            "video_item_keys": sorted(list((((items[-1].get("video_item") or {}).keys())))) if items and items[-1].get("type") == MESSAGE_ITEM_VIDEO else [],
            "image_item_keys": sorted(list((((items[-1].get("image_item") or {}).keys())))) if items and items[-1].get("type") == MESSAGE_ITEM_IMAGE else [],
        }, trace_id=trace_id)
        # #endregion
        response = self.client.post(
            f"{self.base_url}ilink/bot/sendmessage",
            content=payload,
            headers=self._headers(token, payload),
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        parsed = response.json()
        # #region debug-point F6:send-items-response
        _debug_emit("F6", "wechat.py:_send_items", "wechat send items response", {
            "to_user_id": to_user_id,
            "status_code": response.status_code,
            "ret": parsed.get("ret"),
            "errcode": parsed.get("errcode"),
            "errmsg": str(parsed.get("errmsg") or "")[:240],
            "response_keys": sorted(list(parsed.keys()))[:20],
        }, trace_id=trace_id)
        # #endregion
        if int(parsed.get("ret") or 0) != 0:
            raise RuntimeError(
                f"sendMessage ret={parsed.get('ret')} errcode={parsed.get('errcode')} errmsg={parsed.get('errmsg')}"
            )
        return parsed

    def get_config(self, token: str, ilink_user_id: str, context_token: str) -> dict[str, Any]:
        payload = json.dumps({
            "ilink_user_id": ilink_user_id,
            "context_token": context_token,
            "base_info": {"channel_version": "trustworthy_assistant/1.0"},
        })
        response = self.client.post(
            f"{self.base_url}ilink/bot/getconfig",
            content=payload,
            headers=self._headers(token, payload),
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def send_typing(self, token: str, ilink_user_id: str, typing_ticket: str, status: int = 1) -> dict[str, Any]:
        payload = json.dumps({
            "ilink_user_id": ilink_user_id,
            "typing_ticket": typing_ticket,
            "status": status,
            "base_info": {"channel_version": "trustworthy_assistant/1.0"},
        })
        response = self.client.post(
            f"{self.base_url}ilink/bot/sendtyping",
            content=payload,
            headers=self._headers(token, payload),
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()


def _url_encode(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s, safe="")


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
        self._client: ILinkWeChatClient | None = None
        self._account: WeChatAccount | None = None
        self._context_tokens: dict[str, str] = {}
        self._instance_lock = None

    def _acquire_instance_lock(self, account_id: str) -> None:
        if self._instance_lock is not None:
            return
        lock_path = _instance_lock_path(self.config.root_dir, account_id)
        handle = lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise RuntimeError(
                f"检测到另一个 trustworthy-wechat 实例正在运行（account_id={account_id}）。请先停止旧进程。"
            )
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._instance_lock = handle

    def _release_instance_lock(self) -> None:
        if self._instance_lock is None:
            return
        try:
            fcntl.flock(self._instance_lock.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self._instance_lock.close()
        except Exception:
            pass
        self._instance_lock = None

    def _materialize_inbound_images(self, inbound: IncomingWeChatMessage) -> None:
        if not inbound.images or not self._client or not self._account:
            return
        media_dir = _incoming_media_dir(self.config.root_dir, self._account.account_id)
        for index, image in enumerate(inbound.images, start=1):
            if image.local_path:
                continue
            trace_id = f"wximg-{inbound.message_id or 'unknown'}-{index}"
            # #region debug-point W1:materialize-image
            _debug_emit("W1", "wechat.py:_materialize_inbound_images", "start materialize inbound image", {
                "sender_id": inbound.sender_id,
                "message_id": inbound.message_id,
                "index": index,
                "mime_type": image.mime_type,
                "has_encrypt_query_param": bool(image.encrypt_query_param),
                "has_aes_key_b64": bool(image.aes_key_b64),
                "encrypt_query_param_preview": image.encrypt_query_param[:80],
            }, trace_id=trace_id)
            # #endregion
            try:
                ciphertext = self._client.download_cdn_media(image.encrypt_query_param)
                aes_key = _decode_wechat_aes_key(image.aes_key_b64)
                # #region debug-point W1b:materialize-image-bytes
                _debug_emit("W1", "wechat.py:_materialize_inbound_images", "materialize inbound image bytes", {
                    "message_id": inbound.message_id,
                    "index": index,
                    "ciphertext_len": len(ciphertext),
                    "aes_key_len": len(aes_key),
                    "aes_key_preview": image.aes_key_b64[:16],
                }, trace_id=trace_id)
                # #endregion
                plaintext = _aes_ecb_decrypt(ciphertext, aes_key)
                mime_type, suffix = _guess_image_media_type(plaintext, image.mime_type)
                image.mime_type = mime_type or image.mime_type
                file_name = image.file_name.strip() or f"{inbound.message_id or 'msg'}-{index}{suffix or '.bin'}"
                target = media_dir / file_name
                if target.exists():
                    target = media_dir / f"{target.stem}-{int(time.time() * 1000)}{target.suffix}"
                target.write_bytes(plaintext)
                image.local_path = str(target)
                # #region debug-point W2:materialize-image-success
                _debug_emit("W2", "wechat.py:_materialize_inbound_images", "materialize inbound image success", {
                    "message_id": inbound.message_id,
                    "index": index,
                    "ciphertext_len": len(ciphertext),
                    "plaintext_len": len(plaintext),
                    "detected_mime_type": image.mime_type,
                    "local_path": image.local_path,
                }, trace_id=trace_id)
                # #endregion
            except Exception as exc:
                # #region debug-point W3:materialize-image-error
                _debug_emit("W3", "wechat.py:_materialize_inbound_images", "materialize inbound image failed", {
                    "message_id": inbound.message_id,
                    "index": index,
                    "error": str(exc)[:500],
                }, trace_id=trace_id)
                # #endregion
                self.on_event(f"failed to download inbound image for {inbound.sender_id}: {exc}")

    @staticmethod
    def _build_turn_input(inbound: IncomingWeChatMessage) -> str:
        lines: list[str] = []
        if inbound.quoted is not None:
            quoted_label = "这条微信消息带有引用。"
            if inbound.quoted.sender_id:
                quoted_label = f"这条微信消息带有引用，原发送者是 {inbound.quoted.sender_id}。"
            lines.append(quoted_label)
            if inbound.quoted.text:
                lines.append(f"被引用的上一条消息：{inbound.quoted.text}")
                lines.append("请把当前消息理解为用户对这段被引用内容的追问、补充或纠正。")
            else:
                lines.append("检测到引用动作，但当前没有拿到被引用消息的正文。请优先结合当前消息判断用户意图。")
        if inbound.text:
            lines.append(f"用户当前消息：{inbound.text}")
        if inbound.images:
            current_images = [image for image in inbound.images if not image.is_quoted]
            quoted_images = [image for image in inbound.images if image.is_quoted]
            if current_images:
                lines.append(f"用户这次还发送了 {len(current_images)} 张图片。")
                for index, image in enumerate(current_images, start=1):
                    if image.local_path:
                        lines.append(f"当前图片 {index} 本地路径：{image.local_path}")
                    else:
                        lines.append(f"当前图片 {index} 已收到，但当前下载失败，暂时无法读取内容。")
            if quoted_images:
                lines.append(f"被引用的上一条消息里还包含 {len(quoted_images)} 张图片。")
                for index, image in enumerate(quoted_images, start=1):
                    if image.local_path:
                        lines.append(f"被引用图片 {index} 本地路径：{image.local_path}")
                    else:
                        lines.append(f"被引用图片 {index} 已收到，但当前下载失败，暂时无法读取内容。")
            downloadable_images = [image for image in inbound.images if image.local_path]
            if downloadable_images:
                lines.append("如果需要理解图片，请使用 `read_image` 工具读取这些图片，再结合当前消息和引用内容回答。")
            else:
                lines.append("不要说未收到图片；应说明图片已收到，但当前还无法读取其内容。")
        if not lines:
            lines.append("用户发送了一条微信消息。")
        return "\n".join(lines)

    def _send_cron_result(self, channel: str, sender_id: str, text: str) -> None:
        if channel != "wechat" or not self._client or not self._account:
            return
        context_token = self._context_tokens.get(sender_id, "")
        if not context_token:
            context_token = load_context_tokens(self.config.root_dir, self._account.account_id).get(sender_id, "")
        if not context_token:
            self.on_event(f"skip cron reply for {sender_id}: missing context_token")
            return
        try:
            self._send_text_sequence(sender_id, text, context_token)
            self.on_event(f"sent cron reply to {sender_id}")
        except Exception as exc:
            self.on_event(f"failed to send cron reply to {sender_id}: {exc}")

    def _send_channel_text(self, text: str, channel: str, sender_id: str) -> None:
        self._send_cron_result(channel, sender_id, text)

    def _reply_text(self, user_id: str, text: str, context_token: str = "") -> None:
        if not self._client or not self._account:
            return
        resolved_context_token = context_token or self._context_tokens.get(user_id, "")
        if not resolved_context_token:
            resolved_context_token = load_context_tokens(self.config.root_dir, self._account.account_id).get(user_id, "")
        if not resolved_context_token:
            self.on_event(f"skip reply for {user_id}: missing context_token")
            return
        try:
            self._send_text_sequence(user_id, text, resolved_context_token)
        except Exception as exc:
            self.on_event(f"reply send failed for {user_id}: {exc}")

    def _send_text_sequence(self, user_id: str, text: str, context_token: str, allow_split: bool = True) -> None:
        if not self._client or not self._account:
            return
        normalized_text = (text or "").strip()
        if not normalized_text:
            return
        parts = _split_text_for_delivery(normalized_text) if allow_split else [normalized_text]
        if not parts:
            return
        trace_id = f"send-{secrets.token_hex(4)}"
        # #region debug-point Q2:send-sequence
        _debug_emit("Q2", "wechat.py:_send_text_sequence", "send text sequence", {
            "user_id": user_id,
            "allow_split": allow_split,
            "part_count": len(parts),
            "parts": [part[:120] for part in parts],
            "full_text_preview": normalized_text[:240],
        }, trace_id=trace_id)
        # #endregion
        self._send_typing(user_id, context_token, status=1)
        try:
            for index, part in enumerate(parts):
                self._client.send_text(self._account.token, user_id, part, context_token)
                if index < len(parts) - 1:
                    time.sleep(0.35)
        finally:
            self._send_typing(user_id, context_token, status=0)

    def _handle_approval_command(self, inbound: IncomingWeChatMessage) -> bool:
        command = (inbound.text or "").strip().lower()
        if command not in {"/yes", "/always", "/no", "/approvals"}:
            return False
        agent_id = self.app.agent_registry.default_agent_id
        session_key = self.app.session_manager.build_session_key(
            agent_id=agent_id,
            channel="wechat",
            user_id=inbound.sender_id,
        )
        self.app.tools.set_channel_context("wechat", inbound.sender_id, inbound.text, session_key)
        if command == "/approvals":
            lines = self.app.tools.format_pending_status_lines(session_key)
            self._reply_text(inbound.sender_id, "\n".join(lines), inbound.context_token)
            return True
        if command == "/yes":
            result = self.app.tools.approve_pending_command(session_key, remember=False)
        elif command == "/always":
            result = self.app.tools.approve_pending_command(session_key, remember=True)
        else:
            result = self.app.tools.reject_pending_command(session_key)
        self._reply_text(inbound.sender_id, result, inbound.context_token)
        return True

    def _resolve_typing_ticket(self, user_id: str, context_token: str) -> str:
        if not self._client or not self._account:
            return ""
        try:
            config_resp = self._client.get_config(self._account.token, user_id, context_token)
            return str(config_resp.get("typing_ticket") or "").strip()
        except Exception:
            return ""

    def _send_typing(self, user_id: str, context_token: str, status: int = 1) -> None:
        if not self._client or not self._account:
            return
        typing_ticket = self._resolve_typing_ticket(user_id, context_token)
        if not typing_ticket:
            return
        try:
            self._client.send_typing(self._account.token, user_id, typing_ticket, status)
        except Exception:
            pass

    def _send_file(self, file_path: str, channel: str, user_id: str) -> None:
        if channel != "wechat" or not self._client or not self._account:
            raise RuntimeError("File sending is only available via WeChat channel")
        context_token = self._context_tokens.get(user_id, "")
        if not context_token:
            context_token = load_context_tokens(self.config.root_dir, self._account.account_id).get(user_id, "")
        if not context_token:
            raise RuntimeError(f"No context_token for user {user_id}, cannot send file")
        p = Path(file_path)
        media_type = _classify_media_type(p)
        trace_id = f"wxlocal-{secrets.token_hex(4)}"
        # #region debug-point F0:local-send-file
        _debug_emit("F0", "wechat.py:_send_file", "local send_file requested", {
            "file_path": str(p),
            "file_name": p.name,
            "file_size": p.stat().st_size,
            "media_type": media_type,
            "channel": channel,
            "user_id": user_id,
            "context_token_len": len(context_token or ""),
        }, trace_id=trace_id)
        # #endregion
        self.on_event(f"uploading file {p.name} ({p.stat().st_size} bytes) to CDN...")
        self._send_typing(user_id, context_token, status=1)
        try:
            uploaded = self._client.upload_file(
                token=self._account.token,
                file_path=file_path,
                to_user_id=user_id,
                media_type=media_type,
            )
            self.on_event(f"CDN upload complete, sending to {user_id}...")
            if media_type == UPLOAD_MEDIA_IMAGE:
                self._client.send_image(self._account.token, user_id, uploaded, context_token)
            elif media_type == UPLOAD_MEDIA_VIDEO:
                self._client.send_video(self._account.token, user_id, uploaded, context_token)
            else:
                self._client.send_file(self._account.token, user_id, p.name, uploaded, context_token)
            self.on_event(f"sent file {p.name} to {user_id}")
        finally:
            self._send_typing(user_id, context_token, status=0)

    def run_forever(self) -> None:
        account = load_wechat_account(self.config.root_dir, self.config.wechat_account_id)
        if account is None:
            raise RuntimeError("未找到微信账号，请先运行 trustworthy-wechat-login")
        self._acquire_instance_lock(account.account_id)
        context_tokens = load_context_tokens(self.config.root_dir, account.account_id)
        sync_buffer = load_sync_buffer(self.config.root_dir, account.account_id)
        client = ILinkWeChatClient(account.base_url)
        self._client = client
        self._account = account
        self._context_tokens = context_tokens
        self.on_event(f"using account {account.account_id}")
        self.app.cron_scheduler.channel_sender = self._send_cron_result
        self.app.tools.file_sender = self._send_file
        self.app.tools.message_sender = self._send_channel_text
        self.app.cron_scheduler.start()
        try:
            while True:
                updates = client.get_updates(account.token, get_updates_buf=sync_buffer)
                sync_buffer = str(updates.get("get_updates_buf") or sync_buffer)
                save_sync_buffer(self.config.root_dir, account.account_id, sync_buffer)
                messages = updates.get("msgs") or []
                for message in messages:
                    raw_item_list = (message or {}).get("item_list")
                    raw_item_summaries = []
                    if isinstance(raw_item_list, list):
                        for item in raw_item_list[:8]:
                            node = item or {}
                            image_node = (node.get("image_item") or {}) if isinstance(node.get("image_item"), dict) else {}
                            media_node = (image_node.get("media") or {}) if isinstance(image_node.get("media"), dict) else {}
                            raw_item_summaries.append(
                                {
                                    "type": node.get("type"),
                                    "keys": sorted(list(node.keys()))[:20],
                                    "has_ref_msg": isinstance(node.get("ref_msg"), dict),
                                    "image_item_keys": sorted(list(image_node.keys()))[:20],
                                    "media_keys": sorted(list(media_node.keys()))[:20],
                                    "image_aeskey_present": bool(image_node.get("aeskey")),
                                    "image_aes_key_present": bool(image_node.get("aes_key")),
                                    "media_aes_key_present": bool(media_node.get("aes_key")),
                                    "media_encrypt_query_param_present": bool(media_node.get("encrypt_query_param")),
                                    "thumb_size_keys": sorted(list((image_node.get("thumb_size") or {}).keys()))[:20] if isinstance(image_node.get("thumb_size"), dict) else [],
                                    "mid_size_keys": sorted(list((image_node.get("mid_size") or {}).keys()))[:20] if isinstance(image_node.get("mid_size"), dict) else [],
                                    "hd_size_keys": sorted(list((image_node.get("hd_size") or {}).keys()))[:20] if isinstance(image_node.get("hd_size"), dict) else [],
                                }
                            )
                    raw_trace_id = f"raw-{secrets.token_hex(4)}"
                    # #region debug-point W0:raw-inbound
                    _debug_emit("W0", "wechat.py:run_forever", "raw inbound message summary", {
                        "message_id": str((message or {}).get("message_id") or ""),
                        "seq": str((message or {}).get("seq") or ""),
                        "message_type": (message or {}).get("message_type"),
                        "item_count": len(raw_item_list) if isinstance(raw_item_list, list) else 0,
                        "item_summaries": raw_item_summaries,
                    }, trace_id=raw_trace_id)
                    # #endregion
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
                    trace_id = f"inb-{secrets.token_hex(4)}"
                    # #region debug-point Q4:inbound-dedup
                    _debug_emit("Q4", "wechat.py:run_forever", "wechat inbound before dedup", {
                        "sender_id": inbound.sender_id,
                        "message_id": inbound.message_id,
                        "seq": str((message or {}).get("seq") or ""),
                        "received_at": inbound.received_at,
                        "has_quote": bool(inbound.quoted),
                        "quote_text": (inbound.quoted.text if inbound.quoted else "")[:120],
                        "text": (inbound.text or "")[:120],
                        "dedup_key": dedup_key,
                        "seen_before": dedup_key in self._seen,
                    }, trace_id=trace_id)
                    # #endregion
                    if dedup_key in self._seen:
                        continue
                    self._seen.add(dedup_key)
                    if len(self._seen) > 2048:
                        self._seen = set(list(self._seen)[-1024:])
                    if inbound.context_token:
                        persist_context_token(self.config.root_dir, account.account_id, inbound.sender_id, inbound.context_token)
                        self._context_tokens[inbound.sender_id] = inbound.context_token
                    self._materialize_inbound_images(inbound)
                    turn_input = self._build_turn_input(inbound)
                    # #region debug-point Q1:turn-input
                    _debug_emit("Q1", "wechat.py:run_forever", "wechat turn input built", {
                        "sender_id": inbound.sender_id,
                        "message_id": inbound.message_id,
                        "has_quote": bool(inbound.quoted),
                        "quote_text": (inbound.quoted.text if inbound.quoted else "")[:160],
                        "image_count": len(inbound.images),
                        "turn_input": turn_input[:500],
                    }, trace_id=trace_id)
                    # #endregion
                    self.on_event(
                        f"recv {inbound.sender_id}: text={bool(inbound.text)} images={len(inbound.images)} quote={bool(inbound.quoted)}"
                    )
                    if self._handle_approval_command(inbound):
                        continue
                    agent = self.app.agent_registry.get(self.app.agent_registry.default_agent_id)
                    result = self.app.turn_processor.process_turn(
                        turn_input,
                        agent=agent,
                        channel="wechat",
                        user_id=inbound.sender_id,
                        on_progress=lambda text, sender_id=inbound.sender_id, token=inbound.context_token: self._reply_text(sender_id, text, token),
                    )
                    reply = (result.assistant_text or "").strip()
                    # #region debug-point Q3:turn-result
                    _debug_emit("Q3", "wechat.py:run_forever", "wechat turn result", {
                        "sender_id": inbound.sender_id,
                        "message_id": inbound.message_id,
                        "tool_roundtrips": result.tool_roundtrips,
                        "error_count": len(result.errors or []),
                        "assistant_text": reply[:500],
                    }, trace_id=trace_id)
                    # #endregion
                    if result.errors:
                        self.on_event(
                            f"turn processing failed for {inbound.sender_id}: {'; '.join(result.errors)}"
                        )
                        reply = _build_user_facing_error_reply(result.errors)
                    if not reply:
                        continue
                    context_token = inbound.context_token or self._context_tokens.get(inbound.sender_id, "")
                    if not context_token:
                        self.on_event(f"skip reply for {inbound.sender_id}: missing context_token")
                        continue
                    try:
                        self._send_text_sequence(inbound.sender_id, reply, context_token, allow_split=True)
                        self.on_event(f"sent reply to {inbound.sender_id}")
                    except Exception as exc:
                        self.on_event(f"failed to send reply to {inbound.sender_id}: {exc}")
        except KeyboardInterrupt:
            self.on_event("stopped by user")
        finally:
            self.app.cron_scheduler.stop()
            client.close()
            self._release_instance_lock()
            sys.stdout.flush()
