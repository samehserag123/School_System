from django.urls import path
from . import views

app_name = 'hr'

urlpatterns = [
    path('', views.hr_dashboard, name='hr_dashboard'),
    path('employees/add/', views.employee_create_view, name='employee_create'),
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/<int:employee_id>/edit/', views.employee_update_view, name='employee_update'),
    path('attendance/', views.attendance_list, name='attendance_list'),
    path('attendance/upload/', views.upload_and_process_attendance, name='upload_attendance'),
    path('leaves/', views.leave_list, name='leave_list'),
    path('leaves/add/', views.leave_request_view, name='leave_create'),
    
    # 🎯 أضف السطرين دول بالظبط هنا لحل المشكلة:
    path('leaves/<int:leave_id>/approve/', views.leave_approve, name='leave_approve'),
    path('leaves/<int:leave_id>/reject/', views.leave_reject, name='leave_reject'),
    path('payroll/report/', views.monthly_payroll_report, name='payroll_report'),
    # 🚀 أضف هذا السطر لمسارات تطبيق hr لتفعيل صفحة طباعة مفردات راتب الموظف:
    path('payroll/<int:employee_id>/<int:year>/<int:month>/', views.calculate_monthly_salary, name='payroll_slip'),
]