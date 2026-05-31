# Travel Agent Final Project

本專案為生成式 AI 旅遊推薦與行程規劃助手，系統會根據使用者需求，依序產生旅遊基本資訊、航班推薦、飯店推薦、景點安排、餐廳推薦，最後整合成完整旅遊行程。

## 專案模組

1. trip_info_generator.py：產生旅遊地點、天數、目的地
2. flight_recommender.py：推薦航班，讓使用者選擇
3. hotel_recommender.py：推薦飯店，讓使用者選擇
4. attraction_planner.py：推薦與安排景點
5. restaurant_recommender.py：推薦餐廳 / 美食，讓使用者選擇
6. itinerary_planner.py：整合前面選擇，產生完整每日行程

## 如何執行

```bash
pip install -r requirements.txt
python main.py
