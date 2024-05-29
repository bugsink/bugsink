from django.contrib.auth import login  # , authenticate
from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from django.http import Http404

from bugsink.app_settings import get_settings, CB_ANYBODY

from .forms import UserCreationForm


UserModel = get_user_model()


def signup(request):
    if get_settings().USER_REGISTRATION != CB_ANYBODY:
        raise Http404("User self-registration is not allowed.")

    if request.method == 'POST':
        form = UserCreationForm(request.POST)

        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            user = UserModel.objects.get(username=username)
            login(request, user)
            return redirect('home')
    else:
        form = UserCreationForm()

    return render(request, "signup.html", {"form": form})
