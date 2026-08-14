# OrganizaPDF

Aplicativo desktop, gratuito e de código aberto para **unir, ordenar e separar arquivos PDF** com uma interface visual simples em português.

O OrganizaPDF não converte as páginas em imagens. Ele combina a estrutura original dos documentos e procura manter:

- texto pesquisável e selecionável;
- imagens e qualidade originais;
- marcadores hierárquicos;
- links externos e links internos entre páginas;
- anotações e campos de formulário;
- metadados do primeiro documento.

Ao unir, cada arquivo pode receber um marcador próprio no PDF final. Ao separar, o aplicativo mantém em cada parte os marcadores e links cujos destinos continuam presentes naquele arquivo.

## Recursos

- seleção de vários PDFs de uma vez;
- arrastar e soltar arquivos na janela;
- reordenação por arraste ou pelos botões de seta;
- separação de uma página por arquivo;
- separação em blocos com uma quantidade fixa de páginas;
- grupos personalizados, como `1-3; 4-6; 7,9,11`;
- previsão da quantidade de arquivos e páginas antes de separar;
- remoção individual e limpeza da lista;
- contagem de arquivos e páginas antes da união;
- suporte a PDFs protegidos por senha;
- processamento em segundo plano, sem congelar a janela;
- cancelamento seguro entre arquivos;
- gravação atômica: uma falha não deixa um arquivo final incompleto;
- opções para marcadores e metadados;
- abertura do PDF ou da pasta após concluir;
- executável para Windows gerado pelo GitHub Actions.

## Inicialização automática

Os inicializadores verificam o Python, reparam o `pip`, criam um ambiente virtual e instalam os módulos necessários antes de abrir o programa.

### Windows

Dê dois cliques em:

```text
OrganizaPDF-Windows.bat
```

Se o Python não estiver instalado, o arquivo tentará instalá-lo pelo `winget`. Também é possível clicar com o botão direito no `.bat` e criar um atalho na Área de Trabalho.

### Linux

No terminal, execute uma vez:

```bash
chmod +x OrganizaPDF-Linux.sh Instalar-Atalho-Linux.sh
./Instalar-Atalho-Linux.sh
```

Isso adiciona o **OrganizaPDF** ao menu de aplicativos. O inicializador reconhece sistemas baseados em APT, DNF, Pacman e Zypper para preparar o Python quando ele estiver ausente.

## Instalação para usuários

Na página **Releases**, baixe o arquivo `OrganizaPDF-Windows.zip`, extraia e execute `OrganizaPDF.exe`. Não é necessário instalar Python.

> Uma versão publicada é criada com uma tag como `v1.1.0`. O fluxo de release compila o executável automaticamente.

## Execução pelo código-fonte

Requer Python 3.10 ou superior.

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .
organizapdf
```

Linux/macOS:

```bash
source .venv/bin/activate
python -m pip install -e .
organizapdf
```

Também é possível iniciar com:

```bash
python -m organizapdf
```

## Desenvolvimento e testes

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
ruff check .
```

Para gerar o executável localmente no Windows:

```powershell
./scripts/build_windows.ps1
```

## Limites do formato PDF

- Assinaturas digitais anteriores deixam de ser válidas quando documentos são unidos, pois o conteúdo assinado é alterado.
- A senha dos arquivos de origem é usada apenas para leitura e não é aplicada ao PDF final.
- Ao separar, links destinados a páginas que não fazem parte da mesma parte são descartados para evitar referências quebradas.
- PDFs danificados ou que usam extensões proprietárias podem ter estruturas que nenhuma biblioteca consegue preservar integralmente.
- O aplicativo mantém as referências existentes no arquivo; ele não cria referências bibliográficas nem executa OCR.

## Privacidade

Todo o processamento ocorre no computador. Nenhum PDF é enviado para servidores.

## Licença

[MIT](LICENSE)
