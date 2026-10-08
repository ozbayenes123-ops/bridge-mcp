"""isnad-word saf fonksiyon testleri (Word/COM gerekmez)."""
import importlib.util
import json
import os

import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "isnad_word.py")


@pytest.fixture(scope="module")
def m():
    spec = importlib.util.spec_from_file_location("isnad_word", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def book_meta(m):
    return m.coerce_meta({
        "itemKey": "SP8BELED", "itemType": "book",
        "title": "Telḫîṣü'l-edille li-ḳavâʿidi't-tevḥîd",
        "creators": [{"firstName": "Ebû İshâk İbrâhim ez-Zâhid", "lastName": "es-Saffâr"}],
        "date": "1432/2011", "publisher": "el-Ma'hedü'l-Almânî",
        "place": "Beyrut", "extra": "editorial-director: Angelika Brodersen",
    })


def test_version(m):
    assert m.SKILL_VERSION == "2.0.2"


def test_norm_folds_diacritics(m):
    assert m.norm("Telḫîṣü’l-edille") == "telhisu'l-edille"
    assert m.norm("  Saffâr   ") == "saffar"


def test_short_head_keeps_transliteration_letters(m):
    # ʿ/ʾ harftir: tarama anahtarı noktalama kesmesine göre bölünür
    assert m.split_short_head("Telḫîṣü'l-edille") == "Telḫîṣü"


def test_make_short_title(m):
    assert m.make_short_title("Telḫîṣü'l-edille li-ḳavâʿidi't-tevḥîd") == \
        "Telḫîṣü'l-edille li-ḳavâʿidi't-tevḥîd"
    assert m.make_short_title("Ana Başlık: Alt Başlık Uzun Uzun") == "Ana Başlık"


def test_cite_text_forms(m):
    t, f = m.build_cite_text("Saffâr", "Telḫîṣ", "FULL", "2/143", True)
    assert (t, f) == ("Saffâr, Telḫîṣ, 2/143.", "KISA")
    t, f = m.build_cite_text("Saffâr", "Telḫîṣ", "FULL", "", False)
    assert (t, f) == ("FULL.", "TAM")


def test_verify_banned_and_page_s(m):
    codes = [i["code"] for i in m.verify_text("Topaloğlu, Sözlük, s. 55")]
    assert "PAGE_S" in codes and "TRAILING_PERIOD" in codes


def test_verify_banned_age(m):
    codes = [i["code"] for i in m.verify_text("Yazar, a.g.e., 55.")]
    assert "BANNED_AGE" in codes


def test_verify_clean(m):
    assert m.verify_text("Saffâr, Telḫîṣü'l-edille, 2/143.") == []


def test_apply_text_fixes(m):
    assert m.apply_text_fixes("Saffâr,  Telḫîṣ") == "Saffâr, Telḫîṣ."


def test_prepare_book(m):
    meta = book_meta(m)
    assert meta["year"] == "2011" and meta["yearDisplay"] == "1432/2011"
    dip = m.build_dipnot(meta, "2/145")
    assert dip["text"] == ("Ebû İshâk İbrâhim ez-Zâhid es-Saffâr, "
                           "Telḫîṣü'l-edille li-ḳavâʿidi't-tevḥîd, thk. Angelika Brodersen "
                           "(Beyrut: el-Ma'hedü'l-Almânî, 1432/2011), 2/145.")
    kay = m.build_kaynakca(meta)
    assert kay["text"].startswith("es-Saffâr, Ebû İshâk İbrâhim ez-Zâhid.")
    assert kay["text"].endswith("1432/2011.")
    assert "(es-Saffâr, 1432/2011, 2/145)" == m.build_metinici(meta, "2/145")


def test_prepare_article(m):
    meta = m.coerce_meta({"itemType": "journalArticle",
                          "title": "Kelâm'ın Meşrûiyeti Sorunu",
                          "creators": [{"firstName": "Galip", "lastName": "Türcan"}],
                          "journal": "Marife", "volume": "5", "issue": "3",
                          "date": "2005", "pages": "175-193"})
    assert m.build_dipnot(meta, "180")["text"] == \
        "Galip Türcan, \"Kelâm'ın Meşrûiyeti Sorunu\", Marife 5/3 (2005), 180."
    assert m.build_kaynakca(meta)["text"] == \
        "Türcan, Galip. \"Kelâm'ın Meşrûiyeti Sorunu\". Marife 5/3 (2005), 175-193."


def test_coerce_warns_missing(m):
    meta = m.coerce_meta({"itemType": "book", "title": "X"})
    assert any("Yazar" in w for w in meta["warnings"])
    assert meta["yearDisplay"] == "ts."
    assert m.build_dipnot(meta)["text"].endswith("(b.y., ts.).")


def test_coerce_is_idempotent(m):
    meta = book_meta(m)
    again = m.coerce_meta(json.loads(json.dumps(meta)))
    assert again["authors"] == meta["authors"]
    assert m.build_kaynakca(again)["text"] == m.build_kaynakca(meta)["text"]


def test_ris_csl(m):
    meta = book_meta(m)
    ris = m.build_ris(meta)
    assert "TY  - BOOK" in ris and "ID  - SP8BELED" in ris and ris.endswith("ER  - ")
    csl = m.build_csl(meta)
    assert csl["type"] == "book" and csl["issued"] == {"date-parts": [[2011]]}
