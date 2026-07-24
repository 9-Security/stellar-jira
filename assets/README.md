# Report assets

| 檔案 | 用途 |
|------|------|
| `jjnet_logo.png` | 原始／主檔 Logo（可替換）。請用**真透明 PNG**（勿將編輯器棋盤格匯出成不透明灰格）。替換後執行 **`./Tools/run normalize-logo --replace-master`**；月報底圖會自動剔除棋盤格殘影。 |
| `jjnet_header_logo.png` | 舊版頁首小圖（`normalize-logo` 仍可產生；月報已改為全頁淡色底圖，來源以 `jjnet_logo.png` 為主）。 |

```bash
./Tools/run normalize-logo --replace-master   # 換圖後建議執行一次
./Tools/run report --date 2026-05-21 --timezone Asia/Taipei
```
