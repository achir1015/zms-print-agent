"""語音動態教學與各畫面說明。

LESSONS：每一課有步驟 [(圖示, 色調, 步驟文字, 對應畫面代號)] 與旁白；播放時依旁白長度依序點亮步驟（聚光框），
         每一步都可以按「跟著做」直接開啟對應畫面。
         旁白由 tools/make_voice.py 預先產生 MP3（assets/voice/<key>.mp3）。
PAGES：各畫面「本頁說明」的旁白（assets/voice/page_<畫面代號>.mp3）。
"""

LESSONS = [
    dict(key="intro", title="認識資料助秘3D列印AI代理人工具", steps=[
        ("SMART_TOY", "violet", "一句話請 AI 代理人設計", "agent"),
        ("ARCHITECTURE", "amber", "參數化零件：精確尺寸", "design"),
        ("FACT_CHECK", "teal", "七項列印前檢查與修復", "check"),
        ("OPEN_IN_NEW", "green", "開到 Bambu Studio，自己按列印", "design"),
        ("COLLECTIONS_BOOKMARK", "blue", "設計庫：版本、雜湊、核准", "library"),
    ], voice=(
        "歡迎使用資料助秘3D列印AI代理人工具。這套系統把一句描述變成可以在拓竹印表機列印的零件。"
        "你可以直接告訴 AI 代理人想印什麼、大概多大，它會設計零件、做七項列印前檢查，"
        "並估算列印時間和耗材克數。功能性的零件用參數化零件庫，精確到零點一毫米；"
        "日常用品可以先搜尋 MakerWorld 和 Printables 的現成設計；人物和擺件可以用 AI 文字或照片轉 3D；"
        "零件庫沒有的外殼，可以匯入現成模型，分成區塊逐一修改。"
        "滿意以後按 Bambu Studio，模型會在 Bambu Studio 開啟，由你自己檢查、切片、按列印，系統不會自己開始列印。"
        "每個設計都存在設計庫，修改一次就多一個版本，核准後檔案和雜湊值會凍結。")),
    dict(key="agent", title="AI 代理人：用說的設計零件", steps=[
        ("EDIT", "violet", "描述要印的東西與尺寸", "agent"),
        ("VIEW_IN_AR", "blue", "右邊即時出現模型", "agent"),
        ("TUNE", "amber", "直接說要改哪裡", "agent"),
        ("FACT_CHECK", "teal", "看檢查分數與建議", "agent"),
        ("SAVE", "green", "存到設計庫或送 Bambu Studio", "agent"),
    ], voice=(
        "在 AI 代理人的輸入框，用平常說話的方式描述，例如：設計一個六十乘四十乘三十毫米、帶蓋的電子元件盒。"
        "代理人會挑選適合的零件種類、填入尺寸，右邊立刻出現三維模型，可以用滑鼠拖曳旋轉、滾輪放大。"
        "要修改就直接說，例如：壁厚改成二點四、寬改成八十、縮放到十二公分高，或是檢查能不能放進 A1 Mini。"
        "沒有填 Claude 金鑰時，用的是免費的本機規則，看得懂常見說法；"
        "在 AI 與印表機設定填入 Claude API 金鑰後，就能自由描述，還可以附照片或草圖。"
        "左邊是對話紀錄，之前的對話可以接著聊。")),
    dict(key="design", title="零件設計：拉一拉就改尺寸", steps=[
        ("VIEW_LIST", "amber", "左邊選零件種類", "design"),
        ("TUNE", "blue", "拖曳滑桿或輸入數字", "design"),
        ("VIEW_IN_AR", "violet", "模型即時重建", "design"),
        ("PRINT", "green", "選印表機與耗材重新檢查", "design"),
        ("SAVE", "teal", "存到設計庫、匯出 3MF／STL／GLB", "design"),
    ], voice=(
        "零件設計內建十八種參數化零件：帶蓋收納盒、電子元件盒、開孔平板、L 型支架、牆面和桌下掛鉤、理線夾、"
        "手機平板支架、Gridfinity 收納盒、花瓶、花盆、旋鈕、管接頭、層板支架、齒輪、方塊、圓管和墊圈。"
        "左邊選零件，中間拖曳滑桿或直接輸入數字，放開滑鼠模型就會重建。"
        "每個零件都照列印方向設計，大平面朝下、懸垂不超過四十五度，通常不需要支撐；"
        "水平的螺絲孔做成淚滴形，印在牆上也不會塌。"
        "右邊可以選印表機、耗材和用途重新檢查，按切片估算會用 Bambu Studio 的切片引擎算出時間和克數。")),
    dict(key="check", title="模型檢查與修復", steps=[
        ("FOLDER_OPEN", "blue", "開啟 STL、3MF、GLB", "check"),
        ("STRAIGHTEN", "amber", "換算單位、縮放到高度", "check"),
        ("AUTO_FIX_HIGH", "teal", "修復破洞、自動擺放", "check"),
        ("FACT_CHECK", "violet", "七項檢查與評分", "check"),
    ], voice=(
        "下載或 AI 產生的模型常有單位錯誤、破洞、碎片或方向不對。到檢查與修復開啟檔案，"
        "系統會先判斷單位，例如模型只有零點一幾，表示單位是公尺，會自動換算成毫米。"
        "填入想要的高度、勾選修復與自動擺放，按套用並重新檢查。"
        "七項檢查是：網格是否封閉、放不放得進列印範圍、有沒有懸在半空的零件、懸垂角度、壁厚、"
        "和列印板的接觸面積，以及耗材適不適合這台印表機。滿分十分，有嚴重問題時最多四分，紅色的項目要先處理。")),
    dict(key="convert", title="格式轉換與搜尋現成模型", steps=[
        ("SYNC_ALT", "violet", "多色 3MF 轉 GLB", "convert"),
        ("COLOR_LENS", "amber", "彩色模型轉 AMS 多色", "convert"),
        ("TRAVEL_EXPLORE", "teal", "搜尋 MakerWorld、Printables", "search"),
        ("AUTO_AWESOME", "rose", "AI 文字／照片轉 3D", "aigen"),
    ], voice=(
        "格式轉換可以把 Bambu Studio 上過色的多色 3MF 專案轉成 GLB，"
        "每種耗材一個材質，Blender、Unity、網頁和 Windows 三維檢視器都能打開，顏色和 Bambu Studio 裡看到的一樣。"
        "反過來，有紋理的彩色模型也能轉成 AMS 多色 3MF，系統會偵測顏色並配對最接近的拓竹耗材。"
        "搜尋現成模型會同時查 MakerWorld 和 Printables，依下載數排序，點卡片到網站下載，要販售請注意授權。"
        "AI 文字或照片轉 3D 需要你自己的 Meshy、Tripo 或 Rodin 金鑰，每次會扣點數，所以一定會先問你。")),
    dict(key="regions", title="匯入現成模型、分區逐一修改", steps=[
        ("FOLDER_OPEN", "blue", "匯入 STL、OBJ、FBX、Maya", "regions"),
        ("DASHBOARD_CUSTOMIZE", "violet", "自動分成幾個區塊", "regions"),
        ("CHECK_BOX", "amber", "勾選要改的區塊", "regions"),
        ("FORMAT_PAINT", "rose", "刪除、縮放、上色、鑽孔", "regions"),
        ("CONTENT_CUT", "teal", "切成兩半、存檔列印", "regions"),
    ], voice=(
        "零件庫沒有的東西，例如額溫槍外殼，可以先找現成的模型匯入。支援 STL、OBJ 加上同名的 MTL、FBX、Maya 的 ma 檔、3MF 和 GLB；"
        "Maya 的 mb 檔是封閉格式，請先在 Maya 另存成 ma 或匯出 fbx。匯入後按分區，系統會依原檔的材質群組、互不相連的實體、"
        "表面轉折或空間位置，把模型分成幾個區塊，每一區用不同顏色顯示。勾選要修改的區塊，可以刪除、只保留、移動、縮放、旋轉、"
        "改名、合併，也可以指定耗材顏色，存檔時會變成 Bambu Studio 的多色 3MF，AMS 直接列印。"
        "還能在區塊中心鑽孔或加凸台、沿 X、Y、Z 切成兩半。每一步都能復原，AI 代理人也可以幫你做，例如說：分成六區、第三區刪掉、第二區塗黑色。")),
    dict(key="printer", title="Bambu Studio、切片估算與印表機", steps=[
        ("OPEN_IN_NEW", "green", "一鍵開到 Bambu Studio", "design"),
        ("TIMER", "amber", "切片估算時間與克數", "design"),
        ("ROUTER", "blue", "設定印表機 IP 與存取碼", "printers"),
        ("PRINT", "teal", "看進度、溫度、AMS 耗材", "printers"),
    ], voice=(
        "按 Bambu Studio，模型會存成 3MF 並在 Bambu Studio 開啟。請檢查下方的尺寸、確認沒有懸空的部分，"
        "按 Ctrl 加 R 切片，看時間、耗材和支撐，滿意後由你自己按列印。"
        "切片估算會在背景用 Bambu Studio 自己的引擎和設定檔切一次，大約三十秒，算出含開始程序的列印時間和克數。"
        "印表機狀態要先設定區網 IP、序號和存取碼，存取碼只存在這台電腦。"
        "連線是唯讀的，可以看進度、剩餘時間、噴嘴和熱床溫度、AMS 裝了哪些耗材，"
        "但不能開始、暫停或改變列印，暫停或取消請在印表機螢幕或 Bambu Handy 操作。")),
    dict(key="library", title="設計庫、版本與核准", steps=[
        ("COLLECTIONS_BOOKMARK", "blue", "縮圖瀏覽所有設計", "library"),
        ("HISTORY", "violet", "每次修改一個版本", "library"),
        ("FINGERPRINT", "teal", "檔案 SHA-256 雜湊", "library"),
        ("VERIFIED", "green", "核准後凍結", "library"),
        ("DOWNLOAD", "amber", "匯出任何一版", "library"),
    ], voice=(
        "按存到設計庫，模型檔、參數、檢查結果和縮圖都會存進資料庫，備份資料庫就等於備份所有模型。"
        "同一個設計再修改並儲存，會變成下一個版本，舊版本都還在，每一版都有檔案的 SHA-256 雜湊值。"
        "設計主管可以核准設計，核准後檔案和雜湊凍結；之後如果再修改，會變成新的草稿版本，需要重新核准。"
        "列印完成可以標記為已列印，不要的設計可以作廢；已核准的設計不能刪除。")),
    dict(key="admin", title="使用者權限與系統管理", steps=[
        ("ADMIN_PANEL_SETTINGS", "rose", "使用者與權限", "users"),
        ("TUNE", "pink", "AI 金鑰與預設印表機", "aiset"),
        ("BACKUP", "teal", "備份與還原", "backup"),
        ("SYSTEM_UPDATE", "blue", "版本更新與捷徑", "update"),
        ("HISTORY", "slate", "操作紀錄", "audit"),
    ], voice=(
        "使用者與權限有六項功能：AI 代理人、零件設計與設計庫、模型工具、印表機與切片、核准設計和系統管理，"
        "每項分成無、查詢、維護三種等級，也可以套用系統管理員、設計主管、設計師、操作員和訪客的角色範本。"
        "一般使用者只看得到自己的設計，有核准權限的人可以看全部。"
        "所有資料都在內建的 MariaDB 資料庫，請定期備份；金鑰和印表機存取碼只存在這台電腦，不會進備份。"
        "程式開啟時會自動檢查新版本，有新版本時上方會出現提示，按下去就能下載並安裝。")),
]

BY_KEY = {lesson["key"]: lesson for lesson in LESSONS}

PAGES = {
    "home": ("首頁", "在上面的輸入框用一句話告訴代理人要印什麼；下面有五種開始的方法、設計統計和最近的設計。"),
    "agent": ("AI 代理人", "在下面輸入框描述要印的東西和尺寸，按 Enter 送出；右邊會出現模型和檢查結果。"
                        "要修改就直接說，滿意後按 Bambu Studio 或存到設計庫。"),
    "design": ("零件設計", "左邊選零件種類，中間拖曳滑桿或輸入數字調整尺寸，右邊即時顯示模型與七項檢查。"),
    "library": ("設計庫", "左邊是所有設計的縮圖，點一個看明細：版本、雜湊值、檢查結果和切片紀錄，可以繼續編輯、核准或匯出。"),
    "regions": ("匯入與分區編輯", "左邊匯入模型並按分區，中間勾選區塊後選擇修改方式，右邊即時顯示；每一步都能按復原。"),
    "check": ("檢查與修復", "開啟模型檔，設定單位和高度，勾選修復與自動擺放，按套用並重新檢查。"),
    "convert": ("格式轉換", "選擇 Bambu Studio 的多色 3MF 轉成 GLB；或把有紋理的彩色模型轉成 AMS 多色 3MF。"),
    "search": ("搜尋現成模型", "輸入要找的東西，英文效果最好，點卡片到網站查看與下載。"),
    "aigen": ("AI 文字或照片轉 3D", "輸入英文描述或選照片，填好高度，按開始生成；會先確認，因為會扣點數。"),
    "printers": ("印表機狀態", "點一台印表機讀取狀態；第一次使用先按新增，填入 IP、序號和區網存取碼。"),
    "aiset": ("AI 與印表機設定", "填入 Claude API 金鑰讓代理人更聰明，填入 AI 3D 金鑰才能用 AI 生成；也可以指定 Bambu Studio 位置和預設印表機。"),
    "users": ("使用者與權限", "左邊是使用者清單，右邊設定姓名、密碼、角色範本和六項功能的權限。"),
    "backup": ("備份與還原", "按立即備份把資料存成壓縮檔，包含所有模型檔；還原會用備份檔覆蓋目前所有資料，請小心使用。"),
    "update": ("版本更新與捷徑", "按檢查更新查詢新版本，有新版本時按下載並安裝；也可以重建桌面捷徑。"),
    "audit": ("操作紀錄", "列出最近一千筆操作，可以依使用者或對象篩選，並匯出 Excel。"),
    "help": ("語音動態教學", "左邊選課程，按播放語音教學，步驟會隨著講解依序亮起來；每一步都可以按跟著做開啟對應畫面。"),
}


def text_for(sid):
    if sid in PAGES:
        return PAGES[sid]
    return ("本頁說明", "完整的操作教學請到說明的語音動態教學。")


def page_voice_key(sid):
    return "page_" + sid if sid in PAGES else "page_default"
