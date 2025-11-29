import json
import traceback
import os
from events.models import Event  # 直接從資料庫模型匯入
from dotenv import load_dotenv
from google import genai

def process_task(event_id):
    """
    直接從資料庫讀取 Event 資料，解析並回傳 Gemini 分析結果。
    解決 HTTP Deadlock 與 Worker Timeout 問題。
    """
    
    # =========================================================
    # 1. 從資料庫讀取資料 (取代 Curl)
    # =========================================================
    try:
        # 這裡直接用 event_id (UUID) 去資料庫撈資料
        # 這是最快的方法，不需要透過網路，也不需要 Token
        event = Event.objects.get(pk=event_id)
        
        # 取得儲存在資料庫中的原始 JSON 資料
        event_data = event.data 

        # ==========================================
        # [新增功能] 將原始資料寫入 dbData.txt 以供除錯
        # ==========================================
        try:
            # 取得當前檔案 (useAPI.py) 的目錄
            current_dir = os.path.dirname(os.path.abspath(__file__))
            debug_file_path = os.path.join(current_dir, 'dbData.txt')
            
            # 將 event_data (字典) 轉為排版好的 JSON 字串並寫入檔案
            with open(debug_file_path, 'w', encoding='utf-8') as f:
                json.dump(event_data, f, indent=4, ensure_ascii=False)
                
            print(f"除錯資料已寫入: {debug_file_path}")
            
        except Exception as e:
            # 寫檔失敗不應中斷主流程，印出錯誤即可
            print(f"寫入 dbData.txt 失敗: {str(e)}")
        # ==========================================
        
    except Event.DoesNotExist:
        return f"錯誤: 在資料庫中找不到 ID 為 {event_id} 的 Event。"
    except Exception as e:
        return f"讀取資料庫時發生錯誤: {str(e)}"

    # =========================================================
    # 2. 資料解析 (解析 event.data)
    # =========================================================
    if isinstance(event_data, str):
        try:
            event_data = json.loads(event_data)
        except json.JSONDecodeError as e:
            return f"Error decoding JSON: {e}\nRaw content: {event_data[:100]}..."
        
    # 確保轉型後是字典，才能使用 .get()
    if not isinstance(event_data, dict):
         return f"資料格式錯誤: 預期 event.data 為字典，但得到 {type(event_data)}。"



    try:
        # --- A. 基礎環境資訊 ---
        environment = event_data.get("environment", "unknown")
        level = event_data.get("level", "unknown")
        timestamp = event_data.get("timestamp", "unknown")
        
        runtime = event_data.get("contexts", {}).get("runtime", {})
        r_name = runtime.get("name", "Python")
        r_version = runtime.get("version", "")
        runtime_info = f"{r_name} {r_version}".strip() or "Unknown Runtime"

        # --- B. 異常詳情 ---
        exception_values = event_data.get("exception", {}).get("values", [])
        exception = exception_values[0] if exception_values else {}

        error_type = exception.get("type", "Unknown Error Type")
        error_value = exception.get("value", "No error message provided")
        error_mechanism = exception.get("mechanism", {}).get("type", "unknown")

        # --- C. 錯誤發生點 (Last Frame Only) ---
        stacktrace_frames = exception.get("stacktrace", {}).get("frames", [])
        
        # [關鍵邏輯] 只取最後一個 frame，這是錯誤拋出的位置
        last_frame = stacktrace_frames[-1] if stacktrace_frames else {}
        
        filename = last_frame.get("filename", "unknown file")
        abs_path = last_frame.get("abs_path", filename)
        lineno = last_frame.get("lineno", "?")
        function = last_frame.get("function", "unknown function")
        context_line = last_frame.get("context_line", "").strip()
        
        # 格式化為單一區塊
        error_location_info = (
            f"檔案: {abs_path}\n"
            f"行號: {lineno}\n"
            f"函式: {function}\n"
            f"程式碼: {context_line}"
        )

        # --- D. 組合給 Gemini 的 Prompt ---
        ai_context = (
            f"【錯誤報告摘要】\n"
            f"時間: {timestamp}\n"
            f"環境: {environment} ({level})\n"
            f"執行環境: {runtime_info}\n"
            f"錯誤機制: {error_mechanism}\n\n"
            f"【核心錯誤】\n"
            f"錯誤類型: {error_type}\n"
            f"錯誤訊息: {error_value}\n\n"
            f"【錯誤發生位置 (Error Location)】\n"
            f"{error_location_info}"
        )

    except Exception as e:
        return f"資料解析邏輯發生錯誤: {str(e)}\n\n原始錯誤 Traceback:\n{traceback.format_exc()}"

    # =========================================================
    # 3. 呼叫 Gemini (或回傳結果)
    # =========================================================
    
    # 這裡填入您的 Gemini 邏輯...
    # 1. 載入 .env 檔案
    load_dotenv()
    
    # 2. 取得 API Key
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print("錯誤：找不到 GEMINI_API_KEY，請檢查 .env 檔案。")
    else:
        # 3. 初始化 Client
        client = genai.Client(api_key=api_key)
    
        try:
            # 4. 發送請求
            # 這裡使用您指定的 gemini-2.5-flash-lite
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=ai_context
            )

            # 5. 印出回應
            print(f"Gemini 回應：\n{response.text}")
            #ai_context = reponse.text
        except Exception as e:
            print(f"發生錯誤：{e}")

    ###
    
    return f"Gemini 分析報告 (Direct DB Access):\n\n{response.text}"
    #return f"Gemini 分析報告 (Direct DB Access):\n\n{response.text}\n\n{event_data}"
