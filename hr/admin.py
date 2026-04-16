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

# 2. تنسيق قواعد الحضور (تنظيم الأيام في مجموعات)
@admin.register(AttendanceRule)
class AttendanceRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'work_start_time', 'work_end_time', 'grace_period', 'working_days_summary')
    
    fieldsets = (
        ("المعلومات الأساسية", {
            'fields': ('name', 'work_start_time', 'work_end_time')
        }),
        ("إعدادات التأخير والإضافي", {
            'fields': ('grace_period', 'deduction_multiplier', 'overtime_multiplier'),
            'classes': ('collapse',), # جعلها قابلة للطي
        }),
        ("جدول العمل الأسبوعي", {
            'description': "اختر أيام العمل الرسمية لهذا النظام",
            'fields': (('sunday', 'monday', 'tuesday', 'wednesday', 'thursday'), ('friday', 'saturday')),
        }),
    )

    def working_days_summary(self, obj):
        days = []
        if obj.friday: days.append("الجمعة")
        if obj.saturday: days.append("السبت")
        # يمكنك إضافة باقي الأيام هنا
        return ", ".join(days) if days else "دوام كامل"
    working_days_summary.short_description = "أيام العطلة/العمل"

# 3. تنسيق الموظفين (الأهم)
@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('emp_id', 'name', 'department', 'attendance_rule', 'colored_status')
    list_filter = ('department', 'attendance_rule', 'is_active')
    search_fields = ('name', 'emp_id')
    list_editable = ('attendance_rule',) # إمكانية تغيير القاعدة من الخارج مباشرة
    
    def colored_status(self, obj):
        if obj.is_active:
            return format_html('<b style="color:green;">نشط</b>')
        return format_html('<b style="color:red;">موقف</b>')
    colored_status.short_description = "الحالة"

# 4. سجل البصمة الخام (للمراجعة السريعة)
@admin.register(FingerprintLog)
class FingerprintLogAdmin(admin.ModelAdmin):
    list_display = ('emp_id', 'timestamp', 'device_id')
    list_filter = ('timestamp', 'device_id')
    search_fields = ('emp_id',)
    date_hierarchy = 'timestamp' # شريط زمني للتصفح بالأيام والشهور

# 5. الحضور والانصراف المعالج
@admin.register(DailyAttendance)
class DailyAttendanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'check_in', 'check_out', 'status_badge', 'late_minutes')
    list_filter = ('status', 'date', 'employee__department')
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

# 6. طلبات الإجازة
@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'leave_type', 'start_date', 'end_date', 'duration', 'status')
    list_filter = ('status', 'leave_type')
    actions = ['approve_leaves', 'reject_leaves'] # إضافة عمليات جماعية

    def approve_leaves(self, request, queryset):
        queryset.update(status='approved')
    approve_leaves.short_description = "اعتماد الإجازات المختارة"

    def reject_leaves(self, request, queryset):
        queryset.update(status='rejected')
    reject_leaves.short_description = "رفض الإجازات المختارة"