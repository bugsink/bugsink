import json
import traceback
import os
from events.models import Event  # 直接從資料庫模型匯入

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
    try:
        # A. 提取核心錯誤標題
        error_headline = "Unknown Error"
        try:
            # 從原始資料結構中抓取
            exception_values = event_data.get('exception', {}).get('values', [])
            if exception_values:
                exc_data = exception_values[0]
                error_headline = f"{exc_data.get('type', 'Error')}: {exc_data.get('value', 'No message')}"
            else:
                # 嘗試從 metadata 或其他欄位找標題
                error_headline = event_data.get('title', event.title()) # event.title() 是 Model 的方法
        except Exception:
            error_headline = "無法解析錯誤標題"

        # B. 提取環境資訊
        runtime_info = "Unknown Environment"
        try:
            runtime = event_data.get('contexts', {}).get('runtime', {})
            runtime_info = f"{runtime.get('name', 'Python')} {runtime.get('version', '')}"
        except Exception:
            pass

        # C. 提取 Stacktrace (手動轉成易讀格式，模擬 API 的 stacktrace_md)
        stacktrace_text = ""
        try:
            # 嘗試從 exception data 抓取 frames
            frames = event_data.get('exception', {}).get('values', [])[0].get('stacktrace', {}).get('frames', [])
            
            # 反轉 frames (通常我們想看最上面的錯誤點)
            for frame in reversed(frames):
                filename = frame.get('filename', 'unknown')
                lineno = frame.get('lineno', '?')
                function = frame.get('function', 'unknown')
                context_line = frame.get('context_line', '').strip()
                
                stacktrace_text += f"File \"{filename}\", line {lineno}, in {function}\n"
                if context_line:
                    stacktrace_text += f"    {context_line}\n"
                stacktrace_text += "\n"
                
            if not stacktrace_text:
                stacktrace_text = "(無詳細堆疊資料)"
                
        except Exception:
            stacktrace_text = "(解析 Stacktrace 失敗)"

        # D. 組合分析內容
        ai_context = (
            f"【錯誤摘要】: {error_headline}\n"
            f"【執行環境】: {runtime_info}\n"
            f"【詳細堆疊追蹤 (Stacktrace)】:\n{stacktrace_text}"
        )

    except Exception as e:
        return f"資料解析發生錯誤: {str(e)}\n{traceback.format_exc()}"

    # =========================================================
    # 3. 呼叫 Gemini (或回傳結果)
    # =========================================================
    
    # 這裡填入您的 Gemini 邏輯...
    
    return f"Gemini 分析報告 (Direct DB Access):\n\n{ai_context}"
