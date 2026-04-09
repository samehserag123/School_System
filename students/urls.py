# students/urls.py (أو الملف الذي تدير فيه الروابط المالية)
from django.urls import path
from . import views
from students.views import get_pending_sales_api 

urlpatterns = [
    # ... الروابط الموجودة مسبقاً ...
    path('', views.student_list, name='student_list'),
    path('add/', views.add_student, name='add_student'),
    #path('students/basic/', views.student_basic_data, name='student_basic_data'),
    path('students/registry/', views.student_registry_view, name='student_registry'),
 
    # 🟢 أضف هذا الرابط إذا لم يكن موجوداً في ملف urls آخر
    # ملاحظة: تأكد من وجود دالة باسم add_ledger_entry في views.py
    path('treasury/add/', views.add_ledger_entry, name='add_ledger_entry'), 

    path('course-prices/', views.course_prices_view, name='course_prices'),
    path('mark-session/<int:enrollment_id>/', views.mark_session_attendance, name='mark_session_attendance'),
    path('session-history-api/<int:enrollment_id>/', views.session_history_api, name='session_history_api'),
    # students/urls.py
    path('student-analytics/<int:student_id>/', views.student_detail_analytics, name='student_analytics_detail'),
    path('students/analytics/', views.students_analytics_view, name='students_analytics'),
    path('sales/', views.book_sales_list, name='book_sales_list'),
    path('sales/add/', views.add_book_sale, name='add_book_sale'),
    path('sales/print/<int:sale_id>/', views.print_receipt_view, name='print_book_receipt'),
    path('inventory/report/', views.inventory_category_report, name='inventory_report'),
    path('admin/inventory/add-stock/', views.admin_add_restock, name='admin_add_restock'),
    path('students/api/get-pending-sales/<int:student_id>/', get_pending_sales_api, name='get_pending_sales_api'),
    path('collect-fee/<int:enrollment_id>/', views.collect_fee_view, name='collect_fee'),
]