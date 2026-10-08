---
name: isnad-kunye
description: Zotero kitaplığındaki bir eser için İSNAD Atıf Sistemi (2. Edisyon) künyesi üretir — dipnot (ilk/tekrar), kaynakça ve metin-içi formatları. Kullanıcı "İSNAD künyesi hazırla", "bu esere İSNAD'a göre atıf yap", "kaynakça girdisi çıkar" dediğinde kullan.
argument-hint: "<eser adı veya Zotero arama terimi> [dipnot|kaynakça|metin-içi]"
---

# İSNAD Künye Üretici

## Köprü önceliği (bridge MCP)

`bridge` MCP bağlıysa ve sağlıklıysa (`bridge_health` ile kontrol et) arama + künye üretimini
tek adımda yap: `citation_search("<terim>")` → Zotero boşsa Shamela'dan kaynak etiketli döner;
`isnad_kunye(item_key | shamela_book_id, [page])` → normalize üstveri + 3 form.
**`isnad_kunye` çıktısını yine `isnad-kurallari.md`'ye karşı gözle doğrula.**
Bridge yoksa, hata döndürürse veya alan eksikse aşağıdaki manüel zincire
(`zotero_search_items` → `zotero_item_metadata` → shamela fallback) geri dön.

## Girdi belirleme

1. Argüman varsa arama terimi olarak kullan; yoksa kullanıcıdan eser adı, yazar veya Zotero item key iste.
2. Önce `zotero_search_items` (qmode: titleCreatorYear) ile ara; sonuç yoksa qmode: everything dene. Kesin eşleşme bulunca `zotero_item_metadata` ile alanları al.
3. Kullanıcı bir item key verdiyse doğrudan metadata al.

## Künyeyi formatla

1. **Önce `isnad-kurallari.md` oku** (bu dosyanın yanındaki `references/isnad-kurallari.md`) — kural seti, tür şablonları ve alan eşlemesi orada.
2. Elle kuruyorsan aşağıdaki eşlemeyi izle; **otomatik kurulum için** `../isnad-word/scripts/isnad_word.py prepare --meta-json <zotero.json>`
   komutunu kullan (Word gerekmez; dipnot + kısa form + kaynakça + metin-içi önerir,
   `--save` ile normalize üstveriyi `cite --meta-json` için saklar). `prepare` çıktısını
   her zaman kural dosyasına karşı gözle doğrula.
3. Zotero item türünü İSNAD türüne eşle:
   - book → Kitap; bookSection → Kitap Bölümü; journalArticle → Makale;
   - thesis → Tez; dictionaryEntry/encyclopediaArticle → Sözlük/Ansiklopedi;
   - webpage → İnternet Sitesi; manuscript → Yazma Eser; report → Rapor;
   - case/legal → Mahkeme Kararı; statute → Mevzuat.
3. `Extra` alanındaki `editorial-director:` satırlarını `thk.`/`nşr.` olarak yorumla (CSL terimleri).
4. Karar kuralları:
   - Tarih yok → `ts.`; klasik eser → hicrî/milâdî çift yazım
   - 3+ yazar → ilk yazar + `vd.`; iki yazar → araya boşluklu tire
   - Yayınevi/yer yok → `b.y.`; URL sadece kaynakçada
5. Kullanıcı format belirtmediyse üç çıktıyı da hazırla: **dipnot (ilk atıf)**, **dipnot (tekrar/kısa)**, **kaynakça**. Metin-içi istenirse metin-içi kuralına göre üret.
6. Alan eksikse uydurma — eksik alanları kullanıcıya bildir ve mümkünse `shamela` veya `web_search` ile tamamlamayı öner (doğrulanmış künye bilgisiyle).

## Örnek tür referansı

Aynı türün resmi alan dolgusunu görmek için Zotero'daki **"İSNAD 2. Edisyon Eserler"** koleksiyonunu (`TMXG69BJ`) kullan: `zotero_list_collection_items` + `zotero_item_metadata`.

## Zincir notu (Word'e ekleme + Zotero'ya dönüş)

Word'e ekleme `isnad-word` skill'indedir (`cite --meta-json` + `--log` ile meta günlüğe
kaydedilir; `bibliography`/`addbib` kaynakçayı, `export --format ris|csljson` Zotero'ya
aktarımı üretir). Zotero **Short Title** alanını her eserde doldur — zincirin kısa form
anahtarı odur; boşsa `prepare` otomatik üretir ve uyarır.

## Çıktı

Üretilen künyeleri sade metin bloklarında ver (zengin biçim yok); italik/yatay çizgi işaretlerini
kullanıcıya not et: kitap/dergi adları italik, makale adları tırnak içinde. Word'e otomatik eklemek
istiyorsa `/isnad-atiyaz` kullan.
