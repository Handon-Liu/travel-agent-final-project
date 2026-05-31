# -*- coding: utf-8 -*-
r"""
Gemini Adaptive Travel Agent GUI (Worldwide Travel + Hotel/Activity Maps Sync v5.1)

Features:
1. Tkinter GUI travel-planning chat interface.
2. Worldwide destination support instead of Japan-only planning.
3. Local user_profile.json memory for persistent preferences and generated plans.
4. Gemini 2.5 Flash API integration through google-genai.
5. Pydantic structured JSON output for dynamic flight / hotel / activity options.
6. Background threading to avoid freezing the GUI during API calls.
7. Google Maps synchronization through webbrowser + URL encoding for hotel and activity selections only.

Before running:
    pip install google-genai pydantic

PowerShell example:
    cd "C:\Data\NYCU\AI\期末報告"
    $env:GEMINI_API_KEY="your Gemini API Key"
    python .\gemini_travel_agent_gui_worldwide_v5_1.py
"""

import json
import os
import threading
import time
import tkinter as tk
import urllib.parse
import webbrowser
from pathlib import Path
from tkinter import messagebox, scrolledtext

try:
    from google import genai
    from google.genai import types
    from pydantic import BaseModel, Field
except ImportError:
    genai = None
    types = None
    BaseModel = None
    Field = None


# ==========================================
# Pydantic schema for Gemini JSON output
# ==========================================
if BaseModel:
    class OptionItem(BaseModel):
        id: int = Field(description="Unique option ID")
        title: str = Field(description="Precise option title, such as flight, hotel, restaurant, activity, or attraction name")
        detail: str = Field(description="Detailed information such as airport, time, price, district, features, or location")

    class TravelOptionsSchema(BaseModel):
        category: str = Field(description="Recommendation category, such as flight, hotel, or activity")
        description: str = Field(description="Short friendly introduction for the user")
        options: list[OptionItem] = Field(description="Three recommended options")
else:
    OptionItem = None
    TravelOptionsSchema = None


class GeminiAdaptiveTravelAgentGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AI 驅動型全球自適應旅遊規劃 Agent (Worldwide v5.1)")
        self.root.geometry("850x820")
        self.root.minsize(680, 650)
        self.root.configure(bg="#f4f6f9")

        self.profile_path = Path("user_profile.json")
        self.user_profile = self.load_user_profile()

        # State control:
        # 0: confirm whether to reuse historical destination/style
        # 1: collect destination and departure city
        # 2: collect travel style
        # 3: collect date / days / budget / baggage parameters
        # 4: flight option selection
        # 5: hotel option selection
        # 6: activity / restaurant option selection
        # 7: final itinerary adjustment
        self.chat_stage = 1
        self.is_generating = False
        self.dynamic_widgets = []
        self.selected_value = tk.IntVar(value=0)

        self.api_key = self.get_api_key()
        self.client = self.create_gemini_client()

        self.create_widgets()
        self.welcome_user()

    # -----------------------------
    # User memory and API setup
    # -----------------------------
    def get_api_key(self):
        return (
            os.environ.get("Gemini API Key")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )

    def create_gemini_client(self):
        if genai is None or not self.api_key:
            return None
        try:
            return genai.Client(api_key=self.api_key)
        except Exception:
            return None

    def default_profile(self):
        return {
            "chat_count": 0,
            "history_requests": [],
            "departure_city": "",
            "destination_text": "",
            "destination_country": "",
            "destination_city": "",
            "confirmed_style": "未定",
            "travel_days": "",
            "last_trip_params": "",
            "selected_flight": "",
            "selected_hotel": "",
            "selected_activity": "",
            "last_generated_plan": "",
            "conversation_summary": "",
            "updated_at": "",
        }

    def load_user_profile(self):
        if not self.profile_path.exists():
            return self.default_profile()
        try:
            with self.profile_path.open("r", encoding="utf-8") as f:
                profile = json.load(f)
            default = self.default_profile()
            for key, value in default.items():
                profile.setdefault(key, value)
            return profile
        except json.JSONDecodeError:
            messagebox.showwarning(
                "JSON 格式錯誤",
                "user_profile.json 格式損壞，系統將重新建立預設記憶檔。",
            )
            return self.default_profile()
        except Exception:
            return self.default_profile()

    def save_user_profile(self):
        self.user_profile["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.profile_path.open("w", encoding="utf-8") as f:
            json.dump(self.user_profile, f, ensure_ascii=False, indent=4)

    # -----------------------------
    # GUI widgets
    # -----------------------------
    def create_widgets(self):
        title_label = tk.Label(
            self.root,
            text="✨ LLM-Powered 全球旅遊自適應規劃系統 (Worldwide v5)",
            font=("Microsoft JhengHei", 14, "bold"),
            bg="#10a37f",
            fg="white",
            padx=10,
            pady=12,
        )
        title_label.pack(fill=tk.X)

        self.chat_history = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            font=("Microsoft JhengHei", 11),
            bg="white",
            relief=tk.FLAT,
        )
        self.chat_history.pack(padx=12, pady=12, fill=tk.BOTH, expand=True)
        self.chat_history.config(state=tk.DISABLED)

        self.option_panel = tk.Frame(self.root, bg="#f4f6f9")
        self.option_panel.pack(padx=12, pady=(0, 5), fill=tk.X)

        input_frame = tk.Frame(self.root, bg="#f4f6f9")
        input_frame.pack(padx=12, pady=(0, 12), fill=tk.X)

        self.user_input = tk.Entry(input_frame, font=("Microsoft JhengHei", 11), bg="white")
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=7)
        self.user_input.bind("<Return>", lambda event: self.handle_send())

        self.send_button = tk.Button(
            input_frame,
            text="發送",
            font=("Microsoft JhengHei", 10, "bold"),
            bg="#10a37f",
            fg="white",
            width=10,
            command=self.handle_send,
        )
        self.send_button.pack(side=tk.RIGHT, padx=(8, 0))

        reset_button = tk.Button(
            input_frame,
            text="重置記憶",
            font=("Microsoft JhengHei", 9),
            bg="#e5e7eb",
            fg="#111827",
            width=10,
            command=self.reset_profile,
        )
        reset_button.pack(side=tk.RIGHT, padx=(8, 0))

    def bot_say(self, text):
        self.chat_history.config(state=tk.NORMAL)
        self.chat_history.insert(tk.END, "🤖 [Agent AI]: " + str(text).strip() + "\n\n")
        self.chat_history.config(state=tk.DISABLED)
        self.chat_history.see(tk.END)

    def user_say(self, text):
        self.chat_history.config(state=tk.NORMAL)
        self.chat_history.insert(tk.END, "👤 [您]: " + str(text).strip() + "\n\n")
        self.chat_history.config(state=tk.DISABLED)
        self.chat_history.see(tk.END)

    def set_generating_state(self, generating):
        self.is_generating = generating
        state = tk.DISABLED if generating else tk.NORMAL
        self.send_button.config(state=state)
        self.user_input.config(state=state)

    def clear_dynamic_widgets(self):
        for widget in self.dynamic_widgets:
            widget.destroy()
        self.dynamic_widgets.clear()

    def reset_profile(self):
        if messagebox.askyesno("確認", "確定要清除本機記憶嗎？"):
            self.user_profile = self.default_profile()
            self.save_user_profile()
            self.clear_dynamic_widgets()
            self.chat_history.config(state=tk.NORMAL)
            self.chat_history.delete("1.0", tk.END)
            self.chat_history.config(state=tk.DISABLED)
            self.chat_stage = 1
            self.welcome_user()

    def welcome_user(self):
        self.user_profile["chat_count"] += 1
        self.save_user_profile()
        self.bot_say(f"您好！歡迎使用全球旅遊規劃系統，這是我與您的第 {self.user_profile['chat_count']} 次對話。")

        if genai is None or BaseModel is None:
            self.bot_say("⚠️ 尚未安裝 google-genai 或 pydantic 套件。請執行：pip install google-genai pydantic")
            return

        if not self.api_key:
            self.bot_say("⚠️ 尚未偵測到 Gemini API Key。請設定 GEMINI_API_KEY、GOOGLE_API_KEY，或 Gemini API Key 環境變數。")

        if self.user_profile.get("destination_text") and self.user_profile.get("confirmed_style") != "未定":
            self.bot_say(
                "🔍 歷史偏好記憶啟動：\n"
                f"上次目的地：{self.user_profile.get('destination_text')}\n"
                f"上次核心風格：{self.user_profile.get('confirmed_style')}"
            )
            self.bot_say("請問這次是否沿用此目的地與風格？請輸入 yes / no。")
            self.chat_stage = 0
        else:
            self.bot_say(
                "請先告訴我這次的出發地與目的地。\n"
                "格式範例：從台北出發，想去法國巴黎。\n"
                "如果還不確定目的地，也可以輸入：從台北出發，想找便宜又放鬆的海島。"
            )
            self.chat_stage = 1

    # -----------------------------
    # Google Maps integration
    # -----------------------------
    def popup_google_map(self, category, item_text):
        """Open Google Maps only for hotel and activity/restaurant selections."""
        destination = self.user_profile.get("destination_text", "").strip()
        item_text = item_text.strip()

        if category == "hotel":
            search_keyword = f"{item_text} {destination} hotel"
        elif category == "activity":
            search_keyword = f"{item_text} {destination}"
        else:
            # Requirement v5.1: flight selections should not trigger Google Maps.
            return

        encoded_keyword = urllib.parse.quote(search_keyword)
        map_url = f"https://www.google.com/maps/search/?api=1&query={encoded_keyword}"
        self.bot_say(f"🌐 [地圖連動]: 已為您自動開啟 Google 地圖查看：【{search_keyword}】")
        webbrowser.open(map_url)

    # -----------------------------
    # Conversation state machine
    # -----------------------------
    def handle_send(self):
        if self.is_generating:
            self.bot_say("系統仍在產生回覆，請稍候。")
            return

        text = self.user_input.get().strip()
        if not text:
            return

        self.user_input.delete(0, tk.END)
        self.user_say(text)

        if self.chat_stage == 0:
            if text.lower() in ["yes", "y", "是", "好", "沿用", "可以"]:
                self.bot_say("好的，已沿用歷史目的地與風格。請告訴我『日期/天數/預算/行李』，例如：8 月中旬/7 天/預算 6 萬/1 件托運。")
                self.chat_stage = 3
            else:
                self.user_profile["destination_text"] = ""
                self.user_profile["destination_country"] = ""
                self.user_profile["destination_city"] = ""
                self.user_profile["departure_city"] = ""
                self.user_profile["confirmed_style"] = "未定"
                self.save_user_profile()
                self.bot_say("好的，請重新輸入這次的出發地與目的地。例：從台北出發，想去韓國首爾。")
                self.chat_stage = 1
            return

        if self.chat_stage == 1:
            self.user_profile["destination_text"] = text
            self.user_profile["history_requests"].append(f"Destination: {text}")
            self.save_user_profile()
            self.bot_say("目的地資訊已記錄。接下來請描述這次旅行的核心風格或需求，例如：放鬆、美食、購物、自然、親子、蜜月、低預算、文化體驗。")
            self.chat_stage = 2
            return

        if self.chat_stage == 2:
            self.user_profile["confirmed_style"] = text
            self.user_profile["history_requests"].append(f"Style: {text}")
            self.save_user_profile()
            self.bot_say("風格已鎖定。請告訴我『日期/天數/預算/行李』，例如：8 月中旬/7 天/預算 6 萬/1 件托運。")
            self.chat_stage = 3
            return

        if self.chat_stage == 3:
            if self.client is None:
                self.bot_say("❌ Gemini Client 尚未初始化。請確認已安裝套件並設定 GEMINI_API_KEY。")
                return
            self.user_profile["last_trip_params"] = text
            self.save_user_profile()
            self.bot_say("正在根據您的目的地、日期與風格，為您篩選【全球航班選單】...")
            self.chat_stage = 4
            self.set_generating_state(True)
            threading.Thread(target=self.get_json_options_from_gemini, args=("flight",), daemon=True).start()
            return

        if self.chat_stage == 7:
            if self.client is None:
                self.bot_say("❌ Gemini Client 尚未初始化。請確認已安裝套件並設定 GEMINI_API_KEY。")
                return
            self.bot_say("收到您的微調需求，正在根據上一版企劃書重新調整...")
            self.set_generating_state(True)
            threading.Thread(target=self.get_final_itinerary_from_gemini, args=(text,), daemon=True).start()
            return

        self.bot_say("目前請先使用上方選單完成點選，或等待系統生成完成。")

    # -----------------------------
    # User option selection handling
    # -----------------------------
    def handle_option_selection(self, category, options_data):
        if not options_data:
            self.bot_say("⚠️ 目前沒有可選項目，請重新輸入條件或稍後再試。")
            return

        selected_idx = self.selected_value.get()
        if selected_idx < 0 or selected_idx >= len(options_data):
            self.bot_say("⚠️ 選項索引無效，請重新選擇。")
            return

        selected_item = options_data[selected_idx]
        chosen_text = f"{selected_item['title']} ({selected_item['detail']})"
        self.user_say(f"我選擇了：{chosen_text}")

        map_keyword = f"{selected_item['title']} {selected_item['detail']}"
        if category in ["hotel", "activity"]:
            self.popup_google_map(category, map_keyword)
        self.clear_dynamic_widgets()

        if category == "flight":
            self.user_profile["selected_flight"] = chosen_text
            self.save_user_profile()
            self.chat_stage = 5
            self.bot_say("航班選擇成功！接下來正在為您媒合目的地的【住宿區域與飯店選單】...")
            self.set_generating_state(True)
            threading.Thread(target=self.get_json_options_from_gemini, args=("hotel",), daemon=True).start()

        elif category == "hotel":
            self.user_profile["selected_hotel"] = chosen_text
            self.save_user_profile()
            self.chat_stage = 6
            self.bot_say("飯店選擇成功！最後正在為您挑選當地的【景點 / 餐廳 / 體驗選單】...")
            self.set_generating_state(True)
            threading.Thread(target=self.get_json_options_from_gemini, args=("activity",), daemon=True).start()

        elif category == "activity":
            self.user_profile["selected_activity"] = chosen_text
            self.save_user_profile()
            self.chat_stage = 7
            self.bot_say("所有元件挑選完畢！正在為您生成最終版的【全球自由行完整企劃書】...")
            self.set_generating_state(True)
            threading.Thread(target=self.get_final_itinerary_from_gemini, daemon=True).start()

    # -----------------------------
    # Gemini structured option generation
    # -----------------------------
    def get_json_options_from_gemini(self, category):
        try:
            if self.client is None:
                raise RuntimeError("Gemini Client 尚未初始化")

            prompt = f"""
基於以下旅客偏好，請生成 3 個符合主題、最推薦的【{category}】選單供旅客點選。

【出發地與目的地】
{self.user_profile.get('destination_text', '')}

【旅客核心偏好】
{self.user_profile.get('confirmed_style', '')}

【日期、天數、預算與行李參數】
{self.user_profile.get('last_trip_params', '')}

【已選航班】
{self.user_profile.get('selected_flight', '')}

【已選飯店】
{self.user_profile.get('selected_hotel', '')}

如果類別是 flight，請根據出發地與目的地，推薦 3 個合理國際或國內航班選項。detail 必須包含出發機場、抵達機場、航空公司、是否轉機、時間帶與機場代碼，但航班選擇不需要觸發地圖。
如果類別是 hotel，請根據目的地城市推薦 3 個住宿區域或飯店。title 必須是精確飯店名稱或區域名稱，detail 必須包含城市、區域、特色與大約預算等級。
如果類別是 activity，請根據目的地與旅行風格推薦 3 個景點、餐廳或在地體驗。title 必須是可被 Google Maps 搜尋到的精確名稱，detail 必須包含地區、適合原因與注意事項。
"""

            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "你是一個全球自由行旅遊規劃元件篩選專家。"
                        "請嚴格輸出符合 Schema 結構的 JSON 數據，不要有額外聊天字眼。"
                        "選項內容必須符合使用者指定的目的地，不可固定為日本或東京。"
                        "hotel 與 activity 的 title 請使用精確真實名稱，以利 Google Maps 搜尋；flight 可使用航空公司與航班資訊。"
                    ),
                    temperature=0.7,
                    response_mime_type="application/json",
                    response_schema=TravelOptionsSchema,
                ),
            )
            raw_json = json.loads(response.text)
            self.root.after(0, lambda: self.render_dynamic_options(category, raw_json))
        except Exception as e:
            self.root.after(0, lambda: self.finish_error(f"產生選單失敗: {e}"))

    def render_dynamic_options(self, category, json_data):
        self.set_generating_state(False)
        self.clear_dynamic_widgets()
        self.bot_say(json_data.get("description", "請選擇以下最符合您需求的選項："))
        self.selected_value.set(0)
        options = json_data.get("options", [])

        if not options:
            self.bot_say("⚠️ Gemini 沒有回傳可用選項，請重新輸入條件或稍後再試。")
            return

        for idx, item in enumerate(options):
            display_text = f"【{item['title']}】 - {item['detail']}"
            rb = tk.Radiobutton(
                self.option_panel,
                text=display_text,
                variable=self.selected_value,
                value=idx,
                font=("Microsoft JhengHei", 10),
                bg="#f4f6f9",
                anchor="w",
                justify=tk.LEFT,
                wraplength=760,
            )
            rb.pack(fill=tk.X, anchor="w", pady=3)
            self.dynamic_widgets.append(rb)

        confirm_btn = tk.Button(
            self.option_panel,
            text="確認此項選擇 ➔",
            font=("Microsoft JhengHei", 9, "bold"),
            bg="#0084ff",
            fg="white",
            padx=10,
            command=lambda: self.handle_option_selection(category, options),
        )
        confirm_btn.pack(pady=5, anchor="e")
        self.dynamic_widgets.append(confirm_btn)

    # -----------------------------
    # Gemini final itinerary generation
    # -----------------------------
    def get_final_itinerary_from_gemini(self, adjustment_text=""):
        try:
            if self.client is None:
                raise RuntimeError("Gemini Client 尚未初始化")

            previous_plan = self.user_profile.get("last_generated_plan", "")

            if adjustment_text:
                prompt = f"""
以下是上一版旅遊企劃書：
{previous_plan}

以下是使用者提出的微調需求：
{adjustment_text}

請根據使用者微調需求，保留上一版中合理的部分，並重新輸出修訂版完整企劃書。
"""
            else:
                prompt = f"""
請將以下使用者逐步點選確認的元件，融合組裝成完整的『全球自由行完整行程企劃書』：

【出發地與目的地】
{self.user_profile.get('destination_text', '')}

【已選航班】
{self.user_profile.get('selected_flight', '')}

【已選飯店】
{self.user_profile.get('selected_hotel', '')}

【已選景點 / 餐廳 / 體驗】
{self.user_profile.get('selected_activity', '')}

【核心風格偏好】
{self.user_profile.get('confirmed_style', '')}

【日期、天數、預算與行李參數】
{self.user_profile.get('last_trip_params', '')}
"""

            system_instruction = """
你是一位全球自由行旅遊規劃專家，熟悉不同國家城市的交通、住宿區域、景點餐廳、文化注意事項與旅遊風險。
請根據使用者的目的地、預算、天數、旅行風格，以及已點選的航班、飯店與景點/餐廳/體驗，生成一份高質感且實用的完整行程企劃書。
不可固定輸出日本或東京行程，必須依照使用者指定的目的地調整。

排版格式需包含：
1. 點選需求摘要
2. 整體路線與住宿區域安排
3. 每日行程表：上午、下午、晚上、交通、預算提醒
4. 當地交通建議，例如地鐵、鐵路、租車、機場交通或城市通票
5. 飲食、文化、安全與簽證/入境注意事項
6. 風險提示與人工確認事項，例如航班價格、飯店空房、行李額度、營業時間、治安、天氣
7. 是否需要使用者微調的提問
最後語氣要親切專業，使用繁體中文。
"""

            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system_instruction, temperature=0.5),
            )
            self.root.after(0, lambda: self.finish_final_plan(response.text))
        except Exception as e:
            self.root.after(0, lambda: self.finish_error(f"生成完整企劃失敗: {e}"))

    def finish_final_plan(self, result_text):
        self.set_generating_state(False)
        self.user_profile["last_generated_plan"] = result_text
        self.user_profile["conversation_summary"] = (
            f"目的地：{self.user_profile.get('destination_text', '')}；"
            f"核心風格：{self.user_profile.get('confirmed_style', '')}；"
            f"旅行參數：{self.user_profile.get('last_trip_params', '')}；"
            f"航班：{self.user_profile.get('selected_flight', '')}；"
            f"飯店：{self.user_profile.get('selected_hotel', '')}；"
            f"景點/餐廳/體驗：{self.user_profile.get('selected_activity', '')}"
        )
        self.save_user_profile()
        self.chat_stage = 7
        self.bot_say(result_text)
        self.bot_say("✨ 您的全球自由行企劃書已生成！若有任何不滿意，例如行程太滿、想降低預算、想換城市或想增加購物，您可以直接在下方輸入微調要求。")

    def finish_error(self, err_msg):
        self.set_generating_state(False)
        self.bot_say(f"❌ {err_msg}")


if __name__ == "__main__":
    root = tk.Tk()
    app = GeminiAdaptiveTravelAgentGUI(root)
    root.mainloop()
