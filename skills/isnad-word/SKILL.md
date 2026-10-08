---
name: isnad-word
description: "Açık Word belgesine COM (pywin32) üzerinden İSNAD 2. Edisyon dipnotu + kaynakça ekler; MCP gerekmez. Zotero-farkındalıklıdır: önceki atıfları (düz metin + Zotero ADDIN + ISNAD alanları) tarar, tekrar atıfta kısa formu otomatik kullanır. cite --log günlüğünden bibliography ile kaynakça taslağı, export ile Zotero'ya alınabilir RIS/CSL-JSON üretir. Kullanıcı 'word'e atıf ekle', 'İSNAD dipnotu koy', 'kaynakça ekle', 'Zotero'ya aktar' dediğinde kullan."
argument-hint: "<eser adı veya Zotero item key> [atıf noktası: cümle] [sayfa]"
---

# İSNAD-Word — Açık Word Belgesine Zotero-Farkındalıklı İSNAD Atfı (v2.0.2)

Word MCP sunucusuna **gerek yoktur**; tüm işlemler COM (pywin32) ile doğrudan çalışır.
Künye formatı için `isnad-kunye` skill'ini ve yanındaki
`references/isnad-kurallari.md` dosyasını izle. Künye kaynağı Zotero'dur
(`zotero_search_items` → `zotero_item_metadata`).

> **COM mu MCP mi?** Word MCP bağlıysa ve kullanıcı Zotero-Refresh uyumluluğu isterse
> `/isnad-atiyaz` kullan. COM yolu (`isnad-word`) daha hızlıdır, Zotero Refresh
> gerektirmez; Zotero'ya dönüş `export` (RIS/CSL-JSON) ile yapılır.

## Araç seti

Kanonik betik: `scripts/isnad_word.py` (bu dizine göre; sürüm: `python scripts\isnad_word.py --version`).
`isnad` skill'indeki kopya yalnızca yönlendiricidir. Çıktılar JSON'dur; okumadan ekleme yapma.
Çok adımlı işlerde betik çıktısını dosyaya yazdırıp `read_file` ile oku (konsol cp1254
Türkçe/özel harf sorunu çıkarabilir; betik CLI stdout'u zaten UTF-8 sarmalar).

```
python scripts\isnad_word.py list [--doc "Belge1"]
python scripts\isnad_word.py find "alıntının ayırt edici parçası"
python scripts\isnad_word.py footnotes --limit 50
python scripts\isnad_word.py insert --text "Gövde cümlesi."
python scripts\isnad_word.py prepare --meta-json meta.json --page "2/143" [--save norm.json]
python scripts\isnad_word.py cite --anchor "..." --page "2/143" \
  --item-key SP8BELED --surname "Saffâr" --short-title "Telḫîṣü'l-edille" \
  --full "Ebû İshâk İbrâhim ez-Zâhid es-Saffâr, Telḫîṣü'l-edille li-ḳavâʿidi't-tevḥîd, thk. Angelika Brodersen (Beyrut: el-Ma'hedü'l-Almânî li'l-Ebhâsi'l-Şarkiyye, 1432/2011)" \
  --italic-title "Telḫîṣü'l-edille" --meta-json norm.json --log atif.jsonl
python scripts\isnad_word.py shortform 5 "Soyad, Kısa Başlık, 55."
python scripts\isnad_word.py verify [--only FONT,SIZE] [--dry-run]
python scripts\isnad_word.py fix [--only FONT,SIZE] [--dry-run]
python scripts\isnad_word.py bibliography --log atif.jsonl
python scripts\isnad_word.py addbib --text "Soyad, Ad. Eser. Yer: Yayınevi, Yıl." --italic-title "Eser"
python scripts\isnad_word.py export --log atif.jsonl --format ris --out zotero_import.ris
```

`--doc` verilmezse ilk açık belge kullanılır. Belge yoksa kullanıcıdan açmasını iste —
boş belge oluşturma.

## Önerilen uçtan uca akış (dipnot + kaynakça + Zotero)

1. **Künyeyi üret**: `prepare --meta-json` (Zotero üstverisi) → `--full` dipnot, kısa form
   bileşenleri (`--surname`, `--short-title`), kaynakça metni. `prepare --save norm.json`
   ile normalize üstveriyi sakla.
2. **Anchörü bul**: `find` ile cümlenin ayırt edici son parçasını ara; paragraf no + bağlamı doğrula.
3. **Dipnotu ekle**: `cite --meta-json norm.json --log atif.jsonl` — betik önceki atıf
   taraması yapar, **TAM**/**KISA** formunu seçer, günlüğe yazar. Eser adı italik olacaksa
   `--italic-title` ver.
4. **Doğrula**: `verify` ile font (TNR 10), `a.g.e./a.g.m.` yasağı, `s.` yasağı, nokta kontrolü;
   otomatik düzeltilebilirleri `fix` ile uygula.
5. **Kaynakça**: `bibliography --log atif.jsonl` → taslağı onayla → her girdiyi `addbib`
   ile belge sonuna ekle (`--italic-title` ile kitap adını italikle).
6. **Zotero'ya dönüş**: `export --log atif.jsonl --format ris --out ...` → Zotero'da
   File > Import. (Alternatif: `csljson`.) İsteğe bağlı `cite --zotero-field` dipnota
   `ADDIN ZOTERO_ITEM ISNAD` alanı gömer (deneysel; birincil yol RIS'tir).

## Kısa form karar mantığı (betik içinde gömülü)

`cite` tüm dipnotları tarar (aksan/case duyarsız):
- **Düz metin**: soyad + kısa başlık anahtarı metinde mi? (`--search-extra` ek anahtar zorunlu kılar.)
- **Zotero alan kodlu** (`ADDIN ZOTERO_ITEM`): klasik CSL JSON'da item key / soyad var mı?
- **ISNAD alanlı** (`ADDIN ZOTERO_ITEM ISNAD`): gömülü `itemKey` eşleşiyor mu?

Herhangi biri eşleşirse → `Soyad, Kısa Başlık, sayfa.`; yoksa → tam künye + sayfa.
`--page` verilmezse sayfasız künye eklenir (kitabın genel atfı).

Bilinen sınır: senin düz metin ilk atıfından SONRA kullanıcı Zotero eklentisiyle elle
atıf eklerse Zotero senin düz metni görmez ve tam künye getirebilir → `shortform` ile
kısalt (kullanıcıya sor). Ters yön (Zotero-önce → COM-sonra) otomatiktir.

## Kurallar (isnad-kurallari.md özet — ayrıntı için o dosyayı oku)

- Dipnotta parçalar `,` ile; sayfa `s.` harfsiz: `... 1432/2011), 2/143.`
- Kısa form: `Soyad, Kısa Başlık, sayfa.` — `a.g.e./a.g.m.` yasak
- Dipnot fontu: Times New Roman 10 (`--font/--size` ile değişir); kaynakça varsayılan 12
- `--anchor` bulunamazsa betik önce fuzzy, sonra sondan kısaltarak dener; `anchor_method`
  alanını raporla. Başarısızlıkta `suggestions` ile `find` çıktısı verir.

## Çalışma örneği (doğrulanmış)

Belge: Belge1, metinde "…erken döneme taşımıştır" cümlesi var.
Zotero item `SP8BELED` (Saffâr, Telḫîṣü'l-edille). Dipnot 1'de tam künye düz metin mevcut.

```
python scripts\isnad_word.py cite --anchor "erken döneme taşımıştır" --page "2/145" \
  --item-key SP8BELED --surname "Saffâr" --short-title "Telḫîṣü'l-edille" \
  --full "Ebû İshâk İbrâhim ez-Zâhid es-Saffâr, Telḫîṣü'l-edille li-ḳavâʿidi't-tevḥîd, thk. Angelika Brodersen (Beyrut: el-Ma'hedü'l-Almânî li'l-Ebhâsi'l-Şarkiyye, 1432/2011)"
```

Beklenen çıktı: `"form": "KISA"`, `"inserted": "Saffâr, Telḫîṣü'l-edille, 2/145."`

Değişiklikler için `CHANGELOG.md`'ye bak. Saf mantık `tests/test_isnad_pure.py` ile
kilitlidir (`pytest tests/`); kural değişikliğinde testi de güncelle.
