@echo off
set PYTHON_EXE=%~dp0env\Scripts\python.exe

if not exist "%PYTHON_EXE%" (
	echo Python environment not found: %PYTHON_EXE%
	exit /b 1
)

"%PYTHON_EXE%" -c "import PIL; import PyInstaller; print('build_env_ok')"
if errorlevel 1 (
	echo Bootstrapping build dependencies in env...
	"%PYTHON_EXE%" -m pip install Pillow PyInstaller || exit /b 1
)

"%PYTHON_EXE%" -m PyInstaller --clean "%~dp0agent_service.spec" || exit /b 1
copy .\vm_agent\src \\DESKTOP-JJULF7D\agent\DevOPS\vm_agent -r -force; 
copy .\shared \\DESKTOP-JJULF7D\agent\DevOPS -r -force;
copy .\dist \\DESKTOP-JJULF7D\agent\DevOPS -r -force;