@echo off
rem SMENA dev launch: .venv-smena (Python 3.12)
rem Запуск через python.exe без окна консоли: с pythonw.exe драйвер отдаёт OpenGL встроенной AMD, с python.exe — NVIDIA.
cd /d "%~dp0"
start "" ".venv-smena\Scripts\pythonw.exe" -c "import subprocess,sys; subprocess.Popen([sys.executable.replace('pythonw.exe','python.exe'),'-m','smena'],creationflags=0x08000000)"
