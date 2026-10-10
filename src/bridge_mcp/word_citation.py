"""Zotero'nun Word eklentisinin okuduğu alan kodlarını üretir — canlı atıf.

Amaç: Word belgesine, Zotero'nun kendi eklentisiyle eklenmiş gibi davranan
gerçek bir atıf alanı yazmak. Alan kodu Zotero'nun beklediği biçimde olursa
Zotero belgeyi sahiplenir: "Refresh", "Add/Edit Bibliography" ve stil
değiştirme normal çalışır.

Alan kodları (Zotero 7 Word/LibreOffice entegrasyonuyla aynı biçim):

* `` ADDIN ZOTERO_ITEM CSL_CITATION {…} ``  — atıf alanı (CSL citation JSON)
* `` ADDIN ZOTERO_BIBL {…} CSL_BIBLIOGRAPHY `` — kaynakça alanı
* `` ADDIN ZOTERO_PREF_<n> <parça> ``      — belge tercihleri (CSL stili vb.)

Belge XML'i python-docx'e bağımlı olmadan, stdlib zipfile + ElementTree ile
düzenlenir (bridge venv'ine yeni bağımlılık eklenmez).
"""

from __future__ import annotations

import json
import re
import random
import shutil
import string
import zipfile
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
W = f"{{{W_NS}}}"
XML_SPACE = f"{{{XML_NS}}}space"

CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
FOOTNOTES_PART = "word/footnotes.xml"
FOOTNOTES_CT = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
)
FOOTNOTES_RT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
)
DOC_RELS_PART = "word/_rels/document.xml.rels"
CT_PART = "[Content_Types].xml"
STYLES_PART = "word/styles.xml"
SETTINGS_PART = "word/settings.xml"
STYLES_CT = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
)
SETTINGS_CT = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"
)
STYLES_RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
SETTINGS_RT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings"
)

CSL_SCHEMA = (
    "https://github.com/citation-style-language/schema/raw/master/csl-citation.json"
)
ITEM_PREFIX = "ADDIN ZOTERO_ITEM CSL_CITATION"
BIBL_PREFIX = "ADDIN ZOTERO_BIBL"
BIBL_SUFFIX = "CSL_BIBLIOGRAPHY"
PREF_PREFIX = "ADDIN ZOTERO_PREF_"
PREF_CHUNK_SIZE = 255
DATA_VERSION = "3"
ZOTERO_VERSION = "7.0.15"


class WordFieldError(RuntimeError):
    """Alan kodu yazılamadı (mesaj kullanıcıya gösterilebilir)."""


# ------------------------------------------------------------------ yardımcılar

def random_id(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def style_url(style: str) -> str:
    """'isnad-dipnotlu' ya da tam URL kabul eder."""
    style = (style or "").strip()
    if style.startswith("http://") or style.startswith("https://"):
        return style
    return f"http://www.zotero.org/styles/{style}"


def _compact(payload: Any) -> str:
    """JavaScript'in JSON.stringify çıktısı gibi (boşluksuz) serileştirir."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# ------------------------------------------------------------------ alan kodları

def build_citation_payload(
    entries: list[dict[str, Any]],
    *,
    formatted_citation: str,
    note_index: int = 0,
    citation_id: str | None = None,
) -> dict[str, Any]:
    """CSL_CITATION gövdesini kurar.

    `entries` her öğe için {uri, csl, locator?, label?, prefix?, suffix?} taşır.
    """
    citation_items: list[dict[str, Any]] = []
    for entry in entries:
        csl = dict(entry.get("csl") or {})
        item: dict[str, Any] = {
            "id": csl.get("id") or entry.get("uri"),
            "uris": [entry["uri"]] if entry.get("uri") else [],
            "itemData": csl,
        }
        if entry.get("prefix"):
            item["prefix"] = entry["prefix"]
        if entry.get("suffix"):
            item["suffix"] = entry["suffix"]
        if entry.get("locator"):
            item["locator"] = str(entry["locator"])
            item["label"] = entry.get("label") or "page"
        if entry.get("suppress_author"):
            item["suppress-author"] = True
        citation_items.append(item)

    return {
        "citationID": citation_id or random_id(),
        "properties": {
            "formattedCitation": formatted_citation,
            "plainCitation": formatted_citation,
            "noteIndex": note_index,
        },
        "citationItems": citation_items,
        "schema": CSL_SCHEMA,
    }


def citation_instruction(payload: dict[str, Any]) -> str:
    return f" {ITEM_PREFIX} {_compact(payload)} "


def bibliography_instruction(
    uncited: list[str] | None = None,
    omitted: list[str] | None = None,
    custom: list[Any] | None = None,
) -> str:
    payload = {
        "uncited": uncited or [],
        "omitted": omitted or [],
        "custom": custom or [],
    }
    return f" {BIBL_PREFIX} {_compact(payload)} {BIBL_SUFFIX} "


def detect_zotero_version() -> str:
    """Kurulu Zotero sürümünü profilden bulur (yoksa varsayılan sabit)."""
    env = __import__("os").environ.get("ZOTERO_VERSION")
    if env:
        return env
    base = Path(__import__("os").environ.get("APPDATA", "")) / "Zotero" / "Zotero" / "Profiles"
    try:
        for profile in sorted(base.iterdir()):
            ini = profile / "compatibility.ini"
            if not ini.exists():
                continue
            text = ini.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"(\d+\.\d+(?:\.\d+)*)", text)
            if match:
                return match.group(1)
    except OSError:
        pass
    return ZOTERO_VERSION


def build_prefs_json(
    *,
    style: str,
    locale: str = "tr-TR",
    session_id: str | None = None,
    note_type: int = 1,
    has_bibliography: bool = True,
    bibliography_style_has_been_set: bool = True,
    zotero_version: str | None = None,
    delay_citation_updates: bool = False,
    automatic_journal_abbreviations: bool = False,
) -> str:
    """Belge tercihlerini Zotero'nun JSON (dataVersion 4) biçiminde üretir.

    Zotero 7+ `DocumentData.unserialize` önce JSON.parse dener; XML biçimi eski
    sürümlerle uyumluluk içindir. JSON biçimi Zotero'nun kendi
    `serialize()` çıktısının alan adlarıyla birebir aynıdır.
    """
    payload = {
        "style": {
            "styleID": style_url(style),
            "locale": locale,
            "hasBibliography": bool(has_bibliography),
            "bibliographyStyleHasBeenSet": bool(bibliography_style_has_been_set),
        },
        "prefs": {
            "fieldType": "Field",
            "automaticJournalAbbreviations": bool(automatic_journal_abbreviations),
            "delayCitationUpdates": bool(delay_citation_updates),
            "noteType": int(note_type),
        },
        "sessionID": session_id or random_id(8),
        "zoteroVersion": zotero_version or detect_zotero_version(),
        "dataVersion": 4,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_prefs_xml(
    *,
    style: str,
    locale: str = "tr-TR",
    session_id: str | None = None,
    has_bibliography: bool = True,
    note_type: int = 1,
    automatic_journal_abbreviations: bool = False,
) -> str:
    """Belge tercih blob'u. note_type: 0 metin içi, 1 dipnot, 2 sonnot."""
    return (
        f'<data data-version="{DATA_VERSION}" zotero-version="{ZOTERO_VERSION}">'
        f'<session id="{session_id or random_id(8)}"/>'
        f"<style id={quoteattr(style_url(style))} locale={quoteattr(locale)} "
        f'hasBibliography="{1 if has_bibliography else 0}" '
        f'bibliographyStyleHasBeenSet="1"/>'
        f"<prefs>"
        f'<pref name="fieldType" value="Field"/>'
        f'<pref name="automaticJournalAbbreviations" value='
        f'"{str(automatic_journal_abbreviations).lower()}"/>'
        f'<pref name="noteType" value="{note_type}"/>'
        f"</prefs>"
        f"</data>"
    )


def prefs_instructions(prefs_xml: str) -> list[str]:
    chunks = [
        prefs_xml[i : i + PREF_CHUNK_SIZE]
        for i in range(0, len(prefs_xml), PREF_CHUNK_SIZE)
    ] or [""]
    return [f" {PREF_PREFIX}{n} {chunk} " for n, chunk in enumerate(chunks, start=1)]


def parse_citation_instruction(instruction: str) -> dict[str, Any] | None:
    text = (instruction or "").strip()
    if ITEM_PREFIX not in text:
        return None
    _, _, json_part = text.partition(ITEM_PREFIX)
    json_part = json_part.strip()
    if not json_part:
        return None
    try:
        return json.loads(json_part)
    except json.JSONDecodeError:
        end = _matching_brace(json_part)
        if end is None:
            return None
        try:
            return json.loads(json_part[:end])
        except json.JSONDecodeError:
            return None


def _matching_brace(text: str) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def is_citation_field(instruction: str) -> bool:
    return ITEM_PREFIX in (instruction or "")


def is_bibliography_field(instruction: str) -> bool:
    return BIBL_PREFIX in (instruction or "")


def is_prefs_field(instruction: str) -> bool:
    return PREF_PREFIX in (instruction or "")


def parse_prefs_chunk(instruction: str) -> tuple[int, str] | None:
    text = (instruction or "").strip()
    if PREF_PREFIX not in text:
        return None
    _, _, rest = text.partition(PREF_PREFIX)
    number, _, chunk = rest.partition(" ")
    try:
        return int(number), chunk
    except ValueError:
        return None


def style_from_prefs_xml(prefs_xml: str) -> dict[str, str]:
    result: dict[str, str] = {}
    marker = "<style "
    start = prefs_xml.find(marker)
    if start == -1:
        return result
    end = prefs_xml.find("/>", start)
    fragment = prefs_xml[start + len(marker) : end if end != -1 else None]
    for attribute in ("id", "locale", "noteType"):
        needle = f'{attribute}="'
        pos = fragment.find(needle)
        if pos != -1:
            value_start = pos + len(needle)
            value_end = fragment.find('"', value_start)
            result[attribute] = fragment[value_start:value_end]
    for attribute in ("noteType",):
        needle = f'name="{attribute}" value="'
        pos = prefs_xml.find(needle)
        if pos != -1:
            value_start = pos + len(needle)
            value_end = prefs_xml.find('"', value_start)
            result[attribute] = prefs_xml[value_start:value_end]
    return result


# ------------------------------------------------------------------ docx paketi

class FieldMatch:
    """Belgede bulunan bir Word alanı (begin…end koşu dizisi)."""

    def __init__(self, runs: list[ET.Element], instruction: str, result_text: str) -> None:
        self.runs = runs
        self.instruction = instruction
        self.result_text = result_text

    @property
    def citation_id(self) -> str | None:
        payload = parse_citation_instruction(self.instruction)
        if payload:
            return payload.get("citationID")
        return None

    @property
    def item_keys(self) -> list[str]:
        payload = parse_citation_instruction(self.instruction)
        if not payload:
            return []
        keys: list[str] = []
        for item in payload.get("citationItems") or []:
            for uri in item.get("uris") or ([item.get("uri")] if item.get("uri") else []):
                if uri:
                    keys.append(str(uri).rsplit("/", 1)[-1])
        return keys


def _run_text(run: ET.Element) -> str:
    parts: list[str] = []
    for child in run:
        if child.tag == f"{W}t":
            parts.append(child.text or "")
        elif child.tag == f"{W}tab":
            parts.append("\t")
        elif child.tag in (f"{W}br", f"{W}cr"):
            parts.append("\n")
    return "".join(parts)


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(_run_text(r) for r in paragraph.findall(f"{W}r"))


def iter_fields(paragraph: ET.Element) -> Iterator[FieldMatch]:
    """Paragraftaki Word alanlarını (begin → separate → result → end) gezer."""
    runs = paragraph.findall(f"{W}r")
    current: list[ET.Element] = []
    instruction = ""
    result = ""
    in_result = False
    for run in runs:
        char = run.find(f"{W}fldChar")
        instr = run.find(f"{W}instrText")
        if char is not None:
            kind = char.get(f"{W}fldCharType")
            if kind == "begin":
                current, instruction, result, in_result = [run], "", "", False
                continue
            if kind == "separate":
                in_result = True
                if current:
                    current.append(run)
                continue
            if kind == "end":
                if current:
                    current.append(run)
                    yield FieldMatch(list(current), instruction, result)
                current, instruction, result, in_result = [], "", "", False
                continue
        if not current:
            continue
        current.append(run)
        if instr is not None and not in_result:
            instruction += instr.text or ""
        elif in_result:
            result += _run_text(run)


DEFAULT_FONT = "Times New Roman"


def _font_rpr(font: str = DEFAULT_FONT, size_half: int | None = None) -> ET.Element:
    """Koşu özellikleri: yazı tipini AÇIKÇA yaz (kalıtıma bırakma).

    Kalıtıma bırakılırsa Word belgenin varsayılan yazı tipini (ör. Calibri)
    kullanır ve atıf/dipnot görünümü istenen biçimde olmaz.
    """
    rpr = ET.Element(f"{W}rPr")
    fonts = ET.SubElement(rpr, f"{W}rFonts")
    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
        fonts.set(f"{W}{attr}", font)
    if size_half:
        ET.SubElement(rpr, f"{W}sz").set(f"{W}val", str(size_half))
        ET.SubElement(rpr, f"{W}szCs").set(f"{W}val", str(size_half))
    return rpr


def _make_run(text: str, font: str = DEFAULT_FONT) -> ET.Element:
    run = ET.Element(f"{W}r")
    run.append(_font_rpr(font))
    node = ET.SubElement(run, f"{W}t")
    node.set(XML_SPACE, "preserve")
    node.text = text
    return run


def make_field_runs(
    instruction: str, result_text: str, font: str = DEFAULT_FONT
) -> list[ET.Element]:
    """begin → instrText → separate → sonuç → end koşu dizisini üretir."""
    runs: list[ET.Element] = []

    begin = ET.Element(f"{W}r")
    begin.append(_font_rpr(font))
    ET.SubElement(begin, f"{W}fldChar").set(f"{W}fldCharType", "begin")
    runs.append(begin)

    instr_run = ET.Element(f"{W}r")
    instr_run.append(_font_rpr(font))
    instr = ET.SubElement(instr_run, f"{W}instrText")
    instr.set(XML_SPACE, "preserve")
    instr.text = instruction
    runs.append(instr_run)

    separate = ET.Element(f"{W}r")
    separate.append(_font_rpr(font))
    ET.SubElement(separate, f"{W}fldChar").set(f"{W}fldCharType", "separate")
    runs.append(separate)

    # Zotero'nun kendi alanlarında sonuç koşusu yoktur (begin→instrText→
    # separate→end). Boş sonuç koşusu Word/eklenti tarafında alan okumayı
    # bozabildiği için sonuç metni varsa yazılır.
    if result_text:
        runs.append(_make_run(result_text, font))

    end = ET.Element(f"{W}r")
    end.append(_font_rpr(font))
    ET.SubElement(end, f"{W}fldChar").set(f"{W}fldCharType", "end")
    runs.append(end)
    return runs


def _register_prefixes(xml_text: str) -> None:
    """Belgedeki xmlns öneklerini koru (ElementTree aksi halde ns0 üretir)."""
    for prefix, uri in re.findall(r'xmlns:([A-Za-z0-9_]+)="([^"]+)"', xml_text):
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            continue
    if 'xmlns="' in xml_text:
        default = re.search(r'xmlns="([^"]+)"', xml_text)
        if default:
            ET.register_namespace("", default.group(1))


def _root_tag(xml_bytes: bytes) -> str:
    """XML'in kök başlangıç etiketini (tüm xmlns bildirimleriyle) döndürür."""
    text = xml_bytes.decode("utf-8", errors="replace")
    start = text.find("<")
    if start == -1 or text.startswith("<?xml"):
        start = text.find("<", text.find("?>") + 2) if "?>" in text else start
    depth_quote = False
    for index in range(start, len(text)):
        char = text[index]
        if char == '"':
            depth_quote = not depth_quote
        elif char == ">" and not depth_quote:
            return text[start : index + 1]
    return ""


def _serialize_part(root: ET.Element, original: bytes | None) -> bytes:
    """ET ağacını yazarken özgün kök etiketini geri koyar.

    ElementTree yalnızca kullandığı ad alanlarını bildirir; Word belgelerinin
    kökünde `mc:Ignorable` gibi önek listeleri vardır ve bunların bildirimi
    düşerse Word dosyayı "bozuk" sayar. Bu yüzden kök etiketi aynen korunur.
    """
    body = ET.tostring(root, encoding="utf-8").decode("utf-8")
    tag = _root_tag(original) if original else ""
    if tag:
        start = body.find("<")
        end = body.find(">", start)
        if start != -1 and end != -1:
            body = tag + body[end + 1 :]
    header = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    return (header + body).encode("utf-8")


class DocxPackage:
    """docx'ı zip olarak okur, word/document.xml'i düzenler, yeniden yazar."""

    DOC_NAME = "word/document.xml"

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise WordFieldError(f"belge yok: {self.path}")
        self._entries: list[tuple[zipfile.ZipInfo, bytes]] = []
        self._extra: dict[str, bytes] = {}
        raw_xml = b""
        with zipfile.ZipFile(self.path) as zf:
            for info in zf.infolist():
                data = zf.read(info.filename)
                if info.filename == self.DOC_NAME:
                    raw_xml = data
                self._entries.append((info, data))
        if not raw_xml:
            raise WordFieldError("word/document.xml bulunamadı (geçerli bir .docx mi?)")
        _register_prefixes(raw_xml.decode("utf-8", errors="replace"))
        self._xml_bytes = raw_xml
        self.root = ET.fromstring(raw_xml)
        self.body = self.root.find(f"{W}body")
        if self.body is None:
            raise WordFieldError("belge gövdesi (w:body) bulunamadı")
        self._footnotes_root: ET.Element | None = None
        self._footnotes_new = False
        for info, data in self._entries:
            if info.filename == FOOTNOTES_PART:
                self._footnotes_root = ET.fromstring(data)
                break

    # ---------------------------------------------------------------- okuma
    def paragraphs(self) -> list[ET.Element]:
        return list(self.body.iter(f"{W}p"))

    def fields(self) -> list[FieldMatch]:
        out: list[FieldMatch] = []
        for paragraph in self.paragraphs():
            out.extend(iter_fields(paragraph))
        return out

    def citations(self) -> list[FieldMatch]:
        return [f for f in self.fields() if is_citation_field(f.instruction)]

    def document_style(self) -> dict[str, str] | None:
        chunks: list[tuple[int, str]] = []
        for field in self.fields():
            if not is_prefs_field(field.instruction):
                continue
            parsed = parse_prefs_chunk(field.instruction)
            if parsed:
                chunks.append(parsed)
        if not chunks:
            return None
        blob = "".join(chunk for _, chunk in sorted(chunks))
        stripped = blob.lstrip()
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                return None
            style = data.get("style") or {}
            prefs = data.get("prefs") or {}
            return {
                "id": str(style.get("styleID", "")),
                "locale": str(style.get("locale", "")),
                "noteType": str(prefs.get("noteType", "")),
                "bicim": "json",
            }
        info = style_from_prefs_xml(blob)
        if info:
            info["bicim"] = "xml"
        return info

    # ---------------------------------------------------------------- yazma
    def _new_paragraph(self, runs: list[ET.Element]) -> ET.Element:
        paragraph = ET.Element(f"{W}p")
        for run in runs:
            paragraph.append(run)
        return paragraph

    def _insert_index(self) -> int:
        """sectPr'den önce ekle (varsa)."""
        children = list(self.body)
        for index, child in enumerate(children):
            if child.tag == f"{W}sectPr":
                return index
        return len(children)

    def append_field(
        self, instruction: str, result_text: str, font: str = DEFAULT_FONT
    ) -> int:
        paragraph = self._new_paragraph(make_field_runs(instruction, result_text, font))
        index = self._insert_index()
        self.body.insert(index, paragraph)
        return index

    def prepend_field(
        self, instruction: str, result_text: str, font: str = DEFAULT_FONT
    ) -> int:
        """Alanı belgenin BAŞINA ekler.

        Zotero'nun Word eklentisi belge verisini (ZOTERO_PREF_* alanları) belge
        başında arar; sonda duran tercih alanları okunmaz ve Zotero "Belge
        Tercihleri" penceresini açmak zorunda kalır.
        """
        paragraph = self._new_paragraph(make_field_runs(instruction, result_text, font))
        self.body.insert(0, paragraph)
        return 0

    def replace_marker(
        self, marker: str, instruction: str, result_text: str, font: str = DEFAULT_FONT
    ) -> bool:
        """`marker` metnini bulunduğu yerde alan koduyla değiştirir."""
        for paragraph in self.paragraphs():
            for run in paragraph.findall(f"{W}r"):
                node = run.find(f"{W}t")
                if node is None or not node.text or marker not in node.text:
                    continue
                before, _, after = node.text.partition(marker)
                node.text = before or None
                position = list(paragraph).index(run)
                field_runs = make_field_runs(instruction, result_text, font)
                for offset, field_run in enumerate(field_runs):
                    paragraph.insert(position + 1 + offset, field_run)
                if after:
                    paragraph.insert(position + 1 + len(field_runs), _make_run(after, font))
                return True
        return False

    def replace_prefs(self, instructions: list[str], result_text: str = "") -> int:
        """Var olan ZOTERO_PREF alanlarını siler, yenilerini belge BAŞINA ekler."""
        removed = 0
        for paragraph in self.paragraphs():
            for match in list(iter_fields(paragraph)):
                if not is_prefs_field(match.instruction):
                    continue
                for run in match.runs:
                    try:
                        paragraph.remove(run)
                    except ValueError:
                        continue
                removed += 1
        for instruction in reversed(list(instructions)):
            self.prepend_field(instruction, result_text)
        return removed

    def remove_citation(self, citation_id: str) -> bool:
        for paragraph in self.paragraphs():
            for match in list(iter_fields(paragraph)):
                if match.citation_id != citation_id:
                    continue
                for run in match.runs:
                    try:
                        paragraph.remove(run)
                    except ValueError:
                        continue
                return True
        return False

    # ---------------------------------------------------------------- dipnotlar

    def _original_bytes(self, name: str) -> bytes | None:
        for info, data in self._entries:
            if info.filename == name:
                return data
        return None

    def _style_id_for(self, kind: str) -> str:
        """Belgedeki dipnot stilinin kimliğini bulur (yerelleştirilmiş olabilir).

        Türkçe Word belgelerinde stiller `DipnotMetni` / `DipnotBavurusu`
        kimlikleriyle gelir; İngilizce kimlik yazılırsa belgede ikinci bir stil
        oluşur ve sayfa görünümü bozulur.
        """
        fallback = "FootnoteText" if kind == "text" else "FootnoteReference"
        target = "footnote text" if kind == "text" else "footnote reference"
        raw = self._part_bytes(STYLES_PART)
        if raw is None:
            return fallback
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return fallback
        for style in root.findall(f"{W}style"):
            name_node = style.find(f"{W}name")
            if name_node is None:
                continue
            if (name_node.get(f"{W}val") or "").strip().lower() == target:
                return style.get(f"{W}styleId") or fallback
        return fallback

    def _part_bytes(self, name: str) -> bytes | None:
        if name in self._extra:
            return self._extra[name]
        for info, data in self._entries:
            if info.filename == name:
                return data
        return None

    def _register_content_type(self, part_name: str, content_type: str) -> None:
        """[Content_Types].xml'e Override ekler (metin düzeyinde, biçim bozulmadan)."""
        raw = self._part_bytes(CT_PART)
        if raw is None:
            text = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<Types xmlns="{CT_NS}">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                "</Types>"
            )
        else:
            text = raw.decode("utf-8")
        if f'PartName="/{part_name}"' in text:
            return
        entry = (
            f'<Override PartName="/{part_name}" ContentType="{content_type}"/>'
        )
        text = text.replace("</Types>", f"{entry}</Types>")
        self._extra[CT_PART] = text.encode("utf-8")

    def _register_relationship(self, rel_type: str, target: str) -> None:
        """word/_rels/document.xml.rels'e ilişki ekler."""
        raw = self._part_bytes(DOC_RELS_PART)
        if raw is None:
            text = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<Relationships xmlns="{REL_NS}"></Relationships>'
            )
        else:
            text = raw.decode("utf-8")
        if f'"{target}"' in text and rel_type in text:
            return
        counter = 1
        rid = "rIdFootnotes"
        while f'Id="{rid}"' in text:
            counter += 1
            rid = f"rIdFootnotes{counter}"
        entry = f'<Relationship Id="{rid}" Type="{rel_type}" Target="{target}"/>'
        text = text.replace("</Relationships>", f"{entry}</Relationships>")
        self._extra[DOC_RELS_PART] = text.encode("utf-8")

    def ensure_footnotes_part(self) -> ET.Element:
        """word/footnotes.xml'i (yoksa) oluşturur; içerik türü + ilişkiyi ekler."""
        if self._footnotes_root is not None:
            return self._footnotes_root
        root = ET.Element(f"{W}footnotes")
        for fid, tag in ((-1, "separator"), (0, "continuationSeparator")):
            node = ET.SubElement(root, f"{W}footnote")
            node.set(f"{W}type", tag)
            node.set(f"{W}id", str(fid))
            paragraph = ET.SubElement(node, f"{W}p")
            run = ET.SubElement(paragraph, f"{W}r")
            ET.SubElement(run, f"{W}{tag}")
        self._footnotes_root = root
        self._footnotes_new = True
        self._register_content_type(FOOTNOTES_PART, FOOTNOTES_CT)
        self._register_relationship(FOOTNOTES_RT, "footnotes.xml")
        return root

    def _next_footnote_id(self) -> int:
        root = self.ensure_footnotes_part()
        ids: list[int] = []
        for node in root.findall(f"{W}footnote"):
            try:
                ids.append(int(node.get(f"{W}id") or 0))
            except (TypeError, ValueError):
                continue
        return (max(ids) + 1) if ids else 1

    def _footnote_element(
        self, fid: int, instruction: str, result_text: str, font: str = DEFAULT_FONT
    ) -> ET.Element:
        """Dipnot gövdesi: numara işareti (footnoteRef) + atıf alanı.

        Numara işareti olmadan Word dipnot numarasını göstermez, yazı tipi
        açıkça yazılmazsa belgenin varsayılanına düşer.
        """
        node = ET.Element(f"{W}footnote")
        node.set(f"{W}id", str(fid))
        paragraph = ET.SubElement(node, f"{W}p")
        ppr = ET.SubElement(paragraph, f"{W}pPr")
        style = ET.SubElement(ppr, f"{W}pStyle")
        style.set(f"{W}val", self._style_id_for("text"))
        ppr.append(_font_rpr(font, size_half=20))

        number_run = ET.SubElement(paragraph, f"{W}r")
        number_rpr = ET.SubElement(number_run, f"{W}rPr")
        number_style = ET.SubElement(number_rpr, f"{W}rStyle")
        number_style.set(f"{W}val", self._style_id_for("reference"))
        number_rpr.append(_font_rpr(font))
        ET.SubElement(number_run, f"{W}footnoteRef")
        paragraph.append(_make_run(" ", font))

        for run in make_field_runs(instruction, result_text, font):
            paragraph.append(run)
        return node

    def _footnote_reference_run(self, fid: int, font: str = DEFAULT_FONT) -> ET.Element:
        run = ET.Element(f"{W}r")
        rpr = ET.SubElement(run, f"{W}rPr")
        style = ET.SubElement(rpr, f"{W}rStyle")
        style.set(f"{W}val", self._style_id_for("reference"))
        rpr.append(_font_rpr(font))
        ref = ET.SubElement(run, f"{W}footnoteReference")
        ref.set(f"{W}id", str(fid))
        return run

    def add_footnote_at_marker(
        self, marker: str, instruction: str, result_text: str
    ) -> bool:
        """İşaret metnini gerçek bir Word dipnotuna çevirir (içinde atıf alanı)."""
        fid = self.next_footnote_id()
        return self.add_footnote(fid, instruction, result_text, marker=marker)

    def next_footnote_id(self) -> int:
        return self._next_footnote_id()

    def ensure_styles_part(self, font: str = DEFAULT_FONT) -> ET.Element:
        """FootnoteReference/FootnoteText stillerini bulur, yoksa ekler.

        Var olan (ör. Türkçe Word'ün `DipnotMetni`/`DipnotBavurusu`) dipnot
        stillerinin yazı tipi de istenen yazı tipine çekilir: atıf görünümü
        belgenin varsayılan yazı tipinden bağımsız olmalı.
        """
        raw = self._part_bytes(STYLES_PART)
        if raw is None:
            root = ET.Element(f"{W}styles")
            self._register_content_type(STYLES_PART, STYLES_CT)
            self._register_relationship(STYLES_RT, "styles.xml")
        else:
            root = ET.fromstring(raw)
        existing = {s.get(f"{W}styleId") for s in root.findall(f"{W}style")}
        named = {
            (s.find(f"{W}name").get(f"{W}val") or "").strip().lower(): s
            for s in root.findall(f"{W}style")
            if s.find(f"{W}name") is not None
        }

        def _set_font(style: ET.Element) -> None:
            rpr = style.find(f"{W}rPr")
            if rpr is None:
                rpr = ET.SubElement(style, f"{W}rPr")
            fonts = rpr.find(f"{W}rFonts")
            if fonts is None:
                fonts = ET.Element(f"{W}rFonts")
                rpr.insert(0, fonts)
            for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
                fonts.set(f"{W}{attr}", font)

        if "FootnoteReference" not in existing:
            if "footnote reference" in named:
                _set_font(named["footnote reference"])
            else:
                style = ET.SubElement(root, f"{W}style")
                style.set(f"{W}type", "character")
                style.set(f"{W}styleId", "FootnoteReference")
                ET.SubElement(style, f"{W}name").set(f"{W}val", "footnote reference")
                rpr = ET.SubElement(style, f"{W}rPr")
                ET.SubElement(rpr, f"{W}vertAlign").set(f"{W}val", "superscript")
                _set_font(style)
        elif "FootnoteReference" in existing:
            for style in root.findall(f"{W}style"):
                if style.get(f"{W}styleId") == "FootnoteReference":
                    _set_font(style)

        if "FootnoteText" not in existing:
            if "footnote text" in named:
                _set_font(named["footnote text"])
            else:
                style = ET.SubElement(root, f"{W}style")
                style.set(f"{W}type", "paragraph")
                style.set(f"{W}styleId", "FootnoteText")
                ET.SubElement(style, f"{W}name").set(f"{W}val", "footnote text")
                ppr = ET.SubElement(style, f"{W}pPr")
                ET.SubElement(ppr, f"{W}spacing").set(f"{W}after", "0")
                rpr = ET.SubElement(style, f"{W}rPr")
                ET.SubElement(rpr, f"{W}sz").set(f"{W}val", "20")
                _set_font(style)
        elif "FootnoteText" in existing:
            for style in root.findall(f"{W}style"):
                if style.get(f"{W}styleId") == "FootnoteText":
                    _set_font(style)

        self._extra[STYLES_PART] = ET.tostring(
            root, encoding="UTF-8", xml_declaration=True
        )
        return root

    def ensure_settings_part(self) -> ET.Element:
        """settings.xml'e dipnot numaralandırma ayarını (footnotePr) ekler."""
        raw = self._part_bytes(SETTINGS_PART)
        if raw is None:
            root = ET.Element(f"{W}settings")
            self._register_content_type(SETTINGS_PART, SETTINGS_CT)
            self._register_relationship(SETTINGS_RT, "settings.xml")
        else:
            root = ET.fromstring(raw)
        if root.find(f"{W}footnotePr") is None:
            pr = ET.Element(f"{W}footnotePr")
            ET.SubElement(pr, f"{W}numFmt").set(f"{W}val", "decimal")
            ET.SubElement(pr, f"{W}numRestart").set(f"{W}val", "continuous")
            anchor = 0
            for index, child in enumerate(list(root)):
                if child.tag == f"{W}defaultTabStop":
                    anchor = index + 1
            root.insert(anchor, pr)
        self._extra[SETTINGS_PART] = ET.tostring(
            root, encoding="UTF-8", xml_declaration=True
        )
        return root

    def add_footnote(
        self,
        fid: int,
        instruction: str,
        result_text: str,
        marker: str = "",
        font: str = DEFAULT_FONT,
    ) -> bool:
        """Kimliği verilen dipnotu ekler; `marker` varsa o noktaya referans koyar.

        Numara işareti (footnoteRef), dipnot stilleri ve yazı tipi yazılır;
        aksi halde Word numarayı göstermez ya da yazı tipi belgenin
        varsayılanına düşer.
        """
        target: tuple[ET.Element, ET.Element] | None = None
        if marker:
            for paragraph in self.paragraphs():
                for run in paragraph.findall(f"{W}r"):
                    node = run.find(f"{W}t")
                    if node is not None and node.text and marker in node.text:
                        target = (paragraph, run)
                        break
                if target:
                    break
            if target is None:
                return False

        self.ensure_styles_part(font)
        self.ensure_settings_part()
        self.ensure_footnotes_part().append(
            self._footnote_element(fid, instruction, result_text, font)
        )

        if target is None:
            paragraph = ET.Element(f"{W}p")
            paragraph.append(self._footnote_reference_run(fid, font))
            self.body.insert(self._insert_index(), paragraph)
            return True

        paragraph, run = target
        node = run.find(f"{W}t")
        before, _, after = node.text.partition(marker)
        node.text = before or None
        position = list(paragraph).index(run)
        paragraph.insert(position + 1, self._footnote_reference_run(fid, font))
        if after:
            paragraph.insert(position + 2, _make_run(after, font))
        return True

    def add_footnote_at_end(
        self, instruction: str, result_text: str, font: str = DEFAULT_FONT
    ) -> int:
        fid = self.next_footnote_id()
        self.add_footnote(fid, instruction, result_text, font=font)
        return fid

    def footnote_fields(self) -> list[FieldMatch]:
        """Dipnot gövdesindeki alanlar (atıflar dipnotta yaşayabilir)."""
        if self._footnotes_root is None:
            return []
        out: list[FieldMatch] = []
        for node in self._footnotes_root.findall(f"{W}footnote"):
            for paragraph in node.iter(f"{W}p"):
                out.extend(iter_fields(paragraph))
        return out

    def all_fields(self) -> list[FieldMatch]:
        return self.fields() + self.footnote_fields()

    # ---------------------------------------------------------------- kayıt
    def save(self, target: Path | str | None = None, backup: bool = True) -> Path:
        target = Path(target) if target else self.path
        if backup and target == self.path:
            shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".bak"))
        updates: dict[str, bytes] = {
            self.DOC_NAME: _serialize_part(self.root, self._xml_bytes)
        }
        if self._footnotes_root is not None:
            updates[FOOTNOTES_PART] = _serialize_part(
                self._footnotes_root, self._part_bytes(FOOTNOTES_PART)
            )
        for name in (STYLES_PART, SETTINGS_PART):
            if name in self._extra:
                root = ET.fromstring(self._extra[name])
                updates[name] = _serialize_part(root, self._original_bytes(name))
        updates.update(
            {
                key: value
                for key, value in self._extra.items()
                if key in (CT_PART, DOC_RELS_PART)
            }
        )
        tmp = target.with_suffix(target.suffix + ".tmp")
        existing = {info.filename for info, _ in self._entries}
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for info, data in self._entries:
                zf.writestr(info, updates.get(info.filename, data))
            for name, payload in updates.items():
                if name not in existing:
                    zf.writestr(name, payload)
        tmp.replace(target)
        return target


__all__ = [
    "BIBL_PREFIX",
    "CSL_SCHEMA",
    "DocxPackage",
    "FieldMatch",
    "ITEM_PREFIX",
    "PREF_PREFIX",
    "WordFieldError",
    "bibliography_instruction",
    "build_citation_payload",
    "build_prefs_json",
    "build_prefs_xml",
    "citation_instruction",
    "detect_zotero_version",
    "is_bibliography_field",
    "is_citation_field",
    "is_prefs_field",
    "make_field_runs",
    "parse_citation_instruction",
    "prefs_instructions",
    "random_id",
    "style_url",
]
