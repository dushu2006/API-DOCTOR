import tempfile
import shutil
from pathlib import Path
import subprocess
import sys

repo = Path.cwd()
workspace = Path(tempfile.mkdtemp(prefix='api_doctor_workspace_')) / 'repo'
shutil.copytree(repo, workspace, ignore=shutil.ignore_patterns('.git','__pycache__','.venv','venv','node_modules','*.pyc','.pytest_cache','.mypy_cache','htmlcov','dist','build','.tox'), dirs_exist_ok=False)
print('workspace', workspace)

script = f'''import sys
sys.path.insert(0, r"{workspace}")
from app.main import app
import inspect
print('imported app.main from', app.__module__, app.__file__)
print('router file:')
from app.demo_api import router
print('router file', router.__file__)
import httpx, asyncio
async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as c:
        r = await c.post('/api/v1/users/user_2/charge', json={{'amount': 100.0}})
        print('status', r.status_code)
        print('text', r.text)
asyncio.run(main())
'''
print('script:', script)
result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
print('stdout:\n', result.stdout)
print('stderr:\n', result.stderr)
print('returncode', result.returncode)
