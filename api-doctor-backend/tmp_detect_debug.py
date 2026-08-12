import asyncio
from app.detector.failure_detector import FailureDetector
from app.core.config import settings

async def main():
    fd = FailureDetector()
    response = await fd._call_inprocess('/api/v1/users/user_2/charge', 'POST', {'amount': 100.0}, None)
    print('status', response.status_code)
    try:
        print('json', response.json())
    except Exception as exc:
        print('json error', exc, response.text)
    print('headers', response.headers)

asyncio.run(main())
