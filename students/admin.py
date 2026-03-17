from django.contrib import admin
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


# @admin.register(Student)
# class StudentAdmin(admin.ModelAdmin):
#     list_display = [
#         'id',
#         'first_name',
#         'last_name',
#         'grade',
#         'classroom',
#         'gender',
#         'is_active',
#         'created_at'
#     ]

#     list_filter = ['grade', 'classroom', 'gender', 'is_active']
#     search_fields = ['first_name', 'last_name', 'national_id']
#     list_editable = ['is_active']


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    # الأسماء هنا يجب أن تطابق الـ Methods المعرفة بالأسفل
    list_display = (
        'get_full_name', 
        'current_year_fees_display', 
        'total_paid_display', 
        'current_remaining_display', 
        'total_old_debt_display'
    )
    
    # 1. المطلوب الحالي
    def current_year_fees_display(self, obj):
        return obj.current_year_fees_amount
    current_year_fees_display.short_description = "المطلوب (حالي)"

    # 2. المحصل الحالي (تم تعديله ليطابق الموديل)
    def total_paid_display(self, obj):
        return obj.total_paid_amount
    total_paid_display.short_description = "المحصل (حالي)"

    # 3. المتبقي (تم تعديله ليطابق الموديل)
    def current_remaining_display(self, obj):
        return obj.current_remaining_amount
    current_remaining_display.short_description = "المتبقي (حالي)"

    # 4. المديونية القديمة
    def total_old_debt_display(self, obj):
        return obj.total_old_debt
    total_old_debt_display.short_description = "مديونية قديمة"