@echo off
echo ========================================
echo   PDF QA Bot - Starting All Services
echo ========================================
echo.

echo [1/3] Starting RAG service (port 5000)...
start "RAG Service" cmd /k "cd /d %~dp0rag-service && python main.py"

echo Waiting for RAG service to initialize...
timeout /t 5 /nobreak > nul

echo [2/3] Starting API gateway (port 4000)...
start "API Gateway" cmd /k "cd /d %~dp0 && node server.js"

timeout /t 3 /nobreak > nul

echo [3/3] Starting React frontend (port 3000)...
start "Frontend" cmd /k "cd /d %~dp0frontend && npm start"

echo.
echo ========================================
echo   All services started!
echo   Open http://localhost:3000 in your browser
echo ========================================
echo.
echo First-time PDF upload may take 1-2 min to load ML models.
echo Keep all 3 terminal windows open.
echo.
pause
