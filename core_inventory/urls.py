from django.urls import path
from . import views

urlpatterns = [
    # رابط شاشة الصرف والإضافة
    path('transaction/', views.manual_stock_transaction, name='manual_stock_transaction'),
    # رابط شاشة الإعدادات الفندقية
    path('settings/', views.material_control_settings, name='material_control_settings'),
    path('api/add-supplier/', views.ajax_add_supplier, name='ajax_add_supplier'),

]