from django.contrib import admin
from .models import (
    AcademicYear,
    Coupon,
    DailyClosure,
    DeliveryRecord,
    InstallmentPlan,
    InventoryMaster,
    MonthlyClosure,
    Payment,
    PlanItem,
    RevenueCategory,
    StudentAccount,
    StudentInstallment,
    ItemDefinition
)

from .models import GradePriceList # لا تنسَ الاستيراد في الأعلى
from django.utils.html import format_html
from .models import ReceiptBook

from django.utils.safestring import mark_safe

from .models import Expense, ExpenseItem # تأكد من استيراد الموديلات

# تسجيل قائمة بنود المصروفات
admin.site.register(ExpenseItem)

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    # 👇 تم التعديل: استخدام دالة get_expense_name بدلاً من title، وإضافة invoice_number
    list_display = ('get_expense_name', 'invoice_number', 'amount_styled', 'expense_type', 'expense_date', 'spent_by', 'is_closed_status')
    
    # 👇 تم التعديل: إضافة expense_item للفلترة الجانبية
    list_filter = ('expense_type', 'is_closed', 'expense_date', 'spent_by', 'expense_item')
    
    # 👇 تم التعديل: إضافة البحث برقم الفاتورة واسم البند المسجل مسبقاً
    search_fields = ('title', 'notes', 'invoice_number', 'expense_item__name')
    raw_id_fields = ('spent_by', 'closure')

    # --- دوال العرض المخصصة ---

    # 1. دالة جديدة ذكية لعرض اسم المصروف (تدمج بين القائمة والكتابة اليدوية)
    def get_expense_name(self, obj):
        if obj.expense_item:
            return obj.expense_item.name
        return obj.title or "بدون بيان"
    get_expense_name.short_description = "بيان الصرف"

    # 2. تصحيح عرض المبلغ
    def amount_styled(self, obj):
        return format_html('<b style="color: #d9534f;">{} ج.م</b>', obj.amount)
    amount_styled.short_description = "المبلغ"

    # 3. تصحيح حالة الإغلاق
    def is_closed_status(self, obj):
        if obj.is_closed:
            return mark_safe('<span style="color: green; font-weight: bold;">✔ مغلق</span>')
        return mark_safe('<span style="color: orange; font-weight: bold;">⏳ مفتوح</span>')
    is_closed_status.short_description = "حالة الجرد"

    # --- حماية البيانات والأتمتة ---

    # حماية البيانات: منع تعديل المصروف إذا تم إغلاقه
    def get_readonly_fields(self, request, obj=None):
        if obj and obj.is_closed:
            return [f.name for f in self.model._meta.fields]
        return self.readonly_fields

    # تسجيل المستخدم الذي قام بالعملية تلقائياً
    def save_model(self, request, obj, form, change):
        if not obj.spent_by:
            obj.spent_by = request.user
        super().save_model(request, obj, form, change)
            
@admin.register(ReceiptBook)
class ReceiptBookAdmin(admin.ModelAdmin):
    list_display = ('book_number', 'user', 'start_serial', 'end_serial', 'is_active', 'created_at')
    list_filter = ('is_active', 'user')
    search_fields = ('book_number', 'user__username')
    # يمكن لرئيس الحسابات فقط إضافة الدفاتر من هنا
    
    
@admin.register(GradePriceList)
class GradePriceListAdmin(admin.ModelAdmin):
    list_display = ('revenue_category', 'grade', 'academic_year', 'price')
    list_filter = ('grade', 'academic_year', 'revenue_category')
    search_fields = ('revenue_category__name', 'grade__name')
    
@admin.register(ItemDefinition)
class ItemDefinitionAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(InventoryMaster)
class InventoryMasterAdmin(admin.ModelAdmin):
    # تم تعديل الحقول لتطابق الموديل الجديد (استخدام 'item' بدلاً من 'category')
    list_display = ('get_item_name', 'grade', 'academic_year', 'total_quantity', 'remaining_stock')
    
    # الفلاتر يجب أن تعتمد على حقول الموديل (item, grade, academic_year)
    list_filter = ('item', 'grade', 'academic_year')
    
    # البحث يتم عبر اسم الصنف (عبر العلاقة) أو الصف الدراسي
    search_fields = ('item__name', 'grade__name') 

    # دالة لعرض اسم الصنف من كلاس ItemDefinition
    def get_item_name(self, obj):
        return obj.item.name
    get_item_name.short_description = "اسم الصنف"

    # دالة لعرض الرصيد المتبقي في الجدول
    def remaining_stock(self, obj):
        return obj.get_remaining_stock()
    remaining_stock.short_description = "الرصيد المتبقي"    

# 2. تسجيل مخزون الطلاب (Student Inventory)
# 2. تسجيل سجلات تسليم الطلاب (بدلاً من StudentInventory)
@admin.register(DeliveryRecord)
class DeliveryRecordAdmin(admin.ModelAdmin):
    # الحقول مطابقة لما عرفته في الموديل
    list_display = ('student', 'inventory_item', 'delivery_date', 'delivered_by', 'is_received')
    list_filter = ('delivery_date', 'is_received', 'delivered_by')
    search_fields = ('student__first_name', 'student__last_name', 'inventory_item__item__name')
    actions = ['mark_as_received'] # قمت بتغيير اسم الـ Action ليكون أكثر دقة

    def mark_as_received(self, request, queryset):
        # التعديل هنا: استخدمنا الحقل الصحيح (is_received) الموجود في موديلك
        queryset.update(is_received=True) 
    mark_as_received.short_description = "تحديد كـ (تم الاستلام فعلياً)"


class SubCategoryInline(admin.TabularInline):
    model = RevenueCategory
    extra = 1
    fk_name = 'parent'

@admin.register(RevenueCategory)
class RevenueCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent')
    search_fields = ('name',)
    inlines = [SubCategoryInline]

# 4. خطط الأقساط (Plans)
class PlanItemInline(admin.TabularInline):
    model = PlanItem
    extra = 1
    fields = ('name', 'amount', 'due_date', 'order')
    ordering = ('order',)

@admin.register(InstallmentPlan)
class InstallmentPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'academic_year', 'total_amount', 'administrative_fee')
    list_editable = ('administrative_fee',) # لتسهيل تعديلها من الخارج مباشرة
    search_fields = ('name',)
    inlines = [PlanItemInline]
    # تنسيق شكل عرض الحقول داخل صفحة الإضافة/التعديل
    fieldsets = (
        ('البيانات الأساسية', {
            'fields': ('name', 'academic_year', 'number_of_installments')
        }),
        ('المبالغ والأقساط (تدخل في المديونية)', {
            'fields': ('total_amount', 'interest_value')
        }),
        ('إيرادات حرة (لا تدخل في المديونية)', {
            'fields': ('administrative_fee',),
            'description': 'هذه الرسوم تُدفع كإيراد منفصل ولا تُضاف لأقساط الطالب.'
        }),
    )
    

@admin.register(StudentAccount)
class StudentAccountAdmin(admin.ModelAdmin):
    # 1. الأعمدة المعروضة في الجدول
    list_display = [
        'student', 
        'academic_year', # أضفنا السنة هنا للوضوح
        'installment_plan', 
        'total_fees', 
        'discount',
        'net_fees_display', 
        'total_paid_display', 
        'total_remaining_display'
    ]
    
    # 2. الفلاتر الجانبية (تمكنك من اختيار 2024/2025 بضغطة واحدة)
    list_filter = ('academic_year', 'installment_plan', 'revenue_category')
    
    # 3. تحسين الأداء عبر جلب البيانات المرتبطة دفعة واحدة
    list_select_related = ('student', 'installment_plan', 'academic_year')
    
    readonly_fields = ['total_fees']
    search_fields = ['student__first_name', 'student__last_name', 'student__student_code']

    # 4. إضافة إجراءات جماعية (Actions) للحذف أو التعديل السريع
    actions = ['delete_selected_accounts', 'reset_discounts']

    # --- وظائف العرض (Displays) ---
    def net_fees_display(self, obj):
        return obj.net_fees
    net_fees_display.short_description = "صافي المصروفات"

    def total_paid_display(self, obj):
        return obj.total_paid
    total_paid_display.short_description = "إجمالي المدفوع"

    def total_remaining_display(self, obj):
        val = obj.total_remaining
        if val > 0:
            return format_html('<span style="color: red; font-weight: bold;">{} ج.م</span>', val)
        return f"{val} ج.م"
    total_remaining_display.short_description = "المتبقي"

    # --- الإجراءات الجماعية (Actions) ---
    @admin.action(description="حذف حسابات الطلاب المختارة نهائياً")
    def delete_selected_accounts(self, request, queryset):
        """حذف الحسابات والمديونيات المرتبطة بالسنة المختارة"""
        with transaction.atomic():
            count = queryset.count()
            queryset.delete()
            self.message_user(request, f"تم حذف {count} حساب طالب بنجاح.")

    @admin.action(description="تصفير الخصومات للحسابات المختارة")
    def reset_discounts(self, request, queryset):
        updated = queryset.update(discount=0)
        self.message_user(request, f"تم تصفير الخصم لـ {updated} حساب.")


from django.db import transaction

@admin.register(StudentInstallment)
class StudentInstallmentAdmin(admin.ModelAdmin):
    # 1. الحقول المعروضة في الجدول
    list_display = ('student', 'academic_year', 'installment_number', 'amount_due', 'paid_amount', 'get_remaining_balance', 'status')
    
    # 2. الفلاتر الجانبية (هنا تختار السنة الدراسية 2024/2025)
    list_filter = ('academic_year', 'status', 'installment_plan')
    
    # 3. إمكانية البحث باسم الطالب
    search_fields = ('student__first_name', 'student__last_name', 'student__student_code')
    
    readonly_fields = ('paid_amount',)

    # 4. إضافة إجراءات جماعية (Actions)
    actions = ['delete_selected_installments', 'reset_paid_amount']

    def get_remaining_balance(self, obj):
        return obj.amount_due - obj.paid_amount
    get_remaining_balance.short_description = "المبلغ المتبقي"

    def get_queryset(self, request):
        # استخدام select_related لتحسين الأداء كما في لوحة الفحص
        return super().get_queryset(request).select_related('student', 'academic_year')

    # إجراء مخصص لحذف الأقساط المحددة (آمن)
    @admin.action(description="حذف الأقساط المختارة نهائياً")
    def delete_selected_installments(self, request, queryset):
        with transaction.atomic():
            count = queryset.count()
            queryset.delete()
            self.message_user(request, f"تم حذف {count} قسط بنجاح.")

    # إجراء لتصفير المديونية (اختياري بدلاً من الحذف)
    @admin.action(description="تصفير مبالغ الأقساط المختارة")
    def reset_paid_amount(self, request, queryset):
        updated = queryset.update(paid_amount=0, status='Pending')
        self.message_user(request, f"تم إعادة ضبط {updated} قسط إلى 'قيد الانتظار'.")
        
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    # 1. عرض الحقول الأساسية
    list_display = ['id', 'get_student_name', 'revenue_category', 'amount_paid', 'payment_date']
    
    # 2. منع تحميل 1700 طالب في الذاكرة (ممتاز للسرعة)
    raw_id_fields = ['student', 'installment']
    
    # 3. جلب البيانات المرتبطة في استعلام SQL واحد (JOIN) لتقليل الـ 1750 استعلام
    list_select_related = ('student', 'revenue_category')
    
    # 4. تقليل عدد السجلات في الصفحة لسرعة العرض
    list_per_page = 20

    # 5. التصحيح: البحث بالحقول الفعلية (First & Last Name) بدلاً من full_name
    search_fields = ['student__first_name', 'student__last_name', 'id']
    
    # 6. فلترة خفيفة
    list_filter = ['payment_date', 'academic_year']

    # تحسين عرض الاسم في القائمة
    def get_student_name(self, obj):
        if obj.student:
            # استخدام الحقول المباشرة بدلاً من Property لو كانت تسبب بطئاً
            return f"{obj.student.first_name} {obj.student.last_name}"
        return "غير محدد"
    get_student_name.short_description = 'اسم الطالب'
    
@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active']
    list_editable = ['is_active']

@admin.register(DailyClosure)
class DailyClosureAdmin(admin.ModelAdmin):
    list_display = ['closure_id', 'closure_date', 'total_cash', 'closed_by']



@admin.register(MonthlyClosure)
class MonthlyClosureAdmin(admin.ModelAdmin):
    # الحقول التي ستظهر في الجدول الرئيسي
    list_display = ('month', 'total_revenues', 'total_expenses', 'net_balance', 'closing_balance', 'status', 'closed_by')
    
    # إضافة فلاتر جانبية
    list_filter = ('status', 'month')
    
    # جعل كافة الحقول الحسابية للقراءة فقط لمنع التلاعب بالأرقام من لوحة التحكم
    readonly_fields = ('month', 'opening_balance', 'total_revenues', 'total_expenses', 'net_balance', 'closing_balance', 'closed_at', 'closed_by')
    
    # تقسيم الحقول في صفحة التفاصيل بشكل منظم
    fieldsets = (
        ("بيانات الفترة", {
            'fields': ('month', 'status', 'notes')
        }),
        ("الملخص المالي", {
            'fields': ('opening_balance', 'total_revenues', 'total_expenses', 'net_balance', 'closing_balance'),
            'description': "هذه الأرقام تم حسابها آلياً بناءً على حركة الخزينة والمصروفات."
        }),
        ("بيانات الإغلاق", {
            'fields': ('closed_at', 'closed_by'),
        }),
    )

    def has_add_permission(self, request):
        # يفضل دائماً الإغلاق من واجهة النظام وليس من الأدمن لضمان دقة الحسابات
        return False
    

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ['code', 'discount_type', 'discount_value', 'usage_status', 'is_active_status']
    list_filter = ['active', 'discount_type']
    
    def usage_status(self, obj):
        return f"{obj.times_used} / {obj.usage_limit}"
    usage_status.short_description = "الاستخدام"

    def is_active_status(self, obj):
        # أضفنا الأقواس هنا () لاستدعاء الدالة
        if obj.check_validity(): 
            return mark_safe('<span style="color: green;">✅ صالح</span>')
        return mark_safe('<span style="color: red;">❌ غير صالح</span>')
    is_active_status.short_description = "الحالة"

    def has_add_permission(self, request):
        return request.user.is_superuser

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)