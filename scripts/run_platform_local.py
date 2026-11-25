"""PyCharm/Windows local launcher using the prepared project environment."""
import os
from pathlib import Path

root=Path(__file__).resolve().parents[1]
python=root/'platform_backend/.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
if not python.exists():raise SystemExit('先按 platform_backend/README.md 准备应用专用虚拟环境')
if not (root/'apps/geohazard-demo/dist/index.html').exists():raise SystemExit('请先在 apps/geohazard-demo 执行 npm ci 和 npm run build')
temp=root/'work/local-temp';temp.mkdir(parents=True,exist_ok=True)
os.environ.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',TEMP=str(temp),TMP=str(temp))
os.chdir(root)
port=os.environ.get('GEOHAZARD_PORT','8000')
if not port.isascii() or not port.isdigit() or not 1<=int(port)<=65535:raise SystemExit('GEOHAZARD_PORT必须为1至65535整数')
os.execv(str(python),[str(python),'-B','-m','uvicorn','geohazard_platform.main:app','--host',os.environ.get('GEOHAZARD_HOST','127.0.0.1'),'--port',port])
