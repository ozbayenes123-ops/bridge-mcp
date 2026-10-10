# bridge-mcp

Yerel MCP'leri birleştiren köprü sunucusu. Karar LLM'de (orkestratör);
bridge yalnızca tekrarlanan zincirleri tek çağrıya indirir.

## Tool'lar

| Tool | Zincir | Ne yapar |
|---|---|---|
| `citation_search(query, limit?, kaynaklar?, yargi_timeout_s?)` | Zotero + Bedesten + Shamela | Zotero'yu ve (varsayılan olarak) Bedesten'i paralel arar; Şamile yalnızca Zotero boş dönerse sorgulanır. `kaynaklar="zotero,shamela,yargi"` ile kapsam daraltılır. Sonuçlar kaynak etiketli. |
| `isnad_kunye(item_key \| shamela_book_id, page)` | Zotero/Shamela → isnad_word.py | Normalize üstveri + dipnot/kısa/kaynakça formları. Çıktı gözle `isnad-kurallari.md`'ye karşı doğrulanmalı. |
| `citation_export(log_path, fmt)` | isnad_word.py | Atıf günlüğünden RIS/CSL-JSON üretir (Zotero'ya File > Import elle yapılır). |
| `yargi_makale_cek(sorgu, slug, document_id?, birim_adi?)` | Bedesten → makale | Karar markdown'ını `MAKALE_DOCS/<slug>/` altına yazar + `config.json` üretir. |
| `yargi_zotero_kaydet(sorgu?, document_id?, koleksiyon?, etiketler?, dosya_ekle?, birim_adi?, esas_no?, karar_no?, karar_tarihi?)` | Bedesten → Zotero | Kararı Zotero'ya `case` item'ı olarak ekler (başlık alanı `caseName`), markdown'ı dosya eki olarak yükler. `document_id` ile gelinirse üstveri karar metninden çıkarılır; eksikler parametreyle verilir. |
| `shamela_makale_ata(slug, book_id, page_id?, quote?, baslik?)` | Shamela → makale | Sayfayı belge klasörüne kaynak metin olarak yazar, `config.json`'a işler ve İSNAD dipnot/kaynakça formlarını üretir. `page_id` Şamile'nin **iç** sayfa kimliğidir; basılı sayfa künyesi ayrıca raporlanır. |
| `makale_durum(slug?)` | makale MCP | Tek çağrıda `doc_status` + `project_stats` + (slug verilirse) `quality_scan`, `citation_check`, `glossary_check`. Uyarı listesi döndürür. |
| `zotero_word_atif(docx_path, item_keys?, sorgu?, konum?, locator?, stil?, atif_tipi?, bibliyografya?)` | Zotero → Word | Belgeye Zotero eklentisinin tanıdığı **canlı atıf alanı** yazar (`ADDIN ZOTERO_ITEM CSL_CITATION …`). `atif_tipi="dipnot"` atıfı gerçek bir Word dipnotuna koyar (İSNAD dipnotlu stili). Görünen metin İSNAD betiğinden gelir. |
| `zotero_word_atif_listele(docx_path)` | Word | Belgedeki atıf/kaynakça alanlarını ve belge stilini listeler (doğrulama). |
| `terim_arastir(terim, mevzuat_ipucu?, limit?)` | yargi MCP (mevzuat + Resmî Gazete) | Karşılığı belirsiz bir terimin RESMÎ Türkçe kullanımını arar: mevzuat başlıkları + ilgili kanunun METNİ içinde terim örnekleri + Resmî Gazete fihristi. `mevzuat_ara` yalnızca başlık taradığı için terim başlıkta yoksa `mevzuat_ipucu` verilir (ör. ipucu='Vatandaşlık'). Bulunan karşılık `glossary_add` ile kaynağıyla sözlüğe yazılır. |
| `bridge_health(derin?, timeout_s?)` | — | Bileşen durumu (zotero okuma/yazma, Şamile, yargi, makale, isnad betiği) + açık improvement sayısı. Her bileşen **ayrı ve eşzamanlı** kontrol edilir; `timeout_s` (varsayılan 6 sn) dolduğunda "zaman aşımı" yazar, çağrı asla bloke olmaz. `derin=True` Şamile'yi gerçekten çağırır. |
| `improvement_log(konu, tip, hedef, kaynak_tool, detay)` | — | İşlem sonunda tespit edilen eksiklik/hata/özellik fikrini `data/improvements.jsonl`'a kaydeder. |
| `improvement_list(status, hedef)` | — | Açık/tüm kayıtları listeler. |
| `improvement_resolve(id, durum)` | — | Kaydı yapıldı/iptal olarak kapatır. Düzeltme kararı orkestratördedir. |

## MCP prompt'ları

Bu sunucu iki prompt da yayınlar; Claude Desktop/Codex gibi istemcilerde
slash komutu olarak görünürler:

| Prompt | Ne için |
|---|---|
| `isnad_kunye_akisi(item_key?, shamela_book_id?, page?)` | Zotero/Şamile kaynağından İSNAD künyesi üretme adımları. |
| `yargi_makale_akisi(sorgu?, slug?)` | Bedesten kararını bulup makale belgesine ve Zotero'ya alma adımları. |

## Kurulum

Ön koşullar: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+ (Shamela için).

```powershell
uv sync --project <KURULUM_KÖKÜ>\bridge-mcp
uv run --project <KURULUM_KÖKÜ>\bridge-mcp bridge-mcp
```

Command Code kaydı (`~/.commandcode/mcp.json`); `cmdc-stack` deposundaki
`scripts/register-mcp.ps1` bu kaydı sizin için üretir:

```json
{
  "mcpServers": {
    "bridge": {
      "transport": "stdio",
      "command": "uv",
      "args": ["run", "--project", "<KURULUM_KÖKÜ>\\bridge-mcp", "bridge-mcp"]
    }
  }
}
```

## Yapılandırma

Tüm yollar ortam değişkeniyle geçilebilir; varsayılanlar bu deponun kardeş
dizinleridir (yani `<KURULUM_KÖKÜ>` altındaki diğer MCP depoları).

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `YARGI_MCP_PATH` | `<kurulum kökü>/yargi-mcp` | `bedesten_mcp_module` / `emsal_mcp_module` buradan import edilir |
| `ZOTERO_MCP_SRC` | `<kurulum kökü>/zotero-mcp-src` | `zotero_mcp` paketi buradan import edilir |
| `SHAMELA_ENTRY` | `<kurulum kökü>/shamela-mcp/dist/index.js` | Shamela MCP stdio girişi |
| `SHAMELA_COMMAND` | `node` | Shamela'yı çalıştıran komut |
| `SHAMELA_INSTALL_ROOT` | `C:\shamela4` (varsa) | Shamela 4 kurulum kökü |
| `SHAMELA_JRE` | PATH'teki `java` | Shamela'nın kullandığı Java yorumlayıcısı |
| `ISNAD_WORD_SCRIPT` | `~/.commandcode/skills/isnad-word/scripts/isnad_word.py` | Kanonik İSNAD betiği |
| `MAKALE_PATH` | `<kurulum kökü>/makale` | makale deposu (makale MCP sunucusu buradan çalıştırılır) |
| `MAKALE_DOCS` | `<kurulum kökü>/makale/documents` | Zincirlerin yazdığı belge kökü |
| `MAKALE_COMMAND` / `MAKALE_MCP_TIMEOUT_S` | `uv` / `300` | makale MCP sunucusunu başlatan komut ve çağrı süresi |
| `ZOTERO_COMMAND` | `~/.local/bin/zotero-mcp.exe` | Yazma çağrıları için zotero-mcp girişi |
| `BRIDGE_DATA_DIR` | `<depo>/data` | `improvements.jsonl` konumu |

Not: `yargi-mcp` sunucusuyla aynı IP'den paralel istek atılırsa Bedesten
rate-limit bütçesi paylaşılır; gerekirse `BEDESTEN_RATE_*` ile yavaşlatın.

## Mimari

- `zotero_mcp` ile `bedesten_mcp_module` / `emsal_mcp_module` **sys.path ile
  import edilir**; ayrı kurulum gerekmez.
- Shamela, `shamela_client.py` üzerinden her çağrıda taze bir MCP stdio
  oturumu açar.
- makale ve zotero (yazma) sunucuları `mcp_stdio.py` ile **tek oturumda çok
  çağrı** yapacak şekilde çağrılır (mcp sürüm farkı: makale/zotero mcp 2.x,
  bridge mcp 1.x — bu yüzden import değil, tool çağrısı).
- Alt süreç açan her çağrı daemon iş parçacığında (`_util.run_in_daemon`)
  çalışır ve süre sınırına bağlıdır: asılı kalan bir sunucu bridge'in olay
  döngüsünü donduramaz (bu, `bridge_health` 300 sn timeout hatasının köküydü).
- Bridge karar vermez: hangi kaynağın kullanılacağını orkestratör (LLM) seçer.

## Testler

```powershell
uv run --project <KURULUM_KÖKÜ>\bridge-mcp --with pytest pytest -q
```

CI (`.github/workflows/ci.yml`) import smoke'un yanında bu testleri de koşar;
`pytest pythonpath` ayarı `pyproject.toml`'daki `[tool.pytest.ini_options]`
altındadır (daha önce testler CI'da hiç koşmuyordu).

## İlişkili skill'ler

- `skills/isnad/`, `skills/isnad-atiyaz/`, `skills/isnad-kunye/`, `skills/isnad-word/` — İSNAD atıf sistemi zinciri (bridge `isnad_kunye` tool'uyla birlikte çalışır).
- `skills/zotero-word-atif/` — Word belgesine canlı Zotero atıfı yazma akışı
  (`zotero_word_atif` / `zotero_word_atif_listele`), dipnotlu/dipnotsuz üretim
  kuralları ve doğrulama adımları.
