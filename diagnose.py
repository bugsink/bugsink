import os
import django
from django.conf import settings
from django.db import connection

# 1. 確保環境設定
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bugsink.settings")
django.setup()

def diagnose():
    print(f"🔍 [診斷報告]")
    print(f"----------------------------------------")
    
    # 1. 檢查當前工作目錄
    print(f"📂 當前工作目錄 (CWD): {os.getcwd()}")
    
    # 2. 檢查資料庫檔案路徑
    db_config = settings.DATABASES['default']
    db_name = db_config['NAME']
    print(f"💾 設定檔中的 DB 路徑: {db_name}")
    
    # 如果是 SQLite，檢查絕對路徑
    if 'sqlite3' in db_config['ENGINE']:
        abs_path = os.path.abspath(db_name)
        print(f"📍 DB 絕對路徑: {abs_path}")
        print(f"✅ 檔案是否存在: {os.path.exists(abs_path)}")
        if os.path.exists(abs_path):
            print(f"📦 檔案大小: {os.path.getsize(abs_path)} bytes")
    
    # 3. 檢查 User 模型與表格名稱
    from django.contrib.auth import get_user_model
    User = get_user_model()
    expected_table = User._meta.db_table
    print(f"👤 User 模型: {User.__module__}.{User.__name__}")
    print(f"📋 預期表格名稱: {expected_table}")
    
    # 4. 實際查詢資料庫中的表格
    print(f"----------------------------------------")
    print(f"🔍 正在掃描資料庫中的所有表格...")
    with connection.cursor() as cursor:
        # SQLite 查詢所有表名的語法
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        
    if expected_table in tables:
        print(f"✅ 成功找到表格: {expected_table}")
        print(f"📊 資料庫看起來是正常的！")
    else:
        print(f"❌ 找不到表格: {expected_table}")
        print(f"👀 實際存在的表格 ({len(tables)} 個):")
        print(tables[:10]) # 列出前10個
        
        if len(tables) == 0:
            print(f"⚠️  警告: 資料庫是空的！這證實了您連到了錯誤的(空的)資料庫檔案。")

# if __name__ == "__main__":
diagnose()
