@echo off
setlocal EnableExtensions
title OrganizaPDF - Preparacao e inicializacao
cd /d "%~dp0"

echo.
echo ==========================================
echo       OrganizaPDF - Windows
echo ==========================================
echo.

set "PYTHON_CMD="
where py >nul 2>nul && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    where python >nul 2>nul && set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo Python nao foi encontrado. Tentando instalar pelo Windows Package Manager...
    where winget >nul 2>nul
    if errorlevel 1 goto :python_manual
    winget install --id Python.Python.3.12 -e --source winget ^
        --accept-package-agreements --accept-source-agreements
    if errorlevel 1 goto :python_manual

    where py >nul 2>nul && set "PYTHON_CMD=py -3"
    if not defined PYTHON_CMD (
        where python >nul 2>nul && set "PYTHON_CMD=python"
    )
    if not defined PYTHON_CMD (
        echo A instalacao terminou, mas o terminal ainda nao reconhece o Python.
        echo Feche esta janela e execute este arquivo novamente.
        pause
        exit /b 1
    )
)

echo Verificando o pip...
%PYTHON_CMD% -m pip --version >nul 2>nul
if errorlevel 1 (
    %PYTHON_CMD% -m ensurepip --upgrade
    if errorlevel 1 goto :pip_error
)

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente isolado do aplicativo...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :venv_error
)

echo Atualizando ferramentas de instalacao...
".venv\Scripts\python.exe" -m ensurepip --upgrade >nul 2>nul
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :dependency_error

echo Instalando ou reparando os modulos do OrganizaPDF...
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :dependency_error

echo Abrindo o OrganizaPDF...
start "" ".venv\Scripts\pythonw.exe" -m organizapdf
exit /b 0

:python_manual
echo.
echo Nao foi possivel instalar o Python automaticamente.
echo Instale o Python 3.12 em https://www.python.org/downloads/windows/
echo Marque a opcao "Add python.exe to PATH" e execute este arquivo novamente.
pause
exit /b 1

:pip_error
echo.
echo Nao foi possivel preparar o pip desta instalacao do Python.
echo Repare a instalacao do Python habilitando pip e venv.
pause
exit /b 1

:venv_error
echo.
echo Nao foi possivel criar o ambiente virtual .venv.
echo Repare ou reinstale o Python com o componente venv.
pause
exit /b 1

:dependency_error
echo.
echo Nao foi possivel instalar os modulos necessarios.
echo Verifique a conexao com a internet, antivirus ou proxy e tente novamente.
pause
exit /b 1

