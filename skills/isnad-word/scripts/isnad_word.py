"""INAD-Word COM araç seti v2 — açık Word belgesi üzerinde çalışır (MCP gerekmez).

KANONİK DOSYA: bu dosya `isnad-word/skills` altındaki kopyadır. `isnad` skill'indeki
kopya ince bir yönlendiricidir (shim); tüm geliştirmeler BURADA yapılır.

Alt komutlar (çıktı: stdout'a UTF-8 JSON):
  list                          Açık belgeleri listele.
  find <metin>                  Metni belgede ara; paragraf no + bağlam döndür.
  footnotes                     Dipnotları listele (metin, font, italik durumu).
  cite                          Zotero-farkındalıklı İSNAD dipnotu ekle (TAM/KISA otomatik).
  shortform                     Mevcut dipnotu kısa forma çevir.
  insert                        Belge sonuna gövde paragrafı ekle.
  addbib                        Belge sonuna kaynakça girdisi ekle (başlık yoksa oluşturur).
  bibliography                  --log dosyasından İSNAD kaynakça taslağı üret.
  verify                        Dipnotları İSNAD kurallarına karşı denetle (salt okunur).
  fix                           verify'nin otomatik düzeltilebilir bulgularını uygula.
  prepare                       Zotero üstverisinden İSNAD künye öner (Word gerekmez).
  export                        --log dosyasından RIS / CSL-JSON üret (Zotero'ya aktarılır).

Zotero okunurluğu iki yolla sağlanır:
  1) `export` ile RIS/CSL-JSON üret → Zotero'ya File > Import ile alınır (asıl yol).
  2) `cite --zotero-field` ile dipnota ADDIN ZOTERO_ITEM ISNAD alanı gömülür; tarama
     (`scan_prior`) bunu tanır. (Deneysel: Zotero'nun kendi Refresh akışıyla tam
     bütünleşme garanti edilmez; RIS aktarımı birincil yoldur.)
"""

import argparse
import datetime
import io
import json
import os
import re
import sys
import unicodedata

SKILL_VERSION = "2.0.2"
LOG_SCHEMA = 1


def _fix_stdout():
    try:
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                          errors="replace")
    except Exception:
        pass

try:
    import pythoncom
    import win32com.client
    HAS_COM = True
except Exception:
    HAS_COM = False


# ---------------------------------------------------------------- saf çıkışlar

def dump(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def fail(code, **kw):
    obj = {"error": code}
    obj.update(kw)
    dump(obj)
    raise SystemExit(1)


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------- saf metin yardımcıları

_APOS_SRC = ["\u2019", "\u2018", "`", "\u00b4", "\u02bc", "\u02be", "\u02bf"]
_APOS_SPLIT = ["'", "\u2019", "\u2018", "`", "\u00b4"]  # tarama anahtarı; ʾ/ʿ harftir, bölünmez


def norm(s):
    """Karşılaştırma amaçlı normalleştirme: aksansız, küçük harf, tek boşluk."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    for a in _APOS_SRC:
        s = s.replace(a, "'")
    return re.sub(r"\s+", " ", s).strip().casefold()


def split_short_head(short_title):
    """Kısa başlığın tarama anahtarı: kesme işaretinden önceki ayırt edici kısım."""
    st = (short_title or "").strip()
    if not st:
        return ""
    for a in _APOS_SPLIT:
        if a in st:
            head = st.split(a)[0].strip()
            if head:
                return head
    words = st.split()
    return " ".join(words[:3])


def make_short_title(title):
    """Üstveriden kısa başlık üret: alt başlığı at, kalan uzunsa ilk 5 sözcük."""
    title = (title or "").strip()
    if not title:
        return ""
    base = re.split(r"\s*[:–—]\s*", title, maxsplit=1)[0].strip()
    words = base.split()
    return base if len(words) <= 5 else " ".join(words[:5])


def build_cite_text(surname, short_title, full, page, prior):
    """Dipnot metni kur (saf): prior True ise KISA, değilse TAM form."""
    page_part = ", {}".format(page) if page else ""
    if prior:
        return ("{}, {}{}.".format(surname, short_title, page_part), "KISA")
    return ("{}{}.".format(full, page_part), "TAM")


BANNED_RE = re.compile(r"\ba\s*\.\s*g\s*\.\s*(e|m)\s*\.?", re.IGNORECASE)
PAGE_S_RE = re.compile(r"(?<![\w/])s\s*\.\s*\d", re.IGNORECASE)


def verify_text(text):
    """Dipnot metnini İSNAD kurallarına karşı denetle (saf)."""
    issues = []
    t = text or ""
    if not t.strip():
        return [{"code": "EMPTY", "msg": "Dipnot metni boş.", "fixable": False}]
    if BANNED_RE.search(t):
        issues.append({"code": "BANNED_AGE", "msg": "a.g.e./a.g.m. yasak; kısa form kullanılmalı.",
                       "fixable": False})
    if PAGE_S_RE.search(t):
        issues.append({"code": "PAGE_S", "msg": "'s.' kullanılmaz; sayfa doğrudan yazılır.",
                       "fixable": False})
    if re.search(r"  +", t):
        issues.append({"code": "DOUBLE_SPACE", "msg": "Çift boşluk var.", "fixable": True})
    if t != t.strip():
        issues.append({"code": "TRIM", "msg": "Baştaki/sondaki boşluk.", "fixable": True})
    if not t.rstrip().endswith("."):
        issues.append({"code": "TRAILING_PERIOD", "msg": "Dipnot noktayla bitmeli.", "fixable": True})
    return issues


def apply_text_fixes(t):
    t = re.sub(r"  +", " ", t).strip()
    if t and not t.endswith("."):
        t = t + "."
    return t


# ------------------------------------------------- üstveri (meta) eşleme + künye

META_TYPES = ("book", "journalArticle", "bookSection", "thesis",
              "encyclopediaArticle", "webpage")
CSL_TYPES = {"book": "book", "journalArticle": "article-journal",
             "bookSection": "chapter", "thesis": "thesis",
             "encyclopediaArticle": "entry-encyclopedia", "webpage": "webpage"}
RIS_TYPES = {"book": "BOOK", "journalArticle": "JOUR", "bookSection": "CHAP",
             "thesis": "THES", "encyclopediaArticle": "ENCYC", "webpage": "WEB"}


def _split_name(nm):
    nm = (nm or "").strip()
    if not nm:
        return {"first": "", "last": ""}
    parts = nm.split()
    if len(parts) == 1:
        return {"first": "", "last": parts[0]}
    return {"first": " ".join(parts[:-1]), "last": parts[-1]}


def _year_of(date_str):
    """Sayısal yıl (sıralama/CSL/RIS için): çift tarihte son grup (milâdî)."""
    groups = re.findall(r"(\d{3,4})", str(date_str or ""))
    return groups[-1] if groups else ""


def _year_display(date_str):
    """Görünür yıl: '1432/2011' korunur, ISO/doğal tarihten yıl çıkarılır."""
    d = (date_str or "").strip()
    if not d or d.lower() == "ts.":
        return "ts."
    if re.fullmatch(r"\d{3,4}/\d{3,4}", d):
        return d
    y = _year_of(d)
    return y or d


def coerce_meta(raw):
    """Zotero benzi üstveriyi kanonik meta sözlüğe çevir (saf). Uydurma yapmaz."""
    raw = raw or {}
    warn = []
    if isinstance(raw.get("creators"), list) and raw["creators"]:
        authors = []
        for c in raw["creators"]:
            if not isinstance(c, dict):
                continue
            if c.get("firstName") or c.get("lastName"):
                authors.append({"first": (c.get("firstName") or "").strip(),
                                "last": (c.get("lastName") or "").strip()})
            elif c.get("name"):
                authors.append(_split_name(c["name"]))
        if not authors:
            warn.append("Yazar adı boş; künye eksik üretildi.")
    elif isinstance(raw.get("authors"), list) and raw["authors"] and \
            all(isinstance(a, dict) for a in raw["authors"]):
        # Zaten normalize edilmiş üstveri (prepare --save çıktısı): aynen al.
        authors = [{"first": (a.get("first") or "").strip(),
                    "last": (a.get("last") or "").strip()} for a in raw["authors"]]
        if not any(a["last"] for a in authors):
            warn.append("Yazar adı boş; künye eksik üretildi.")
    elif raw.get("author") or raw.get("authors"):
        val = raw.get("authors") or [raw.get("author")]
        authors = [_split_name(a) if isinstance(a, str) else {"first": "", "last": ""} for a in val]
    else:
        authors = []
        warn.append("Yazar bilgisi yok.")
    mtype = raw.get("itemType") or raw.get("type") or "book"
    if mtype not in META_TYPES:
        warn.append("Bilinmeyen tür '{}'; 'book' varsayıldı.".format(mtype))
        mtype = "book"
    extra = str(raw.get("extra") or "")
    thk, nsr = [], []
    for line in extra.splitlines():
        mm = re.match(r"\s*editorial-director\s*:\s*(.+)", line)
        if mm:
            thk.append(mm.group(1).strip())
    raw_date = (raw.get("date") or raw.get("year") or "").strip()
    meta = {
        "itemKey": raw.get("itemKey") or raw.get("key") or raw.get("id") or "",
        "itemType": mtype,
        "title": (raw.get("title") or "").strip(),
        "shortTitle": (raw.get("shortTitle") or "").strip(),
        "authors": authors,
        "date": raw_date,
        "year": _year_of(raw_date),
        "yearDisplay": _year_display(raw_date),
        "publisher": (raw.get("publisher") or "").strip(),
        "place": (raw.get("place") or "").strip(),
        "edition": (raw.get("edition") or "").strip(),
        "volume": str(raw.get("volume") or "").strip(),
        "issue": str(raw.get("issue") or raw.get("number") or "").strip(),
        "pages": str(raw.get("pages") or "").strip(),
        "journal": (raw.get("publicationTitle") or raw.get("journal") or "").strip(),
        "bookTitle": (raw.get("bookTitle") or "").strip(),
        "editor": (raw.get("editor") or "").strip(),
        "tahkik": [t for t in (raw.get("tahkik") or thk)],
        "nesir": list(raw.get("nesir") or nsr),
        "translator": (raw.get("translator") or "").strip(),
        "thesisType": (raw.get("thesisType") or raw.get("type") or "").strip(),
        "university": (raw.get("university") or raw.get("school") or "").strip(),
        "url": (raw.get("url") or "").strip(),
        "accessDate": (raw.get("accessDate") or "").strip(),
    }
    if not meta["shortTitle"] and meta["title"]:
        meta["shortTitle"] = make_short_title(meta["title"])
        warn.append("Short Title yoktu; otomatik üretildi: '{}'.".format(meta["shortTitle"]))
    if not meta["title"]:
        warn.append("Eser adı yok.")
    if not meta["year"]:
        warn.append("Yıl yok; 'ts.' uygulandı.")
    meta["warnings"] = warn
    meta["_coerced"] = True
    return meta


def _dipnot_authors(authors):
    names = ["{} {}".format(a["first"], a["last"]).strip() for a in authors if a["last"]]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return "{} - {}".format(names[0], names[1])
    return "{} vd.".format(names[0])


def _kaynakca_authors(authors):
    names = ["{}, {}".format(a["last"], a["first"]).strip(", ") for a in authors if a["last"]]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return "{} - {}".format(names[0], names[1])
    return "{} vd.".format(names[0])


def _surname(authors):
    return authors[0]["last"] if authors and authors[0]["last"] else ""


def _pub_bits(meta, parens):
    pub = meta["publisher"]
    place = meta["place"] or "b.y."
    core = "{}: {}".format(place, pub) if pub else place
    bits = [core]
    if meta["edition"]:
        bits.append(meta["edition"])
    bits.append(meta["yearDisplay"] or "ts.")
    s = ", ".join(bits)
    return "({})".format(s) if parens else s


def _roles(meta):
    """thk./nşr./çev. parçaları, başsız (birleşim yerinde virgül eklenir)."""
    r = []
    if meta["tahkik"]:
        r.append("thk. {}".format(" - ".join(meta["tahkik"])))
    if meta["nesir"]:
        r.append("nşr. {}".format(" - ".join(meta["nesir"])))
    if meta["translator"]:
        r.append("çev. {}".format(meta["translator"]))
    return ", ".join(r)


def _pg(page):
    return ", {}".format(page) if page else ""


def build_dipnot(meta, page=""):
    """Tam künye dipnot metni + italik aralıklar (saf)."""
    t = meta["itemType"]
    a = _dipnot_authors(meta["authors"])
    roles = _roles(meta)
    italic = []
    if t == "book":
        italic = [meta["title"]] if meta["title"] else []
        text = "{}, {}".format(a, meta["title"])
        if roles:
            text += ", {}".format(roles)
        text += " {}".format(_pub_bits(meta, True))
    elif t == "journalArticle":
        vol = meta["volume"]
        if meta["issue"]:
            vol = "{}/{}".format(vol, meta["issue"]) if vol else meta["issue"]
        head = "{} {}".format(meta["journal"], vol).strip()
        text = '{}, "{}", {} ({})'.format(a, meta["title"], head,
                                          meta["yearDisplay"] or "ts.")
    elif t == "bookSection":
        text = '{}, "{}", içinde {}'.format(a, meta["title"], meta["bookTitle"])
        if meta["editor"]:
            text += ", ed. {}".format(meta["editor"])
        if roles:
            text += ", {}".format(roles)
        text += " {}".format(_pub_bits(meta, True))
    elif t == "thesis":
        typ = meta["thesisType"] or "Tez"
        text = "{}, {} ({}, {}, {})".format(a, meta["title"], typ, meta["university"],
                                            meta["yearDisplay"] or "ts.")
    elif t == "encyclopediaArticle":
        cited = page or meta["pages"]
        text = '{}, "{}", {} {}'.format(a, meta["title"], meta["bookTitle"],
                                        _pub_bits(meta, True))
        if cited:
            text += ", {}".format(cited)
            page = ""
    else:  # webpage: dipnotta URL yok
        text = '{}, "{}" (Erişim {})'.format(a or "İnternet", meta["title"],
                                             meta["accessDate"] or "tarihsiz")
    text = re.sub(r"\s+", " ", "{}{}.".format(text, _pg(page))).strip()
    return {"text": text, "italic": [i for i in italic if i]}


def build_kaynakca(meta):
    """İSNAD kaynakça girdisi (saf)."""
    t = meta["itemType"]
    a = _kaynakca_authors(meta["authors"])
    roles = _roles(meta)
    if t == "book":
        text = "{}. {}".format(a, meta["title"])
        if roles:
            text += ". {}".format(roles)
        text += ". {}".format(_pub_bits(meta, False))
    elif t == "journalArticle":
        vol = meta["volume"]
        if meta["issue"]:
            vol = "{}/{}".format(vol, meta["issue"]) if vol else meta["issue"]
        head = "{} {}".format(meta["journal"], vol).strip()
        text = '{}. "{}". {} ({})'.format(a, meta["title"], head,
                                          meta["yearDisplay"] or "ts.")
        if meta["pages"]:
            text += ", {}".format(meta["pages"])
    elif t == "bookSection":
        text = '{}. "{}"'.format(a, meta["title"])
        if meta["pages"]:
            text += ". {}".format(meta["pages"])
        text += ". {}".format(meta["bookTitle"])
        if meta["editor"]:
            text += ", ed. {}".format(meta["editor"])
        if roles:
            text += ", {}".format(roles)
        text += ". {}".format(_pub_bits(meta, False))
    elif t == "thesis":
        typ = meta["thesisType"] or "Tez"
        text = "{}. {}. {}, {}, {}".format(a, meta["title"], typ, meta["university"],
                                           meta["yearDisplay"] or "ts.")
    elif t == "encyclopediaArticle":
        text = '{}. "{}". {}'.format(a, meta["title"], meta["bookTitle"])
        if meta["pages"]:
            text += ". {}".format(meta["pages"])
        text += ". {}".format(_pub_bits(meta, False))
    else:
        text = "{}. {}. Erişim {}".format(a, meta["title"],
                                          meta["accessDate"] or "tarihsiz")
        if meta["url"]:
            text += ". {}".format(meta["url"])
    text = re.sub(r"\s+", " ", text).strip()
    if t != "webpage" or not meta["url"]:
        text = text.rstrip(".") + "."
    return {"text": text, "italic": [meta["title"]] if t == "book" and meta["title"] else []}


def build_metinici(meta, page=""):
    s = _surname(meta["authors"])
    n = len([a for a in meta["authors"] if a["last"]])
    who = "{} vd.".format(s) if n > 2 else s
    return "({}, {}{})".format(who, meta["yearDisplay"] or "ts.", _pg(page))


# ------------------------------------------------------------- RIS / CSL-JSON

def _ris_pages(pages):
    m = re.match(r"\s*([\w/()]+)\s*[-–]\s*([\w/()]+)\s*", pages or "")
    if m:
        return m.group(1), m.group(2)
    return (pages or ""), ""


def build_ris(meta, dipnot_full=""):
    L = []
    L.append("TY  - {}".format(RIS_TYPES.get(meta["itemType"], "BOOK")))
    for a in meta["authors"]:
        L.append("AU  - {}, {}".format(a["last"], a["first"]).strip(", "))
    if meta["title"]:
        L.append("TI  - {}".format(meta["title"]))
    if meta["itemType"] == "journalArticle" and meta["journal"]:
        L.append("JO  - {}".format(meta["journal"]))
    if meta["itemType"] in ("bookSection", "encyclopediaArticle") and meta["bookTitle"]:
        L.append("T2  - {}".format(meta["bookTitle"]))
    if meta["publisher"]:
        L.append("PB  - {}".format(meta["publisher"]))
    if meta["place"]:
        L.append("CY  - {}".format(meta["place"]))
    if meta["year"]:
        L.append("Y1  - {}///".format(meta["year"]))
    if meta["volume"]:
        L.append("VL  - {}".format(meta["volume"]))
    if meta["issue"]:
        L.append("IS  - {}".format(meta["issue"]))
    sp, ep = _ris_pages(meta["pages"])
    if sp:
        L.append("SP  - {}".format(sp))
    if ep:
        L.append("EP  - {}".format(ep))
    if meta["edition"]:
        L.append("ET  - {}".format(meta["edition"]))
    if meta["url"]:
        L.append("UR  - {}".format(meta["url"]))
    if meta["itemKey"]:
        L.append("ID  - {}".format(meta["itemKey"]))
    notes = []
    if meta["tahkik"]:
        notes.append("thk.: {}".format("; ".join(meta["tahkik"])))
    if dipnot_full:
        notes.append("İSNAD dipnot: {}".format(dipnot_full))
    for n_ in notes:
        L.append("N1  - {}".format(n_))
    L.append("ER  - ")
    return "\n".join(L)


def build_csl(meta, dipnot_full=""):
    item = {"id": meta["itemKey"] or "isnad-1",
            "type": CSL_TYPES.get(meta["itemType"], "book")}
    if meta["title"]:
        item["title"] = meta["title"]
    if meta["shortTitle"]:
        item["shortTitle"] = meta["shortTitle"]
    if meta["authors"]:
        item["author"] = [{"family": a["last"], "given": a["first"]} for a in meta["authors"]]
    if meta["year"]:
        try:
            item["issued"] = {"date-parts": [[int(meta["year"])]]}
        except ValueError:
            item["issued"] = {"literal": meta["year"]}
    if meta["publisher"]:
        item["publisher"] = meta["publisher"]
    if meta["place"]:
        item["publisher-place"] = meta["place"]
    if meta["edition"]:
        item["edition"] = meta["edition"]
    if meta["volume"]:
        item["volume"] = meta["volume"]
    if meta["issue"]:
        item["issue"] = meta["issue"]
    if meta["pages"]:
        item["page"] = meta["pages"]
    if meta["itemType"] == "journalArticle" and meta["journal"]:
        item["container-title"] = meta["journal"]
    if meta["itemType"] in ("bookSection", "encyclopediaArticle") and meta["bookTitle"]:
        item["container-title"] = meta["bookTitle"]
    if meta["url"]:
        item["URL"] = meta["url"]
    if dipnot_full:
        item["note"] = "İSNAD dipnot: {}".format(dipnot_full)
    return item


# ------------------------------------------------------------------ COM katmanı

def need_com():
    if not HAS_COM:
        fail("no-com", msg="pywin32 yok; bu komut Word gerektirir. 'prepare' COM'suz çalışır.")


def get_apps():
    """Tüm çalışan Word örneklerini döndür (ROT gezgini + etkin nesne).

    Dispatch() tek başına, kayıtlı olmayan örnek varken GİZLİ boş bir örnek
    açabilir; o yüzden önce ROT'taki tüm Word.Application moniker'ları toplanır.
    """
    need_com()
    import win32com.client
    found = []

    def _add(app):
        try:
            sig = tuple(sorted(d.FullName.lower() for d in app.Documents))
        except Exception:
            sig = None
        if sig:
            key = ("docs", sig)
        else:
            key = ("empty", 0)  # belgesiz örneklerden tek temsilci yeter
        if all(k != key for k, _ in found):
            found.append((key, app))

    try:
        _add(win32com.client.GetActiveObject("Word.Application"))
    except Exception:
        pass
    try:
        ctx = pythoncom.CreateBindCtx(0)
        rot = pythoncom.GetRunningObjectTable()
        enum = rot.EnumRunning()
        while True:
            try:
                fetched = enum.Next(1)
            except Exception:
                break
            if not fetched:
                break
            mon = fetched[0]
            try:
                name = mon.GetDisplayName(ctx, None)
            except Exception:
                continue
            is_word_class = ("Word.Application" in name) or \
                ("{000209FF-0000-0000-C000-000000000046}" in name.upper())
            if is_word_class:
                try:
                    unk = rot.GetObject(mon)
                    _add(win32com.client.Dispatch(
                        unk.QueryInterface(pythoncom.IID_IDispatch)))
                except Exception:
                    continue
                continue
            if name.startswith("!"):
                continue
            # Dosya moniker'ı (kaydedilmemiş belgeler uzantısız da olabilir:
            # örn. 'Belge1'). Bağla, belgeyse uygulamasını al.
            low = name.lower()
            if "\\startup\\" in low:
                continue
            if os.path.basename(low) in ("normal.dotm", "normal.dot"):
                continue
            try:
                unk = rot.GetObject(mon)
                disp = win32com.client.Dispatch(
                    unk.QueryInterface(pythoncom.IID_IDispatch))
                app = disp.Application
                _ = app.Documents.Count
                _add(app)
            except Exception:
                continue
    except Exception:
        pass
    if not found:
        _add(win32com.client.Dispatch("Word.Application"))
    return [a for _, a in found]


def get_app():
    return get_apps()[0]


def open_doc(apps, doc_name):
    """Belgeyi TÜM örneklerde ara. --doc yoksa belgesi olan ilk örneği seç."""
    if not isinstance(apps, list):
        apps = [apps]
    if doc_name:
        key = doc_name.strip().lower()
        stem = os.path.splitext(key)[0]
        for app in apps:
            try:
                docs = list(app.Documents)
            except Exception:
                continue
            for d in docs:
                try:
                    nm, fp = d.Name.lower(), d.FullName.lower()
                except Exception:
                    continue
                if key in (nm, fp) or stem == os.path.splitext(nm)[0]:
                    return d
        all_docs = []
        for app in apps:
            try:
                all_docs += [d.Name for d in app.Documents]
            except Exception:
                pass
        fail("document-not-found", doc=doc_name, open_documents=all_docs)
    for app in apps:
        try:
            if app.Documents.Count > 0:
                return app.Documents(1)
        except Exception:
            continue
    fail("no-document", msg="Açık belge yok; Word'de belgeyi açın.")


def rng_fields(rng):
    try:
        return list(rng.Fields)
    except Exception:
        return []


def _has_zotero_field(rng):
    for fld in rng_fields(rng):
        try:
            if "ZOTERO_ITEM" in fld.Code.Text:
                return True
        except Exception:
            continue
    return False


def isnad_payload(code):
    """ADDIN ZOTERO_ITEM ISNAD {...} yükünü çöz (varsa)."""
    m = re.search(r"ADDIN\s+ZOTERO_ITEM\s+ISNAD\s*(\{.*\})", code, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def scan_prior(doc, surname, short_title, item_key, search_extra="", before_pos=None):
    """Önceki atıf tara (konumsal): çapa ÖNCESİNDE kalan dipnotlara bakılır.

    before_pos verilmezse (None) tüm belge taranır (eski davranış).
    """
    res = {"plain": False, "zotero_field": False, "isnad_field": False, "sources": []}
    nsur = norm(surname)
    last = norm(surname.split()[-1]) if surname else ""
    head = norm(split_short_head(short_title))
    nxtra = norm(search_extra) if search_extra else ""
    for i in range(1, doc.Footnotes.Count + 1):
        fn = doc.Footnotes(i)
        if before_pos is not None:
            try:
                if fn.Reference.Start >= before_pos:
                    continue
            except Exception:
                pass
        rng = fn.Range
        ntxt = norm(rng.Text)
        if nsur and head and nsur in ntxt and head in ntxt:
            if not nxtra or nxtra in ntxt:
                res["plain"] = True
                res["sources"].append("plain-text (footnote {})".format(i))
        for fld in rng_fields(rng):
            try:
                code = fld.Code.Text
            except Exception:
                continue
            if "ZOTERO_ITEM" not in code:
                continue
            pay = isnad_payload(code)
            if pay is not None:
                hit = (item_key and pay.get("itemKey") == item_key) or \
                      (last and last in norm(pay.get("surname", "")))
                if hit:
                    res["isnad_field"] = True
                    res["sources"].append("isnad-field (footnote {})".format(i))
                continue
            m = re.search(r"\{.*\}", code, re.S)
            blob = m.group(0) if m else code
            if (item_key and item_key in blob) or (last and last in norm(blob)):
                res["zotero_field"] = True
                res["sources"].append("zotero-field (footnote {})".format(i))
    return res


def fresh_range(doc):
    return doc.Range(0, doc.Content.End)


def locate_anchor(doc, anchor):
    """Anchörü bul: tam eşleşme → Word fuzzy → sondan kısaltma. (COM)."""
    rng = fresh_range(doc)
    rng.Find.ClearFormatting()
    rng.Find.MatchWildcards = False
    try:
        rng.Find.MatchFuzzy = False
    except Exception:
        pass
    if rng.Find.Execute(FindText=anchor):
        return rng, "exact"
    try:
        rng = fresh_range(doc)
        rng.Find.MatchFuzzy = True
        if rng.Find.Execute(FindText=anchor):
            return rng, "fuzzy"
    except Exception:
        pass
    words = anchor.split()
    for n in (6, 4, 2):
        if len(words) > n:
            tail = " ".join(words[-n:])
            rng = fresh_range(doc)
            rng.Find.MatchFuzzy = False
            if rng.Find.Execute(FindText=tail):
                return rng, "tail-{}".format(n)
    return None, "not-found"


def set_italic(rng, needle):
    """Dipnot aralığında geçen başlığı italik yap (COM)."""
    if not needle:
        return False
    f = rng.Duplicate
    f.Find.ClearFormatting()
    f.Find.MatchWildcards = False
    if f.Find.Execute(FindText=needle):
        f.Font.Italic = True
        return True
    return False


def load_meta_file(path):
    try:
        if path == "-":
            raw = json.load(sys.stdin)
        else:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
    except Exception as ex:
        fail("bad-meta", msg="Üstveri okunamadı: {}".format(ex))
    return coerce_meta(raw)


def read_log(path):
    recs = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        recs.append(json.loads(line))
                    except Exception:
                        pass
    except FileNotFoundError:
        pass
    return recs


def cmd_list(args):
    apps = get_apps()
    docs = []
    for ai, app in enumerate(apps):
        try:
            all_docs = list(app.Documents)
        except Exception:
            all_docs = []
        for d in all_docs:
            try:
                docs.append({"instance": ai, "name": d.Name,
                             "path": d.FullName, "paragraphs": d.Paragraphs.Count})
            except Exception:
                continue
    dump({"instances": len(apps), "count": len(docs), "documents": docs})


def cmd_find(args):
    apps = get_apps()
    doc = open_doc(apps, args.doc)
    rng = fresh_range(doc)
    hits = []
    while rng.Find.Execute(FindText=args.text) and len(hits) < 20:
        start = max(rng.Start - 60, 0)
        ctx = doc.Range(start, min(rng.End + 60, doc.Content.End)).Text
        para = doc.Range(0, rng.End).Paragraphs.Count
        hits.append({"paragraph": para, "context": ctx.replace("\r", " ").strip()})
        rng.Collapse(0)
        rng.End = doc.Content.End
    dump({"doc": doc.Name, "query": args.text, "matches": hits})


def cmd_footnotes(args):
    apps = get_apps()
    doc = open_doc(apps, args.doc)
    total = doc.Footnotes.Count
    items = []
    for i in range(1, min(total, args.limit) + 1):
        fn = doc.Footnotes(i)
        ref = fn.Reference
        try:
            it = fn.Range.Font.Italic
            italic = None if it in (None, 9999999) else bool(it)
        except Exception:
            italic = None
        items.append({
            "index": i,
            "text": fn.Range.Text.replace("\r", " ").strip(),
            "font": fn.Range.Font.Name,
            "size": fn.Range.Font.Size,
            "italic_mixed": italic,
            "ref_paragraph": doc.Range(0, ref.End).Paragraphs.Count,
            "has_zotero_field": _has_zotero_field(fn.Range),
        })
    dump({"doc": doc.Name, "total": total, "footnotes": items})


def cmd_cite(args):
    apps = get_apps()
    doc = open_doc(apps, args.doc)
    meta = load_meta_file(args.meta_json) if args.meta_json else None
    rng, method = locate_anchor(doc, args.anchor)
    if rng is None:
        sugg = []
        try:
            fr = fresh_range(doc)
            tail = " ".join(args.anchor.split()[-4:])
            while fr.Find.Execute(FindText=tail) and len(sugg) < 3:
                ctx = doc.Range(max(fr.Start - 40, 0),
                                min(fr.End + 40, doc.Content.End)).Text
                sugg.append(ctx.replace("\r", " ").strip())
                fr.Collapse(0)
                fr.End = doc.Content.End
        except Exception:
            pass
        fail("anchor-not-found", anchor=args.anchor, suggestions=sugg,
             hint="find komutuyla ayırt edici parçayı doğrulayın.")
    rng.Collapse(0)
    # Konumsal tarama: çapa noktasından ÖNCEKİ dipnotlarda aynı eser varsa KISA.
    try:
        anchor_pos = rng.Start
    except Exception:
        anchor_pos = None
    prev = scan_prior(doc, args.surname, args.short_title, args.item_key,
                      search_extra=args.search_extra, before_pos=anchor_pos)
    prior = prev["plain"] or prev["zotero_field"] or prev["isnad_field"]
    text, form = build_cite_text(args.surname, args.short_title, args.full, args.page, prior)
    foot = doc.Footnotes.Add(rng, "", "")
    foot.Range.Text = text
    foot.Range.Font.Name = args.font
    foot.Range.Font.Size = args.size
    italic_applied = set_italic(foot.Range, args.italic_title) if args.italic_title else False
    field_embedded = False
    if args.zotero_field and args.item_key:
        try:
            payload = json.dumps({"itemKey": args.item_key, "surname": args.surname,
                                  "shortTitle": args.short_title, "page": args.page or "",
                                  "form": form, "skill": "isnad-word", "v": LOG_SCHEMA},
                                 ensure_ascii=False)
            frng = foot.Range
            frng.Collapse(0)
            fld = foot.Range.Fields.Add(Range=frng, Type=19)
            fld.Code.Text = "ADDIN ZOTERO_ITEM ISNAD {}".format(payload)
            field_embedded = True
        except Exception as ex:
            field_embedded = "error: {}".format(ex)
    rec = None
    if args.log:
        rec = {"v": LOG_SCHEMA, "ts": utcnow(), "doc": doc.Name,
               "footnote_index": doc.Footnotes.Count, "form": form,
               "surname": args.surname, "short_title": args.short_title,
               "full": args.full, "page": args.page or "", "item_key": args.item_key or "",
               "italic_title": args.italic_title or "", "meta": meta}
        try:
            with open(args.log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as ex:
            rec = {"log_error": str(ex)}
    dump({"doc": doc.Name, "form": form, "inserted": text,
          "footnote_index": doc.Footnotes.Count, "anchor_method": method,
          "prev_detection": prev, "italic_applied": italic_applied,
          "zotero_field": field_embedded, "logged": bool(args.log)})


def cmd_shortform(args):
    apps = get_apps()
    doc = open_doc(apps, args.doc)
    try:
        fn = doc.Footnotes(args.index)
    except Exception:
        fail("no-footnote", index=args.index)
    old = fn.Range.Text.strip()
    fn.Range.Text = args.text
    fn.Range.Font.Name = args.font
    fn.Range.Font.Size = args.size
    italic_applied = set_italic(fn.Range, args.italic_title) if args.italic_title else False
    dump({"doc": doc.Name, "footnote": args.index, "old": old, "new": args.text,
          "italic_applied": italic_applied})


def cmd_insert(args):
    apps = get_apps()
    doc = open_doc(apps, args.doc)
    p = doc.Paragraphs.Add()
    p.Range.Text = args.text
    p.Range.Font.Name = args.font
    p.Range.Font.Size = args.size
    dump({"doc": doc.Name, "paragraphs": doc.Paragraphs.Count, "added": args.text})


def cmd_addbib(args):
    apps = get_apps()
    doc = open_doc(apps, args.doc)
    nhead = norm(args.heading)
    found = False
    for p in doc.Paragraphs:
        if norm(p.Range.Text) == nhead:
            found = True
            break
    if not found:
        hp = doc.Paragraphs.Add()
        hp.Range.Text = args.heading
        try:
            hp.Range.set_Style("Heading 1")
        except Exception:
            pass
    entry = doc.Paragraphs.Add()
    entry.Range.Text = args.text
    entry.Range.Font.Name = args.font
    entry.Range.Font.Size = args.size
    if args.italic_title:
        set_italic(entry.Range, args.italic_title)
    dump({"doc": doc.Name, "heading_created": not found, "added": args.text})


def cmd_bibliography(args):
    recs = read_log(args.log) if args.log else []
    groups = {}
    for r in recs:
        key = r.get("item_key") or "{}|{}".format(norm(r.get("surname", "")),
                                                  norm(r.get("short_title", "")))
        g = groups.setdefault(key, {"surname": r.get("surname", ""),
                                    "short_title": r.get("short_title", ""),
                                    "item_key": r.get("item_key", ""),
                                    "count": 0, "indices": [], "full": "", "meta": None})
        g["count"] += 1
        if r.get("footnote_index") not in g["indices"]:
            g["indices"].append(r.get("footnote_index"))
        if r.get("form") == "TAM" and r.get("full"):
            g["full"] = r["full"]
        if r.get("meta"):
            g["meta"] = r["meta"]
    entries = []
    for key in sorted(groups, key=lambda k: norm(groups[k]["surname"])):
        g = groups[key]
        if g["meta"]:
            kb = build_kaynakca(g["meta"])
            entries.append({"key": key, "surname": g["surname"], "count": g["count"],
                            "indices": sorted(i for i in g["indices"] if i),
                            "kaynakca": kb["text"], "italic": kb["italic"],
                            "needs_meta": False})
        else:
            entries.append({"key": key, "surname": g["surname"], "count": g["count"],
                            "indices": sorted(i for i in g["indices"] if i),
                            "kaynakca": "", "dipnot_tam": g["full"],
                            "needs_meta": True,
                            "hint": "Kaynakça için cite --meta-json ile meta kaydedin."})
    dump({"log": args.log, "works": len(entries), "entries": entries})


def cmd_verify(args):
    apps = get_apps()
    doc = open_doc(apps, args.doc)
    total = doc.Footnotes.Count
    out, counts = [], {}
    for i in range(1, min(total, args.limit) + 1):
        fn = doc.Footnotes(i)
        text = fn.Range.Text.replace("\r", " ").strip()
        for is_ in verify_text(text):
            is_ = dict(is_, index=i)
            out.append(is_)
            counts[is_["code"]] = counts.get(is_["code"], 0) + 1
        try:
            fname, fsize = fn.Range.Font.Name, fn.Range.Font.Size
        except Exception:
            fname, fsize = "", 0
        if fname != args.font:
            out.append({"index": i, "code": "FONT",
                        "msg": "Font '{}' olmalı, '{}' bulundu.".format(args.font, fname),
                        "fixable": True})
            counts["FONT"] = counts.get("FONT", 0) + 1
        if fsize != args.size:
            out.append({"index": i, "code": "SIZE",
                        "msg": "Punto {} olmalı, {} bulundu.".format(args.size, fsize),
                        "fixable": True})
            counts["SIZE"] = counts.get("SIZE", 0) + 1
    dump({"doc": doc.Name, "checked": min(total, args.limit), "total": total,
          "issues": out, "counts": counts})


def cmd_fix(args):
    apps = get_apps()
    doc = open_doc(apps, args.doc)
    only = set(c.strip().upper() for c in (args.only or "").split(",") if c.strip())
    total = doc.Footnotes.Count
    applied, skipped = [], []
    for i in range(1, min(total, args.limit) + 1):
        fn = doc.Footnotes(i)
        if not only or "TRIM" in only or "DOUBLE_SPACE" in only or "TRAILING_PERIOD" in only:
            new = apply_text_fixes(fn.Range.Text.replace("\r", " ").strip())
            if new != fn.Range.Text.strip() and not args.dry_run:
                fn.Range.Text = new
            if new != fn.Range.Text.strip() or args.dry_run:
                applied.append({"index": i, "code": "TEXT"})
        try:
            fname, fsize = fn.Range.Font.Name, fn.Range.Font.Size
        except Exception:
            fname, fsize = "", 0
        if (not only or "FONT" in only) and fname != args.font:
            if not args.dry_run:
                fn.Range.Font.Name = args.font
            applied.append({"index": i, "code": "FONT"})
        if (not only or "SIZE" in only) and fsize != args.size:
            if not args.dry_run:
                fn.Range.Font.Size = args.size
            applied.append({"index": i, "code": "SIZE"})
        for is_ in verify_text(fn.Range.Text):
            if not is_["fixable"]:
                skipped.append({"index": i, "code": is_["code"], "msg": is_["msg"]})
    dump({"doc": doc.Name, "dry_run": args.dry_run, "applied": applied,
          "manual": skipped})


def cmd_prepare(args):
    meta = load_meta_file(args.meta_json)
    page = args.page or ""
    if args.format in ("dipnot", "all"):
        dip = build_dipnot(meta, page)
    else:
        dip = None
    if args.format in ("kaynakca", "all"):
        kay = build_kaynakca(meta)
    else:
        kay = None
    out = {"surname": _surname(meta["authors"]),
           "short_title": meta["shortTitle"],
           "item_key": meta["itemKey"],
           "warnings": meta["warnings"]}
    if dip:
        out["dipnot_tam"] = dip["text"]
        out["dipnot_italic"] = dip["italic"]
        out["kisa_sablon"] = "{}, {}, {}.".format(out["surname"], meta["shortTitle"],
                                                  page or "[sayfa]")
    if kay:
        out["kaynakca"] = kay["text"]
        out["kaynakca_italic"] = kay["italic"]
    if args.format in ("metinici", "all"):
        out["metinici"] = build_metinici(meta, page)
    if args.save:
        try:
            with open(args.save, "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False, indent=2)
            out["saved_meta"] = args.save
        except Exception as ex:
            out["save_error"] = str(ex)
    dump(out)


def cmd_export(args):
    recs = read_log(args.log)
    with_meta = {}
    order = []
    for r in recs:
        if not r.get("meta"):
            continue
        key = r.get("item_key") or "{}|{}".format(norm(r.get("surname", "")),
                                                  norm(r.get("short_title", "")))
        if key not in with_meta:
            with_meta[key] = r["meta"]
            order.append(key)
    skipped = sum(1 for r in recs if not r.get("meta"))
    fmt = args.format.lower()
    if fmt == "ris":
        body = "\n\n".join(build_ris(with_meta[k]) for k in order)
        if body:
            body += "\n"
    elif fmt in ("csljson", "csl-json", "json"):
        body = json.dumps([build_csl(with_meta[k]) for k in order],
                          ensure_ascii=False, indent=2)
    else:
        fail("bad-format", format=args.format, want=["ris", "csljson"])
    try:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(body)
    except Exception as ex:
        fail("write-error", msg=str(ex))
    dump({"log": args.log, "format": fmt, "out": args.out,
          "items": len(order), "skipped_no_meta": skipped,
          "hint": "Zotero: File > Import from Clipboard / File ile alın."})


# ------------------------------------------------------------------ CLI

def add_doc_arg(p):
    p.add_argument("--doc", default="",
                   help="Hedef belge adı/tam yolu (varsayılan: ilk açık belge)")


def add_sub_doc_arg(p):
    # Alt komut SONRASI --doc: verilmezse üstteki global değer korunur (SUPPRESS).
    p.add_argument("--doc", default=argparse.SUPPRESS,
                   help="Hedef belge (komuttan önce veya sonra verilebilir)")


def add_font_args(p):
    p.add_argument("--font", default="Times New Roman")
    p.add_argument("--size", type=float, default=10)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="store_true", help="Betik sürümünü yazdır.")
    add_doc_arg(p)
    sub = p.add_subparsers(dest="cmd", required=False)

    sub.add_parser("list", help="Açık belgeleri listele.")
    f = sub.add_parser("find", help="Metni belgede ara."); add_sub_doc_arg(f)
    f.add_argument("text")

    fn = sub.add_parser("footnotes", help="Dipnotları listele."); add_sub_doc_arg(fn)
    fn.add_argument("--limit", type=int, default=200)

    c = sub.add_parser("cite", help="İSNAD dipnotu ekle (TAM/KISA otomatik)."); add_sub_doc_arg(c)
    c.add_argument("--anchor", required=True, help="Dipnot işaretinin konacağı cümle/parça.")
    c.add_argument("--page", default="", help="Sayfa (örn. 2/143). Verilmezse sayfasız künye.")
    c.add_argument("--item-key", default="", help="Zotero item key.")
    c.add_argument("--surname", required=True)
    c.add_argument("--short-title", required=True)
    c.add_argument("--full", required=True, help="Sayfasız tam künye.")
    c.add_argument("--search-extra", default="",
                   help="Düz metin taramasını güçlendiren ek anahtar.")
    c.add_argument("--italic-title", default="",
                   help="İtalik yapılacak eser adı (dipnotta).")
    c.add_argument("--zotero-field", action="store_true",
                   help="Dipnota ADDIN ZOTERO_ITEM ISNAD alanı göm (deneysel).")
    c.add_argument("--meta-json", default="",
                   help="prepare çıktısı / Zotero üstveri JSON yolu (log + kaynakça için).")
    c.add_argument("--log", default="", help="Atıf günlüğü JSONL dosyası (kaynakça/export için).")
    add_font_args(c)

    s = sub.add_parser("shortform", help="Dipnotu kısa forma çevir."); add_sub_doc_arg(s)
    s.add_argument("index", type=int)
    s.add_argument("text")
    s.add_argument("--italic-title", default="")
    add_font_args(s)

    b = sub.add_parser("addbib", help="Belge sonuna kaynakça girdisi ekle."); add_sub_doc_arg(b)
    b.add_argument("--text", required=True)
    b.add_argument("--heading", default="Kaynakça")
    b.add_argument("--italic-title", default="")
    b.add_argument("--font", default="Times New Roman")
    b.add_argument("--size", type=float, default=12)

    ins = sub.add_parser("insert", help="Belge sonuna gövde paragrafı ekle."); add_sub_doc_arg(ins)
    ins.add_argument("--text", required=True)
    ins.add_argument("--font", default="Times New Roman")
    ins.add_argument("--size", type=float, default=12)

    bb = sub.add_parser("bibliography", help="Günlükten kaynakça taslağı üret.")
    bb.add_argument("--log", required=True)

    v = sub.add_parser("verify", help="Dipnotları denetle (salt okunur)."); add_sub_doc_arg(v)
    v.add_argument("--limit", type=int, default=200)
    add_font_args(v)

    fx = sub.add_parser("fix", help="Otomatik düzeltmeleri uygula."); add_sub_doc_arg(fx)
    fx.add_argument("--limit", type=int, default=200)
    fx.add_argument("--only", default="", help="Virgüllü kod listesi (örn. FONT,SIZE).")
    fx.add_argument("--dry-run", action="store_true")
    add_font_args(fx)

    pr = sub.add_parser("prepare", help="Üstveriden İSNAD künye öner (Word gerekmez).")
    pr.add_argument("--meta-json", required=True, help="Üstveri JSON yolu ('-' stdin).")
    pr.add_argument("--format", default="all",
                    choices=["all", "dipnot", "kaynakca", "metinici"])
    pr.add_argument("--page", default="")
    pr.add_argument("--save", default="", help="Normalize üstveriyi kaydet (cite'ta yeniden kullan).")

    ex = sub.add_parser("export", help="Günlükten RIS/CSL-JSON üret (Zotero'ya aktarılır).")
    ex.add_argument("--log", required=True)
    ex.add_argument("--format", required=True, help="ris | csljson")
    ex.add_argument("--out", required=True)

    args = p.parse_args(argv)
    if args.version:
        dump({"script": "isnad_word.py", "version": SKILL_VERSION, "log_schema": LOG_SCHEMA})
        return
    if not args.cmd:
        p.print_help()
        raise SystemExit(2)
    try:
        {"list": cmd_list, "find": cmd_find, "footnotes": cmd_footnotes,
         "cite": cmd_cite, "shortform": cmd_shortform, "addbib": cmd_addbib,
         "insert": cmd_insert,
         "bibliography": cmd_bibliography, "verify": cmd_verify, "fix": cmd_fix,
         "prepare": cmd_prepare, "export": cmd_export}[args.cmd](args)
    except SystemExit:
        raise
    except Exception as ex:
        fail("internal", msg=str(ex))


if __name__ == "__main__":
    _fix_stdout()
    main()
