from django.urls import path
from .views import StudentListAPI

urlpatterns = [
    path('', StudentListAPI.as_view(), name='student_list_api'),
]
