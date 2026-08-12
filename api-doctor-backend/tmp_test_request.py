import asyncio
import httpx
from app.main import app

async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as c:
        r = await c.post('/api/v1/users/user_2/charge', json={'amount': 100.0})
        print('status', r.status_code)
        print('headers', r.headers)
        print('text', r.text)

asyncio.run(main())
