import warnings
warnings.filterwarnings('ignore')
from config.api_config import config
import requests
from urllib.parse import urlencode, quote_plus

k = config.odsay.api_key
print('Loaded key repr:', repr(k))
params = {'apiKey': k, 'SX':127.0276, 'SY':37.4979, 'EX':126.978, 'EY':37.5665}
qs = urlencode(params, quote_via=quote_plus)
url = f"https://api.odsay.com/v1/api/searchPubTransPathT?{qs}"
print('Request URL:', url)
try:
    r = requests.get(url, timeout=15, verify=False)
    print('Status:', r.status_code)
    print('Response headers:', dict(r.headers))
    print('Response text (first 1000 chars):')
    print(r.text[:1000])
    try:
        print('JSON keys:', list(r.json().keys()))
    except Exception as e:
        print('JSON parse error:', e)
except Exception as e:
    print('Request failed:', e)
