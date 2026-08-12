import tempfile
import shutil
from pathlib import Path
import subprocess
import sys

repo = Path.cwd()
workspace = Path(tempfile.mkdtemp(prefix='api_doctor_workspace_')) / 'repo'
shutil.copytree(repo, workspace, ignore=shutil.ignore_patterns('.git','__pycache__','.venv','venv','node_modules','*.pyc','.pytest_cache','.mypy_cache','htmlcov','dist','build','.tox'), dirs_exist_ok=False)
print('workspace', workspace)
print('router exists', (workspace / 'app' / 'demo_api' / 'router.py').exists())
print('router content:')
print((workspace / 'app' / 'demo_api' / 'router.py').read_text().splitlines()[70:95])
script = "import sys; sys.path.insert(0, r'{}'); from app.main import app; import httpx, asyncio; async def main():\n    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as c:\n        r = await c.post('/api/v1/users/user_2/charge', json={{'amount': 100}})\n        print('status', r.status_code)\n        print('text', r.text)\nasyncio.run(main())".format(workspace)
print('running request in workspace')
result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
print(result.stdout)
print(result.stderr)
