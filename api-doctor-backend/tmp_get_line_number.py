from pathlib import Path
p = Path('app/demo_api/bugs.py')
for i, l in enumerate(p.read_text().splitlines(), 1):
    if 'token = user.payment_method.token' in l:
        print(i)
        break
