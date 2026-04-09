from django.urls import path
from . import views

urlpatterns = [
    # داشبورد الخزينة
    path('dashboard/', views.treasury_dashboard, name='treasury_dashboard'),
    
    # إضافة إيراد
    path('add/', views.add_treasury_entry, name='add_treasury_entry'),

    # تقرير الإيرادات اليومية
    path('report/daily/', views.daily_revenue_report, name='daily_revenue_report'),
    
    # تقرير الجرد والإغلاق
    path('report/closure/', views.daily_closure_report, name='daily_closure_report'),

    # 🔥 أضف ده عشان تمسك اللينك اللي بتفتحه
    path('daily-summary/', views.daily_closure_report, name='daily_summary_debug'),
]