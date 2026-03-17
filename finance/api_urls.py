from django.urls import path
from . import views

urlpatterns = [
    # 📊 API لوحة التحكم
    path('dashboard-summary/', views.DashboardSummaryAPI.as_view(), name='dashboard_summary'),
    
    # 🔍 البحث والعمليات السريعة (AJAX)
    path('ajax/get-students-by-year/', views.get_students_by_year, name='get_students_by_year'),
    path('get-student-balance/<int:student_id>/', views.get_student_balance, name='get_student_balance'),
]