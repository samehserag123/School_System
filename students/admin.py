from django.contrib import admin
from django.utils.html import format_html
from .models import Grade, Classroom, Student

@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']

@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'grade']
    list_filter = ['grade']
    search_fields = ['name']

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    # قائمة الأعمدة التي ستظهر في الجدول
    list_display = (
        'student_code',
        'get_full_name', 
        'current_year_fees_display', 
        'total_paid_display', 
        'final_remaining_display',
        'old_debt_display'
    )
    
    search_fields = ['first_name', 'last_name', 'student_code']
    list_filter = ['grade', 'classroom', 'academic_year']

    # 1. إجمالي المطلوب (حالي + قديم)
    def current_year_fees_display(self, obj):
        # الاسم من الموديل عندك: total_required_amount
        return f"{obj.total_required_amount} ج.م"
    current_year_fees_display.short_description = "إجمالي المطلوب"

    # 2. إجمالي المحصل
    def total_paid_display(self, obj):
        # الاسم من الموديل عندك: current_year_paid
        return f"{obj.current_year_paid} ج.م"
    total_paid_display.short_description = "إجمالي المحصل"

    # 3. المتبقي النهائي (باللون الأحمر إذا كان أكبر من صفر)
    def final_remaining_display(self, obj):
        # الاسم من الموديل عندك: final_remaining
        val = obj.final_remaining
        if val > 0:
            return format_html('<span style="color: red; font-weight: bold;">{} ج.م</span>', val)
        return f"{val} ج.م"
    final_remaining_display.short_description = "المتبقي النهائي"

    # 4. المديونية القديمة (حل مشكلة AttributeError هنا)
    def old_debt_display(self, obj):
        # في صورتك الحقل اسمه total_old_debt
        # سنستخدم getattr للأمان في حال عدم وجود القيمة
        val = getattr(obj, 'total_old_debt', 0)
        return f"{val} ج.م"
    old_debt_display.short_description = "مديونية سابقة"