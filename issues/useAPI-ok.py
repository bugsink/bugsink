import json
import os
import subprocess

def process_task(event_id):
    """
    使用系統 curl 指令取得 API 資料，解析 JSON，並回傳分析結果。
    """

    # =========================================================
    # 1. 設定 Token (從同目錄下的 token.txt 讀取)
    # =========================================================
    current_dir = os.path.dirname(os.path.abspath(__file__))
    token_file_path = os.path.join(current_dir, 'token.txt')

    if not os.path.exists(token_file_path):
        return "錯誤: 找不到 token.txt，請先生成token"

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
    # 2. 設定 API URL 與 執行 Curl
    # =========================================================
    
    # 設定目標
    PORT = "9048" 
    HOST = "lsap2.lu.im.ntu.edu.tw"
    # 0 是 Project ID
    api_url = f'http://{HOST}:{PORT}/api/canonical/0/events/{event_id}/'

    # 建構 Curl 指令 (使用 List 傳遞參數較安全)
    # -s: Silent mode (不顯示進度條)
    curl_command = [
        "curl", 
        "-X", "GET", 
        api_url,
        "-H", "accept: application/json",
        "-H", f"Authorization: Bearer {AUTHORIZE_TOKEN}",
        "-s"
    ]

    try:
        # 執行指令
        # capture_output=True: 抓取 stdout/stderr
        # text=True: 自動將 bytes 轉為字串
        # check=True: 若回傳碼非 0 (錯誤) 則拋出 CalledProcessError
        result = subprocess.run(curl_command, capture_output=True, text=True, check=True)
        
        json_output = result.stdout

        # 檢查是否為空回應
        if not json_output:
            return "錯誤: Curl 回傳內容為空 (Empty Response)"

        # 解析 JSON
        try:
            api_data = json.loads(json_output)
        except json.JSONDecodeError:
            # 有時候 Curl 可能回傳 HTML 錯誤頁面而非 JSON
            return f"無法解析 API 回傳資料 (非 JSON 格式):\n{json_output[:200]}..."

        # =========================================================
        # 3. 資料解析與提取
        # =========================================================

        # ** 成功讀取確認 **
        print(f"成功讀取 Event ID: {event_id}")

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

    except subprocess.CalledProcessError as e:
        # Curl 指令執行失敗 (例如連不到主機)
        return f"Curl 指令執行失敗 (Exit Code {e.returncode}):\n{e.stderr}"
    except Exception as e:
        return f"資料處理發生錯誤: {str(e)}"

    # =========================================================
    # 4. 回傳結果
    # =========================================================
    
    # 這裡依照您的需求，在開頭印出「成功讀取」
    return f"成功讀取！Gemini 分析報告 (Subprocess/Curl 版本):\n\n{ai_context}"
