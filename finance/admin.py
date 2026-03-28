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

@admin.register(InstallmentPlan)
class InstallmentPlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'total_amount', 'number_of_installments']
    inlines = [PlanItemInline]

# 5. حسابات الطلاب (Accounts)
@admin.register(StudentAccount)
class StudentAccountAdmin(admin.ModelAdmin):
    list_display = ['student', 'installment_plan', 'total_fees', 'net_fees_display', 'total_paid_display', 'total_remaining_display']
    list_select_related = ('student', 'installment_plan')
    readonly_fields = ['total_fees']
    search_fields = ['student__first_name', 'student__last_name', 'student__student_code']
    # تحويل الخصائص (Properties) إلى أعمدة قابلة للعرض
    def net_fees_display(self, obj):
        return obj.net_fees
    net_fees_display.short_description = "صافي المصروفات"

    def total_paid_display(self, obj):
        return obj.total_paid
    total_paid_display.short_description = "إجمالي المدفوع"

    def total_remaining_display(self, obj):
        # يعرض المتبقي مع تلوينه بالأحمر إذا كان هناك مستحقات
        val = obj.total_remaining
        if val > 0:
            return format_html('<span style="color: red; font-weight: bold;">{} ج.م</span>', val)
        return f"{val} ج.م"
    total_remaining_display.short_description = "المتبقي"

# 6. الأقساط والمدفوعات (Payments)
@admin.register(StudentInstallment)
class StudentInstallmentAdmin(admin.ModelAdmin):
    list_display = ['student', 'installment_number', 'amount_due', 'status', 'due_date']
    list_filter = ['academic_year', 'status']

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['get_student_name', 'revenue_category', 'amount_paid', 'payment_date']
    list_filter = ['academic_year', 'revenue_category', 'payment_date']
    
    # إضافة هذا السطر لجلب البيانات المرتبطة بـ "استعلام واحد" (SQL JOIN)
    # نستخدم 'student' و 'installment__student' لأن installment مرتبطة بـ student
    list_select_related = ('student', 'installment__student') 
    
    def get_student_name(self, obj):
        # الكود الخاص بك سيعمل الآن بسرعة أكبر بفضل list_select_related
        if obj.student:
            return f"{obj.student}"
        if obj.installment:
            return f"{obj.installment.student}"
        return "غير محدد"
    get_student_name.short_description = 'اسم الطالب'
# 7. الموديلات الإدارية والجرد
@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active']
    list_editable = ['is_active']

@admin.register(DailyClosure)
class DailyClosureAdmin(admin.ModelAdmin):
    list_display = ['closure_id', 'closure_date', 'total_cash', 'closed_by']

@admin.register(MonthlyClosure)
class MonthlyClosureAdmin(admin.ModelAdmin):
    list_display = ['month', 'total_collected', 'total_remaining']

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ['code', 'discount_value', 'active']
    def has_add_permission(self, request):
        return request.user.is_superuser