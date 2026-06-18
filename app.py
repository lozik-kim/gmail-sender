#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
개별 발송 웹앱 — Brevo HTTP API 방식
- 여러 명에게 '개인 메일'을 따로따로 발송 (수신자끼리 주소 안 보임).
- 서식(굵게/색상/링크), 구글 드라이브 링크, PC 파일 첨부 지원.
- Render 무료 서버는 SMTP를 차단하므로, HTTPS로 동작하는 Brevo API를 사용.
- 입력한 Brevo API 키는 서버에 저장하지 않고 발송에만 사용.

[준비물 — Brevo]
  1) https://www.brevo.com 무료 가입
  2) 발신자 인증: Settings → Senders → 발신 이메일 추가 → 인증 메일 클릭
  3) API 키 발급: Settings → SMTP & API → API Keys → Generate
  무료 플랜: 하루 300통

로컬 실행:  python3 app.py   →  http://localhost:8000
"""

import os
import re
import json
import time
import base64
import html as html_lib

import requests
from flask import Flask, request, render_template, Response, stream_with_context

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
MAX_RECIPIENTS = 300                 # Brevo 무료 하루 한도에 맞춘 상한
MAX_TOTAL_BYTES = 10 * 1024 * 1024   # 첨부 총 용량(여유있게 10MB)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024


def parse_recipients(raw: str):
    found = EMAIL_RE.findall(raw or "")
    seen, result = set(), []
    for e in found:
        k = e.lower()
        if k not in seen:
            seen.add(k)
            result.append(e)
    return result


def nl2br_escape(text: str) -> str:
    return html_lib.escape(text).replace("\n", "<br>")


def send_via_brevo(api_key, sender_email, sender_name, to_addr, subject, html_body, attachments):
    sender = {"email": sender_email}
    if sender_name:
        sender["name"] = sender_name
    payload = {
        "sender": sender,
        "to": [{"email": to_addr}],
        "subject": subject or " ",
        "htmlContent": html_body or " ",
    }
    if attachments:
        payload["attachment"] = [
            {"name": fname, "content": base64.b64encode(data).decode("ascii")}
            for fname, data in attachments
        ]
    r = requests.post(
        BREVO_URL,
        json=payload,
        headers={"api-key": api_key, "accept": "application/json",
                 "content-type": "application/json"},
        timeout=30,
    )
    if r.status_code in (200, 201):
        return
    # 오류 메시지 정리
    try:
        msg = r.json().get("message", r.text)
    except Exception:
        msg = r.text
    raise RuntimeError(f"{r.status_code}: {msg}")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/send", methods=["POST"])
def send():
    f = request.form
    api_key = (f.get("api_key") or "").strip()
    sender_email = (f.get("sender") or "").strip()
    from_name = (f.get("from_name") or "").strip()
    subject = (f.get("subject") or "").strip()
    body_html = f.get("body_html") or ""
    signature = (f.get("signature") or "").rstrip()
    recipients = parse_recipients(f.get("recipients") or "")
    try:
        delay = max(0.0, min(10.0, float(f.get("delay", 0.5))))
    except (TypeError, ValueError):
        delay = 0.5

    if signature:
        body_html = body_html.rstrip() + "<br><br>-- <br>" + nl2br_escape(signature)

    attachments = []
    total_bytes = 0
    for fs in request.files.getlist("attachments"):
        if not fs or not fs.filename:
            continue
        data = fs.read()
        total_bytes += len(data)
        attachments.append((fs.filename, data))

    def event(obj):
        return json.dumps(obj, ensure_ascii=False) + "\n"

    @stream_with_context
    def generate():
        if not api_key:
            yield event({"type": "error", "msg": "Brevo API 키를 입력하세요."}); return
        if not sender_email or not EMAIL_RE.fullmatch(sender_email):
            yield event({"type": "error", "msg": "올바른 발신자 이메일을 입력하세요. (Brevo에서 인증한 주소)"}); return
        if not recipients:
            yield event({"type": "error", "msg": "받는 사람이 없습니다."}); return
        if len(recipients) > MAX_RECIPIENTS:
            yield event({"type": "error", "msg": f"한 번에 최대 {MAX_RECIPIENTS}명까지 보낼 수 있습니다. (Brevo 무료 하루 300통)"}); return
        if total_bytes > MAX_TOTAL_BYTES:
            mb = total_bytes / 1024 / 1024
            yield event({"type": "error",
                         "msg": f"첨부 용량이 {mb:.1f}MB로 한도(10MB)를 초과했습니다. 큰 파일은 구글 드라이브 링크를 사용하세요."}); return

        att_note = f" (첨부 {len(attachments)}개)" if attachments else ""
        yield event({"type": "start", "total": len(recipients), "note": att_note})
        yield event({"type": "info", "msg": f"Brevo로 발송을 시작합니다.{att_note}"})

        success, fail = 0, 0
        for i, to_addr in enumerate(recipients, 1):
            try:
                send_via_brevo(api_key, sender_email, from_name, to_addr,
                               subject, body_html, attachments)
                success += 1
                yield event({"type": "ok", "i": i, "addr": to_addr})
            except Exception as e:
                fail += 1
                emsg = str(e)
                if emsg.startswith("401"):
                    emsg = "API 키가 올바르지 않습니다."
                elif "sender" in emsg.lower() and ("not" in emsg.lower() or "valid" in emsg.lower()):
                    emsg = "발신자 이메일이 Brevo에서 인증되지 않았습니다. (Settings → Senders 확인)"
                yield event({"type": "fail", "i": i, "addr": to_addr, "msg": emsg})
            if delay and i < len(recipients):
                time.sleep(delay)

        yield event({"type": "done", "success": success, "fail": fail})

    return Response(generate(), mimetype="application/x-ndjson")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
