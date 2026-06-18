#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gmail 개별 발송 — 웹 버전 (HTML 메일 + 첨부파일 + 링크 지원)
- 브라우저에서 접속해 여러 명에게 '개인 메일'을 따로따로 발송합니다.
- 받는 사람들은 서로의 주소를 볼 수 없습니다.
- 서식(굵게/색상), 클릭 링크, 구글 드라이브 링크, PC 파일 첨부를 지원합니다.
- 입력한 Gmail 앱 비밀번호는 서버에 저장하지 않고, 발송에만 한 번 사용됩니다.

로컬 실행:  python3 app.py   →  http://localhost:8000
"""

import os
import re
import ssl
import json
import time
import html as html_lib
import smtplib
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from email import encoders

from flask import Flask, request, render_template, Response, stream_with_context

try:
    import certifi
    _CAFILE = certifi.where()
except ImportError:
    _CAFILE = None

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
MAX_RECIPIENTS = 500           # 한 번 요청당 안전 상한
MAX_TOTAL_BYTES = 25 * 1024 * 1024  # Gmail 첨부 총 용량 한도(약 25MB)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 요청 본문 상한


def parse_recipients(raw: str):
    found = EMAIL_RE.findall(raw or "")
    seen, result = set(), []
    for e in found:
        k = e.lower()
        if k not in seen:
            seen.add(k)
            result.append(e)
    return result


def html_to_text(html_str: str) -> str:
    """HTML 본문에서 일반 텍스트 대체본을 간단히 생성(메일 클라이언트 호환용)."""
    text = re.sub(r"<\s*br\s*/?>", "\n", html_str, flags=re.I)
    text = re.sub(r"</\s*(div|p|li|tr|h[1-6])\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    return text.strip()


def nl2br_escape(text: str) -> str:
    """일반 텍스트(서명 등)를 안전한 HTML로 변환."""
    return html_lib.escape(text).replace("\n", "<br>")


def build_message(sender, from_name, to_addr, subject, html_body, attachments):
    msg = MIMEMultipart("mixed")
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), sender)) if from_name else sender
    msg["To"] = to_addr
    msg["Subject"] = Header(subject, "utf-8")

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_to_text(html_body) or " ", "plain", "utf-8"))
    alt.attach(MIMEText(html_body or " ", "html", "utf-8"))
    msg.attach(alt)

    for fname, data in attachments:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", fname))
        msg.attach(part)
    return msg


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/send", methods=["POST"])
def send():
    f = request.form
    sender = (f.get("sender") or "").strip()
    password = (f.get("password") or "").replace(" ", "").strip()
    from_name = (f.get("from_name") or "").strip()
    subject = (f.get("subject") or "").strip()
    body_html = f.get("body_html") or ""
    signature = (f.get("signature") or "").rstrip()
    recipients = parse_recipients(f.get("recipients") or "")
    try:
        delay = max(0.0, min(10.0, float(f.get("delay", 1.0))))
    except (TypeError, ValueError):
        delay = 1.0

    if signature:
        body_html = body_html.rstrip() + "<br><br>-- <br>" + nl2br_escape(signature)

    # 첨부파일을 메모리로 미리 읽음 (스트리밍 응답 전에 요청 컨텍스트에서 처리)
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
        if not sender or not EMAIL_RE.fullmatch(sender):
            yield event({"type": "error", "msg": "올바른 Gmail 주소를 입력하세요."}); return
        if not password:
            yield event({"type": "error", "msg": "앱 비밀번호를 입력하세요."}); return
        if not recipients:
            yield event({"type": "error", "msg": "받는 사람이 없습니다."}); return
        if len(recipients) > MAX_RECIPIENTS:
            yield event({"type": "error", "msg": f"한 번에 최대 {MAX_RECIPIENTS}명까지 보낼 수 있습니다."}); return
        if total_bytes > MAX_TOTAL_BYTES:
            mb = total_bytes / 1024 / 1024
            yield event({"type": "error",
                         "msg": f"첨부 용량이 {mb:.1f}MB로 한도(25MB)를 초과했습니다. 큰 파일은 구글 드라이브 링크를 사용하세요."}); return

        att_note = f" (첨부 {len(attachments)}개)" if attachments else ""
        yield event({"type": "start", "total": len(recipients), "note": att_note})

        success, fail = 0, 0
        try:
            context = ssl.create_default_context(cafile=_CAFILE)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as server:
                server.starttls(context=context)
                server.login(sender, password)
                yield event({"type": "info", "msg": f"로그인 성공. 발송을 시작합니다.{att_note}"})

                for i, to_addr in enumerate(recipients, 1):
                    try:
                        msg = build_message(sender, from_name, to_addr, subject, body_html, attachments)
                        server.sendmail(sender, [to_addr], msg.as_string())
                        success += 1
                        yield event({"type": "ok", "i": i, "addr": to_addr})
                    except Exception as e:
                        fail += 1
                        yield event({"type": "fail", "i": i, "addr": to_addr, "msg": str(e)})
                    if delay and i < len(recipients):
                        time.sleep(delay)

        except smtplib.SMTPAuthenticationError:
            yield event({"type": "error",
                         "msg": "로그인 실패: 일반 비밀번호가 아닌 '앱 비밀번호'를 사용하세요. (2단계 인증 필요)"})
            return
        except Exception as e:
            yield event({"type": "error", "msg": f"오류: {e}"}); return

        yield event({"type": "done", "success": success, "fail": fail})

    return Response(generate(), mimetype="application/x-ndjson")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
