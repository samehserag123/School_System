from django.urls import path
from .views import add_student, student_list

urlpatterns = [
    path('', student_list, name='student_list'),
    path('add/', add_student, name='add_student'),

    # نخلي الـ API ليه مسار خاص
    #path('api/', StudentListAPI.as_view(), name='student_list_api'),
]
