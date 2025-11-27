import json
import os
import requests

def process_task(event_id):
    """
    使用 Python requests 庫取得 API 資料，解析 JSON，並回傳分析結果。
    """

    # =========================================================
    # 1. 設定 Token (從同目錄下的 token.txt 讀取)
    # =========================================================
    current_dir = os.path.dirname(os.path.abspath(__file__))
    token_file_path = os.path.join(current_dir, 'token.txt')

    if not os.path.exists(token_file_path):
        return "錯誤: 找不到 token.txt，請先執行 python manage.py create_auth_token"

    AUTHORIZE_TOKEN = ""
    try:
        with open(token_file_path, 'r', encoding='utf-8') as f:
            # 讀取非空行，並移除前後空白
            lines = [line.strip() for line in f.readlines() if line.strip()]

        if not lines:
            return "錯誤: token.txt 檔案內容為空。"
        
        # 取得最後一行作為 Token
        AUTHORIZE_TOKEN = lines[-1]

    except Exception as e:
        return f"讀取 Token 檔案時發生錯誤: {str(e)}"

    # =========================================================
    # 2. 設定 API URL 與 發送請求
    # =========================================================
    
    # 請確認您的 Port 是 9048 或 9046
    PORT = "9048" 
    HOST = "lsap2.lu.im.ntu.edu.tw"
    # 0 是 Project ID
    api_url = f'http://{HOST}:{PORT}/api/canonical/0/events/{event_id}/'

    # 設定 Headers (優先嘗試 Bearer)
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {AUTHORIZE_TOKEN}"
    }

    try:
        # 發送 GET 請求 (Timeout 設為 30秒)
        response = requests.get(api_url, headers=headers, timeout=30)

        # 檢查 401 (若失敗，可考慮在此處自動切換成 Token header 重試，目前先報錯)
        if response.status_code != 200:
            return (
                f"API 請求失敗 (HTTP {response.status_code})\n"
                f"URL: {api_url}\n"
                f"回應: {response.text[:200]}"
            )

        # 解析 JSON
        try:
            api_data = response.json()
        except json.JSONDecodeError:
            return f"無法解析 API 回傳資料: {response.text[:100]}..."

        # =========================================================
        # 3. 資料解析與提取
        # =========================================================

        # A. 提取錯誤標題
        error_headline = "Unknown Error"
        try:
            exception_values = api_data.get('data', {}).get('exception', {}).get('values', [])
            if exception_values:
                data = exception_values[0]
                error_headline = f"{data.get('type', 'Error')}: {data.get('value', 'No message')}"
            else:
                error_headline = api_data.get('title', '無法解析錯誤標題')
        except (IndexError, AttributeError):
            error_headline = "無法解析錯誤標題"

        # B. 提取 Stacktrace MD
        stacktrace_content = api_data.get('stacktrace_md', '(未提供 Stacktrace)')

        # C. 提取環境資訊
        runtime_info = "Unknown Environment"
        try:
            runtime = api_data.get('data', {}).get('contexts', {}).get('runtime', {})
            runtime_info = f"{runtime.get('name', 'Python')} {runtime.get('version', '')}"
        except AttributeError:
            pass

        # D. 組合分析內容
        ai_context = (
            f"【錯誤摘要】: {error_headline}\n"
            f"【執行環境】: {runtime_info}\n"
            f"【詳細堆疊追蹤】:\n{stacktrace_content}"
        )

    except requests.exceptions.RequestException as e:
        return f"連線發生錯誤: {str(e)}"
    except Exception as e:
        return f"資料處理發生錯誤: {str(e)}"

    # =========================================================
    # 4. 回傳結果
    # =========================================================
    return f"Gemini 分析報告 (Requests 成功):\n\n{ai_context}"

''' old version for test
# issues/useAPI.py
from events.models import Event 
# 假設您需要從這裡自己撈資料，或者您可以 import 其他任何需要的模組

def process_task(event_id):
    """
    這是 View 唯一呼叫的接口。
    """
    
    # 1. 在這裡自己決定怎麼取得資料 (符合您的需求)
    # 例如：
    try:
        event = Event.objects.get(pk=event_id)
        raw_data = event.data  # 取得 JSON 資料
        error_message = event.title()
    except Event.DoesNotExist:
        return "找不到該 Event 資料 (由 useAPI 回報)"

    # 2. 在這裡呼叫 Gemini 或做任何您想做的事
    # ... 呼叫 AI 的邏輯 ...
    ai_result = f"useAPI 已經收到 ID: {event_id}。錯誤訊息是：{error_message}。Gemini 分析結果..."

    return ai_result
'''
