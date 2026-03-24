from django.urls import path
from . import views

urlpatterns = [
    # مسار عرض سجل الخزينة العامة (الجدول المجمع)
    path('dashboard/', views.treasury_dashboard, name='treasury_dashboard'),
    
    # مسار إضافة إيراد يدوي جديد للخزينة
    path('add/', views.add_treasury_entry, name='add_treasury_entry'),

    # مسار تقرير الإيرادات اليومية
    path('report/daily/', views.daily_revenue_report, name='daily_revenue_report'),
    
    path('report/closure/', views.daily_closure_report, name='daily_closure_report'),
]