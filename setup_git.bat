@echo off
set REPO_URL=https://github.com/e1134171019/agent_3D.git

echo Changing directory...
cd /d "d:\agent_test"

echo Initializing Git...
"C:\Program Files\Git\cmd\git.exe" init
if errorlevel 1 (
    echo.
    echo ERROR: Cannot find Git. Please make sure Git is installed!
    echo Download Git from: https://git-scm.com/downloads
    pause
    exit /b 1
)

echo.
echo Adding files...
"C:\Program Files\Git\cmd\git.exe" add .

echo.
echo Committing...
"C:\Program Files\Git\cmd\git.exe" commit -m "initial commit"

echo.
echo Setting branch...
"C:\Program Files\Git\cmd\git.exe" branch -M main

echo.
echo Adding remote...
"C:\Program Files\Git\cmd\git.exe" remote add origin %REPO_URL%

echo.
echo Pushing to GitHub...
"C:\Program Files\Git\cmd\git.exe" push -u origin main

echo.
echo =========================
echo DONE! Push successful!
echo =========================
pause
