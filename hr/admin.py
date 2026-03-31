from django.contrib import admin
from .models import Employee, Department, PayrollArchive, Leave

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    # الحقول التي ستظهر في قائمة الأقسام
    list_display = ('name', 'description')
    search_fields = ('name',)

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    # الحقول الشاملة التي ستظهر في قائمة الموظفين
    list_display = (
        'emp_id', 'name', 'department', 'job_title', 
        'base_salary', 'social_insurance', 'medical_insurance', 
        'penalties', 'loans', 'weekly_day_off'
    )
    search_fields = ('name', 'emp_id')
    list_filter = ('department', 'job_title', 'weekly_day_off')
    ordering = ('emp_id',)

# ==========================================
# الجداول الجديدة (أرشيف المرتبات والإجازات)
# ==========================================

@admin.register(PayrollArchive)
class PayrollArchiveAdmin(admin.ModelAdmin):
    # عرض المرتبات المؤرشفة في لوحة التحكم
    list_display = ('employee', 'month', 'year', 'net_salary', 'archived_at')
    list_filter = ('month', 'year', 'employee__department')
    search_fields = ('employee__name', 'employee__emp_id')
    
    # منع تعديل الأرشيف من لوحة التحكم (للحفاظ على مصداقية الحسابات)
    def has_change_permission(self, request, obj=None):
        return False

@admin.register(Leave)
class LeaveAdmin(admin.ModelAdmin):
    # عرض سجل الإجازات في لوحة التحكم
    list_display = ('employee', 'leave_type', 'start_date', 'end_date', 'days', 'created_at')
    list_filter = ('leave_type', 'start_date')
    search_fields = ('employee__name', 'employee__emp_id')