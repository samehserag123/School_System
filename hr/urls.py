from django.urls import path
from . import views

app_name = 'hr'

urlpatterns = [
    # مسارات إدارة الموظفين
    path('', views.employee_list, name='employee_list'),
    path('employee/add/', views.employee_create, name='employee_create'),
    path('employee/edit/<int:pk>/', views.employee_update, name='employee_update'),
    
    # مسارات الأقسام 
    path('departments/', views.department_list, name='department_list'),
    path('departments/add/', views.department_create, name='department_create'),
    path('departments/edit/<int:pk>/', views.department_update, name='department_update'),
    
    # مسارات الإجازات
    path('leaves/', views.leave_list, name='leave_list'),
    path('leaves/add/', views.leave_create, name='leave_create'),
    
    # مسار المرتبات والبصمة
    path('payroll/', views.calculate_payroll, name='calculate_payroll'),
    path('payroll/archive/save/', views.save_payroll_archive, name='save_payroll_archive'),
    path('payroll/archive/', views.payroll_archive, name='payroll_archive'),
    
    # --------> هذا هو السطر الذي يسبب لك الخطأ لعدم وجوده <--------
    path('payroll/archive/print/<int:month>/<int:year>/', views.print_pay_slips, name='print_pay_slips'),
]