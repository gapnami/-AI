import warnings
warnings.filterwarnings('ignore')
from config.api_config import config
from urllib.parse import urlencode, quote_plus
import requests

k = getattr(config.odsay, 'api_key', None)
params = {'apiKey': k, 'SX':127.0276, 'SY':37.4979, 'EX':126.978, 'EY':37.5665}
qs = urlencode(params, quote_via=quote_plus)
url = f"https://api.odsay.com/v1/api/searchPubTransPathT?{qs}"
print('Request URL:', url)
try:
    r = requests.get(url, timeout=15, verify=False)
    print('Status:', r.status_code)
    print('Response headers:\n', r.headers)
    print('Response text (first 2000 chars):\n', r.text[:2000])
    try:
        j = r.json()
        print('JSON keys:', list(j.keys()))
        print('Full JSON:', j)
    except Exception as e:
        print('JSON parse error:', e)
except Exception as e:
    print('Request failed:', e)
