from django.urls import path
from . import views


urlpatterns = [
    # 📦 المخزن واستلام الكتب
    path('student-inventory/<int:student_id>/', views.student_inventory_view, name='student_inventory_view'),
    path('inventory/deliver/<int:item_id>/', views.mark_item_delivered, name='mark_item_delivered'),

    # 📊 التقارير ولوحة التحكم (صفحات)
    path('dashboard/', views.finance_dashboard, name='finance_dashboard'),
    path('overdue/', views.overdue_report, name='overdue_report'),
    path('reports/debts/', views.debt_report, name='debt_report'),

    # 💰 إدارة الخطط المالية (التسكين)
    path('assign-plan/', views.assign_plan, name='assign_plan'),
    path('assign-plan/<int:student_id>/', views.assign_plan, name='assign_plan_with_id'),
    path('student/<int:student_id>/manual-enroll/', views.manual_finance_enroll, name='manual_finance_enroll'),
    path('mass-assign-plans/', views.mass_assign_plans, name='mass_assign_plans'),
    path('plans/', views.installment_plan_list, name='installment_plan_list'),
    path('generate-installments/<int:account_id>/', views.generate_installments_view, name='generate_installments'),
    
    # 🧾 التحصيل والطباعة
    path('quick-collection/', views.quick_collection, name='quick_collection'),
    path('receipt/<int:payment_id>/', views.print_receipt, name='print_receipt'),
    path('student/<int:student_id>/print-statement/', views.student_statement_print, name='student_statement_print'),
    path('student/<int:student_id>/settle-debt/', views.pay_old_debt, name='settle_old_debt'),

    # 🎓 شؤون الطلاب والترقية
    path('students/bulk-promote/', views.bulk_promote_students, name='bulk_promote'),
    
    # 🔒 إغلاق الحسابات والخزينة
    path('close-month/', views.close_month, name='close_month'),
    path('daily-summary/', views.daily_cashier_summary, name='daily_cashier_summary'),
    path('trigger-closure/', views.trigger_daily_closure, name='trigger_daily_closure'),
    path('payments-archive/', views.payments_archive, name='payments_archive'),
]