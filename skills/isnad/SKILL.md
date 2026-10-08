---
name: isnad
description: "İSNAD 2. Edisyon künyesi üretir ve açık Word belgesine COM (pywin32) üzerinden gerçek dipnot olarak ekler — Word MCP gerekmez. Zotero-farkındalıklıdır: belgedeki önceki atıfları (düz metin + Zotero ADDIN alan kodları) tarar, aynı eser daha önce atıflıysa kısa formu otomatik kullanır. Kullanıcı 'İSNAD künyesi hazırla', 'Word'e atıf ekle', 'İSNAD dipnotu koy', 'aynı yere tekrar atıf', 'künyeyi Word'e yaz', 'kaynakçayı güncelle' dediğinde kullan."
argument-hint: "<eser adı / Zotero item key> [atıf noktası: cümle] [sayfa] [dipnot|kaynakça|metin-içi]"
---

# İSNAD — Künye Üretimi ve Word'e Atıf

Tek skill, iki iş: **(A)** Zotero'dan İSNAD 2. Edisyon künyesi üretmek,
**(B)** açık Word belgesine COM (pywin32) ile dipnot + kaynakça olarak eklemek.
Word MCP sunucusu yoktur; Word'e giden tek yol kanonik betiktir:
`../isnad-word/scripts/isnad_word.py` (v2.0.0; bu dizindeki `scripts/isnad_word.py`
yalnızca yönlendiricidir). Künye kaynağı Zotero MCP'dir
(`zotero_search_items` → `zotero_item_metadata`).

## Kural kaynağı

**Köprü önceliği:** `bridge` MCP bağlıysa künye üretiminde önce `citation_search` +
`isnad_kunye` (item key veya shamela_book_id) kullan; çıktıyı `isnad-kurallari.md`'ye karşı
gözle doğrula. Bridge yoksa/hata verirse aşağıdaki Zotero zincirine geri dön. Word tarafı
(cite/addbib/export) bu köprünün kapsamı dışında kalır — betik aynen kullanılır.

Tüm format kararları `references/isnad-kurallari.md` dosyasından alınır — kural seti,
tür şablonları ve Zotero alan eşlemesi orada. Emin olunmayan türde Zotero'daki
**"İSNAD 2. Edisyon Eserler"** koleksiyonundan (`TMXG69BJ`) örnek al
(`zotero_list_collection_items` + `zotero_item_metadata`).

## Araç seti (Word tarafı)

Tek betik: `../isnad-word/scripts/isnad_word.py` (kanonik; ayrıntı `isnad-word` SKILL.md'de).
Alt komutlar: `list`, `find`, `footnotes`, `cite`, `shortform`, `verify`, `fix`,
`prepare`, `bibliography`, `addbib`, `export`. Çıktılar JSON'dur; okumadan ekleme yapma.

```
python "<kanonik>\isnad_word.py" list
python "<kanonik>\isnad_word.py" --doc "Belge1" find "alıntının ayırt edici parçası"
python "<kanonik>\isnad_word.py" footnotes --limit 50
python "<kanonik>\isnad_word.py" prepare --meta-json meta.json --page "2/143" --save norm.json
python "<kanonik>\isnad_word.py" cite --anchor "..." --page "2/143" \
  --item-key SP8BELED --surname "Saffâr" \
  --short-title "Telḫîṣü'l-edille" \
  --full "Ebû İshâk İbrâhim ez-Zâhid es-Saffâr, Telḫîṣü'l-edille li-ḳavâʿidi't-tevḥîd, thk. Angelika Brodersen (Beyrut: el-Ma'hedü'l-Almânî li'l-Ebhâsi'l-Şarkiyye, 1432/2011)" \
  --italic-title "Telḫîṣü'l-edille" --meta-json norm.json --log atif.jsonl
python "<kanonik>\isnad_word.py" shortform 5 "Soyad, Kısa Başlık, 55."
python "<kanonik>\isnad_word.py" verify
python "<kanonik>\isnad_word.py" bibliography --log atif.jsonl
python "<kanonik>\isnad_word.py" export --log atif.jsonl --format ris --out zotero_import.ris
```

`<kanonik>` = `...\skills\isnad-word\scripts\isnad_word.py` (bu dizindeki
`scripts\isnad_word.py` aynı betiğe yönlendirir; ikisini de kullanabilirsin).
Çok adımlı işlerde
betik çıktısını dosyaya yazdırıp `read_file` ile oku (konsol cp1254 Türkçe/özel harf
sorunu çıkarabilir; betik stdout'u zaten UTF-8 sarmalar).

## A — Künye üretimi (Word'e yazmadan)

1. **Girdi**: argüman varsa arama terimi olarak kullan; yoksa kullanıcıdan eser adı,
   yazar veya item key iste. `zotero_search_items` (qmode: titleCreatorYear) ile ara;
   sonuç yoksa qmode: everything dene. Kesin eşleşmede `zotero_item_metadata` al;
   item key verildiyse doğrudan metadata al.
2. Zotero item türünü İSNAD türüne eşle (kitap / kitap bölümü / makale / tez /
   sözlük-ansiklopedi / internet / yazma eser / rapor / mahkeme kararı / mevzuat —
   eşleme tablosu kural dosyasında).
3. `Extra` alanındaki `editorial-director:` satırlarını `thk.`/`nşr.` olarak yorumla.
4. Alan eksikse **uydurma** — eksikleri kullanıcıya bildir, mümkünse `shamela` veya
   `web_search` ile tamamlamayı öner.
5. Format belirtilmediyse üç çıktıyı da ver: **dipnot (ilk atıf)**, **dipnot (kısa)**,
   **kaynakça**. Metin-içi istenirse kural dosyasındaki metin-içi bölümüne göre üret.
6. Künyeleri sade metin bloklarında ver; italik/tırnak işaretlerini kullanıcıya not et
   (kitap/dergi adları italik, makale adları çift tırnak).

## B — Word'e dipnot ekleme (COM akışı)

1. **Hedef belgeyi tespit et**: `list` ile açık belgeleri al. Birden fazlaysa kullanıcıya
   sor ve seçilen belgeyi `--doc "<ad>"` ile sonraki tüm çağrılara geçir (`--doc`
   verilmezse betik ilk açık belgeyi kullanır). Belge yoksa: kullanıcıdan belgeyi
   açmasını iste — boş belge oluşturma.
2. **Künyeyi üret**: A bölümündeki akışla; İSNAD kurallarına göre `--full` (sayfasız)
   künyeyi kur. Kısa form bileşenleri: `--surname` (soyad), `--short-title` (Zotero
   Short Title alanı; yoksa eser adının ayırt edici ilk kısmı). `--item-key` her zaman ver.
3. **Anchörü bul**: `find` ile dipnotun geleceği cümlenin ayırt edici son parçasını ara.
   Paragraf no + bağlamı doğrula. Anchör yoksa kullanıcıdan metni netleştir.
4. **Dipnotu ekle**: `cite --meta-json norm.json --log atif.jsonl` — betik otomatik önceki atıf taraması yapar ve **TAM** (ilk
   atıf) veya **KISA** (tekrar atıf) formunu seçer; `form` alanını kullanıcıya raporla.
   `--page` verilmezse sayfasız künye eklenir (kitabın genel atfı). Sayfa bilgisi künyeden
   ayrı bir veri değil, `2/143` biçiminde künyenin son parçasıdır. Eser adı italik olacaksa
   `--italic-title` ver.
5. **Doğrula**: `verify` ile font (TNR 10), `a.g.e./a.g.m.` ve `s.` yasaklarını denetle;
   otomatik düzeltilebilirleri `fix` ile uygula. `footnotes` ile eklenen dipnotun metnini,
   fontunu, italik durumunu oku.
6. **Kaynakça**: kullanıcı isterse `bibliography --log atif.jsonl` ile taslağı üret
   (meta kaydedilmiş işler tam kaynakça verir), onayla, her girdiyi `addbib` ile belge
   sonuna ekle. `addbib` "Kaynakça" başlığı yoksa oluşturur.
7. **Zotero'ya dönüş**: kullanıcı isterse `export --log atif.jsonl --format ris`
   ile RIS üret → Zotero'ya File > Import. (Alternatif: `csljson`.)

## Kısa form karar mantığı (betik içinde gömülü)

`cite` çalıştırıldığında betik tüm dipnotları tarar:
- **Düz metin dipnotlar**: soyad + kısa başlığın ilk kelimesi metinde mi?
- **Zotero alan kodlu dipnotlar** (`ADDIN ZOTERO_ITEM`): alan kodundaki JSON'da item key
  veya yazar soyadı geçiyor mu?

Herhangi biri eşleşirse → `Soyad, Kısa Başlık, sayfa.`; hiçbiri yoksa → tam künye + sayfa.

Bilinen sınır: senin düz metin ilk atıfından SONRA kullanıcı Zotero eklentisiyle elle
atıf eklerse Zotero senin düz metni görmez ve tam künye getirebilir → `shortform` ile
kısalt (kullanıcıya sor). Ters yön (Zotero-önce → COM-sonra) otomatiktir.

## Karar kuralları

- Dipnotta parçalar `,` ile; sayfa `s.` harfsiz: `... 1432/2011), 2/143.`
- Kısa form: `Soyad, Kısa Başlık, sayfa.` — `a.g.e./a.g.m.` yasak
- Dipnot fontu: Times New Roman 10 punto (kullanıcı başkaca isterse `--font/--size`)
- `after_text`/anchor bulunamazsa: metni kısaltıp yeniden dene (cümle sonu kelime)
- Zotero'da eser yoksa: künyeyi kullanıcıdan al veya `shamela`/`web_search` ile doğrula;
  asla eksik alan uydurma
- Kullanıcı metin-içi sistem istediyse dipnot ekleme — metin-içi künye paragrafın
  akışına gömülür; kullanıcıya `(Soyad, Yıl, s.)` metnini nereye koyacağını sor

## Çalışma örneği (doğrulanmış)

Belge: Belge1, metinde "…erken döneme taşımıştır" cümlesi var.
Zotero item `SP8BELED` (Saffâr, Telḫîṣü'l-edille). Dipnot 1'de tam künye düz metin mevcut.

```
python scripts\isnad_word.py cite --anchor "erken döneme taşımıştır" --page "2/145" \
  --item-key SP8BELED --surname "Saffâr" --short-title "Telḫîṣü'l-edille" \
  --full "Ebû İshâk İbrâhim ez-Zâhid es-Saffâr, Telḫîṣü'l-edille li-ḳavâʿidi't-tevḥîd, thk. Angelika Brodersen (Beyrut: el-Ma'hedü'l-Almânî li'l-Ebhâsi'l-Şarkiyye, 1432/2011)"
```

Beklenen çıktı: `"form": "KISA"`, `"inserted": "Saffâr, Telḫîṣü'l-edille, 2/145."`
