from django.apps import apps
from django.contrib.auth import get_user_model
from django.conf import settings
import os

# ==========================================
# [工具] 動態模型載入
# ==========================================
def get_model(app_label, model_name):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        print(f"⚠️  警告: 找不到模型 {app_label}.{model_name}")
        return None

def init_data():
    print("🚀 [Init] 開始執行 (欄位修正版)...")

    # 1. 獲取 Admin (users.User)
    # ------------------------------------------------
    User = get_user_model()
    admin = None
    try:
        # 嘗試獲取 Admin，若無則建立
        if not User.objects.filter(username="admin").exists():
            admin = User.objects.create_superuser("admin", "admin@example.com", "admin")
            print("✅ Admin 建立成功")
        else:
            admin = User.objects.get(username="admin")
            print("✅ Admin 已存在")
    except Exception as e:
        print(f"⚠️ Admin 處理異常: {e}")

    # 2. 建立 Team & Membership
    # ------------------------------------------------
    Team = get_model('teams', 'Team')
    TeamMembership = get_model('teams', 'TeamMembership')
    
    team = None
    if Team and admin:
        try:
            # 建立團隊
            team, created = Team.objects.get_or_create(
                name="Default Team",
                defaults={"visibility": 10} # 10=Discoverable
            )
            print(f"✅ Team 確認: {team.name}")

            # [關鍵修復] 綁定成員：讓 Admin 在網頁看得到團隊
            if TeamMembership:
                if not TeamMembership.objects.filter(team=team, user=admin).exists():
                    try:
                        # 嘗試綁定 Admin 權限 (Role=1)
                        TeamMembership.objects.create(team=team, user=admin, role=1, accepted=True)
                        print("✅ Admin 已成功加入團隊 (解決看不到團隊的問題)")
                    except Exception as e:
                        print(f"⚠️ 加入團隊失敗: {e}")
                else:
                    print("ℹ️ Admin 已經是團隊成員")
        except Exception as e:
            print(f"❌ Team 操作失敗: {e}")
            return

    # 3. 建立 Project
    # ------------------------------------------------
    Project = get_model('projects', 'Project')
    project = None
    
    if Project and team:
        try:
            print("🔧 正在建立專案...")
            project_slug = "default-project"
            
            # [關鍵修復] 移除 'platform' 欄位，因為模型不支援
            defaults = {"name": "Default Project"} 
            
            # 動態檢查關聯欄位 (Team vs Organization)
            kwargs = {"slug": project_slug, "defaults": defaults}
            field_names = [f.name for f in Project._meta.get_fields()]
            
            if 'team' in field_names:
                kwargs['team'] = team
            
            project, created = Project.objects.get_or_create(**kwargs)
            print(f"✅ Project 確認: {project.name}")
            
            # 4. 尋找 DSN
            # ------------------------------------------------
            # 這裡沿用之前的探勘邏輯，找出 Key
            print("\n🔍 [DSN 探勘] 正在尋找 Key...")
            found_key = None
            target_host = os.environ.get("REPORT_HOST", "localhost:8000")

            # 策略 A: 檢查 ProjectKey 模型
            ProjectKey = get_model('projects', 'ProjectKey')
            if ProjectKey:
                key = ProjectKey.objects.filter(project=project).first()
                if key:
                    raw_dsn = key.dsn_public
                    found_key = raw_dsn.replace("example.com", target_host)
                    if "http" not in found_key:
                         found_key = f"http://{key.public_key}@{target_host}/{project.id}"
                    print(f"   -> 透過 ProjectKey 找到 DSN")

            # 策略 B: 檢查 Project 本身欄位 (如果上面沒找到)
            if not found_key:
                possible_keys = ['public_key', 'api_key', 'key', 'dsn']
                for k in possible_keys:
                    if hasattr(project, k):
                        val = getattr(project, k)
                        if val:
                            found_key = f"http://{val}@{target_host}/{project.id}"
                            print(f"   -> 透過 Project.{k} 欄位組裝 DSN")
                            break

            # 5. 輸出結果
            if found_key:
                print(f"🔑 [DSN] 最終結果: {found_key}")
                with open("dsn.txt", "w") as f:
                    f.write(found_key)
            else:
                print("❌ 無法取得 DSN (ProjectKey 不存在且 Project 無 Key 欄位)")

        except Exception as e:
            print(f"❌ Project 操作失敗: {e}")
            # 印出可用欄位幫助除錯
            if Project:
                print(f"   (提示) Project 模型可用欄位: {[f.name for f in Project._meta.get_fields()]}")

# 直接執行
print("⚡ 腳本載入完成，正在執行 init_data()...")
init_data()
