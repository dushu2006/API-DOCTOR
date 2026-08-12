import asyncio
import inspect
from app.core.config import settings
from app.orchestrator import Orchestrator
import app.demo_api.router as router

print('current repo root', settings.REPO_ROOT)
print('router file', router.__file__)
print('charge source:')
print(inspect.getsource(router.charge))

try:
    from app.main import app
    print('main app module', app.__module__)
except Exception as exc:
    print('failed import app.main', exc)

async def main():
    orch = Orchestrator()
    print('orchestrator created')
    incident = await orch.detect_and_create('/api/v1/users/user_2/charge', 'POST', {'amount': 100.0})
    print('incident status', incident.status)
    print('incident detection', incident.detection)

asyncio.run(main())
