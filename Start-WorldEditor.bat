@echo off
title 3DX World Editor
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3 is required: https://www.python.org/downloads/ & pause & exit /b 1)
python -c "import UnityPy, numpy, PIL" >nul 2>nul || (
  echo Installing asset-extraction packages ^(one time^)...
  python -m pip install --quiet -r requirements.txt
)
python server.py %*
pause
