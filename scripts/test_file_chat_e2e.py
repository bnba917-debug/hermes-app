#!/usr/bin/env python3
"""Quick e2e: upload file + ask question via app gateway."""

from __future__ import annotations

import json
import os
import sys
import uuid
import urllib.error
import urllib.request

BASE = os.environ.get("HERMES_APP_GATEWAY_URL", "http://127.0.0.1:8787")
PHONE = os.environ.get("HERMES_E2E_PHONE", "8613900139000")
DEV_CODE = os.environ.get("HERMES_E2E_SMS_CODE", "111111")


def main() -> int:
    req = urllib.request.Request(
        f"{BASE}/v1/auth/login",
        data=json.dumps({"phone": PHONE, "code": DEV_CODE}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        token = json.loads(r.read())["access_token"]

    headers = {
        "Authorization": f"Bearer {token}",
        "X-User-Token": token,
        "X-Hermes-Session-Id": "app",
    }

    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
    file_body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="test.txt"\r\n'
        f"Content-Type: text/plain\r\n\r\n"
        f"Hello from uploaded file. The secret code is BLUEFISH.\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/v1/chat/attachments",
        data=file_body,
        headers={
            **headers,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        meta = json.loads(r.read())
    print("upload:", meta)

    text = "这个文件里写的秘密代码是什么？"
    inline = meta.get("inline_text")
    path = meta.get("path", "")
    name = meta.get("filename", "test.txt")
    if inline:
        msg = f"{text}\n\n--- {name} ---\n{inline}"
    elif path:
        msg = (
            f"{text}\n\n[附件「{name}」已保存至工作区路径 `{path}`，"
            "请使用 read_file 读取并回答]"
        )
    else:
        msg = text

    body = {
        "messages": [{"role": "user", "content": msg}],
        "stream": False,
        "use_server_history": False,
    }
    req = urllib.request.Request(
        f"{BASE}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={**headers, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            ans = json.loads(r.read())["choices"][0]["message"]["content"]
            print("ANSWER:", ans[:500])
            return 0
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read()[:500])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
