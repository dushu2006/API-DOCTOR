import time
import requests

import sys

incident_id = sys.argv[1] if len(sys.argv) > 1 else 'cb655dd9-224a-469b-976c-78f29eaf03de'
url = f'http://localhost:8000/api/incidents/{incident_id}/status'
for i in range(60):
    try:
        r = requests.get(url, timeout=5)
    except Exception as e:
        print(i+1, 'error', e)
        time.sleep(2)
        continue
    print(i+1, r.status_code, r.text)
    try:
        js = r.json()
    except Exception:
        js = {}
    if js.get('status') == 'FIX_VERIFIED':
        print('FIX_VERIFIED at check', i+1)
        break
    if js.get('status') in ('REPAIR_LIMIT_REACHED', 'FAILED'):
        print('Terminal status', js.get('status'))
        break
    time.sleep(2)
else:
    print('timed out without FIX_VERIFIED')
