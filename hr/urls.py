from django.urls import path
from . import views

app_name = 'hr'

urlpatterns = [
    path('', views.hr_dashboard, name='hr_dashboard'),
    path('employees/', views.employee_list, name='employee_list'),
    path('attendance/', views.attendance_list, name='attendance_list'),
    
    # ✅ هذا هو المسار المفقود الذي تسبب في المشكلة
    path('attendance/upload/', views.upload_and_process_attendance, name='upload_attendance'),
    
    path('leaves/', views.leave_list, name='leave_list'),
    path('leaves/add/', views.leave_request_view, name='leave_create'),
]