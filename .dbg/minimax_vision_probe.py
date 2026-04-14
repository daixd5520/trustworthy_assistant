import base64
import json
import sys
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def derive_base_url(raw: str) -> str:
    normalized = (raw or "").strip().rstrip("/")
    if not normalized:
        return "https://api.minimaxi.com/v1"
    if normalized.endswith("/anthropic"):
        return normalized[: -len("/anthropic")] + "/v1"
    if normalized.endswith("/anthropic/messages"):
        return normalized[: -len("/anthropic/messages")] + "/v1"
    return normalized


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    env = load_env(root / ".env")
    model = sys.argv[1] if len(sys.argv) > 1 else env.get("MODEL_ID", "MiniMax-M2.7")
    mode = sys.argv[2] if len(sys.argv) > 2 else "inline"
    image_path = (
        Path(sys.argv[3])
        if len(sys.argv) > 3
        else root / ".wechat_personal/incoming/0bbec9eb31a9_im.bot/7449503693530876296-1.jpg"
    )
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    media_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    url = derive_base_url(env.get("ANTHROPIC_BASE_URL", "")) + "/chat/completions"
    if mode == "image_url":
        content: str | list[dict[str, object]] = [
            {"type": "text", "text": "请用一句话描述这张图片的主要内容。"},
            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
        ]
    else:
        content = (
            "请用一句话描述这张图片的主要内容。"
            "请识别这张图片，并优先描述其中主体、场景和可见文字。"
            f"[图片base64:{image_b64}]"
        )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": content,
            }
        ],
        "max_tokens": 200,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {env['ANTHROPIC_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print("STATUS", exc.code)
        print(exc.read().decode("utf-8", "ignore")[:4000])
        return 1
    print("MODEL", body.get("model", ""))
    print("TEXT", str(body["choices"][0]["message"]["content"]).replace("\n", " ")[:1000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
