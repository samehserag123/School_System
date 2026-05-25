from django.contrib import admin
from .models import GeneralLedger

@admin.register(GeneralLedger)
class GeneralLedgerAdmin(admin.ModelAdmin):
    # الخانات التي ستظهر في الجدول الرئيسي
    list_display = ('date', 'category', 'amount', 'student', 'collected_by')
    
    # فلاتر جانبية لتسهيل الوصول للبيانات
    list_filter = ('category', 'date', 'collected_by')
    
    # البحث باسم الطالب أو رقم الإيصال
    search_fields = ('student__first_name', 'student__last_name', 'receipt_number')
    
    # جعل التاريخ للقراءة فقط لمنع التلاعب
    readonly_fields = ('date',)
    
    
from .models import Product, ScanHistory

# لعرض التواريخ داخل صفحة المنتج نفسه كقائمة سفلية (TabularInline)
class ScanHistoryInline(admin.TabularInline):
    model = ScanHistory
    extra = 0
    readonly_fields = ['scanned_at', 'ip_address'] # جعلها للقراءة فقط حتى لا تعدل التواريخ يدوياً
    can_delete = False # يمنع حذف تواريخ المسح من هنا

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'serial_number', 'is_active', 'scan_count', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['serial_number', 'product_name']
    inlines = [ScanHistoryInline] # دمج تواريخ المسح أسفل المنتج