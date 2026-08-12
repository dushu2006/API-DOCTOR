import inspect
from pathlib import Path
import app.demo_api.router as router
print('module file:', router.__file__)
print('charge func firstlineno:', router.charge.__code__.co_firstlineno)
print('charge source:')
print(inspect.getsource(router.charge))
print('---')
print('app/demo_api/router.py contents:')
print(Path('app/demo_api/router.py').read_text())
