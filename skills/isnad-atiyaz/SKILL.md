---
name: isnad-atiyaz
description: Zotero'dan İSNAD künyesi üretip açık Word belgesine gerçek dipnot olarak ekler (word MCP). Kullanıcı "Word'e atıf ekle", "bu cümleye İSNAD dipnotu koy", "kaynakçayı güncelle" dediğinde kullan.
argument-hint: "<eser adı / item key> [atıf noktası: cümle veya paragraf no]"
---

# İSNAD Atıyaz — Word'e İSNAD Dipnotu Ekle (Word MCP yolu)

Önkoşullar: Word açık ve hedef belge yüklü; `word` MCP sunucusu bağlı (`/mcp` ile doğrula);
Zotero açık (künye kaynağı).

> **Hangi yol?** Word MCP bağlı ve Zotero-Refresh uyumluluğu şartsa **atiyaz** (bu skill).
> Hızlı COM ekleme, otomatik kısa form, `verify`/`fix`, kaynakça (`bibliography`/`addbib`)
> ve RIS/CSL-JSON dışa aktarımı için **isnad-word** kullan. İkisini aynı belgede karıştırırsan
> `verify` ile tutarlılığı denetle.
>
> **Durum notu (2026-09):** `word` MCP bu makinede kurulu değil; PyPI'daki bilinen aday
> (`office-word-mcp-server`) dosya-tabanlı çalışır (kayıtlı .docx) ve bu skill'in beklediği
> canlı-belge araçlarıyla (`list_documents`, `insert_footnote`, `export_page_image` …)
> uyuşmaz. O yüzden varsayılan yol **isnad-word (COM)**'dur; bu skill yalnızca eşleşen
> bir canlı-Word MCP kurulursa kullanılır.

## Akış

1. **Hedef belgeyi tespit et**: `list_documents` ile açık belgeleri listele; birden fazlaysa kullanıcıya sor veya isim eşleşen seç.
2. **Künyeyi üret**: `/isnad-kunye` akışını izle — `zotero_search_items` → `zotero_item_metadata`,
   künyeyi `isnad-kunye` skill'inin `references/isnad-kurallari.md` dosyasına göre formatla
   (`~/.commandcode/skills/isnad-kunye/references/isnad-kurallari.md`).
3. **Atıf türünü belirle**:
   - `list_footnotes` ile mevcut dipnotları kontrol et. Aynı eser zaten atıflıysa **kısa form**
     (tekrar atıf) kullan; ilk atıfsa tam künye.
   - Birden fazla dipnot eklenecekse sırayla işlem yap ve her eklemeden sonra listeyi yenile
     (dipnot numaraları kayar).
4. **Ekleme noktasını bul**:
   - Kullanıcı cümle/alıntı verdiyse: `find_text` ile cümlenin ayırt edici kısmını ara →
     sonuçta `paragraph` numarası ve eşleşen metin gelir.
   - Paragraf numarası verildiyse doğrudan onu kullan.
   - Dipnot alıntıdan sonra gelmelidir; `insert_footnote` çağrısında `after_text` olarak
     alıntının son kelimelerini geç (tırnak işareti dahil).
5. **Dipnotu ekle**: `insert_footnote(text=<İSNAD künye>, paragraph_index=<N>, after_text=<isteğe bağlı>)`.
   Dipnot metni sonundaki sayfa bilgisini künyeden ayır: `... 2/143.` — sayfa atıf yapılan yerse
   künyenin son parçasıdır; kitabın genel atfıysa sayfa yok.
6. **Biçim**: İSNAD dipnotlar genelde Times New Roman 10 punto — belgeye uymuyorsa
   `set_footnote_font(apply_to="one", size=10, font_name="Times New Roman")` uygula (once sor).
7. **Kaynakça**: kullanıcı isterse belge sonunda "Kaynakça" başlığını bul (`find_text`,
   style Heading ise kaydet), yoksa `insert_paragraph_after` ile başlık oluştur; her künyeyi
   kaynakça formatında (noktalı ayrım) ayrı paragraf olarak ekle, girintiyi belge standardına göre ayarla.
8. **Doğrula**: `get_footnote` ile eklenen dipnotun metnini oku; `export_page_image` ile atıf
   yapılan sayfanın görselini kontrol et.

## Karar kuralları

- Belge açıksa ama `word` MCP bağlantı hatası verirse: `/mcp` durumunu bildir, Word'ün açık
  olduğunu doğrula, sunucu hatasını göster (araçlar hata JSON'ında traceback döndürür).
- `after_text` bulunamazsa aracı hata döndürür; metni kısaltıp yeniden dene (cümle sonu kelime).
- Zotero'da eser yoksa: künyeyi kullanıcıdan al veya `shamela`/`web_search` ile doğrula;
  asla eksik alan uydurma.
- Kullanıcı metin-içi sistem istediyse dipnot ekleme; `(Soyad, Yıl, s.)` metnini `replace_text`
  veya `insert_paragraph_after` ile işle (metin-içinde künye paragrafın akışına gömülür).

## Kural referansı

Her durumda format kararlarını
`~/.commandcode/skills/isnad-kunye/references/isnad-kurallari.md`
dosyasından al; emin olmadığın türde Zotero'daki "İSNAD 2. Edisyon Eserler" (`TMXG69BJ`)
koleksiyonundan örnek al.
