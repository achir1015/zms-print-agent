# 資料助秘3D列印AI代理人工具 https://achir1015.github.io/zms-print-agent/app/
<img width="1134" height="707" alt="image" src="https://github.com/user-attachments/assets/cd98c571-d249-44a0-a532-62adc8e0aa04" />

<img src="assets/icon.png" width="128" align="right" alt="資料助秘3D列印AI代理人工具圖示">
說明


https://github.com/user-attachments/assets/a085edc1-5482-49eb-bbe7-21e5db55cf38


從一句描述到可以在拓竹（Bambu Lab）印表機列印的零件：**描述 → 零件 → 七項列印前檢查 → Bambu Studio**。
列印永遠由您自己在 Bambu Studio 按下；代理人只負責設計、檢查、估算與開啟檔案。

- **AI 代理人**：用一句話描述（例如「設計一個 60×40×30 毫米、帶蓋的電子元件盒」），代理人挑零件、填尺寸、
  檢查、縮放、搜尋現成模型、切片估算、開 Bambu Studio、讀印表機狀態。
  - 沒有金鑰：免費的**本機規則**（看得懂尺寸、零件種類、「壁厚改成 2.4」「縮放到 12 公分高」「搜尋手機架」等常見說法）。
  - 填入 Claude API 金鑰：使用 `claude-opus-5-5`，可以自由描述、附照片與草圖；工具都在這台電腦上執行。
- **匯入現成模型、分區逐一修改**（v1.1.0）：零件庫沒有的東西，匯入 STL、OBJ（含 .mtl）、FBX、Maya .ma、3MF、GLB、PLY
  （Maya .mb 是封閉格式，請在 Maya 另存 .ma 或匯出 FBX／OBJ）。自動讀出原檔的材質群組（例如 Body、screen、button），
  或依表面轉折、空間分塊、由下往上分層切成幾個區塊；再一區一區刪除、只保留、移動、縮放、旋轉、改名、合併、
  指定耗材顏色（存成 Bambu 多色 3MF）、沿平面切成兩半殼、鑽孔、加凸台。也可以直接跟代理人說
  「分成 6 區」「第 2 區塗黑色」「在第 3 區鑽 9.5 mm 孔」「沿 Z 切兩半」。
- **零件設計**：19 種參數化零件（manifold3d 實體布林運算，保證封閉）— 帶蓋收納盒、電子元件盒、開孔平板、L 型支架、
  牆面／桌下掛鉤、理線夾、手機平板支架、Gridfinity 收納盒、花瓶燈罩、花盆、旋鈕、管接頭、層板支架、漸開線齒輪、
  方塊、圓管、墊圈，以及**額溫槍外殼**（槍型／直棒型；內建 GOOUUU ESP32-S3 42 pin 開發板滑軌與 USB-C 開口、
  503450 鋰電池艙、MLX90614 紅外線感測器座、0.96 吋 OLED 窗與 M2 螺絲柱、扳機按鍵孔、M2 合殼螺絲；
  切成左右兩半殼後自動嵌合排版，兩塊放得進同一個 A1 列印盤）。拖曳滑桿即時重建，照列印方向設計（水平孔做成淚滴形免支撐）。
- **七項列印前檢查**：網格完整、列印範圍（13 種拓竹機型）、懸空零件、懸垂、壁厚、底面接觸、材料適用，10 分制，
  並給建議的層高、填充、牆數、溫度與支撐。可修復破洞、自動擺放、縮放到指定高度、換算單位。
- **Bambu Studio**：一鍵存成 3MF 並開啟；用 Bambu Studio 自己的切片引擎無頭估算列印時間與耗材克數。
- **格式轉換**：Bambu Studio 多色 3MF（上色筆刷）→ GLB（每種耗材一個材質）；有紋理的模型 → AMS 多色 3MF。
- **搜尋現成模型**：同時搜尋 MakerWorld 與 Printables，依下載數排序。
- **AI 文字／照片轉 3D**：Meshy、Tripo、Rodin（自備金鑰；會扣點數，一定先確認）。
- **印表機狀態**：區網唯讀（進度、剩餘時間、溫度、AMS 耗材）；不能開始、暫停或改變列印。
- **設計庫**：每次修改存一版（檔案＋SHA-256＋參數＋檢查結果＋縮圖都在資料庫），核准後凍結。
- **資料庫**：內建 MariaDB（自動啟動、關閉程式就停止），使用者與六項權限
  （AI 代理人、零件設計與設計庫、模型工具、印表機與切片、核准設計、系統管理）。
- **語音動態教學**（9 課，步驟聚光框＋跟著做）、各頁「本頁說明」、程式內更新、桌面捷徑、備份還原、操作紀錄。

金鑰（Claude、AI 3D）與印表機存取碼只存在這台電腦的 `secrets.json`，不進資料庫、不進備份。

## 下載

| 平台 | 檔案 |
|---|---|
| Windows 11 | [ZMSPrintAgent-Setup-1.0.0.exe](https://github.com/achir1015/zms-print-agent/releases/latest) |
| macOS 11 以上（Intel／Apple 晶片，已公證） | [ZMSPrintAgent-1.0.0-mac.dmg](https://github.com/achir1015/zms-print-agent/releases/latest)（打開後把 App 拖到「應用程式」） |
| 線上版（電腦、手機、平板的瀏覽器，免安裝） | https://achir1015.github.io/zms-print-agent/ |
| iPhone／iPad（iOS 17 以上） | [線上安裝頁](https://achir1015.github.io/zms-print-agent/ios/)（用 Safari 開；限登記過的裝置；App 內可檢查更新） |
| Android 8 以上 | [ZMSPrintAgent-1.0.0-android.apk](https://github.com/achir1015/zms-print-agent/releases/latest)（下載後點開安裝；App 內可檢查更新） |

線上版：AI 代理人（本機規則或自己的 Claude 金鑰，瀏覽器直接呼叫）、19 種零件（manifold-3d wasm，含額溫槍外殼）、七項檢查、
匯入 FBX／Maya .ma／OBJ 分區逐一修改（含拆開／組裝檢視、多色 3MF、鑽孔、切兩半）、3MF → GLB、匯出 3MF／STL／GLB／OBJ、設計庫（存在瀏覽器 IndexedDB）、語音教學；不能連 Bambu Studio、印表機、切片，
搜尋改成開啟 MakerWorld／Printables 的搜尋頁。

## 開發

```powershell
.venv\Scripts\python -m pytest -q          # 引擎、資料庫、畫面測試
.venv\Scripts\python run_web.py            # 網頁預覽 http://127.0.0.1:8670（自動登入 admin）
.venv\Scripts\python tools\demo_data.py --reset
.venv\Scripts\python tools\build_windows.py # 安裝檔 → dist-installer\
.venv\Scripts\python tools\make_pages.py --libs  # 線上版資料（data.js、語音、three.js、manifold wasm）
```

- 線上版的零件與檢查在 `docs/app/engine.js`、`checks.js`（JavaScript 移植），改 `pa/recipes.py` 要一起改；
  `tests/test_web_parity.py` 用 Node 比對兩邊的體積、尺寸與檢查結果。分區編輯在 `docs/app/regions.js`（移植 `pa/importers.py`、`pa/segment.py`）。改線上版程式要遞增 `docs/sw.js` 的 `CACHE`。

- `pa/recipes.py` 參數化零件、`pa/mesh3d.py` 讀寫、`pa/render.py` 預覽繪圖、`pa/checks.py` 檢查、
  `pa/agent.py` 代理人、`pa/tools3d.py` Bambu Studio／印表機／搜尋／AI 生成、`pa/designbiz.py` 設計庫。
- 埠：資料庫 3498（測試 3508）、網頁預覽 8670。

## 授權與致謝

本程式以 **GNU AGPL-3.0** 授權發佈（因為內含 AGPL 的 3MF 多色解碼器）。

- [bambu-studio-ai](https://github.com/heyixuan2/bambu-studio-ai)（MIT，Yixuan He）：網格檢查與修復、自動擺放、搜尋、
  AI 生成、切片估算、印表機狀態、彩色化 — 放在 `vendor/bsa`。
- [bambu-3mf-to-glb](https://github.com/kylertran/bambu-3mf-to-glb)（AGPL-3.0）：Bambu 上色筆刷解碼 — 放在 `vendor/b3g`。
- [Form Studio](https://github.com/kaizensx/form-studio)（MIT）：「建構模組」與設計版本雜湊的構想（程式為自行撰寫）。
- manifold3d（Apache-2.0）、trimesh（MIT）、Flet（Apache-2.0）、MariaDB（GPL-2.0，獨立程式）、Noto Sans TC（OFL）。

系統開發：吳玉柱 先生 與 Claude AI Opus 5.5
