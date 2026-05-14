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
    
    
from .models import Product

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    # الأعمدة التي ستظهر في القائمة الرئيسية للأدمن
    list_display = ('serial_number', 'product_name', 'is_original', 'scan_count', 'created_at')
    
    # إمكانية البحث بالرقم المسلسل أو اسم المنتج
    search_fields = ('serial_number', 'product_name')
    
    # فلاتر جانبية للتصفية
    list_filter = ('is_original', 'created_at')
    
    # 🔥 تم حذف scan_count من هنا عشان تقدر تكتبه وتعدله يدويًا
    readonly_fields = ('created_at',)