#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

run_as_admin() {
    if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        echo "É necessário acesso administrativo para instalar o Python: $*" >&2
        return 1
    fi
}

install_python() {
    echo "Python 3 não foi encontrado. Tentando instalar pelo gerenciador do sistema..."
    if command -v apt-get >/dev/null 2>&1; then
        run_as_admin apt-get update
        run_as_admin apt-get install -y python3 python3-venv python3-pip
    elif command -v dnf >/dev/null 2>&1; then
        run_as_admin dnf install -y python3 python3-pip
    elif command -v pacman >/dev/null 2>&1; then
        run_as_admin pacman -Sy --needed python python-pip
    elif command -v zypper >/dev/null 2>&1; then
        run_as_admin zypper --non-interactive install python3 python3-pip python3-virtualenv
    else
        echo "Gerenciador de pacotes não reconhecido. Instale Python 3, pip e venv." >&2
        return 1
    fi
}

install_gui_runtime() {
    echo "Instalando bibliotecas gráficas necessárias ao Qt..."
    if command -v apt-get >/dev/null 2>&1; then
        run_as_admin apt-get update
        run_as_admin apt-get install -y \
            libegl1 libgl1 libxcb-cursor0 libxkbcommon-x11-0 libxcb-xinerama0
    elif command -v dnf >/dev/null 2>&1; then
        run_as_admin dnf install -y \
            mesa-libEGL mesa-libGL libxkbcommon-x11 xcb-util-cursor
    elif command -v pacman >/dev/null 2>&1; then
        run_as_admin pacman -Sy --needed mesa libxkbcommon-x11 xcb-util-cursor
    elif command -v zypper >/dev/null 2>&1; then
        run_as_admin zypper --non-interactive install \
            Mesa-libEGL1 Mesa-libGL1 libxkbcommon-x11-0 libxcb-cursor0
    else
        echo "Instale as bibliotecas EGL, OpenGL, XCB Cursor e XKB do seu sistema." >&2
        return 1
    fi
}

command -v python3 >/dev/null 2>&1 || install_python
PYTHON_BIN="$(command -v python3)"

if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    "$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || true
fi

if [[ ! -x ".venv/bin/python" ]]; then
    echo "Criando ambiente isolado do aplicativo..."
    if ! "$PYTHON_BIN" -m venv .venv; then
        if command -v apt-get >/dev/null 2>&1; then
            run_as_admin apt-get install -y python3-venv
            "$PYTHON_BIN" -m venv .venv
        else
            echo "Não foi possível criar .venv. Instale o módulo venv do Python." >&2
            exit 1
        fi
    fi
fi

echo "Instalando ou reparando os módulos do OrganizaPDF..."
".venv/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
".venv/bin/python" -m pip install --upgrade pip setuptools wheel
".venv/bin/python" -m pip install -e .

if ! ".venv/bin/python" -c "from PySide6.QtWidgets import QApplication" >/dev/null 2>&1; then
    install_gui_runtime
    ".venv/bin/python" -c "from PySide6.QtWidgets import QApplication"
fi

echo "Abrindo o OrganizaPDF..."
nohup ".venv/bin/python" -m organizapdf >"${TMPDIR:-/tmp}/organizapdf.log" 2>&1 &
disown 2>/dev/null || true
