import csv
from django.contrib import admin
from django.http import HttpResponse
from .models import GeneralLedger, Product, ScanHistory

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


# دالة مخصصة لتصدير المنتجات المحددة إلى ملف CSV
@admin.action(description='تصدير أرقام الكيو آر والمنتجات المحددة إلى ملف CSV')
def export_products_as_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig') # تدعم اللغة العربية في إكسل
    response['Content-Disposition'] = 'attachment; filename="products_qr_export.csv"'

    writer = csv.writer(response)
    # كتابة أعمدة الملف
    writer.writerow(['اسم المنتج', 'رقم الكيو آر (Serial Number)', 'الحالة', 'عدد مرات المسح', 'تاريخ الإنشاء'])

    # كتابة بيانات المنتجات المحددة
    for product in queryset:
        writer.writerow([
            product.product_name,
            product.serial_number,
            product.is_active,
            product.scan_count,
            product.created_at
        ])

    return response

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'serial_number', 'is_active', 'scan_count', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['serial_number', 'product_name']
    actions = [export_products_as_csv]  # <--- هذا هو السطر الهام جداً الذي كان ناقصاً
    inlines = [ScanHistoryInline] # دمج تواريخ المسح أسفل المنتج