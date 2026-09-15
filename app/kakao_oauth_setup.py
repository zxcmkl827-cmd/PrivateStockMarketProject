"""카카오 액세스/리프레시 토큰 최초 발급 도우미 (브라우저 로그인 후 1회 수동 실행)."""
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
DEFAULT_REDIRECT_URI = "http://localhost:5000/oauth"

load_dotenv(ENV_PATH)


def exchange_code_for_token(
    code: str, client_id: str, redirect_uri: str, client_secret: str | None = None
) -> dict:
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    if client_secret:
        data["client_secret"] = client_secret

    resp = requests.post(TOKEN_URL, data=data, timeout=10)
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    import os

    if len(sys.argv) < 2:
        print(f"사용법: python3 app/kakao_oauth_setup.py <인가코드> [redirect_uri={DEFAULT_REDIRECT_URI}]")
        return 1

    code = sys.argv[1]
    redirect_uri = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_REDIRECT_URI
    client_id = os.environ["KAKAO_REST_API_KEY"]
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET")

    tokens = exchange_code_for_token(code, client_id, redirect_uri, client_secret)
    set_key(str(ENV_PATH), "KAKAO_ACCESS_TOKEN", tokens["access_token"])
    if "refresh_token" in tokens:
        set_key(str(ENV_PATH), "KAKAO_REFRESH_TOKEN", tokens["refresh_token"])

    print("액세스/리프레시 토큰을 .env에 저장했습니다.")
    print(f"만료(초): access={tokens.get('expires_in')}, refresh={tokens.get('refresh_token_expires_in')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
