# Travel Agent Final Project

AI 協作式旅遊規劃平台，整合航班推薦、住宿推薦、景點推薦、美食推薦與最後行程建議。

## 專案結構

```text
main.py                         Tkinter 桌面版入口
web_app.py                      Web 版入口，預設 http://127.0.0.1:7860/
requirements.txt                Python 套件需求
.env.example                    環境變數範本，請複製成 .env 後填入自己的 key
modules/
  flight_recommender.py         航班推薦橋接模組
  hotel_recommender.py          Gemini 住宿推薦模組
  attraction_planner.py         景點推薦模組，可選擇 Gemini 或 fallback
  trip_info_generator.py        舊版需求整理模組
flight_agent_project/
  flight_recommender.py         原始航班推薦系統
```

## 安裝

```powershell
pip install -r requirements.txt
```

## 設定環境變數

請先複製 `.env.example`：

```powershell
Copy-Item .env.example .env
```

接著打開 `.env`，填入自己的 API key：

```env
GEMINI_API_KEY=your_gemini_api_key_here
DUFFEL_ACCESS_TOKEN=your_duffel_access_token_here
ATTRACTION_USE_GEMINI=0
GOOGLE_MAPS_API_KEY=your_google_maps_api_key_here
```

說明：

- `GEMINI_API_KEY`：住宿、美食、最後行程建議會使用。
- `DUFFEL_ACCESS_TOKEN`：航班查詢會使用。
- `ATTRACTION_USE_GEMINI=0`：景點推薦使用程式內建 fallback，不消耗 Gemini 額度。
- `ATTRACTION_USE_GEMINI=1`：景點推薦改用 Gemini，會消耗 Gemini 額度。

請不要把 `.env` push 到 GitHub。

## 啟動 Web 版

```powershell
python web_app.py
```

開啟：

```text
http://127.0.0.1:7860/
```

## 目前工作流

1. 左側表單輸入旅遊基本資料。
2. 系統查詢並推薦航班。
3. 使用者選定航班後，進入住宿推薦。
4. 使用者選定住宿後，進入景點推薦。
5. 使用者可複選景點。
6. 系統根據景點推薦周邊美食。
7. 使用者可複選美食。
8. 系統整理成最後的行程建議頁。

## 會呼叫 Gemini 的地方

- 住宿推薦
- 美食推薦
- 最後行程建議
- 景點推薦：只有 `ATTRACTION_USE_GEMINI=1` 時才會呼叫

航班推薦目前使用 `flight_agent_project` 裡的航班推薦系統，不是 Gemini。
