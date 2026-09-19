import warnings
warnings.filterwarnings('ignore')
from config.api_config import config
import requests
from urllib.parse import urlencode, quote_plus

k = config.odsay.api_key
params = {'apiKey': k, 'SX':127.0276, 'SY':37.4979, 'EX':126.978, 'EY':37.5665}
qs = urlencode(params, quote_via=quote_plus)
url_q = f"https://api.odsay.com/v1/api/searchPubTransPathT?{qs}"
url = "https://api.odsay.com/v1/api/searchPubTransPathT"

print('=== Query (encoded) ===')
print('URL:', url_q)
try:
    r = requests.get(url_q, timeout=15, verify=False)
    print('Status:', r.status_code)
    print('Body:', r.text)
except Exception as e:
    print('Query request failed:', e)

print('\n=== Header ===')
headers = {'apiKey': k}
params_no_key = {'SX':127.0276, 'SY':37.4979, 'EX':126.978, 'EY':37.5665}
try:
    r2 = requests.get(url, params=params_no_key, headers=headers, timeout=15, verify=False)
    print('Request URL:', r2.request.url)
    print('Request headers:', dict(r2.request.headers))
    print('Status:', r2.status_code)
    print('Response headers:', dict(r2.headers))
    print('Body:', r2.text)
except Exception as e:
    print('Header request failed:', e)
