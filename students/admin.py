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


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'first_name',
        'last_name',
        'grade',
        'classroom',
        'gender',
        'is_active',
        'created_at'
    ]

    list_filter = ['grade', 'classroom', 'gender', 'is_active']
    search_fields = ['first_name', 'last_name', 'national_id']
    list_editable = ['is_active']


