from django.shortcuts import render

def home(request):
    return render(request, 'home.html')  # أو 'home.html' لو تتذكر الاسم