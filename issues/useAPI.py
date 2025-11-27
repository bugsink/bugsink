import json
import os
import requests  # 使用 requests 函式庫 (Django 環境通常預設都有)
# import google.generativeai as genai

def process_task(event_id):
    """
    使用 Python requests 庫取得 API 資料 (替代 curl)，解析特定 JSON 格式，並回傳 Gemini 分析結果。
    解決 [Errno 2] No such file or directory: 'curl' 問題。
    """

    # =========================================================
    # 1. 設定 Token (從檔案讀取)
    # =========================================================
    # 設定 token 檔案路徑: 抓取當前檔案位置的同一層目錄下的 token.txt
    current_dir = os.path.dirname(os.path.abspath(__file__))
    token_file_path = os.path.join(current_dir, 'token.txt')

    if not os.path.exists(token_file_path):
        return "Please make an authorize token first (Token file not found)"

    try:
        with open(token_file_path, 'r', encoding='utf-8') as f:
            # 讀取所有行，去除空白行
            lines = [line.strip() for line in f.readlines() if line.strip()]

        if not lines:
            return "Token file is empty"
        # 取得最後一行作為最新的 Token
        AUTHORIZE_TOKEN = lines[-1]

    except Exception as e:
        return f"讀取 Token 檔案時發生錯誤: {str(e)}"

    # =========================================================
    # 2. 設定 URL 與 發送請求
    # =========================================================

    # 假設 0 是 Project ID
    api_url = f'http://lsap2.lu.im.ntu.edu.tw:9048/api/canonical/0/events/{event_id}/'

    # 使用 requests 設定 Headers
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {AUTHORIZE_TOKEN}"
    }

    try:
        # 發送 GET 請求 (等同於 curl -X GET ...)
        # timeout=10 避免請求卡死
        response = requests.get(api_url, headers=headers, timeout=60)
        
        # 檢查 HTTP 狀態碼
        if response.status_code != 200:
            return f"API 請求失敗 (HTTP {response.status_code}): {response.text[:200]}"

        # 取得 JSON 資料
        try:
            api_data = response.json()
        except json.JSONDecodeError:
            return f"無法解析 API 回傳資料: {response.text[:100]}..."

        # =========================================================
        # 3. 資料解析
        # =========================================================

        # A. 提取核心錯誤標題
        error_headline = "Unknown Error"
        try:
            exception_data = api_data.get('data', {}).get('exception', {}).get('values', [])[0]
            err_type = exception_data.get('type', 'Error')
            err_value = exception_data.get('value', 'No message')
            error_headline = f"{err_type}: {err_value}"
        except (IndexError, AttributeError):
            error_headline = "無法解析錯誤標題"

        # B. 提取 Stacktrace MD
        stacktrace_content = api_data.get('stacktrace_md', '(未提供 Stacktrace)')

        # C. 提取環境資訊
        runtime_info = "Unknown Environment"
        try:
            runtime = api_data.get('data', {}).get('contexts', {}).get('runtime', {})
            r_name = runtime.get('name', 'Python')
            r_version = runtime.get('version', '')
            runtime_info = f"{r_name} {r_version}"
        except AttributeError:
            pass

        # D. 組合給 Gemini 的 Prompt 資料
        ai_context = (
            f"【錯誤摘要】: {error_headline}\n"
            f"【執行環境】: {runtime_info}\n"
            f"【詳細堆疊追蹤 (Stacktrace)】:\n"
            f"{stacktrace_content}"
        )

    except requests.exceptions.RequestException as e:
        return f"連線發生錯誤: {str(e)}"
    except Exception as e:
        return f"資料處理發生錯誤: {str(e)}"

    # =========================================================
    # 4. 呼叫 Gemini
    # =========================================================

    # ---------------------------------------------------------
    # 這裡填入你的 Gemini 呼叫邏輯
    # ---------------------------------------------------------
    # try:
    #     genai.configure(api_key="你的_GEMINI_API_KEY")
    #     model = genai.GenerativeModel('gemini-pro')
    #     prompt = f"你是一個資深的 Python 工程師。請根據以下錯誤資訊，分析原因並給出具體的程式碼修正建議：\n\n{ai_context}"
    #     response = model.generate_content(prompt)
    #     return response.text
    # except Exception as e:
    #     return f"Gemini 分析失敗: {str(e)}"

    return f"Gemini 分析報告 (Requests 版本):\n\n收到資料，準備分析...\n\n{ai_context}"
'''
    try:
        event = Event.objects.get(pk=event_id)
        raw_data = event.data  # 取得 JSON 資料
        error_message = event.title()
    except Event.DoesNotExist:
        ai_result = "useAPI 中出錯 !!!"
        return ai_result

    ai_result = f"useAPI 已經收到 ID: {event_id}。錯誤訊息是：{error_message}。Gemini 分析結果..."

    return ai_result
'''
