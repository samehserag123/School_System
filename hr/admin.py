from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Department, AttendanceRule, Employee,
    FingerprintLog, DailyAttendance, LeaveRequest,
    ShiftRoster,
    MissionRequest, PermissionRequest,  # 🟢 تم استيراد موديلات المأموريات والأذونات
    PenaltyRecord  # 🛡️ موديل الجزاء الإداري
)

# 1. تنسيق عرض الإدارات
@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'get_employee_count')
    search_fields = ('name',)

    def get_employee_count(self, obj):
        return obj.employee_set.count()
    get_employee_count.short_description = "عدد الموظفين"


# 2. تنسيق لوائح الحضور والانصراف
@admin.register(AttendanceRule)
class AttendanceRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'shift_type', 'grace_period', 'late_deduction_multiplier', 'overtime_multiplier_normal')
    list_filter = ('shift_type',)

    fieldsets = (
        ('المعلومات الأساسية ونوع الوردية', {
            'fields': ('name', 'shift_type')
        }),
        ('مواعيد وساعات العمل', {
            'fields': ('work_start_time', 'work_end_time', 'target_work_hours'),
            'description': 'حدد وقت الحضور والانصراف (للوردية الثابتة)، أو الساعات المستهدفة (للوردية المرنة).'
        }),
        ('قوانين التأخير والغياب', {
            'fields': ('grace_period', 'max_late_allowed_minutes', 'late_deduction_multiplier', 'absent_deduction_days')
        }),
        ('لوائح العمل الإضافي (Overtime)', {
            'fields': ('overtime_multiplier_normal', 'overtime_multiplier_weekend')
        }),
        ('أيام الدوام الأسبوعية', {
            'fields': ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'),
            'description': 'ضع علامة (صح) أمام أيام العمل الرسمية، واترك أيام العطلات فارغة. (لأفراد الأمن، اختر كل الأيام وحدد الإجازات المجمعة من ملف الموظف مباشرة).'
        }),
    )

    def working_days_summary(self, obj):
        days_mapping = {
            'sunday': 'الأحد', 'monday': 'الاثنين', 'tuesday': 'الثلاثاء',
            'wednesday': 'الأربعاء', 'thursday': 'الخميس', 'friday': 'الجمعة', 'saturday': 'السبت'
        }
        working_days = [arabic_name for eng_name, arabic_name in days_mapping.items() if getattr(obj, eng_name)]

        if len(working_days) == 7:
            return "دوام كامل (7 أيام)"
        elif len(working_days) == 0:
            return "لا يوجد أيام عمل!"
        return ", ".join(working_days)
    working_days_summary.short_description = "أيام العمل الرسمية"


# 3. إعداد الـ Inline لجدول الورديات المتغيرة
class ShiftRosterInline(admin.TabularInline):
    model = ShiftRoster
    extra = 5
    fields = ('date', 'is_working', 'shift_start', 'shift_end')
    classes = ('collapse',)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    # 🟢 إضافة hire_date للعرض في الجدول
    list_display = ('emp_id', 'name', 'department', 'hire_date', 'attendance_rule', 'base_salary', 'is_insured', 'colored_status')
    list_filter = ('department', 'attendance_rule', 'is_active', 'is_insured')
    search_fields = ('name', 'emp_id')
    list_editable = ('attendance_rule',)

    fieldsets = (
        ('البيانات الأساسية والتعاقدية', {
            # 🟢 تم إضافة hire_date هنا ليظهر في نموذج لوحة الإدارة
            'fields': ('emp_id', 'name', 'hire_date', 'department', 'attendance_rule', 'is_active', 'base_salary')
        }),
        ('البيانات التأمينية والبدلات 🛡️', {
            'fields': ('is_insured', 'insurance_number', 'insurance_basic_salary', 'insurance_variable_allowance', 'insurance_deduction'),
            'description': 'تفعيل خيار التأمين يربط حسابات الموظف تلقائياً بمحرك الخصومات في كشف الرواتب.'
        }),
        ('إدارة أرصدة الإجازات التراكمية', {
            'fields': ('annual_balance', 'casual_balance', 'sick_balance')
        }),
    )

    inlines = [ShiftRosterInline]

    def colored_status(self, obj):
        if obj.is_active:
            return format_html('<b style="color:green;">نشط</b>')
        return format_html('<b style="color:red;">موقوف</b>')
    colored_status.short_description = "الحالة"


# 5. سجل البصمة الخام
@admin.register(FingerprintLog)
class FingerprintLogAdmin(admin.ModelAdmin):
    list_display = ('emp_id', 'timestamp', 'device_id')
    list_filter = ('timestamp', 'device_id')
    search_fields = ('emp_id',)
    date_hierarchy = 'timestamp'


# 6. الحضور والانصراف المعالج
@admin.register(DailyAttendance)
class DailyAttendanceAdmin(admin.ModelAdmin):
    # 🟢 تمت إضافة administrative_penalty_days للجدول
    list_display = ('employee', 'date', 'check_in', 'check_out', 'status_badge', 'late_minutes', 'deduction_hours', 'administrative_penalty_days')
    list_filter = ('status', 'date', 'employee__department', 'employee__attendance_rule')
    date_hierarchy = 'date'
    # 🟢 الحل الحاسم: تقييد عرض الصفحة بـ 50 سجلاً فقط لمنع تجاوز عدد الحقول
    list_per_page = 50
    list_max_show_all = 100

    def status_badge(self, obj):
        colors = {
            'present': 'green',
            'absent': 'red',
            'leave': 'blue',
            'holiday': 'gray',
            'mission': 'purple', # 🟢 تمت إضافة لون خاص بالمأمورية
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 10px; border-radius: 10px;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_badge.short_description = "حالة اليوم"


# 7. طلبات الإجازة المربوطة بالأرصدة
@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'leave_type', 'start_date', 'end_date', 'get_duration', 'status')
    list_filter = ('status', 'leave_type')
    actions = ['approve_leaves', 'reject_leaves']

    @admin.display(description='مدة الإجازة (أيام)')
    def get_duration(self, obj):
        return obj.duration_days

    def approve_leaves(self, request, queryset):
        for leave in queryset:
            leave.status = 'approved'
            leave.save()
        self.message_user(request, "تم اعتماد الإجازات المختارة وتحديث أرصدة الموظفين تلقائياً.")
    approve_leaves.short_description = "اعتماد الإجازات المختارة"

    def reject_leaves(self, request, queryset):
        queryset.update(status='rejected')
        self.message_user(request, "تم رفض طلبات الإجازة المختارة.")
    reject_leaves.short_description = "رفض الإجازات المختارة"


# 🟢 8. إدارة المأموريات
@admin.register(MissionRequest)
class MissionRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'start_date', 'end_date', 'status')
    list_filter = ('status', 'start_date')
    search_fields = ('employee__name', 'reason')
    actions = ['approve_missions', 'reject_missions']

    def approve_missions(self, request, queryset):
        queryset.update(status='approved')
        self.message_user(request, "تم اعتماد المأموريات المحددة بنجاح.")
    approve_missions.short_description = "اعتماد المأموريات المختارة"

    def reject_missions(self, request, queryset):
        queryset.update(status='rejected')
        self.message_user(request, "تم رفض المأموريات المحددة.")
    reject_missions.short_description = "رفض المأموريات المختارة"


# 🟢 9. إدارة الأذونات
@admin.register(PermissionRequest)
class PermissionRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'status')
    list_filter = ('status', 'date')
    search_fields = ('employee__name', 'reason')
    actions = ['approve_permissions', 'reject_permissions']

    def approve_permissions(self, request, queryset):
        # الاعتماد هنا يمر عبر دالة save لتفعيل حماية الـ clean (مرة واحدة شهرياً) إن أردت، أو تحديث مباشر
        for permission in queryset:
            permission.status = 'approved'
            permission.save()
        self.message_user(request, "تم اعتماد الأذونات المحددة بنجاح.")
    approve_permissions.short_description = "اعتماد الأذونات المختارة"

    def reject_permissions(self, request, queryset):
        queryset.update(status='rejected')
        self.message_user(request, "تم رفض الأذونات المحددة.")
    reject_permissions.short_description = "رفض الأذونات المختارة"


# 🛡️ 10. إدارة الجزاءات الإدارية
@admin.register(PenaltyRecord)
class PenaltyRecordAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'penalty_type', 'deduction_days', 'created_by', 'created_at')
    list_filter = ('penalty_type', 'date')
    search_fields = ('employee__name', 'employee__emp_id', 'reason')
    date_hierarchy = 'date'
    readonly_fields = ('created_at',)

    def save_model(self, request, obj, form, change):
        # تسجيل مين وقّع الجزاء تلقائياً لو اتضاف من لوحة الإدارة مباشرة
        if not obj.pk and not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# 1. إنشاء جدول فرعي لاختيار الموظفين
class EmployeeInline(admin.TabularInline):
    model = Employee.hr_managers.through
    extra = 1
    verbose_name = "موظف"
    verbose_name_plural = "الموظفين المربوطين بهذا الـ HR"

# 2. إلغاء تسجيل اليوزر الافتراضي
admin.site.unregister(User)

# 3. إعادة تسجيل اليوزر مع إضافة جدول الموظفين
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = [EmployeeInline]