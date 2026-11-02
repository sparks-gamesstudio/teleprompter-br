@echo off
chcp 65001 >nul
title Instalando o Teleprompter BR
cd /d "%~dp0"
echo.
echo   Teleprompter BR - instalacao
echo   ----------------------
echo.

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo   Python nao encontrado.
    echo   Instale o Python 3.10 ou mais novo em https://www.python.org/downloads/
    echo   e marque "Add python.exe to PATH" na instalacao.
    pause
    exit /b 1
  )
  set PY=python
) else (
  set PY=py -3
)

echo   [1/3] Criando ambiente isolado...
%PY% -m venv .venv || goto erro

echo   [2/3] Instalando dependencias (pode levar alguns minutos)...
.venv\Scripts\python -m pip install -q --upgrade pip
.venv\Scripts\python -m pip install -q -r requirements.txt || goto erro

echo   [3/3] Criando atalhos...
.venv\Scripts\python -m teleprompter.atalhos || goto erro

echo.
echo   Pronto! Abrindo o Teleprompter BR...
echo   Aperte ESPACO e comece a ler. Na primeira vez ele baixa o modelo de voz (50 MB).
start "" .venv\Scripts\pythonw.exe -m teleprompter
timeout /t 8 >nul
exit /b 0

:erro
echo.
echo   Algo deu errado. Copie a mensagem acima e abra uma issue no GitHub.
pause
exit /b 1
