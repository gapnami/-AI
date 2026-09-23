import warnings
warnings.filterwarnings('ignore')
from config.api_config import config
import requests
from urllib.parse import urlencode, quote_plus

# Busan Station (부산역) -> Seoul Station (서울역)
# 부산역 대략 좌표: (35.1156, 129.0756)
# 서울역 대략 좌표: (37.5567, 126.9706)

k = getattr(config.odsay, 'api_key', None)
print('Loaded key repr:', repr(k))
params = {'apiKey': k, 'SX':129.0756, 'SY':35.1156, 'EX':126.9706, 'EY':37.5567}
qs = urlencode(params, quote_via=quote_plus)
url = f"https://api.odsay.com/v1/api/searchPubTransPathT?{qs}"
print('Request URL:', url)
try:
    r = requests.get(url, timeout=15, verify=False)
    print('Status:', r.status_code)
    print('Response text:', r.text)
    try:
        print('JSON keys:', list(r.json().keys()))
    except Exception as e:
        print('JSON parse error:', e)
except Exception as e:
    print('Request failed:', e)
