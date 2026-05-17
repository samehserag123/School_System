from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Department, AttendanceRule, Employee, 
    FingerprintLog, DailyAttendance, LeaveRequest
)
# 1. تنسيق عرض الإدارات
@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'get_employee_count')
    search_fields = ('name',)

    def get_employee_count(self, obj):
        return obj.employee_set.count()
    get_employee_count.short_description = "عدد الموظفين"

# 2. تنسيق قواعد الحضور والانصراف المرنة
@admin.register(AttendanceRule)
class AttendanceRuleAdmin(admin.ModelAdmin):
    # تم تحديث الحقول المعروضة لتشمل المعاملات الحسابية الجديدة
    list_display = ('name', 'work_start_time', 'work_end_time', 'grace_period', 'working_days_summary')
    
    fieldsets = (
        ("المعلومات الأساسية", {
            'fields': ('name', 'work_start_time', 'work_end_time')
        }),
        ("إعدادات التأخير والإضافي المرنة", {
            'fields': ('grace_period', 'deduction_multiplier', 'overtime_multiplier', 'absent_deduction_days', 'requires_fingerprint'),
            'classes': ('collapse',), # جعلها قابلة للطي للتنظيم
        }),
        ("جدول العمل الأسبوعي", {
            'description': "اختر أيام العمل الرسمية (المحددة بـ صح تعني يوم عمل، وغير المحددة تعني عطلة)",
            'fields': (('sunday', 'monday', 'tuesday', 'wednesday', 'thursday'), ('friday', 'saturday')),
        }),
    )

    def working_days_summary(self, obj):
        """تحديث احترافي لعرض أيام العمل الفعلية في جدول الإدارة"""
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

# 3. تنسيق الموظفين
@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('emp_id', 'name', 'department', 'attendance_rule', 'base_salary', 'colored_status')
    list_filter = ('department', 'attendance_rule', 'is_active')
    search_fields = ('name', 'emp_id')
    list_editable = ('attendance_rule',) # تغيير القاعدة بنقرة واحدة من الخارج لتسهيل الحالات الخاصة
    
    def colored_status(self, obj):
        if obj.is_active:
            return format_html('<b style="color:green;">نشط</b>')
        return format_html('<b style="color:red;">موقف</b>')
    colored_status.short_description = "الحالة"

# 4. سجل البصمة الخام
@admin.register(FingerprintLog)
class FingerprintLogAdmin(admin.ModelAdmin):
    list_display = ('emp_id', 'timestamp', 'device_id')
    list_filter = ('timestamp', 'device_id')
    search_fields = ('emp_id',)
    date_hierarchy = 'timestamp'

# 5. الحضور والانصراف المعالج (تمت إضافة حقول الخصم والإضافي المحسوبة بالمعاملات)
@admin.register(DailyAttendance)
class DailyAttendanceAdmin(admin.ModelAdmin):
    # أضفنا 'overtime_hours' و 'deduction_hours' الناتجة عن الحسابات المرنة للمراجعة الفورية
    list_display = ('employee', 'date', 'check_in', 'check_out', 'status_badge', 'late_minutes', 'deduction_hours', 'overtime_hours')
    list_filter = ('status', 'date', 'employee__department', 'employee__attendance_rule')
    date_hierarchy = 'date'
    
    def status_badge(self, obj):
        colors = {
            'present': 'green',
            'absent': 'red',
            'leave': 'blue',
            'holiday': 'gray',
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 10px; border-radius: 10px;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_badge.short_description = "حالة اليوم"

# 6. طلبات الإجازة المربوطة بالأرصدة
@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'leave_type', 'start_date', 'end_date', 'duration', 'status')
    list_filter = ('status', 'leave_type')
    actions = ['approve_leaves', 'reject_leaves']

    def approve_leaves(self, request, queryset):
        # باستخدام دالة الحفظ الفردية لتفعيل منطق خصم رصيد الإجازات التلقائي من موديل LeaveRequest
        for leave in queryset:
            leave.status = 'approved'
            leave.save()
        self.message_user(request, "تم اعتماد الإجازات المختارة وتحديث أرصدة الموظفين تلقائياً.")
    approve_leaves.short_description = "اعتماد الإجازات المختارة"

    def reject_leaves(self, request, queryset):
        queryset.update(status='rejected')
        self.message_user(request, "تم رفض طلبات الإجازة المختارة.")
    reject_leaves.short_description = "رفض الإجازات المختارة"