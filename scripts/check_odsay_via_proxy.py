import warnings
warnings.filterwarnings('ignore')
from urllib.parse import urlencode, quote_plus
import requests

# Coordinates: Busan Station -> Seoul Station
SX, SY = 129.0756, 35.1156
EX, EY = 126.9706, 37.5567

API_KEY = 'opr3qVsjxHwBy8GuJiTzoQ'  # provided
PROXY_HOST = 'https://ai-navigator-2usw.onrender.com'

def call(url):
    try:
        r = requests.get(url, timeout=15, verify=False)
        print('URL:', url)
        print('Status:', r.status_code)
        print('Text:', r.text)
        try:
            print('JSON keys:', list(r.json().keys()))
        except Exception as e:
            print('JSON parse error:', e)
    except Exception as e:
        print('Request failed:', e)

# Direct ODsay
params = {'apiKey': API_KEY, 'SX': SX, 'SY': SY, 'EX': EX, 'EY': EY}
qs = urlencode(params, quote_via=quote_plus)
odsay_url = f"https://api.odsay.com/v1/api/searchPubTransPathT?{qs}"
print('--- Direct ODsay ---')
call(odsay_url)

# Via provided proxy host (assume same path)
proxy_url = f"{PROXY_HOST}/v1/api/searchPubTransPathT?{qs}"
print('\n--- Via Proxy Host ---')
call(proxy_url)

# Also try proxy root endpoint if available
proxy_root = f"{PROXY_HOST}/?{qs}"
print('\n--- Proxy Root (?) ---')
call(proxy_root)
