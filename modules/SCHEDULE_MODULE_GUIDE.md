# Schedule 模組串接說明

`schedule_module.py` 負責接收前置模組資料，呼叫 Gemini 編排每日行程，並填入 `itinerary["schedule"]`。

## 安裝

```powershell
pip install google-genai pydantic
```

## 離線檢查輸入格式

不需要 API Key：

```powershell
python .\schedule_module.py .\mock_itinerary_input.json --validate-only
```

## 呼叫 Gemini 生成行程

```powershell
$env:GEMINI_API_KEY="你的 API Key"
python .\schedule_module.py .\mock_itinerary_input.json -o .\generated_itinerary.json
```

## 讓其他模組呼叫

```python
from schedule_module import generate_itinerary

result = generate_itinerary(itinerary)
schedule = result["schedule"]
```

## 輸入約定

前置模組需要提供：

- `plan.days`：旅遊天數，正整數。
- `flights`：至少一筆，內容需包含抵達與離境機場資訊。
- `hotels`：至少一筆。
- `attractions`：可為空陣列。
- `restaurants`：可為空陣列。

生成結果的抵達日與離境日一定會包含 `airport_transfer`。無法即時確認的票價、空房和營業時間會放在 `notes`。
