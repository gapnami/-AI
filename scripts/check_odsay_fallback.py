"""ODsay 직접 호출 후 실패 시 프록시로 폴백하여 결과를 비교하는 스크립트
사용법: venv 활성화 후 프로젝트 루트에서 실행
    python scripts/check_odsay_fallback.py
"""
import os
import sys
import warnings
warnings.filterwarnings('ignore')

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.api_config import config
import requests
from urllib.parse import urlencode, quote_plus

API_KEY = getattr(config.odsay, 'api_key', None)
PROXY_HOST = os.getenv('ODSAY_PROXY_URL', 'https://ai-navigator-2usw.onrender.com')
TIMEOUT = 15

# 테스트할 좌표들: (start_lon,start_lat) notation used by ODsay params SX,SY
TESTS = [
    # short route (example): 강남역 주변 -> 서울역 주변
    (127.0276, 37.4979, 126.978, 37.5665),
    # Busan Station -> Seoul Station
    (129.0756, 35.1156, 126.9706, 37.5567),
]


def call_direct(api_key, sx, sy, ex, ey):
    params = {'apiKey': api_key, 'SX': sx, 'SY': sy, 'EX': ex, 'EY': ey}
    qs = urlencode(params, quote_via=quote_plus)
    url = f"https://api.odsay.com/v1/api/searchPubTransPathT?{qs}"
    r = requests.get(url, timeout=TIMEOUT, verify=False)
    return r.status_code, r.text, r


def call_proxy(proxy_host, sx, sy, ex, ey, with_key=True, api_key=None):
    params = {'SX': sx, 'SY': sy, 'EX': ex, 'EY': ey}
    if with_key and api_key:
        params['apiKey'] = api_key
    qs = urlencode(params, quote_via=quote_plus)
    # try proxy endpoint that mirrors ODsay path
    url1 = f"{proxy_host}/v1/api/searchPubTransPathT?{qs}"
    # try proxy root fallback
    url2 = f"{proxy_host}/?{qs}"
    # try both
    for url in (url1, url2):
        try:
            r = requests.get(url, timeout=TIMEOUT, verify=False)
            return r.status_code, r.text, r, url
        except Exception as e:
            # return exception for logging if all fail
            last_exc = e
    return None, None, None, None


if __name__ == '__main__':
    print('Loaded key repr:', repr(API_KEY))
    if not API_KEY:
        print('ODsay API 키가 설정되지 않았습니다. .env 확인하세요.')
        sys.exit(1)

    for sx, sy, ex, ey in TESTS:
        print('\n=== TEST COORDS ===')
        print('SX,SY -> EX,EY:', sx, sy, '->', ex, ey)

        print('\n-- Direct ODsay --')
        try:
            status, text, resp = call_direct(API_KEY, sx, sy, ex, ey)
            print('Status:', status)
            print('Text:', text[:1000])
            try:
                j = resp.json()
                if j.get('error'):
                    print('Direct returned error:', j['error'])
                else:
                    print('Direct success: result keys', list(j.keys()))
            except Exception:
                print('Direct: non-json or parse failed')
        except Exception as e:
            print('Direct request failed:', e)

        print('\n-- Proxy attempts --')
        # attempt proxy with apiKey param
        status, text, resp, used_url = call_proxy(PROXY_HOST, sx, sy, ex, ey, with_key=True, api_key=API_KEY)
        if status is None:
            print('Proxy (with key) requests all failed or timed out')
        else:
            print('Tried URL:', used_url)
            print('Status:', status)
            print('Text:', text[:1000])
            try:
                j = resp.json()
                print('Proxy-with-key JSON keys:', list(j.keys()))
            except Exception:
                print('Proxy-with-key: non-json or parse failed')

        print('\n-- Proxy attempts (without sending apiKey) --')
        status, text, resp, used_url = call_proxy(PROXY_HOST, sx, sy, ex, ey, with_key=False)
        if status is None:
            print('Proxy (no key) requests all failed or timed out')
        else:
            print('Tried URL:', used_url)
            print('Status:', status)
            print('Text:', text[:1000])
            try:
                j = resp.json()
                print('Proxy-no-key JSON keys:', list(j.keys()))
            except Exception:
                print('Proxy-no-key: non-json or parse failed')

    print('\nAll tests completed')
