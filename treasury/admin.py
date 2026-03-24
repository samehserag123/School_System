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