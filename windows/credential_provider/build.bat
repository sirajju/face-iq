@echo off
REM Build FaceIQCredentialProvider.dll with MSVC directly (no CMake needed).
REM Run from a normal shell; it sets up the VS environment itself.
setlocal
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
cl /nologo /LD /EHsc /W3 /DUNICODE /D_UNICODE /DWIN32_LEAN_AND_MEAN ^
   Dll.cpp CFaceProvider.cpp CFaceCredential.cpp helpers.cpp FaceIpc.cpp ^
   /Fe:FaceIQCredentialProvider.dll ^
   /link /DEF:FaceIQCredentialProvider.def ^
   shlwapi.lib credui.lib secur32.lib bcrypt.lib ole32.lib advapi32.lib user32.lib uuid.lib
echo EXIT CODE %ERRORLEVEL%
endlocal
