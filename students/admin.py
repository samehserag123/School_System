from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html
from .models import Grade, Classroom, Student, Teacher, Subject, CourseGroup, SubjectPrice
from .models import CoursePayment

from django.contrib import admin
from django.utils.html import format_html
from .models import CoursePayment, Teacher  # تأكد من استيراد الموديلات الصح

@admin.register(CoursePayment)
class CoursePaymentAdmin(admin.ModelAdmin):
    # 1. الأعمدة التي تظهر في الجدول الرئيسي
    list_display = (
        'get_student', 
        'get_subject', 
        'amount_paid', 
        'payment_date', 
        'get_status_display',
        'collected_by'
    )
    
    # 2. الفلاتر الجانبية
    list_filter = (
        'payment_date', 
        'course_enrollment__course_info__subject', 
        'course_enrollment__course_info__teacher'
    )
    
    # 3. خانات البحث
    # ملاحظة: تأكد من مسميات الحقول في موديل الطالب (مثلاً first_name)
    search_fields = (
        'course_enrollment__student__name', # لو الاسم حقل واحد اسمه name
        'notes'
    )
    
    # 4. تقسيم الحقول عند الإضافة
    fieldsets = (
        ('بيانات التحصيل الأساسية', {
            'fields': ('course_enrollment', 'amount_paid')
        }),
        ('معلومات إضافية', {
            'fields': ('notes', 'collected_by'),
            'classes': ('collapse',), 
        }),
    )

    def save_model(self, request, obj, form, change):
        if not obj.collected_by:
            obj.collected_by = request.user
        super().save_model(request, obj, form, change)

    # --- دوال العرض ---
    
    def get_student(self, obj):
        return obj.course_enrollment.student
    get_student.short_description = 'الطالب'

    def get_subject(self, obj):
        return obj.course_enrollment.course_info.subject
    get_subject.short_description = 'المادة'

    def get_status_display(self, obj):
        """عرض حالة الدفع بشكل ملون - تم إصلاح الخطأ هنا"""
        remaining = obj.course_enrollment.remaining_amount
        
        if remaining <= 0:
            # الحل: لازم نبعت متغير حتى لو مش هنستخدمه جوه الـ HTML أو نستخدم mark_safe
            # لكن الأفضل استخدام format_html بشكل صحيح
            return format_html('<span style="color: #10b981; font-weight: bold;">{}</span>', "خالص ✅")
        
        return format_html('<span style="color: #ef4444; font-weight: bold;">باقي {} ج.م</span>', remaining)
    
    get_status_display.short_description = 'حالة الاشتراك'

    # تحسين الاختيار لو عندك طلاب كتير
    raw_id_fields = ('course_enrollment',)

@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    # تأكد أن هذه الحقول موجودة فعلاً في موديل Teacher في ملف models.py
    list_display = ['id', 'name', 'phone'] # حذفنا 'subject' لأنه سبب المشكلة
    search_fields = ['name']

# 2. تسجيل المادة (Subject) - ليظهر في القائمة الجانبية
@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']

@admin.register(SubjectPrice)
class SubjectPriceAdmin(admin.ModelAdmin):
    list_display = ('subject', 'teacher', 'grade', 'session_type', 'price')
    list_filter = ('grade', 'session_type', 'teacher')
    search_fields = ('subject__name', 'teacher__name')
    
# 3. تسجيل أسعار الكورسات والمجموعات
@admin.register(CourseGroup)
class CourseGroupAdmin(admin.ModelAdmin):
    # نستخدم دوال (get_...) لعرض البيانات من الجدول المرتبط في القائمة
    list_display = ('student', 'get_subject', 'get_teacher', 'get_session_type', 'get_price')
    
    # الحقول التي تظهر عند الإضافة (يجب أن تشمل الحقول الموجودة في الموديل الجديد فقط)
    fields = ('student', 'course_info', 'notes')
    
    # تحسين البحث والاختيار
    raw_id_fields = ('student', 'course_info')
    search_fields = ('student__first_name', 'course_info__subject__name', 'course_info__teacher__name')
    list_filter = ('course_info__grade', 'course_info__session_type')

    # دوال جلب البيانات من الموديل المرتبط SubjectPrice
    def get_subject(self, obj): return obj.course_info.subject
    get_subject.short_description = 'المادة'

    def get_teacher(self, obj): return obj.course_info.teacher
    get_teacher.short_description = 'المدرس'

    def get_session_type(self, obj): return obj.course_info.get_session_type_display()
    get_session_type.short_description = 'نوع التدريس'

    def get_price(self, obj): return obj.course_info.price
    get_price.short_description = 'السعر'

    # حساب الإجمالي في أسفل الجدول
    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            if hasattr(response, 'context_data'):
                qs = response.context_data['cl'].queryset
                # نصل للسعر عبر العلاقة course_info__price
                total_price = qs.aggregate(total=Sum('course_info__price'))['total'] or 0
                extra_context = extra_context or {}
                extra_context['total_price'] = total_price
                response.context_data.update(extra_context)
        except:
            pass
        return response


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