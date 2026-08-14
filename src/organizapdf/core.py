"""Núcleo de inspeção e união de PDFs.

O módulo não depende da interface gráfica e pode ser reutilizado em testes ou
em uma futura interface de linha de comando.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pypdf import PdfReader, PdfWriter
from pypdf.errors import FileNotDecryptedError, PdfReadError, WrongPasswordError

from organizapdf import __version__


class OrganizaPdfError(Exception):
    """Erro esperado e apresentável ao usuário."""


class PdfPasswordRequired(OrganizaPdfError):
    """O PDF exige uma senha válida para leitura."""


class MergeCancelled(OrganizaPdfError):
    """A operação foi cancelada entre dois arquivos."""


@dataclass(frozen=True, slots=True)
class PdfSource:
    path: Path
    password: str | None = None

    @property
    def label(self) -> str:
        return self.path.stem


@dataclass(frozen=True, slots=True)
class PdfInfo:
    pages: int
    size_bytes: int
    encrypted: bool
    title: str | None


@dataclass(frozen=True, slots=True)
class MergeOptions:
    preserve_outline: bool = True
    add_file_bookmarks: bool = True
    preserve_metadata: bool = True


@dataclass(frozen=True, slots=True)
class MergeReport:
    output: Path
    files: int
    pages: int
    size_bytes: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SplitOptions:
    preserve_outline: bool = True
    preserve_metadata: bool = True


@dataclass(frozen=True, slots=True)
class SplitReport:
    output_dir: Path
    files: int
    pages: int
    size_bytes: int
    paths: tuple[Path, ...]
    warnings: tuple[str, ...] = ()


ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]
SplitMode = Literal["single", "chunks", "ranges"]


def _open_reader(source: PdfSource) -> PdfReader:
    try:
        reader = PdfReader(source.path, strict=False)
    except (OSError, PdfReadError) as exc:
        raise OrganizaPdfError(f"Não foi possível ler “{source.path.name}”: {exc}") from exc

    if reader.is_encrypted:
        try:
            result = reader.decrypt(source.password or "")
        except (WrongPasswordError, FileNotDecryptedError) as exc:
            reader.close()
            raise PdfPasswordRequired(
                f"“{source.path.name}” está protegido. Informe a senha correta."
            ) from exc
        if result == 0:
            reader.close()
            raise PdfPasswordRequired(f"“{source.path.name}” está protegido. Informe a senha correta.")
    return reader


def inspect_pdf(source: PdfSource) -> PdfInfo:
    """Valida um arquivo e retorna informações básicas sem alterar o original."""

    path = source.path.expanduser().resolve()
    if not path.is_file():
        raise OrganizaPdfError(f"Arquivo não encontrado: {path}")
    if path.suffix.lower() != ".pdf":
        raise OrganizaPdfError(f"O arquivo “{path.name}” não é um PDF.")

    reader = _open_reader(PdfSource(path, source.password))
    try:
        try:
            pages = len(reader.pages)
        except (PdfReadError, FileNotDecryptedError) as exc:
            raise OrganizaPdfError(f"Não foi possível contar as páginas de “{path.name}”.") from exc
        if pages == 0:
            raise OrganizaPdfError(f"“{path.name}” não contém páginas.")

        metadata = reader.metadata or {}
        title = metadata.get("/Title")
        return PdfInfo(
            pages=pages,
            size_bytes=path.stat().st_size,
            encrypted=reader.is_encrypted,
            title=str(title) if title else None,
        )
    finally:
        reader.close()


def _safe_metadata(reader: PdfReader) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in (reader.metadata or {}).items():
        if isinstance(key, str) and key.startswith("/") and value is not None:
            try:
                result[key] = str(value)
            except Exception:
                continue
    return result


def merge_pdfs(
    sources: Sequence[PdfSource],
    output: Path,
    options: MergeOptions | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> MergeReport:
    """Une PDFs na ordem recebida e grava o resultado de forma atômica.

    ``PdfWriter.append`` clona as páginas, anotações e destinos e também
    remapeia links internos. Nenhuma página é convertida em imagem.
    """

    if not sources:
        raise OrganizaPdfError("Adicione pelo menos um arquivo PDF.")
    options = options or MergeOptions()

    normalized = [PdfSource(s.path.expanduser().resolve(), s.password) for s in sources]
    destination = output.expanduser().resolve()
    if destination.suffix.lower() != ".pdf":
        destination = destination.with_suffix(".pdf")
    if destination in {source.path for source in normalized}:
        raise OrganizaPdfError("O arquivo de saída não pode substituir um dos PDFs de origem.")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OrganizaPdfError(f"Não foi possível acessar a pasta de destino: {destination.parent}") from exc

    writer = PdfWriter()
    readers: list[PdfReader] = []
    warnings: list[str] = []
    page_total = 0

    try:
        for index, source in enumerate(normalized, start=1):
            if should_cancel and should_cancel():
                raise MergeCancelled("Operação cancelada.")
            if progress:
                progress(index, len(normalized), source.path.name)

            reader = _open_reader(source)
            readers.append(reader)
            page_total += len(reader.pages)
            if index == 1 and options.preserve_metadata:
                metadata = _safe_metadata(reader)
                metadata["/Producer"] = f"OrganizaPDF {__version__} (pypdf)"
                writer.add_metadata(metadata)

            writer.append(
                reader,
                outline_item=source.label if options.add_file_bookmarks else None,
                import_outline=options.preserve_outline,
                excluded_fields=(),
            )

            if reader.is_encrypted:
                warnings.append(f"A proteção por senha de “{source.path.name}” não foi copiada.")

        if should_cancel and should_cancel():
            raise MergeCancelled("Operação cancelada.")

        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                suffix=".pdf",
                prefix=".organizapdf-",
                dir=destination.parent,
                delete=False,
            ) as temp_file:
                temp_name = temp_file.name
                writer.write(temp_file)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, destination)
        except Exception as exc:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)
            raise OrganizaPdfError(f"Não foi possível salvar “{destination.name}”: {exc}") from exc
    finally:
        writer.close()
        for reader in readers:
            reader.close()

    return MergeReport(
        output=destination,
        files=len(normalized),
        pages=page_total,
        size_bytes=destination.stat().st_size,
        warnings=tuple(warnings),
    )


def build_page_groups(
    total_pages: int,
    mode: SplitMode,
    *,
    chunk_size: int = 1,
    ranges: str = "",
) -> list[list[int]]:
    """Monta grupos de índices, usando números de página iniciados em 1 na entrada.

    Em ``ranges``, ponto e vírgula ou quebra de linha inicia um novo PDF;
    vírgulas juntam páginas e intervalos no mesmo arquivo.
    """

    if total_pages < 1:
        raise OrganizaPdfError("O PDF não contém páginas.")
    if mode == "single":
        return [[page] for page in range(total_pages)]
    if mode == "chunks":
        if chunk_size < 1:
            raise OrganizaPdfError("A quantidade de páginas por arquivo deve ser maior que zero.")
        return [
            list(range(start, min(start + chunk_size, total_pages)))
            for start in range(0, total_pages, chunk_size)
        ]
    if mode != "ranges":
        raise OrganizaPdfError("Modo de separação desconhecido.")

    raw_groups = [part.strip() for part in re.split(r"[;\n]+", ranges) if part.strip()]
    if not raw_groups:
        raise OrganizaPdfError("Informe ao menos um grupo de páginas.")

    groups: list[list[int]] = []
    for raw_group in raw_groups:
        pages: list[int] = []
        for token in (part.strip() for part in raw_group.split(",")):
            if not token:
                raise OrganizaPdfError(f"Grupo de páginas inválido: “{raw_group}”.")
            match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", token)
            if not match:
                raise OrganizaPdfError(f"Página ou intervalo inválido: “{token}”.")
            start = int(match.group(1))
            end = int(match.group(2) or start)
            if start < 1 or end < 1 or start > total_pages or end > total_pages:
                raise OrganizaPdfError(f"“{token}” está fora do PDF, que possui {total_pages} página(s).")
            if start > end:
                raise OrganizaPdfError(f"O intervalo “{token}” está em ordem inversa.")
            pages.extend(range(start - 1, end))
        groups.append(list(dict.fromkeys(pages)))
    return groups


def _split_filename(source: PdfSource, index: int, pages: Sequence[int]) -> str:
    if len(pages) == 1:
        description = f"pagina_{pages[0] + 1:03d}"
    elif list(pages) == list(range(pages[0], pages[-1] + 1)):
        description = f"paginas_{pages[0] + 1:03d}-{pages[-1] + 1:03d}"
    else:
        labels = "-".join(str(page + 1) for page in pages)
        description = f"paginas_{labels}"
    safe_stem = re.sub(r"[^\w.-]+", "_", source.path.stem, flags=re.UNICODE).strip("._")
    safe_stem = safe_stem or "documento"
    return f"{safe_stem}_parte_{index:03d}_{description}.pdf"


def split_pdf(
    source: PdfSource,
    output_dir: Path,
    groups: Sequence[Sequence[int]],
    options: SplitOptions | None = None,
    *,
    overwrite: bool = False,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> SplitReport:
    """Separa páginas em vários PDFs sem rasterizar o documento de origem."""

    options = options or SplitOptions()
    normalized = PdfSource(source.path.expanduser().resolve(), source.password)
    destination = output_dir.expanduser().resolve()
    if not groups:
        raise OrganizaPdfError("Defina ao menos uma parte para separar.")

    reader = _open_reader(normalized)
    was_encrypted = reader.is_encrypted
    temp_paths: list[Path] = []
    final_paths: list[Path] = []
    metadata = _safe_metadata(reader) if options.preserve_metadata else {}
    if metadata:
        metadata["/Producer"] = f"OrganizaPDF {__version__} (pypdf)"

    try:
        total_pages = len(reader.pages)
        normalized_groups: list[list[int]] = []
        for group in groups:
            pages = list(group)
            if not pages:
                raise OrganizaPdfError("Uma das partes não possui páginas.")
            if any(page < 0 or page >= total_pages for page in pages):
                raise OrganizaPdfError(f"Uma página solicitada está fora do intervalo de 1 a {total_pages}.")
            normalized_groups.append(pages)

        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OrganizaPdfError(f"Não foi possível acessar a pasta de destino: {destination}") from exc

        final_paths = [
            destination / _split_filename(normalized, index, pages)
            for index, pages in enumerate(normalized_groups, start=1)
        ]
        collisions = [path.name for path in final_paths if path.exists()]
        if collisions and not overwrite:
            preview = ", ".join(collisions[:3])
            suffix = "…" if len(collisions) > 3 else ""
            raise OrganizaPdfError(f"{len(collisions)} arquivo(s) já existem na pasta: {preview}{suffix}")

        for index, (pages, final_path) in enumerate(
            zip(normalized_groups, final_paths, strict=True),
            start=1,
        ):
            if should_cancel and should_cancel():
                raise MergeCancelled("Operação cancelada.")
            if progress:
                progress(index, len(normalized_groups), final_path.name)

            writer = PdfWriter()
            try:
                if metadata:
                    writer.add_metadata(metadata)
                writer.append(
                    reader,
                    pages=pages,
                    import_outline=options.preserve_outline,
                    excluded_fields=(),
                )
                with tempfile.NamedTemporaryFile(
                    mode="w+b",
                    suffix=".pdf",
                    prefix=".organizapdf-parte-",
                    dir=destination,
                    delete=False,
                ) as temp_file:
                    temp_path = Path(temp_file.name)
                    temp_paths.append(temp_path)
                    writer.write(temp_file)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
            finally:
                writer.close()

        if should_cancel and should_cancel():
            raise MergeCancelled("Operação cancelada.")
        for temp_path, final_path in zip(temp_paths, final_paths, strict=True):
            os.replace(temp_path, final_path)
        temp_paths.clear()
    except OrganizaPdfError:
        raise
    except Exception as exc:
        raise OrganizaPdfError(f"Não foi possível separar “{normalized.path.name}”: {exc}") from exc
    finally:
        for temp_path in temp_paths:
            temp_path.unlink(missing_ok=True)
        reader.close()

    warnings: tuple[str, ...] = ()
    if was_encrypted:
        warnings = ("A proteção por senha do arquivo de origem não foi copiada.",)
    return SplitReport(
        output_dir=destination,
        files=len(final_paths),
        pages=sum(len(group) for group in normalized_groups),
        size_bytes=sum(path.stat().st_size for path in final_paths),
        paths=tuple(final_paths),
        warnings=warnings,
    )
