# CHANGELOG — isnad-word

## 2.0.2 (atıf sırası düzeltmesi)

- **Konumsal kısa form:** `cite` önce çapayı bulur, yalnızca çapa ÖNCESİNDEKİ dipnotlarda
  aynı eser varsa KISA kullanır. Sıra dışı eklemede başa geçen KISA hatası bitti.
- `--doc` artık komuttan önce VE sonra verilebilir (`SUPPRESS`).
- Kısa formda da `--italic-title` uygulanır (kısa başlık italik).

## 2.0.1 (canlı deneme düzeltmeleri)

- Çoklu Word örneği: ROT gezgini (sınıf + dosya moniker'ları; kayıtsız `Belge1`
  gibi uzantısız adlar dahil). `Dispatch`'in açtığı gizli boş örneğe takılma bitti;
  `--doc` verilmezse belgesi olan ilk örnek seçilir.
- Yeni: `insert` (belge sonuna gövde paragrafı).
- `coerce_meta` idempotent: `prepare --save` çıktısı `cite --meta-json`'a verilince
  yazarlar düşmüyordu (düzeltildi) + regresyon testi.
- `list`: örnek sayısıyla birlikte tüm belgeler.

## 2.0.0

- Tek kanonik betik: `isnad` skill'indeki kopya shim'e çevrildi (`isnad_word.v1.bak` yedekte).
- `cite`: `--doc`, opsiyonel `--page`, `--search-extra`, `--italic-title`, `--meta-json`,
  `--log`, `--zotero-field`; esnek anchor (tam → fuzzy → sondan kısaltma) + `suggestions`.
- Normalizasyon: aksan/case duyarsız tarama; ʾ/ʿ harf sayılır, tarama anahtarını bölmez.
- Yeni: `prepare` (üstveriden dipnot/kısa/kaynakça/metin-içi önerisi, Word gerekmez),
  `bibliography` + `addbib` (İSNAD kaynakça akışı), `export` (RIS/CSL-JSON → Zotero),
  `verify` + `fix` (font, a.g.e./s. denetimi).
- `footnotes`: italik durumu (`italic_mixed`) + `--doc`.
- `shortform`: `--doc`, `--font/--size`, `--italic-title`.
- Hata çıktısı stdout JSON + kod 1 (`fail`); `--version` bayrağı.
- `tests/test_isnad_pure.py`: 13 test (pytest).
- stdout UTF-8 sarmalama yalnızca CLI girişinde (pytest içe aktarması güvenli).

## 1.x (v1.bak)

- `list/find/footnotes/cite/shortform`; `--doc` ve opsiyonel `--page` yalnızca
  `isnad` kopyasında vardı; kopyalar arası sapma mevcuttu.
