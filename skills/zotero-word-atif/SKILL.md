---
name: zotero-word-atif
description: "Use when the user asks to cite something at a specific place in a Word document (\"şuraya atıf yap\", \"buraya kaynak ekle\"), or to produce a footnoted / footnote-free version."
version: 1.0.0
metadata:
  hermes:
    tags: [zotero, word, citation, isnad, docx]
    related_skills: [isnad, isnad-word, makale-translation]
---

# Zotero Word atıfı (canlı alan kodları)

Word belgesine, Zotero'nun Kendi Word eklentisinin **tanıyacağı** gerçek bir
atıf alanı yazar. Kullanıcı Word'de Zotero ile Refresh yaptığında atıf
Zotero'nun yönettiği bir atfa dönüşür: stil değiştirme, kaynakça ekleme ve
yeniden biçimlendirme normal çalışır.

Araçlar (bridge MCP):

| Araç | Ne yapar |
|---|---|
| `zotero_word_atif(docx_path, item_keys?, sorgu?, konum, locator?, stil, atif_tipi, bibliyografya?)` | Atıf alanını belgeye yazar |
| `zotero_word_atif_listele(docx_path)` | Belgedeki atıfları, kaynakça alanını ve stili doğrular |

## Kullanıcı "şuraya atıf yap" dediğinde

1. **Kaynağı Zotero'da bul ve anahtarını al.** İsim/sorgu serbest metinse
   önce `citation_search` (veya Zotero'da ara) ile item anahtarını bul; aynı
   kaynağın iki varyantını tahmin etme. Anahtar yoksa `sorgu` parametresi
   kullanılabilir ama ilk sonucu alır — hangi kaydı aldığını kullanıcıya söyle.
2. **Yeri belirle.** Belgede işaret metni varsa (ör. `{{ATIF}}`) onu `konum`
   olarak ver; yoksa `konum="son"` belge sonuna ekler. Kullanıcı "şu paragrafın
   sonuna" diyorsa önce belgeye bir işaret koymayı ya da `zotero_word_atif_listele`
   ile mevcut durumu doğrulamayı düşün.
3. **Tür seç:** `atif_tipi="dipnot"` gerçek bir Word dipnotu oluşturur ve atıf
   alanını dipnotun içine koyar (İSNAD **dipnotlu** stili böyle çalışır).
   `atif_tipi="metinici"` alanı paragrafın içine koyar (İSNAD **metiniçi**).
   Kaynakça gerekiyorsa `bibliyografya=True`.
4. **Doğrula:** `zotero_word_atif_listele` ile atıf sayısını/anahtarlarını ve
   belge stilini oku. Görünen metin İSNAD betiğinden gelir (`dipnot_tam` /
   `kaynakca`); üretilemezse kaba bir yedek metin yazılır ve `isnad_uyarilari`
   alanında bildirilir.
5. **Kullanıcıya tek adım söyle:** Word'de belgeyi açıp Zotero sekmesinden
   **Refresh**. Zotero alanı sahiplenir ve stile göre yeniden biçimlendirir.

## Doğrulama kuralları

- Atıf uydurma. Kaynak Zotero'da yoksa önce kaydı oluştur
  (`yargi_zotero_kaydet` veya `zotero_create_item`), sonra atıf yaz.
- Araç `.docx`'in yanına `.docx.bak` yedeği bırakır; kullanıcıya söyle.
- Zotero, ilk yenilemede belgeyi tanımazsa (Word/Zotero'da bir onay isteği
  çıkabilir) kullanıcı bir kez onaylar; sonrasında yenileme sessiz çalışır.
  Bu onay sırasında **Word açık kalmalı** — belge kapanırsa Zotero hata verir.
- Zotero'nun biçimlendirdiğinin kanıtı: refresh sonrası alanın görünen metni
  değişir (ör. başlık büyük-küçük harf farkı). Değişmiyorsa onay
  verilmemiş ya da stil belgede yazılı değildir.
- Otomasyonla (COM) Word açarken **native ters bölü yollar** kullan
  (`C:\Users\...\x.docx`); ileri eğik çizgili yol Word tarafından bulunamaz.

## Zotero eklenti uyumu (kanıtlanmış ayrıntılar)

Zotero'nun Word eklentisi belgeyi "kendi belgesi" sayması için şunlar şart:

1. **Stil tercihi belgeye yazılır ve bir kez seçilir.** `stil` boş verilirse
   araç önce belgedeki stili, yoksa Zotero'nun `extensions.zotero.export.lastStyle`
   tercihini (kullanıcının Zotero'da son seçtiği stil) kullanır. Belgede stil
   zaten yazılıysa tercih alanları YENİDEN yazılmaz — kullanıcı her belgede
   İSNAD'ı tekrar seçmek zorunda kalmaz.
2. **Tercih alanları belgenin BAŞINDA durur** (`ZOTERO_PREF_*`). Belge sonuna
   yazılırsa Zotero belge verisini okuyamaz ve "Belge Tercihleri" penceresini
   açar — bu, kullanıcının gördüğü "eksik atıf" hissinin sebebiydi.
3. **Veri biçimi**: tercihler JSON `dataVersion 4` (Zotero'nun kendi
   `DocumentData.serialize()` alan adlarıyla: style/prefs/sessionID/
   zoteroVersion/dataVersion). `zoteroVersion` kurulu Zotero sürümünden okunur.
4. **Tercih alanının sonuç koşusu OLMAZ** (begin→instrText→separate→end).
   Boş bir sonuç koşusu eklenirse Zotero belge verisini okuyamaz ve her
   yenilemede "Belge Tercihleri" penceresini açar — kullanıcının "her seferinde
   stil soruyor / atıf eksik görünüyor" dediği durum buydu. Tek belgede
   üst üste iki yenileme test edildi: pencere açılmadı, atıflar Zotero
   biçiminde kaldı.
5. **Dipnot içinde numara işareti** (`w:footnoteRef` + `FootnoteReference`
   stili) ve `settings.xml` içinde `footnotePr` yazılır; yoksa Word dipnot
   numarasını göstermez ve atıf elle yazılmış gibi görünür.
6. **`properties.noteIndex` = dipnot numarası** olmalı (not stilli atıflarda).
7. Dolaylı sonuç: **aynı eserin ikinci atıfında kısa biçimi Zotero yazar.**
   İSNAD dipnotlu CSL'inde `position="subsequent"` kuralı ve 29 `form="short"`
   kullanımı vardır. Testte ikinci dipnot "AlMajed, …" biçiminde (soyad önce)
   çıktı; **tam kısa başlık** için Zotero'da item'ın "Kısa Başlık" (Short Title)
   alanı doldurulmalıdır — CSL kısa başlık yoksa tam başlığa düşer.
8. Yazı tipi: makale DOCX hattı Normal/Title/Heading/Dipnot stillerini
   Times New Roman'a ayarlar; bridge'in eklediği dipnot stilleri yazı tipini
   ezmez, belgeninkini devralır.

## Dipnotlu / dipnotsuz üretim

- "Dipnotlu versiyon" isteniyorsa: `atif_tipi="dipnot"` +
  `stil="isnad-dipnotlu"`.
- "Dipnotsuz / metin içi versiyon" isteniyorsa: `atif_tipi="metinici"` +
  `stil="isnad-metinici"`, `bibliyografya` ihtiyaca göre.
- makale hattında dipnot taşıma davranışı belge bazında ayarlanır: derleme
  çıktısı için `docx.footnotes` (`auto` | `on` | `off`) ve İçindekiler için
  `docx.toc` (`auto` | true | false); "auto" kaynak belgeye bakar ve olmayan
  bir bölümü uydurmaz.
