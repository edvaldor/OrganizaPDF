$ErrorActionPreference = "Stop"

python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name OrganizaPDF `
  --icon src/organizapdf/assets/icon.ico `
  --add-data "src/organizapdf/assets;organizapdf/assets" `
  src/organizapdf/__main__.py

Write-Host "Executável criado em dist/OrganizaPDF/OrganizaPDF.exe"
