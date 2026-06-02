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
from tkinter import messagebox, scrolledtext, ttk

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from modules.trip_info_generator import run as generate_trip_info
from modules.flight_recommender import run as recommend_flight_options
from modules.hotel_recommender import run as recommend_hotel_options
from modules.attraction_planner import get_attractions
from modules.restaurant_recommender import get_dining_plan

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
        self.root.title("AI 協作式旅遊規劃平台")
        self.root.geometry("1320x860")
        self.root.minsize(1080, 720)
        self.root.configure(bg="#ffffff")

        self.colors = {
            "bg": "#eef2f7",
            "card": "#ffffff",
            "primary": "#2563eb",
            "primary_dark": "#1e40af",
            "accent": "#10b981",
            "text": "#111827",
            "muted": "#6b7280",
            "border": "#dbe4ef",
            "bot_bubble": "#eff6ff",
            "user_bubble": "#dcfce7",
            "danger": "#ef4444",
            "sidebar": "#f3f5fa",
            "surface": "#ffffff",
            "soft_blue": "#e8f2ff",
        }

        self.profile_path = Path("user_profile.json")
        self.user_profile = self.load_user_profile()

        # State control:
        # 0: confirm whether to reuse historical destination/style
        # 1: collect destination and departure city
        # 2: collect travel style
        # 3: collect date / days / budget / baggage parameters
        # 4: flight option selection
        # 5: hotel option selection
        # 6: activity option selection
        # 7: restaurant option selection
        # 8: final itinerary adjustment
        self.chat_stage = 1
        self.is_generating = False
        self.awaiting_structured_followup = False
        self.auto_start_after_form = False
        self.dynamic_widgets = []
        self.selected_value = tk.IntVar(value=0)

        if load_dotenv is not None:
            load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)

        self.api_key = self.get_api_key()
        self.client = self.create_gemini_client()

        self.create_widgets()
        self.welcome_user()

    # -----------------------------
    # User memory and API setup
    # -----------------------------
    def get_api_key(self):
        return os.environ.get("GEMINI_API_KEY")

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
            "selected_restaurant": "",
            "last_generated_plan": "",
            "conversation_summary": "",
            "structured_request": {},
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
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Travel.TNotebook",
            background=self.colors["surface"],
            borderwidth=0,
        )
        style.configure(
            "Travel.TNotebook.Tab",
            font=("Microsoft JhengHei", 11),
            padding=(18, 9),
            background="#ffffff",
            foreground=self.colors["text"],
        )
        style.map(
            "Travel.TNotebook.Tab",
            background=[("selected", "#ffffff")],
            foreground=[("selected", self.colors["primary"])],
        )
        style.configure(
            "Travel.TCombobox",
            fieldbackground="#ffffff",
            background="#ffffff",
            foreground=self.colors["text"],
            padding=8,
        )

        shell = tk.Frame(self.root, bg=self.colors["surface"])
        shell.pack(fill=tk.BOTH, expand=True)

        sidebar = tk.Frame(shell, bg=self.colors["sidebar"], width=360, padx=24, pady=28)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        tk.Label(
            sidebar,
            text="旅遊基本資料",
            font=("Microsoft JhengHei", 18, "bold"),
            bg=self.colors["sidebar"],
            fg=self.colors["text"],
            anchor="w",
        ).pack(fill=tk.X, pady=(6, 20))

        self.destination_city_map = {
            "韓國": ["首爾", "釜山", "濟州", "大邱"],
            "日本": ["東京", "大阪", "京都", "福岡", "札幌", "沖繩"],
            "泰國": ["曼谷", "清邁", "普吉"],
            "越南": ["河內", "胡志明市", "峴港", "富國島"],
            "美國": ["洛杉磯", "紐約", "舊金山", "西雅圖", "拉斯維加斯"],
            "法國": ["巴黎", "尼斯", "里昂"],
            "義大利": ["羅馬", "米蘭", "威尼斯", "佛羅倫斯"],
            "香港": ["香港"],
            "新加坡": ["新加坡"],
            "印尼": ["峇里島", "雅加達"],
        }

        self.departure_var = tk.StringVar(value=self.user_profile.get("departure_city") or "台北")
        self.country_var = tk.StringVar(value=self.user_profile.get("destination_country") or "韓國")
        self.city_var = tk.StringVar(value=self.user_profile.get("destination_city") or "首爾")
        self.start_date_var = tk.StringVar()
        self.end_date_var = tk.StringVar()
        self.days_var = tk.IntVar(value=5)
        self.nights_var = tk.IntVar(value=4)
        self.people_var = tk.IntVar(value=2)
        self.transfer_var = tk.StringVar(value="只要直飛")
        self.flight_budget_var = tk.StringVar(value="8000")
        self.hotel_budget_var = tk.StringVar(value="4000")
        self.total_budget_var = tk.StringVar(value="80000")
        self.baggage_var = tk.StringVar(value="每人 1 件托運")

        self._add_sidebar_entry(sidebar, "出發地", self.departure_var)
        self.country_combo = self._add_sidebar_combo(
            sidebar,
            "目的國家",
            self.country_var,
            list(self.destination_city_map.keys()),
        )
        self.city_combo = self._add_sidebar_combo(
            sidebar,
            "目的城市",
            self.city_var,
            self.destination_city_map.get(self.country_var.get(), []),
        )
        self.country_combo.bind("<<ComboboxSelected>>", lambda event: self.update_city_options())

        date_row = tk.Frame(sidebar, bg=self.colors["sidebar"])
        date_row.pack(fill=tk.X, pady=(0, 12))
        self._add_inline_entry(date_row, "出發日", self.start_date_var, "YYYY-MM-DD")
        self._add_inline_entry(date_row, "回程日", self.end_date_var, "YYYY-MM-DD")

        number_row = tk.Frame(sidebar, bg=self.colors["sidebar"])
        number_row.pack(fill=tk.X, pady=(0, 12))
        self._add_spinbox(number_row, "天數", self.days_var, 1, 30)
        self._add_spinbox(number_row, "晚數", self.nights_var, 0, 30)
        self._add_spinbox(number_row, "人數", self.people_var, 1, 12)

        self._add_sidebar_combo(
            sidebar,
            "直飛 / 轉機",
            self.transfer_var,
            ["只要直飛", "可轉機一次", "可轉機兩次以上", "不限"],
        )
        self._add_sidebar_entry(sidebar, "每人機票預算 TWD", self.flight_budget_var)
        self._add_sidebar_entry(sidebar, "每晚住宿預算 TWD", self.hotel_budget_var)
        self._add_sidebar_entry(sidebar, "整趟總預算 TWD", self.total_budget_var)
        self._add_sidebar_combo(
            sidebar,
            "行李",
            self.baggage_var,
            ["無托運", "每人 1 件托運", "每人 2 件托運", "依航空公司規定"],
        )

        tk.Label(
            sidebar,
            text="旅行風格",
            font=("Microsoft JhengHei", 10),
            bg=self.colors["sidebar"],
            fg=self.colors["text"],
            anchor="w",
        ).pack(fill=tk.X, pady=(2, 6))
        self.style_text = tk.Text(
            sidebar,
            height=4,
            font=("Microsoft JhengHei", 11),
            bg="#ffffff",
            fg=self.colors["text"],
            relief=tk.FLAT,
            padx=12,
            pady=10,
            wrap=tk.WORD,
        )
        initial_style = self.user_profile.get("confirmed_style") or "未定"
        self.style_text.insert("1.0", initial_style if initial_style != "未定" else "美食、購物、拍照，不要太趕")
        self.style_text.pack(fill=tk.X, pady=(0, 16))

        self.form_go_button = tk.Button(
            sidebar,
            text="GO!",
            font=("Microsoft JhengHei", 12, "bold"),
            bg="#111827",
            activebackground="#1f2937",
            fg="white",
            activeforeground="white",
            relief=tk.FLAT,
            bd=0,
            pady=12,
            command=self.handle_form_go,
        )
        self.form_go_button.pack(fill=tk.X, pady=(0, 10))

        reset_button = tk.Button(
            sidebar,
            text="重置記憶",
            font=("Microsoft JhengHei", 10),
            bg="#ffffff",
            activebackground="#e5e7eb",
            fg=self.colors["text"],
            relief=tk.FLAT,
            bd=0,
            pady=10,
            command=self.reset_profile,
        )
        reset_button.pack(fill=tk.X)

        main = tk.Frame(shell, bg=self.colors["surface"], padx=44, pady=38)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            main,
            text="AI 協作式旅遊規劃平台",
            font=("Microsoft JhengHei", 30, "bold"),
            bg=self.colors["surface"],
            fg="#202124",
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 22))

        self.workflow_notebook = ttk.Notebook(main, style="Travel.TNotebook")
        self.workflow_notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_frames = {}
        self.option_panels = {}
        self.panel_placeholders = {}
        tab_specs = [
            ("flight", "航班", "航班推薦", "這裡之後會接 modules 裡的 flight recommender。"),
            ("hotel", "住宿", "住宿推薦", "完成航班選擇後，會依目的地與住宿預算媒合住宿。"),
            ("activity", "附近景點", "附近景點", "完成住宿後，會依住宿區域推薦附近景點與體驗。"),
            ("restaurant", "周邊美食", "景點周邊美食", "完成景點選擇後，會推薦周邊餐廳與在地美食。"),
            ("itinerary", "行程建議", "行程建議", "航班、住宿、景點與餐廳確認後，會產生完整行程。"),
        ]
        for key, tab_title, heading, placeholder in tab_specs:
            frame = tk.Frame(self.workflow_notebook, bg=self.colors["surface"])
            self.workflow_notebook.add(frame, text=tab_title)
            self.tab_frames[key] = frame

            content = tk.Frame(frame, bg=self.colors["surface"], padx=2, pady=28)
            content.pack(fill=tk.BOTH, expand=True)
            tk.Label(
                content,
                text=heading,
                font=("Microsoft JhengHei", 20, "bold"),
                bg=self.colors["surface"],
                fg=self.colors["text"],
                anchor="w",
            ).pack(fill=tk.X, pady=(0, 18))

            panel = tk.Frame(content, bg=self.colors["soft_blue"], padx=18, pady=14)
            panel.pack(fill=tk.X, anchor="n")
            placeholder_label = tk.Label(
                panel,
                text=placeholder,
                font=("Microsoft JhengHei", 11),
                bg=self.colors["soft_blue"],
                fg="#0f4c81",
                justify=tk.LEFT,
                anchor="w",
                wraplength=760,
            )
            placeholder_label.pack(fill=tk.X)
            self.panel_placeholders[key] = placeholder_label
            self.option_panels[key] = panel

        self.option_panel = self.option_panels["flight"]

        chat_card = tk.Frame(main, bg="#f8fafc", padx=12, pady=10)
        chat_card.pack(fill=tk.X, pady=(18, 0))

        tk.Label(
            chat_card,
            text="對話紀錄與補充指令",
            font=("Microsoft JhengHei", 11, "bold"),
            bg="#f8fafc",
            fg=self.colors["text"],
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 8))

        self.chat_history = scrolledtext.ScrolledText(
            chat_card,
            wrap=tk.WORD,
            height=8,
            font=("Microsoft JhengHei", 10),
            bg="#ffffff",
            fg=self.colors["text"],
            relief=tk.FLAT,
            bd=0,
            padx=12,
            pady=10,
        )
        self.chat_history.pack(fill=tk.X)
        self.chat_history.config(state=tk.DISABLED)

        self.chat_history.tag_config(
            "bot",
            background="#eef6ff",
            foreground=self.colors["text"],
            lmargin1=10,
            lmargin2=10,
            rmargin=80,
            spacing1=5,
            spacing3=7,
        )
        self.chat_history.tag_config(
            "user",
            background="#ecfdf5",
            foreground=self.colors["text"],
            justify=tk.RIGHT,
            lmargin1=80,
            lmargin2=80,
            rmargin=10,
            spacing1=5,
            spacing3=7,
        )
        self.chat_history.tag_config(
            "system",
            foreground=self.colors["muted"],
            justify=tk.CENTER,
            spacing1=4,
            spacing3=6,
        )

        input_card = tk.Frame(main, bg="#ffffff", padx=0, pady=10)
        input_card.pack(fill=tk.X)

        self.user_input = tk.Entry(
            input_card,
            font=("Microsoft JhengHei", 11),
            bg="#f3f4f6",
            fg=self.colors["text"],
            insertbackground=self.colors["primary"],
            relief=tk.FLAT,
        )
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=9, padx=(0, 8))
        self.user_input.bind("<Return>", lambda event: self.handle_send())

        self.send_button = tk.Button(
            input_card,
            text="發送",
            font=("Microsoft JhengHei", 10, "bold"),
            bg=self.colors["primary"],
            activebackground=self.colors["primary_dark"],
            fg="white",
            activeforeground="white",
            relief=tk.FLAT,
            bd=0,
            width=10,
            padx=6,
            pady=8,
            command=self.handle_send,
        )
        self.send_button.pack(side=tk.RIGHT)

    def _add_sidebar_label(self, parent, text):
        tk.Label(
            parent,
            text=text,
            font=("Microsoft JhengHei", 10),
            bg=self.colors["sidebar"],
            fg=self.colors["text"],
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 6))

    def _add_sidebar_entry(self, parent, label, variable):
        self._add_sidebar_label(parent, label)
        entry = tk.Entry(
            parent,
            textvariable=variable,
            font=("Microsoft JhengHei", 11),
            bg="#ffffff",
            fg=self.colors["text"],
            relief=tk.FLAT,
            insertbackground=self.colors["primary"],
        )
        entry.pack(fill=tk.X, ipady=9, pady=(0, 12))
        return entry

    def _add_sidebar_combo(self, parent, label, variable, values):
        self._add_sidebar_label(parent, label)
        combo = ttk.Combobox(
            parent,
            textvariable=variable,
            values=values,
            state="readonly",
            font=("Microsoft JhengHei", 11),
            style="Travel.TCombobox",
        )
        combo.pack(fill=tk.X, ipady=6, pady=(0, 12))
        return combo

    def _add_inline_entry(self, parent, label, variable, placeholder=""):
        block = tk.Frame(parent, bg=self.colors["sidebar"])
        block.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        tk.Label(
            block,
            text=label,
            font=("Microsoft JhengHei", 10),
            bg=self.colors["sidebar"],
            fg=self.colors["text"],
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 6))
        entry = tk.Entry(
            block,
            textvariable=variable,
            font=("Microsoft JhengHei", 10),
            bg="#ffffff",
            fg=self.colors["text"],
            relief=tk.FLAT,
            insertbackground=self.colors["primary"],
        )
        entry.insert(0, placeholder)
        entry.pack(fill=tk.X, ipady=8)
        entry.bind("<FocusIn>", lambda event, e=entry, p=placeholder: e.delete(0, tk.END) if e.get() == p else None)
        return entry

    def _add_spinbox(self, parent, label, variable, from_, to):
        block = tk.Frame(parent, bg=self.colors["sidebar"])
        block.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        tk.Label(
            block,
            text=label,
            font=("Microsoft JhengHei", 10),
            bg=self.colors["sidebar"],
            fg=self.colors["text"],
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 6))
        spin = tk.Spinbox(
            block,
            from_=from_,
            to=to,
            textvariable=variable,
            font=("Microsoft JhengHei", 10),
            bg="#ffffff",
            fg=self.colors["text"],
            relief=tk.FLAT,
            width=5,
        )
        spin.pack(fill=tk.X, ipady=7)
        return spin

    def update_city_options(self):
        cities = self.destination_city_map.get(self.country_var.get(), [])
        self.city_combo.config(values=cities)
        if cities:
            self.city_var.set(cities[0])

    def build_form_request_text(self):
        start_date = self.start_date_var.get().strip()
        end_date = self.end_date_var.get().strip()
        if start_date == "YYYY-MM-DD":
            start_date = ""
        if end_date == "YYYY-MM-DD":
            end_date = ""

        style_text = self.style_text.get("1.0", tk.END).strip()
        country = self.country_var.get().strip()
        city = self.city_var.get().strip()
        destination = f"{country} {city}".strip()

        return (
            f"出發地：{self.departure_var.get().strip()}\n"
            f"目的地：{destination}\n"
            f"出發日期：{start_date or '未填'}\n"
            f"回程日期：{end_date or '未填'}\n"
            f"旅遊天數：{self.days_var.get()} 天 {self.nights_var.get()} 晚\n"
            f"人數：{self.people_var.get()} 人\n"
            f"航班偏好：{self.transfer_var.get()}\n"
            f"每人機票預算：TWD {self.flight_budget_var.get().strip()}\n"
            f"每晚住宿預算：TWD {self.hotel_budget_var.get().strip()}\n"
            f"整趟總預算：TWD {self.total_budget_var.get().strip()}\n"
            f"行李：{self.baggage_var.get()}\n"
            f"旅行風格：{style_text or '未填'}"
        )

    def handle_form_go(self):
        request_text = self.build_form_request_text()
        self.user_say("使用左側表單開始規劃：\n" + request_text)

        country = self.country_var.get().strip()
        city = self.city_var.get().strip()
        destination = f"{country} {city}".strip()
        style_text = self.style_text.get("1.0", tk.END).strip() or "未定"

        self.user_profile["departure_city"] = self.departure_var.get().strip()
        self.user_profile["destination_country"] = country
        self.user_profile["destination_city"] = city
        self.user_profile["destination_text"] = destination
        self.user_profile["confirmed_style"] = style_text
        self.user_profile["last_trip_params"] = request_text
        self.save_user_profile()

        self.chat_stage = 3
        self.auto_start_after_form = True
        self.workflow_notebook.select(self.tab_frames["flight"])
        self.bot_say("已收到左側表單資訊，正在整理成查詢條件並準備搜尋航班。")
        self.set_generating_state(True)
        threading.Thread(target=self.generate_structured_trip_request, daemon=True).start()

    def bot_say(self, text):
        self.chat_history.config(state=tk.NORMAL)
        message = "🤖 Agent AI\n" + str(text).strip() + "\n\n"
        self.chat_history.insert(tk.END, message, "bot")
        self.chat_history.config(state=tk.DISABLED)
        self.chat_history.see(tk.END)

    def user_say(self, text):
        self.chat_history.config(state=tk.NORMAL)
        message = "👤 您\n" + str(text).strip() + "\n\n"
        self.chat_history.insert(tk.END, message, "user")
        self.chat_history.config(state=tk.DISABLED)
        self.chat_history.see(tk.END)

    def set_generating_state(self, generating):
        self.is_generating = generating
        state = tk.DISABLED if generating else tk.NORMAL
        self.send_button.config(state=state)
        self.user_input.config(state=state)
        if hasattr(self, "form_go_button"):
            self.form_go_button.config(state=state)

    def clear_dynamic_widgets(self):
        for widget in self.dynamic_widgets:
            widget.destroy()
        self.dynamic_widgets.clear()

    def reset_profile(self):
        if messagebox.askyesno("確認", "確定要清除本機記憶嗎？"):
            self.user_profile = self.default_profile()
            self.save_user_profile()
            self.clear_dynamic_widgets()
            if hasattr(self, "panel_placeholders"):
                for key, label in self.panel_placeholders.items():
                    if not label.winfo_manager():
                        label.pack(fill=tk.X)
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
            self.bot_say("⚠️ 尚未偵測到 Gemini API Key。請確認專案 .env 已設定 GEMINI_API_KEY。")

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
        elif category in ["activity", "restaurant"]:
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
                self.bot_say('好的，已沿用歷史目的地與風格。請一次告訴我：日期/天數/人數/直飛或可轉機/每人機票預算/每晚住宿預算/整趟總預算/行李。例如：2026/7/1-2026/7/7，7天，4人，可轉機一次，每人機票8000，每晚住宿3000，總預算80000，1件托運。')
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
            self.bot_say('風格已鎖定。請一次告訴我：日期/天數/人數/直飛或可轉機/每人機票預算/每晚住宿預算/整趟總預算/行李。例如：2026/7/1-2026/7/7，7天，4人，可轉機一次，每人機票8000，每晚住宿3000，總預算80000，1件托運。')
            self.chat_stage = 3
            return

        if self.chat_stage == 3:
            previous_params = self.user_profile.get("last_trip_params", "").strip()
            if self.awaiting_structured_followup and previous_params:
                self.user_profile["last_trip_params"] = previous_params + "\n補充資訊：" + text
            else:
                self.user_profile["last_trip_params"] = text
            self.awaiting_structured_followup = False
            self.save_user_profile()
            self.bot_say("正在將您的旅遊需求整理成結構化資料...")
            self.set_generating_state(True)
            threading.Thread(target=self.generate_structured_trip_request, daemon=True).start()
            return


        if self.chat_stage == 4:
            if text in ['確認', '確認，開始查航班', '開始查航班', '查航班', '好', '可以']:
                self.confirm_structured_request()
                return
            if text in ['修改', '我要修改', '重填', '更改']:
                self.revise_structured_request()
                return
            self.bot_say("請先點選『確認，開始查航班』或『我要修改』，也可以直接輸入：確認 / 修改。")
            return

        if self.chat_stage == 8:
            if self.client is None:
                self.bot_say("❌ Gemini Client 尚未初始化。請確認已安裝套件並設定 GEMINI_API_KEY。")
                return
            self.bot_say("收到您的微調需求，正在根據上一版企劃書重新調整...")
            self.set_generating_state(True)
            threading.Thread(target=self.get_final_itinerary_from_gemini, args=(text,), daemon=True).start()
            return

        self.bot_say("目前請先使用上方選單完成點選，或等待系統生成完成。")


    def _format_twd(self, value):
        if value is None or value == "":
            return "未指定"
        try:
            return f"TWD {float(value):,.0f}"
        except (TypeError, ValueError):
            return str(value)

    def format_structured_request_summary(self, structured_request):
        sr = structured_request or {}
        flight = sr.get("flight_preferences") or {}
        hotel = sr.get("hotel_preferences") or {}

        styles = sr.get("travel_style") or []
        if isinstance(styles, list):
            styles_text = "、".join(str(x) for x in styles) if styles else "未指定"
        else:
            styles_text = str(styles)

        if flight.get("prefer_direct") is True or flight.get("max_transfer_count") == 0:
            transfer_text = "只要直飛"
        elif flight.get("max_transfer_count") is not None:
            transfer_text = f"可接受最多轉機 {flight.get('max_transfer_count')} 次"
        else:
            transfer_text = flight.get("transfer_preference") or "不限直飛或轉機"


        def _to_float(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        people_count = _to_float(sr.get("people")) or 0
        nights_count = _to_float(sr.get("nights")) or 0
        flight_per_person = _to_float(flight.get("flight_budget_twd_per_person"))
        hotel_per_night = _to_float(hotel.get("hotel_budget_twd_per_night"))
        hotel_total_budget = _to_float(hotel.get("hotel_budget_twd_total"))
        total_budget = _to_float(sr.get("total_budget_twd") or sr.get("budget_twd"))
        estimated_flight_budget = flight_per_person * people_count if flight_per_person and people_count else None
        estimated_hotel_budget = hotel_total_budget or (hotel_per_night * nights_count if hotel_per_night and nights_count else None)
        estimated_known_budget = sum(x for x in [estimated_flight_budget, estimated_hotel_budget] if x is not None)
        estimated_remaining_budget = total_budget - estimated_known_budget if total_budget is not None else None

        lines = [
            "目前整理到的旅遊需求如下：",
            "",
            "【基本行程】",
            f"- 出發地：{sr.get('departure_city') or '未指定'}（{sr.get('departure_airport') or '機場未指定'}）",
            f"- 目的地：{sr.get('destination_country') or '未指定'} {sr.get('destination_city') or ''}（{sr.get('arrival_airport') or '機場未指定'}）",
            f"- 日期：{sr.get('start_date') or sr.get('start_date_text') or '未指定'} 至 {sr.get('end_date') or '未指定'}",
            f"- 天數 / 晚數：{sr.get('travel_days') or '未指定'} 天 / {sr.get('nights') or '未指定'} 晚",
            f"- 人數：{sr.get('people') or '未指定'} 人",
            "",
            "【航班需求】",
            f"- 直飛 / 轉機：{transfer_text}",
            f"- 偏好出發時段：{flight.get('preferred_departure_time') or '不限'}",
            f"- 每人機票預算：{self._format_twd(flight.get('flight_budget_twd_per_person'))}",
            f"- 行李需求：{sr.get('baggage') or '未指定'}",
            "",
            "【住宿需求】",
            f"- 偏好區域：{hotel.get('preferred_area') or '未指定'}",
            f"- 房型需求：{hotel.get('room_type') or '未指定'}",
            f"- 是否近車站：{hotel.get('near_station') if hotel.get('near_station') is not None else '未指定'}",
            f"- 每晚住宿預算：{self._format_twd(hotel.get('hotel_budget_twd_per_night'))}",
            f"- 住宿總預算：{self._format_twd(hotel.get('hotel_budget_twd_total'))}",
            "",
            "【整體偏好與預算】",
            f"- 旅行風格：{styles_text}",
            f"- 步調偏好：{sr.get('preferred_pace') or '未指定'}",
            f"- 整趟總預算：{self._format_twd(sr.get('total_budget_twd') or sr.get('budget_twd'))}",
            f"- 機票預算小計：{self._format_twd(estimated_flight_budget)}",
            f"- 住宿預算小計：{self._format_twd(estimated_hotel_budget)}",
            f"- 扣除機票與住宿後預估剩餘：{self._format_twd(estimated_remaining_budget)}",
            f"- 其他備註：{sr.get('special_notes') or '無'}",
            "",
            "資料確認完整後，我會依照以上條件查詢航班。",
        ]
        return "\n".join(lines)

    def missing_field_label(self, field):
        labels = {
            "departure_city": "出發城市",
            "departure_airport": "出發機場",
            "destination_country": "目的地國家",
            "destination_city": "目的地城市",
            "arrival_airport": "抵達機場",
            "start_date": "出發日期",
            "end_date": "回程日期",
            "travel_days": "旅行天數",
            "nights": "住宿晚數",
            "people": "人數",
            "budget_twd": "預算",
            "total_budget_twd": "整趟總預算",
            "travel_style": "旅行風格",
            "baggage": "行李需求",
            "flight_transfer_preference": "直飛或轉機偏好",
            "flight_budget_twd_per_person": "每人機票預算",
            "hotel_budget": "住宿預算",
        }
        return labels.get(field, field)

    def format_missing_fields_message(self, missing_fields):
        labels = []
        seen = set()
        for field in missing_fields or []:
            label = self.missing_field_label(field)
            if label not in seen:
                labels.append(label)
                seen.add(label)

        if not labels:
            return "目前還缺少一些必要資訊，請補充目的地、日期、人數、預算或行李等需求。"

        lines = ["目前還缺這些資訊："]
        lines.extend(f"- {label}" for label in labels)
        lines.append("請直接補充以上項目，我會保留前面已經整理好的內容。")
        return "\n".join(lines)

    def render_requirement_confirmation(self):
        self.clear_dynamic_widgets()
        if hasattr(self, "workflow_notebook"):
            self.workflow_notebook.select(self.tab_frames["flight"])
            self.option_panel = self.option_panels["flight"]
            self.panel_placeholders["flight"].pack_forget()

        note = tk.Label(
            self.option_panel,
            text="請確認以下需求是否正確：",
            font=("Microsoft JhengHei", 10, "bold"),
            bg=self.colors["soft_blue"],
            anchor="w",
            justify=tk.LEFT,
        )
        note.pack(fill=tk.X, anchor="w", pady=(4, 6))
        self.dynamic_widgets.append(note)

        button_frame = tk.Frame(self.option_panel, bg=self.colors["soft_blue"])
        button_frame.pack(fill=tk.X, anchor="w", pady=(0, 6))
        self.dynamic_widgets.append(button_frame)

        confirm_btn = tk.Button(
            button_frame,
            text="確認，開始查航班",
            font=("Microsoft JhengHei", 9, "bold"),
            bg="#0084ff",
            fg="white",
            padx=12,
            pady=4,
            command=self.confirm_structured_request,
        )
        confirm_btn.pack(side=tk.LEFT, padx=(0, 8))

        revise_btn = tk.Button(
            button_frame,
            text="我要修改",
            font=("Microsoft JhengHei", 9, "bold"),
            bg="#6c757d",
            fg="white",
            padx=12,
            command=self.revise_structured_request,
        )
        revise_btn.pack(side=tk.LEFT)

    def confirm_structured_request(self, silent=False):
        self.clear_dynamic_widgets()
        if not silent:
            self.user_say("確認，開始查航班")
        if hasattr(self, "workflow_notebook"):
            self.workflow_notebook.select(self.tab_frames["flight"])
        self.bot_say("好的，正在使用航班推薦系統查詢實際航班選項...")
        self.chat_stage = 4
        self.set_generating_state(True)
        threading.Thread(target=self.get_flight_options_from_recommender, daemon=True).start()

    def revise_structured_request(self):
        self.clear_dynamic_widgets()
        self.auto_start_after_form = False
        self.user_say("我要修改")
        self.awaiting_structured_followup = True
        self.chat_stage = 3
        self.bot_say(
            "好的，請直接輸入要修改或補充的內容。例如：改成只要直飛、每人機票預算提高到 12000、住宿每晚改 4000、總預算改 90000。"
        )

    def generate_structured_trip_request(self):
        raw_request = {
            "destination_text": self.user_profile.get("destination_text", ""),
            "confirmed_style": self.user_profile.get("confirmed_style", ""),
            "last_trip_params": self.user_profile.get("last_trip_params", ""),
            "conversation_summary": self.user_profile.get("conversation_summary", ""),
            "previous_structured_request": self.user_profile.get("structured_request", {}),
        }

        try:
            result = generate_trip_info(raw_request)
        except Exception as e:
            result = {
                "module": "trip_info_generator",
                "status": "error",
                "structured_request": {},
                "missing_fields": [],
                "message": str(e),
            }

        self.root.after(0, lambda: self.finish_structured_trip_request(result))

    def finish_structured_trip_request(self, result):
        self.set_generating_state(False)

        status = result.get("status", "error")
        structured_request = result.get("structured_request") or {}
        missing_fields = result.get("missing_fields") or []
        message = result.get("message", "")

        if status == "success":
            self.awaiting_structured_followup = False
            self.user_profile["structured_request"] = structured_request
            self.save_user_profile()
            self.chat_stage = 4
            pretty_json = json.dumps(structured_request, ensure_ascii=False, indent=2)
            print("structured_request:")
            print(pretty_json)
            self.bot_say(self.format_structured_request_summary(structured_request))
            if self.auto_start_after_form:
                self.auto_start_after_form = False
                self.bot_say("資料完整，正在進入航班分頁並開始查詢。")
                self.confirm_structured_request(silent=True)
                return
            self.bot_say("請確認以下需求是否正確：")
            self.render_requirement_confirmation()
            return

        if status == "need_more_info":
            self.awaiting_structured_followup = True
            if structured_request:
                self.user_profile["structured_request"] = structured_request
                self.save_user_profile()
            self.chat_stage = 3
            if structured_request:
                self.bot_say(self.format_structured_request_summary(structured_request))
            if missing_fields:
                self.bot_say(self.format_missing_fields_message(missing_fields))
            else:
                self.bot_say(
                    "目前資訊還不完整："
                    + (message or "請再補充目的地、日期、人數、預算或行李等需求。")
                )
            return

        self.chat_stage = 3
        self.awaiting_structured_followup = True
        self.auto_start_after_form = False
        self.bot_say(f"❌ 需求整理失敗：{message or '未知錯誤'}")

    def get_flight_options_from_recommender(self):
        try:
            structured_request = self.user_profile.get("structured_request", {})
            result = recommend_flight_options(structured_request)
        except Exception as e:
            result = {
                "module": "flight_recommender",
                "status": "error",
                "options": [],
                "message": str(e),
            }

        self.root.after(0, lambda: self.finish_flight_recommendation(result))

    def finish_flight_recommendation(self, result):
        status = result.get("status", "error")
        if status == "success":
            self.render_dynamic_options(
                "flight",
                {
                    "description": "以下是根據你的日期、機場與預算查到的航班推薦：",
                    "options": result.get("options", []),
                },
            )
            return

        self.set_generating_state(False)
        message = result.get("message", "航班推薦失敗。")
        if status == "need_more_info":
            self.bot_say(f"目前還不能查航班：{message}")
        else:
            self.bot_say(f"❌ 航班推薦失敗：{message}")
            self.bot_say("如果要調整條件，請輸入「修改」，例如提高每人機票預算、改成可轉機，或換日期。")

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
        if category in ["hotel", "activity", "restaurant"]:
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
            self.bot_say("住宿選擇成功！正在為您挑選住宿附近的【景點 / 體驗選單】...")
            self.set_generating_state(True)
            threading.Thread(target=self.get_json_options_from_gemini, args=("activity",), daemon=True).start()

        elif category == "activity":
            self.user_profile["selected_activity"] = chosen_text
            self.save_user_profile()
            self.chat_stage = 7
            self.bot_say("景點選擇成功！正在為您挑選景點周邊的【餐廳 / 美食選單】...")
            self.set_generating_state(True)
            threading.Thread(target=self.get_json_options_from_gemini, args=("restaurant",), daemon=True).start()

        elif category == "restaurant":
            self.user_profile["selected_restaurant"] = chosen_text
            self.save_user_profile()
            self.chat_stage = 8
            if hasattr(self, "workflow_notebook"):
                self.workflow_notebook.select(self.tab_frames["itinerary"])
            self.bot_say("所有元件挑選完畢！正在為您生成最終版的【全球自由行完整企劃書】...")
            self.set_generating_state(True)
            threading.Thread(target=self.get_final_itinerary_from_gemini, daemon=True).start()

    # -----------------------------
    # Gemini structured option generation
    # -----------------------------
    def build_hotel_recommender_state(self):
        structured_request = self.user_profile.get("structured_request") or {}
        selected_flight = self.user_profile.get("selected_flight", "")
        return {
            "structured_request": structured_request,
            "selected": {
                "flight": {
                    "title": "已選航班",
                    "detail": selected_flight,
                }
            },
        }

    def get_hotel_options_from_module(self):
        try:
            result = recommend_hotel_options(self.build_hotel_recommender_state())
            status = result.get("status", "error")
            if status != "success":
                raise RuntimeError(result.get("message", "住宿推薦失敗。"))

            json_data = {
                "description": result.get("description")
                or "以下是根據你的住宿預算、偏好區域與旅遊條件產生的住宿推薦：",
                "options": result.get("options", []),
            }
            self.root.after(0, lambda: self.render_dynamic_options("hotel", json_data))
        except Exception as e:
            self.root.after(0, lambda: self.finish_error(f"產生住宿選單失敗: {e}"))

    def build_attraction_user_profile(self):
        structured_request = self.user_profile.get("structured_request") or {}
        selected_hotel = self.user_profile.get("selected_hotel", "")
        styles = structured_request.get("travel_style") or []
        if isinstance(styles, list):
            style_text = "、".join(str(item) for item in styles if item)
        else:
            style_text = str(styles or "")
        destination = " ".join(
            part
            for part in [
                structured_request.get("destination_country"),
                structured_request.get("destination_city"),
            ]
            if part
        ).strip()
        return {
            "departure": structured_request.get("departure_city") or "",
            "destination": destination,
            "days": structured_request.get("travel_days") or "",
            "budget": structured_request.get("total_budget_twd") or structured_request.get("budget_twd") or "",
            "style": f"{style_text}；已選住宿：{selected_hotel}" if selected_hotel else style_text,
        }

    def normalize_attraction_options(self, attractions, destination):
        options = []
        for idx, item in enumerate((attractions or [])[:6], start=1):
            if not isinstance(item, dict):
                continue
            title = item.get("name") or item.get("title") or f"景點 {idx}"
            tags = item.get("tags") if isinstance(item.get("tags"), list) else []
            tags_text = "、".join(str(tag) for tag in tags if tag)
            duration_hours = item.get("duration_hours")
            if isinstance(duration_hours, (int, float)):
                duration_text = f"約 {duration_hours:g} 小時"
            else:
                duration_text = str(item.get("duration") or duration_hours or "")

            detail_lines = []
            if item.get("area"):
                detail_lines.append(f"區域：{item.get('area')}")
            if tags_text:
                detail_lines.append(f"特色：{tags_text}")
            if item.get("rating"):
                detail_lines.append(f"評分參考：{item.get('rating')}")
            if duration_text:
                detail_lines.append(f"建議停留：{duration_text}")
            if item.get("best_time"):
                detail_lines.append(f"適合時段：{item.get('best_time')}")
            if item.get("indoor_outdoor"):
                detail_lines.append(f"空間類型：{item.get('indoor_outdoor')}")
            if item.get("rain_friendly"):
                detail_lines.append("雨天適合：是")
            if item.get("description"):
                detail_lines.append(str(item.get("description")))
            if item.get("detail"):
                detail_lines.append(str(item.get("detail")))

            options.append({
                "id": idx,
                "title": title,
                "detail": "\n".join(detail_lines),
                "reason": item.get("why_recommended") or item.get("description") or "符合目的地、住宿位置與旅行風格。",
                "area": item.get("area") or "",
                "map_query": f"{destination} {title}".strip(),
                "main_category": item.get("main_category") or "",
                "tags": tags,
                "indoor_outdoor": item.get("indoor_outdoor") or "",
                "rain_friendly": bool(item.get("rain_friendly")),
                "rain_backup": item.get("rain_backup") or "",
                "duration_hours": item.get("duration_hours"),
            })
        return options

    def get_activity_options_from_module(self):
        try:
            user_profile = self.build_attraction_user_profile()
            attractions = get_attractions(user_profile)
            options = self.normalize_attraction_options(
                attractions,
                user_profile.get("destination") or "",
            )

            json_data = {
                "description": "以下是根據目的地、住宿位置與旅行風格產生的附近景點推薦：",
                "options": options,
            }
            self.root.after(0, lambda: self.render_dynamic_options("activity", json_data))
        except Exception as e:
            self.root.after(0, lambda: self.finish_error(f"產生景點選單失敗: {e}"))

    def build_restaurant_user_profile(self):
        structured_request = self.user_profile.get("structured_request") or {}
        styles = structured_request.get("travel_style") or []
        if isinstance(styles, list):
            style_text = "、".join(str(item) for item in styles if item)
        else:
            style_text = str(styles or "")
        destination = " ".join(
            part
            for part in [
                structured_request.get("destination_country"),
                structured_request.get("destination_city"),
            ]
            if part
        ).strip()
        selected_activity = self.user_profile.get("selected_activity", "")
        attraction_name = selected_activity.split(" (", 1)[0].strip() if selected_activity else ""
        attraction_pool = []
        if attraction_name:
            attraction_pool.append({
                "name": attraction_name,
                "area": destination,
                "categories": ["已選景點"],
            })
        return {
            "destination_text": f"{structured_request.get('departure_city') or ''} 出發，前往 {destination}".strip(),
            "travel_days": structured_request.get("travel_days") or 3,
            "confirmed_style": style_text or self.user_profile.get("confirmed_style", ""),
            "selected_hotel": self.user_profile.get("selected_hotel", ""),
            "attraction_pool": attraction_pool,
        }

    def dining_plan_to_single_option(self, dining_plan):
        lines = []
        for day in dining_plan.get("days", []):
            lines.append(f"Day {day.get('day_number')}：{day.get('day_theme', '')}")
            for meal_key, meal_label in [
                ("breakfast_options", "早餐"),
                ("lunch_options", "午餐"),
                ("dinner_options", "晚餐"),
            ]:
                options = day.get(meal_key) or []
                names = " / ".join(
                    str(item.get("title", ""))
                    for item in options
                    if isinstance(item, dict) and item.get("title")
                )
                if names:
                    lines.append(f"{meal_label}候選：{names}")
        return {
            "id": 1,
            "title": "完整餐飲規劃",
            "detail": "\n".join(lines) or dining_plan.get("overall_description", ""),
            "raw": dining_plan,
        }

    def get_restaurant_options_from_module(self):
        try:
            dining_plan = get_dining_plan(self.build_restaurant_user_profile())
            json_data = {
                "description": dining_plan.get("overall_description")
                or "以下是依照已選住宿與景點產生的完整餐飲規劃：",
                "options": [self.dining_plan_to_single_option(dining_plan)],
            }
            self.root.after(0, lambda: self.render_dynamic_options("restaurant", json_data))
        except Exception as e:
            self.root.after(0, lambda: self.finish_error(f"產生餐飲規劃失敗: {e}"))

    def get_json_options_from_gemini(self, category):
        try:
            if category == "hotel":
                self.get_hotel_options_from_module()
                return
            if category == "activity":
                self.get_activity_options_from_module()
                return
            if category == "restaurant":
                self.get_restaurant_options_from_module()
                return

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

STRUCTURED_REQUEST_SUMMARY
{self.format_structured_request_summary(self.user_profile.get('structured_request', {}))}



【已選航班】
{self.user_profile.get('selected_flight', '')}

【已選飯店】
{self.user_profile.get('selected_hotel', '')}

【已選景點】
{self.user_profile.get('selected_activity', '')}

如果類別是 flight，請根據出發地與目的地，推薦 3 個合理國際或國內航班選項。detail 必須包含出發機場、抵達機場、航空公司、是否轉機、時間帶與機場代碼，但航班選擇不需要觸發地圖。
如果類別是 hotel，請根據目的地城市、每晚住宿預算、住宿總預算與偏好區域推薦 3 個住宿區域或飯店。title 必須是精確飯店名稱或區域名稱，detail 必須包含城市、區域、特色、是否符合住宿預算與大約每晚價格。
如果類別是 activity，請根據已選住宿、目的地與旅行風格推薦 3 個附近景點或在地體驗，不要混入餐廳。title 必須是可被 Google Maps 搜尋到的精確名稱，detail 必須包含地區、適合原因、預估停留時間與注意事項。
如果類別是 restaurant，請根據已選景點、住宿位置與旅行風格推薦 3 個景點周邊餐廳或在地美食。title 必須是可被 Google Maps 搜尋到的精確餐廳名稱，detail 必須包含地區、特色菜、適合原因、預估價格與是否需訂位。
"""

            response = self.client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "你是一個全球自由行旅遊規劃元件篩選專家。"
                        "請嚴格輸出符合 Schema 結構的 JSON 數據，不要有額外聊天字眼。"
                        "選項內容必須符合使用者指定的目的地，不可固定為日本或東京。"
                        "hotel、activity 與 restaurant 的 title 請使用精確真實名稱，以利 Google Maps 搜尋；flight 可使用航空公司與航班資訊。"
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
        panel_key = category if category in self.option_panels else "flight"
        self.option_panel = self.option_panels.get(panel_key, self.option_panel)
        if hasattr(self, "workflow_notebook") and panel_key in self.tab_frames:
            self.workflow_notebook.select(self.tab_frames[panel_key])
            self.panel_placeholders[panel_key].pack_forget()
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
                bg=self.colors["soft_blue"],
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

【已選景點 / 體驗】
{self.user_profile.get('selected_activity', '')}

【已選餐廳 / 美食】
{self.user_profile.get('selected_restaurant', '')}

【核心風格偏好】
{self.user_profile.get('confirmed_style', '')}

【日期、天數、預算與行李參數】
{self.user_profile.get('last_trip_params', '')}

STRUCTURED_REQUEST_SUMMARY
{self.format_structured_request_summary(self.user_profile.get('structured_request', {}))}


"""

            system_instruction = """
你是一位全球自由行旅遊規劃專家，熟悉不同國家城市的交通、住宿區域、景點餐廳、文化注意事項與旅遊風險。
請根據使用者的目的地、預算、天數、旅行風格，以及已點選的航班、飯店、景點/體驗與餐廳，生成一份高質感且實用的完整行程企劃書。
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
                model="gemini-2.5-flash-lite",
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
            f"景點/體驗：{self.user_profile.get('selected_activity', '')}；"
            f"餐廳/美食：{self.user_profile.get('selected_restaurant', '')}"
        )
        self.save_user_profile()
        self.chat_stage = 8
        if hasattr(self, "workflow_notebook"):
            self.workflow_notebook.select(self.tab_frames["itinerary"])
            panel = self.option_panels["itinerary"]
            self.option_panel = panel
            self.panel_placeholders["itinerary"].pack_forget()
            self.clear_dynamic_widgets()
            plan_box = scrolledtext.ScrolledText(
                panel,
                wrap=tk.WORD,
                height=18,
                font=("Microsoft JhengHei", 10),
                bg="#ffffff",
                fg=self.colors["text"],
                relief=tk.FLAT,
                padx=12,
                pady=10,
            )
            plan_box.insert(tk.END, result_text)
            plan_box.config(state=tk.DISABLED)
            plan_box.pack(fill=tk.BOTH, expand=True)
            self.dynamic_widgets.append(plan_box)
        self.bot_say(result_text)
        self.bot_say("✨ 您的全球自由行企劃書已生成！若有任何不滿意，例如行程太滿、想降低預算、想換城市或想增加購物，您可以直接在下方輸入微調要求。")

    def finish_error(self, err_msg):
        self.set_generating_state(False)
        self.bot_say(f"❌ {err_msg}")


if __name__ == "__main__":
    root = tk.Tk()
    app = GeminiAdaptiveTravelAgentGUI(root)
    root.mainloop()
