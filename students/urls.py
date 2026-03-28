from django.urls import path
from .views import add_student, student_list
from . import views

urlpatterns = [
    # روابط الطلاب الأساسية
    path('', views.student_list, name='student_list'),
    path('add/', views.add_student, name='add_student'),
    path('promote/<int:student_id>/', views.promote_student, name='promote_student'),
    path('ajax/load-classrooms/', views.get_classrooms, name='ajax_load_classrooms'),
    path('debt-history/<int:student_id>/', views.debt_history, name='debt_history'),
    
    # روابط الدورات التدريبية والرسوم
    path('course-prices/', views.course_prices_view, name='course_prices'),
    path('collect-fee/<int:enrollment_id>/', views.collect_course_fee_view, name='collect_fee'),
    
    # --- نظام إدارة صرف الكتب والزي المدرسي ---
    
    # 1. سجل عمليات الصرف (المبيعات)
    path('sales/', views.book_sales_list, name='book_sales_list'),
    
    # 2. إضافة عملية صرف جديدة
    path('sales/add/', views.add_book_sale, name='add_book_sale'),
    
    # 3. طباعة إيصال صرف الكتب (تم تغيير الاسم لمنع تعارض الـ 404)
    path('sales/print/<int:sale_id>/', views.print_receipt_view, name='print_book_receipt'),
        
    # 5. تقرير جرد المخزن التفصيلي
    path('inventory/report/', views.inventory_category_report, name='inventory_report'),
    
    # ✅ التعديل الصحيح في ملف students/urls.py
    path('inventory/history/<int:item_id>/', views.get_item_history, name='get_item_history'),
    # امسح الرابط القديم وضعه مكانه هذا:
    path('admin/inventory/add-stock/', views.admin_add_restock, name='admin_add_restock'),
]