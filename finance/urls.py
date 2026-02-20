from django.urls import path
from . import views
from .views import print_receipt, close_month, DashboardSummaryAPI
from .views import DashboardSummaryAPI
from .models import AcademicYear

def get_active_year():
    return AcademicYear.objects.filter(is_active=True).first()


urlpatterns = [
    path('dashboard/', views.finance_dashboard, name='finance_dashboard'),
    path('receipt/<int:payment_id>/', views.print_receipt, name='print_receipt'),
    path('close-month/', views.close_month, name='close_month'),
    path('dashboard-summary/', views.DashboardSummaryAPI.as_view(), name='dashboard_summary'),
]
