import os
from django.shortcuts import render, redirect
from django.http import Http404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.utils.translation import gettext_lazy as _

from bugsink.decorators import atomic_for_request_method

from .models import AuthToken


@atomic_for_request_method
@user_passes_test(lambda u: u.is_superuser)
def auth_token_list(request):
    auth_tokens = AuthToken.objects.all()

    if request.method == 'POST':
        # DIT KOMT ZO WEL
        full_action_str = request.POST.get('action')
        action, pk = full_action_str.split(":", 1)
        if action == "delete":
            AuthToken.objects.get(pk=pk).delete()

            messages.success(request, _('Token deleted'))
            return redirect('auth_token_list')

    return render(request, 'bsmain/auth_token_list.html', {
        'auth_tokens': auth_tokens,
    })


@atomic_for_request_method
@user_passes_test(lambda u: u.is_superuser)
def auth_token_create(request):
    if request.method != 'POST':
        raise Http404("Invalid request method")

    auth_token = AuthToken.objects.create()
    try:
        # 修改重點 1: 計算相對路徑
        # os.path.abspath(__file__) 取得當前檔案 (views.py) 的絕對路徑
        # os.path.dirname() 往上跳一層
        # 邏輯: views.py -> bsmain 資料夾 -> bugsink 專案根目錄 -> issues 資料夾 -> token.txt
        current_file_path = os.path.abspath(__file__)
        bsmain_dir = os.path.dirname(current_file_path) # 取得 bsmain 資料夾路徑
        project_root = os.path.dirname(bsmain_dir)       # 取得上一層 (bugsink 專案根目錄)
        
        target_file_path = os.path.join(project_root, 'issues', 'token.txt')

        # 確保目標資料夾存在，如果不存在則嘗試建立
        os.makedirs(os.path.dirname(target_file_path), exist_ok=True)

        # 使用 'a' 模式 (Append) 附加內容，並確保換行
        with open(target_file_path, 'a', encoding='utf-8') as f:
            f.write(f"{auth_token.token}\n")

        # 可選：通知使用者已寫入檔案
        messages.info(request, f"Token saved to {target_file_path}")

    except (PermissionError, OSError, IOError) as e:
        # 錯誤處理
        error_msg = f"Token created, but failed to write to file: {str(e)}"
        messages.warning(request, error_msg)
        print(error_msg) # 也在後台印出錯誤以便除錯
    return redirect("auth_token_list")
