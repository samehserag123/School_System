from django.urls import path
from . import views

urlpatterns = [
    # الموظفين
    path('employees/', views.employee_list, name='employee_list'),
    
    # الحضور والانصراف
    path('attendance/', views.attendance_list, name='attendance_list'),
    path('attendance/upload/', views.upload_and_process_attendance, name='upload_attendance'),
    
    # الإجازات
    path('leaves/', views.leave_list, name='leave_list'),
    path('leaves/add/', views.leave_request_view, name='add_leave'),
]