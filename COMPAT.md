# COMPAT — bridge sunucusunu diger uygulamalara baglama

Tek komut: `uvrun --project C:\dev\mcp\bridge-mcp bridge-mcp`
Bu komut asagidaki uclude aynen boyle kullanilir.

## Claude Desktop
Konum: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "bridge": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "C:\\dev\\mcp\\bridge-mcp",
        "bridge-mcp"
      ]
    }
  }
}
```

## Codex CLI
Konum: `%USERPROFILE%\.codex\config.toml` (satirlari ekleyin)

```toml
# Codex CLI: %USERPROFILE%\.codex\config.toml

[mcp_servers.bridge]
command = "uv"
args = ["run", "--project", "C:\dev\mcp\bridge-mcp", "bridge-mcp"]

```

## ChatGPT (masaustu/web)
Yerel stdio sunuculari baglanti olarak dogrudan takilmaz; relay/Developer Mode gerekir.
Surum: `cmdc-stack/mcp/hostconfigs/CHATGPT.md`

> Merkezi kurulum/senkron icin: `cmdc-stack` deposu (`scripts/install.ps1`) tumunu
> tek manifestten kaydeder (Hermes / CommandCode dahil).
