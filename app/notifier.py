"""카카오톡(나에게 보내기)/이메일 발송 연동. 카카오 실패 시 이메일로 자동 대체."""
import json
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

KAKAO_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

load_dotenv(ENV_PATH)


def refresh_kakao_access_token() -> str:
    """리프레시 토큰으로 새 액세스 토큰을 발급받는다(액세스 토큰은 약 6시간만 유효)."""
    client_id = os.environ["KAKAO_REST_API_KEY"]
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET")
    refresh_token = os.environ["KAKAO_REFRESH_TOKEN"]

    data = {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh_token}
    if client_secret:
        data["client_secret"] = client_secret

    resp = requests.post(KAKAO_TOKEN_URL, data=data, timeout=10)
    resp.raise_for_status()
    tokens = resp.json()

    access_token = tokens["access_token"]
    if ENV_PATH.exists():
        set_key(str(ENV_PATH), "KAKAO_ACCESS_TOKEN", access_token)
        if "refresh_token" in tokens:
            set_key(str(ENV_PATH), "KAKAO_REFRESH_TOKEN", tokens["refresh_token"])
    return access_token


def send_kakao_memo(message: str, access_token: str) -> bool:
    headers = {"Authorization": f"Bearer {access_token}"}
    template = json.dumps({"object_type": "text", "text": message, "link": {}})
    resp = requests.post(KAKAO_MEMO_URL, headers=headers, data={"template_object": template}, timeout=10)
    if resp.status_code != 200:
        print(f"[kakao] 발송 실패: status={resp.status_code} body={resp.text[:300]}", file=sys.stderr)
    return resp.status_code == 200


def send_email(subject: str, body: str) -> bool:
    sender = os.environ["EMAIL_SENDER"]
    password = os.environ["EMAIL_APP_PASSWORD"]
    recipient = os.environ.get("EMAIL_RECIPIENT", sender)
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())
    return True


def send_notification(message: str, subject: str = "종목 알림") -> str:
    """카카오톡을 우선 시도하고 실패하면 이메일로 대체 발송. 실제 사용된 채널명을 반환."""
    if os.environ.get("KAKAO_REFRESH_TOKEN"):
        try:
            access_token = refresh_kakao_access_token()
            if send_kakao_memo(message, access_token):
                return "kakao"
        except (requests.RequestException, KeyError) as exc:
            print(f"[kakao] 토큰 갱신/발송 중 오류로 이메일로 대체: {exc!r}", file=sys.stderr)

    if os.environ.get("EMAIL_SENDER") and os.environ.get("EMAIL_APP_PASSWORD"):
        send_email(subject, message)
        return "email"

    raise RuntimeError("카카오톡/이메일 발송 모두 실패했거나 설정되지 않음")
