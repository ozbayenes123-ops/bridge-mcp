"""Zotero Word alan kodları: yük oluşturma, ayrıştırma, docx'e yazma."""

import json
import zipfile

import pytest

from bridge_mcp.word_citation import (
    DocxPackage,
    bibliography_instruction,
    build_citation_payload,
    build_prefs_json,
    build_prefs_xml,
    citation_instruction,
    is_bibliography_field,
    is_citation_field,
    is_prefs_field,
    make_field_runs,
    parse_citation_instruction,
    parse_prefs_chunk,
    prefs_instructions,
    style_from_prefs_xml,
    style_url,
)

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)
DOC = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body>"
    '<w:p><w:r><w:t xml:space="preserve">Atıf: {{ATIF}} sonrası</w:t></w:r></w:p>'
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
    "</w:body></w:document>"
)


def make_docx(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", RELS)
        zf.writestr("word/document.xml", DOC)
    return path


# --------------------------------------------------------------- yük ve alan kodu

def test_style_url_accepts_bare_id_and_url():
    assert style_url("isnad-dipnotlu") == "http://www.zotero.org/styles/isnad-dipnotlu"
    assert style_url("http://x/y") == "http://x/y"


def test_citation_payload_shape_and_roundtrip():
    entries = [
        {
            "uri": "http://zotero.org/users/9689905/items/U4WYW7NQ",
            "csl": {"id": "http://zotero.org/users/9689905/items/U4WYW7NQ", "type": "thesis"},
            "locator": "12",
        }
    ]
    payload = build_citation_payload(entries, formatted_citation="AlMajed, 2018.", citation_id="ABC123")
    assert payload["citationID"] == "ABC123"
    assert payload["properties"]["formattedCitation"] == "AlMajed, 2018."
    assert payload["citationItems"][0]["uris"] == [entries[0]["uri"]]
    assert payload["citationItems"][0]["locator"] == "12"
    assert payload["schema"].endswith("csl-citation.json")

    instruction = citation_instruction(payload)
    assert instruction.startswith(" ADDIN ZOTERO_ITEM CSL_CITATION ")
    assert is_citation_field(instruction)

    parsed = parse_citation_instruction(instruction)
    assert parsed == json.loads(json.dumps(payload))


def test_parse_citation_instruction_tolerates_trailing_junk():
    payload = {"citationID": "X", "properties": {"noteIndex": 0}, "citationItems": []}
    instruction = citation_instruction(payload) + " artık metin"
    assert parse_citation_instruction(instruction)["citationID"] == "X"


def test_parse_citation_instruction_returns_none_for_other_fields():
    assert parse_citation_instruction(" PAGE ") is None


def test_bibliography_instruction_detected():
    instruction = bibliography_instruction()
    assert is_bibliography_field(instruction)
    assert instruction.strip().endswith("CSL_BIBLIOGRAPHY")


# --------------------------------------------------------------- belge tercihleri

def test_prefs_chunking_and_style_roundtrip():
    xml = build_prefs_xml(style="isnad-dipnotlu", locale="tr-TR", note_type=1)
    instructions = prefs_instructions(xml)
    assert all(is_prefs_field(i) for i in instructions)
    blob = "".join(parse_prefs_chunk(i)[1] for i in instructions)
    assert blob == xml
    info = style_from_prefs_xml(blob)
    assert info["id"] == "http://www.zotero.org/styles/isnad-dipnotlu"
    assert info["locale"] == "tr-TR"
    assert info["noteType"] == "1"


def test_prefs_chunk_size_limit():
    xml = build_prefs_xml(style="apa")
    for instruction in prefs_instructions(xml):
        _, chunk = parse_prefs_chunk(instruction)
        assert len(chunk) <= 255


def test_prefs_json_matches_zotero_documentdata_shape():
    from bridge_mcp.word_citation import build_prefs_json

    blob = build_prefs_json(style="isnad-dipnotlu", note_type=1, zotero_version="10.0.6")
    data = json.loads(blob)
    assert data["dataVersion"] == 4
    assert data["style"]["styleID"] == "http://www.zotero.org/styles/isnad-dipnotlu"
    assert data["style"]["hasBibliography"] is True
    assert data["prefs"]["fieldType"] == "Field"
    assert data["prefs"]["noteType"] == 1
    assert data["zoteroVersion"] == "10.0.6"
    assert data["sessionID"]


def test_document_style_reads_json_prefs(tmp_path):
    from bridge_mcp.word_citation import build_prefs_json

    path = make_docx(tmp_path / "p.docx")
    pkg = DocxPackage(path)
    pkg.replace_prefs(prefs_instructions(build_prefs_json(style="isnad-dipnotlu", note_type=1)))
    pkg.save()

    again = DocxPackage(path)
    style = again.document_style()
    assert style["id"] == "http://www.zotero.org/styles/isnad-dipnotlu"
    assert style["noteType"] == "1"
    assert style["bicim"] == "json"


# --------------------------------------------------------------- docx düzenleme

def test_docx_marker_replaced_by_citation_field(tmp_path):
    path = make_docx(tmp_path / "t.docx")
    payload = build_citation_payload(
        [{"uri": "http://zotero.org/users/1/items/AAA", "csl": {"id": "x", "type": "book"}}],
        formatted_citation="Yazar, 2000.",
        citation_id="CID1",
    )
    pkg = DocxPackage(path)
    assert pkg.replace_marker("{{ATIF}}", citation_instruction(payload), "Yazar, 2000.")
    assert pkg.citations(), "atıf alanı bulunamadı"
    assert pkg.citations()[0].citation_id == "CID1"
    assert pkg.citations()[0].item_keys == ["AAA"]
    pkg.save()

    text = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    assert "ADDIN ZOTERO_ITEM CSL_CITATION" in text
    assert "{{ATIF}}" not in text
    assert "sonrası" in text, "işaretten sonraki metin korunmalı"
    assert "fldCharType=\"begin\"" in text and "fldCharType=\"end\"" in text


def test_docx_append_field_and_reload(tmp_path):
    path = make_docx(tmp_path / "t2.docx")
    pkg = DocxPackage(path)
    pkg.append_field(bibliography_instruction(), "Kaynakça")
    pkg.replace_prefs(prefs_instructions(build_prefs_xml(style="isnad-metinici", note_type=0)))
    pkg.save()

    again = DocxPackage(path)
    assert len(again.citations()) == 0
    assert again.document_style()["id"] == "http://www.zotero.org/styles/isnad-metinici"


def test_docx_rejects_non_docx(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_text("bu bir docx değil", encoding="utf-8")
    with pytest.raises(Exception):
        DocxPackage(bad)


def test_field_without_result_has_no_result_run():
    """Zotero tercih alanlarında sonuç koşusu yoktur; boş sonuç koşusu eklenmez."""
    def tags_of(runs):
        return [
            child.tag.split("}")[-1]
            for run in runs
            for child in run
            if child.tag.split("}")[-1] != "rPr"
        ]

    runs = make_field_runs(" ADDIN ZOTERO_PREF_1 {} ", "")
    assert tags_of(runs) == ["fldChar", "instrText", "fldChar", "fldChar"]

    runs_with_result = make_field_runs(" ADDIN ZOTERO_ITEM CSL_CITATION {} ", "Yazar, 2000.")
    assert tags_of(runs_with_result) == [
        "fldChar",
        "instrText",
        "fldChar",
        "t",
        "fldChar",
    ]


def test_runs_carry_explicit_font():
    """Yazı tipi kalıtıma bırakılmaz; atıf/dipnot TNR yazılmalı."""
    runs = make_field_runs(" ADDIN ZOTERO_ITEM CSL_CITATION {} ", "Yazar, 2000.")
    for run in runs:
        fonts = run.find(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rPr/"
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts"
        )
        assert fonts is not None, "koşuda rFonts yok"
        assert (
            fonts.get(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ascii"
            )
            == "Times New Roman"
        )


def test_prefs_field_written_at_document_start(tmp_path):
    """Tercih alanları belge başında olmalı; Zotero belge verisini orada arar."""
    path = make_docx(tmp_path / "p2.docx")
    pkg = DocxPackage(path)
    pkg.replace_prefs(prefs_instructions(build_prefs_json(style="isnad-dipnotlu")))
    pkg.save()

    document = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    prefs_pos = document.index("ADDIN ZOTERO_PREF_1")
    body_pos = document.index("Atıf:") if "Atıf:" in document else document.index("<w:body>")
    assert prefs_pos < body_pos, "tercih alanı gövdeden sonra yazılmış"


# --------------------------------------------------------------- dipnot içinde atıf

def _payload(cid="F1"):
    return build_citation_payload(
        [{"uri": "http://zotero.org/users/1/items/AAA", "csl": {"id": "x", "type": "book"}}],
        formatted_citation="Yazar, 2000.",
        citation_id=cid,
    )


def test_footnote_part_created_with_citation_field(tmp_path):
    path = make_docx(tmp_path / "f.docx")
    pkg = DocxPackage(path)
    assert pkg.add_footnote_at_marker("{{ATIF}}", citation_instruction(_payload()), "Yazar, 2000.")
    pkg.save()

    zf = zipfile.ZipFile(path)
    names = zf.namelist()
    assert "word/footnotes.xml" in names, "dipnot parçası oluşmadı"
    footnotes = zf.read("word/footnotes.xml").decode("utf-8")
    assert "ADDIN ZOTERO_ITEM CSL_CITATION" in footnotes
    assert footnotes.count("w:footnote ") >= 2, "separator dipnotları yok"

    content_types = zf.read("[Content_Types].xml").decode("utf-8")
    assert "/word/footnotes.xml" in content_types
    rels = zf.read("word/_rels/document.xml.rels").decode("utf-8")
    assert "footnotes" in rels

    document = zf.read("word/document.xml").decode("utf-8")
    assert "footnoteReference" in document
    assert "{{ATIF}}" not in document
    assert "sonrası" in document


def test_footnote_field_readable_after_reload(tmp_path):
    path = make_docx(tmp_path / "f2.docx")
    pkg = DocxPackage(path)
    pkg.add_footnote_at_marker("{{ATIF}}", citation_instruction(_payload("F2")), "Yazar, 2000.")
    pkg.add_footnote_at_end(citation_instruction(_payload("F3")), "İkinci, 2001.")
    pkg.save()

    again = DocxPackage(path)
    footnote_citations = [
        f.citation_id for f in again.all_fields() if is_citation_field(f.instruction)
    ]
    assert "F2" in footnote_citations and "F3" in footnote_citations
    assert again.footnote_fields(), "dipnot alanları okunamadı"


def test_footnote_ids_increment(tmp_path):
    path = make_docx(tmp_path / "f3.docx")
    pkg = DocxPackage(path)
    first = pkg.add_footnote_at_end(citation_instruction(_payload("A")), "a")
    second = pkg.add_footnote_at_end(citation_instruction(_payload("B")), "b")
    assert first != second
    ids = [
        int(node.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id"))
        for node in pkg.ensure_footnotes_part().findall(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}footnote"
        )
    ]
    assert len(set(ids)) == len(ids), "dipnot kimlikleri benzersiz olmalı"
