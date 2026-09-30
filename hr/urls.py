from django.urls import path
from . import views

app_name = 'hr'

urlpatterns = [
    path('', views.hr_dashboard, name='hr_dashboard'),
    path('employees/add/', views.employee_create_view, name='employee_create'),
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/<int:employee_id>/edit/', views.employee_update_view, name='employee_update'),

    # مسارات الحضور والانصراف
    path('attendance/', views.attendance_list, name='attendance_list'),
    path('attendance/upload/', views.upload_and_process_attendance, name='upload_attendance'),
    # 🆕 المسار الجديد لتسجيل الانصراف اليدوي في حالات عطل البصمة
    path('attendance/manual-checkout/<int:record_id>/', views.manual_checkout, name='manual_checkout'),

    path('attendance/export-excel/', views.export_attendance_excel, name='export_attendance_excel'),

    path('leaves/', views.leave_list, name='leave_list'),
    path('leaves/add/', views.leave_request_view, name='leave_create'),

    path('leaves/<int:leave_id>/approve/', views.leave_approve, name='leave_approve'),
    path('leaves/<int:leave_id>/reject/', views.leave_reject, name='leave_reject'),
    path('leaves/<int:leave_id>/cancel/', views.leave_cancel, name='leave_cancel'),

    path('payroll/report/', views.monthly_payroll_report, name='payroll_report'),
    path('payroll/<int:employee_id>/<int:year>/<int:month>/', views.calculate_monthly_salary, name='payroll_slip'),

    # 🟢 مسار تصدير كشف الرواتب إلى إكسيل (Excel)
    path('payroll/export/<int:year>/<int:month>/', views.export_payroll_excel, name='export_payroll_excel'),
    # مسار تصدير كشف التأمينات إلى إكسيل
    path('payroll/export-insurance/<int:year>/<int:month>/', views.export_insurance_excel, name='export_insurance_excel'),

    # مسارات المأموريات
    path('missions/', views.mission_list, name='mission_list'),
    path('missions/<int:req_id>/status/<str:status>/', views.update_mission_status, name='update_mission_status'),

    # مسارات الأذونات
    path('permissions/', views.permission_list, name='permission_list'),
    path('permissions/<int:req_id>/status/<str:status>/', views.update_permission_status, name='update_permission_status'),

    # مسار التسويات والاستثناءات المالية الجديد
    path('adjustments/', views.adjustment_list, name='adjustment_list'),

    path('mobile-approvals/', views.mobile_approvals_view, name='mobile_approvals'),

    # 🔴 مسار توقيع جزاء التحايل (خروج بدون إذن)
    path('attendance/<int:record_id>/fraud-penalty/', views.apply_fraud_penalty, name='apply_fraud_penalty'),
    path('attendance/<int:record_id>/remove-penalty/', views.remove_fraud_penalty, name='remove_fraud_penalty'),

    # 🛡️ مسارات الجزاء الإداري العام (نوع + سبب + أيام خصم يحددها المدير)
    path('penalty/add/', views.penalty_add, name='penalty_add_general'),
    path('penalty/add/<int:employee_id>/', views.penalty_add, name='penalty_add'),
    path('penalty/list/', views.penalty_list, name='penalty_list'),
    path('penalty/list/<int:employee_id>/', views.penalty_list, name='penalty_list_for_employee'),
    path('penalty/<int:penalty_id>/delete/', views.penalty_delete, name='penalty_delete'),

    # مسار العطلات الرسمية
    path('holidays/', views.public_holiday_list, name='public_holiday_list'),
]