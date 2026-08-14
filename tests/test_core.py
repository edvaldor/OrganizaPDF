from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, RectangleObject

from organizapdf.core import (
    MergeOptions,
    OrganizaPdfError,
    PdfPasswordRequired,
    PdfSource,
    SplitOptions,
    build_page_groups,
    inspect_pdf,
    merge_pdfs,
    split_pdf,
)


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def make_pdf(self, name: str, widths: list[int], author: str | None = None) -> Path:
        path = self.base / name
        writer = PdfWriter()
        for width in widths:
            writer.add_blank_page(width=width, height=400)
        writer.add_outline_item("Seção interna", 0)
        writer.add_annotation(
            page_number=0,
            annotation=Link(rect=(0, 0, 40, 20), url="https://example.com/referencia"),
        )
        if len(widths) > 1:
            # Constrói um link interno com uma referência indireta real, como
            # fazem os geradores de PDF. Isso permite testar o remapeamento do
            # destino quando páginas anteriores são acrescentadas ao resultado.
            source_page = writer.pages[0]
            target_page = writer.pages[1]
            internal_link = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Annot"),
                    NameObject("/Subtype"): NameObject("/Link"),
                    NameObject("/Rect"): RectangleObject((50, 0, 90, 20)),
                    NameObject("/Dest"): ArrayObject([target_page.indirect_reference, NameObject("/Fit")]),
                    NameObject("/P"): source_page.indirect_reference,
                }
            )
            link_reference = writer._add_object(internal_link)
            source_page[NameObject("/Annots")].append(link_reference)
        if author:
            writer.add_metadata({"/Author": author, "/Title": name})
        writer.write(path)
        writer.close()
        return path

    def test_inspect_pdf(self) -> None:
        path = self.make_pdf("entrada.pdf", [100, 120], "Edvaldo")
        info = inspect_pdf(PdfSource(path))
        self.assertEqual(info.pages, 2)
        self.assertEqual(info.title, "entrada.pdf")
        self.assertGreater(info.size_bytes, 0)

    def test_merge_preserves_order_bookmarks_links_and_metadata(self) -> None:
        first = self.make_pdf("primeiro.pdf", [101, 102], "Edvaldo Rodrigues")
        second = self.make_pdf("segundo.pdf", [203])
        output = self.base / "resultado.pdf"

        report = merge_pdfs([PdfSource(second), PdfSource(first)], output)
        reader = PdfReader(output)

        self.assertEqual(report.files, 2)
        self.assertEqual(report.pages, 3)
        self.assertEqual([int(page.mediabox.width) for page in reader.pages], [203, 101, 102])
        self.assertIn("segundo", self._outline_titles(reader.outline))
        self.assertIn("primeiro", self._outline_titles(reader.outline))
        self.assertIn("Seção interna", self._outline_titles(reader.outline))
        external_uri = reader.pages[0]["/Annots"][0].get_object()["/A"]["/URI"]
        self.assertEqual(external_uri, "https://example.com/referencia")
        first_document_page = reader.pages[1]
        internal_annotation = first_document_page["/Annots"][1].get_object()
        self.assertEqual(
            internal_annotation["/Dest"][0],
            reader.pages[2].indirect_reference,
        )
        self.assertEqual(reader.metadata.author, None)

        output2 = self.base / "resultado_metadados.pdf"
        merge_pdfs([PdfSource(first), PdfSource(second)], output2)
        reader2 = PdfReader(output2)
        self.assertEqual(reader2.metadata.author, "Edvaldo Rodrigues")
        self.assertIn("OrganizaPDF", reader2.metadata.producer)

    def test_options_can_disable_bookmarks(self) -> None:
        source = self.make_pdf("origem.pdf", [100])
        output = self.base / "sem_marcadores.pdf"
        merge_pdfs(
            [PdfSource(source)],
            output,
            MergeOptions(preserve_outline=False, add_file_bookmarks=False, preserve_metadata=False),
        )
        self.assertEqual(PdfReader(output).outline, [])

    def test_refuses_to_overwrite_source(self) -> None:
        source = self.make_pdf("origem.pdf", [100])
        with self.assertRaises(OrganizaPdfError):
            merge_pdfs([PdfSource(source)], source)

    def test_password_protected_pdf(self) -> None:
        source = self.base / "protegido.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("segredo")
        writer.write(source)
        writer.close()

        with self.assertRaises(PdfPasswordRequired):
            inspect_pdf(PdfSource(source))

        info = inspect_pdf(PdfSource(source, "segredo"))
        self.assertEqual(info.pages, 1)
        self.assertTrue(info.encrypted)

        output = self.base / "desprotegido.pdf"
        report = merge_pdfs([PdfSource(source, "segredo")], output)
        self.assertEqual(report.pages, 1)
        self.assertFalse(PdfReader(output).is_encrypted)

    def test_build_page_groups(self) -> None:
        self.assertEqual(build_page_groups(4, "single"), [[0], [1], [2], [3]])
        self.assertEqual(build_page_groups(5, "chunks", chunk_size=2), [[0, 1], [2, 3], [4]])
        self.assertEqual(
            build_page_groups(8, "ranges", ranges="1-3; 4,6; 8"),
            [[0, 1, 2], [3, 5], [7]],
        )
        with self.assertRaises(OrganizaPdfError):
            build_page_groups(5, "ranges", ranges="1-6")
        with self.assertRaises(OrganizaPdfError):
            build_page_groups(5, "ranges", ranges="4-2")

    def test_split_preserves_pages_metadata_and_internal_links(self) -> None:
        source = self.make_pdf("caderno.pdf", [101, 102, 103, 104], "Edvaldo Rodrigues")
        output_dir = self.base / "partes"
        groups = [[0, 1], [2], [3]]

        report = split_pdf(
            PdfSource(source),
            output_dir,
            groups,
            SplitOptions(preserve_outline=True, preserve_metadata=True),
        )

        self.assertEqual(report.files, 3)
        self.assertEqual(report.pages, 4)
        self.assertEqual(len(report.paths), 3)
        first = PdfReader(report.paths[0])
        self.assertEqual([int(page.mediabox.width) for page in first.pages], [101, 102])
        self.assertEqual(first.metadata.author, "Edvaldo Rodrigues")
        self.assertIn("Seção interna", self._outline_titles(first.outline))
        internal_annotation = first.pages[0]["/Annots"][1].get_object()
        self.assertEqual(internal_annotation["/Dest"][0], first.pages[1].indirect_reference)
        self.assertEqual(len(PdfReader(report.paths[1]).pages), 1)
        self.assertEqual(len(PdfReader(source).pages), 4)

        with self.assertRaises(OrganizaPdfError):
            split_pdf(PdfSource(source), output_dir, groups)

    @staticmethod
    def _outline_titles(outline: list) -> list[str]:
        titles: list[str] = []
        for item in outline:
            if isinstance(item, list):
                titles.extend(CoreTests._outline_titles(item))
            else:
                titles.append(item.title)
        return titles


if __name__ == "__main__":
    unittest.main()
