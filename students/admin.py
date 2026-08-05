from django.contrib import admin
from django.db.models import Sum, F
from django.utils.html import format_html
from django.urls import reverse

from .models import (
    Grade, Classroom, Student, Teacher, Subject, Uniform,
    InventoryItem, GradePackagePrice, SubjectPrice, BookSale, CourseGroup,
    CoursePayment, SystemSettings, BusRoute, BusSubscription, BusPayment,
    RemedialFeeSetting, RemedialProgramRecord, StudentControlSheet,
    StudentAcademicHistory, SubjectConfig, ReEnrollmentRecord, AttendanceRecord,
    ControlRoomConfig, StudentTermControlNumber,
    AcademyDoctor, AcademyCourse, AcademySubject, AcademyTermSubject,
    AcademyEnrollment, AcademyLecture, AcademyAttendance
)

@admin.register(AcademyDoctor)
class AcademyDoctorAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'specialty', 'phone')
    search_fields = ('name', 'specialty', 'phone')

@admin.register(AcademyTermSubject)
class AcademyTermSubjectAdmin(admin.ModelAdmin):
    list_display = ('course', 'term_number', 'subject', 'doctor')
    list_filter = ('term_number', 'course', 'doctor')
    search_fields = ('course__name', 'subject__name', 'doctor__name')
    raw_id_fields = ('course', 'subject', 'doctor')


@admin.register(AcademyCourse)
class AcademyCourseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'duration_months', 'total_terms', 'base_price')
    list_filter = ('duration_months', 'total_terms')
    search_fields = ('name',)


@admin.register(AcademySubject)
class AcademySubjectAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'code')
    search_fields = ('name', 'code')


@admin.register(AcademyEnrollment)
class AcademyEnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'course', 'enrollment_date', 'get_final_price', 'is_graduated')
    list_filter = ('is_graduated', 'course', 'enrollment_date')
    search_fields = ('student__first_name', 'student__last_name', 'student__student_code', 'course__name')
    raw_id_fields = ('student',)

    def get_final_price(self, obj):
        return f"{obj.final_price} ج.م"
    get_final_price.short_description = "سعر الاشتراك"


@admin.register(AcademyLecture)
class AcademyLectureAdmin(admin.ModelAdmin):
    list_display = ('title', 'term_subject', 'lecture_date')
    list_filter = ('term_subject__course', 'term_subject__term_number', 'lecture_date')
    search_fields = ('title', 'term_subject__subject__name')
    raw_id_fields = ('term_subject',)


@admin.register(AcademyAttendance)
class AcademyAttendanceAdmin(admin.ModelAdmin):
    list_display = ('enrollment', 'lecture', 'status')
    list_filter = ('status', 'lecture__term_subject__course')
    raw_id_fields = ('enrollment', 'lecture')


# 🚀 تم تحديث الاستيراد ليشمل الموديلات الجديدة (ControlRoomConfig و StudentTermControlNumber) لمنع الـ NameError
from .models import (
    Grade, Classroom, Student, Teacher, Subject, Uniform,
    InventoryItem, GradePackagePrice, SubjectPrice, BookSale, CourseGroup,
    CoursePayment, SystemSettings, BusRoute, BusSubscription, BusPayment,
    RemedialFeeSetting, RemedialProgramRecord, StudentControlSheet,
    StudentAcademicHistory, SubjectConfig, ReEnrollmentRecord, AttendanceRecord,
    ControlRoomConfig, StudentTermControlNumber
)

@admin.register(ControlRoomConfig)
class ControlRoomConfigAdmin(admin.ModelAdmin):
    """لوحة تحديد سعة الفصول واللجان لكل عام دراسي"""
    list_display = ('academic_year', 'students_per_committee')
    list_editable = ('students_per_committee',)


@admin.register(StudentTermControlNumber)
class StudentTermControlNumberAdmin(admin.ModelAdmin):
    """لوحة عرض وتوليد شيت الكنترول العام لأرقام الجلوس واللجان"""
    list_display = (
        'seating_number',
        'secret_number',
        'student_link',
        'get_grade',
        'get_study_type',
        'get_integration',
        'committee_label',
        'seat_number_in_committee',
        'term',
        'academic_year'
    )
    list_filter = ('term', 'academic_year', 'committee_number', 'student__grade', 'student__study_type', 'student__integration_status')
    search_fields = ('seating_number', 'secret_number', 'committee_number', 'student__first_name', 'student__last_name', 'student__student_code')
    ordering = ('seating_number',)
    raw_id_fields = ('student',)

    actions = ['generate_term1_numbers', 'generate_term2_numbers', 'generate_second_session_numbers']

    def get_grade(self, obj): return obj.student.grade.name if obj.student.grade else "غير محدد"
    get_grade.short_description = "الصف"

    def get_study_type(self, obj): return obj.student.get_study_type_display()
    get_study_type.short_description = "نوع الدراسة"

    def get_integration(self, obj):
        if obj.student.integration_status:
            return format_html('<span style="color: #fd7e14; font-weight: bold;">دمج ♿</span>')
        return "طبيعي"
    get_integration.short_description = "الحالة"

    def committee_label(self, obj):
        return format_html('<span style="background: #20c997; color: #fff; padding: 2px 8px; border-radius: 4px; font-weight: bold;">لجنة {}</span>', obj.committee_number)
    committee_label.short_description = "رقم اللجنة"

    def student_link(self, obj):
        url = reverse("admin:students_student_change", args=[obj.student.id])
        return format_html('<a href="{}" style="font-weight:bold; color:#007bff;">{}</a>', url, obj.student.get_full_name())
    student_link.short_description = "اسم الطالب"

    def generate_term1_numbers(self, request, queryset):
        from finance.utils import get_active_year
        active_year = get_active_year()
        StudentTermControlNumber.generate_numbers_for_term(active_year, 'term1')
        self.message_user(request, "🎉 الكنترول جاهز! تم توليد أرقام الجلوس والسرية وتوزيع اللجان بالتساوي للترم الأول.")
    generate_term1_numbers.short_description = "⚡ توليد أرقام الجلوس وتوزيع اللجان (الترم الأول)"

    def generate_term2_numbers(self, request, queryset):
        from finance.utils import get_active_year
        active_year = get_active_year()
        StudentTermControlNumber.generate_numbers_for_term(active_year, 'term2')
        self.message_user(request, "🎉 الكنترول جاهز! تم توليد أرقام الجلوس والسرية وتوزيع اللجان بالتساوي للترم الثاني.")
    generate_term2_numbers.short_description = "⚡ توليد أرقام الجلوس وتوزيع اللجان (الترم الثاني)"

    def generate_second_session_numbers(self, request, queryset):
        from finance.utils import get_active_year
        active_year = get_active_year()
        StudentTermControlNumber.generate_numbers_for_term(active_year, 'second_session')
        self.message_user(request, "⚠️ تم حصر طلاب الملاحق وعزلهم في لجان أرقام جلوس مستقلة للدور الثاني.")
    generate_second_session_numbers.short_description = "🔥 توليد أرقام الجلوس وتوزيع اللجان (الدور الثاني)"


@admin.register(StudentControlSheet)
class StudentControlSheetAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'academic_year', 'term1_total', 'term2_total', 'total_year_score', 'second_session_total', 'display_status')
    list_filter = ('academic_year', 'status', 'subject', 'student__grade')
    search_fields = ('student__first_name', 'student__last_name', 'student__student_code', 'subject__name')
    raw_id_fields = ('student',)
    readonly_fields = ('status',)

    def display_status(self, obj):
        if obj.status == 'passed':
            return format_html('<span style="color: #28a745; font-weight: bold;">ناجح ✅</span>')
        elif obj.status == 'second_session':
            return format_html('<span style="color: #fd7e14; font-weight: bold;">دور ثانٍ ⚠️</span>')
        return format_html('<span style="color: #dc3545; font-weight: bold;">راسب ❌</span>')
    display_status.short_description = "الحالة النهائية"


@admin.register(StudentAcademicHistory)
class StudentAcademicHistoryAdmin(admin.ModelAdmin):
    list_display = ('student', 'academic_year', 'grade', 'classroom', 'display_result', 'total_attendance_percentage')
    list_filter = ('academic_year', 'grade', 'final_result')
    search_fields = ('student__first_name', 'student__last_name', 'student__student_code')
    raw_id_fields = ('student',)

    def display_result(self, obj):
        if obj.final_result == 'Promoted':
            return format_html('<span style="color: #28a745; font-weight: bold;">ناجح ومنقول 🎓</span>')
        return format_html('<span style="color: #dc3545; font-weight: bold;">باقٍ للإعادة ❌</span>')
    display_result.short_description = "نتيجة العام"


@admin.register(SubjectConfig)
class SubjectConfigAdmin(admin.ModelAdmin):
    list_display = ('subject', 'grade', 'academic_year', 'max_cultural', 'max_practical', 'passing_score')
    list_filter = ('academic_year', 'grade', 'subject')
    search_fields = ('subject__name', 'grade__name')


@admin.register(ReEnrollmentRecord)
class ReEnrollmentRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'academic_year', 'dismissal_date', 'reenrollment_date', 'status', 'fee_paid')
    list_filter = ('academic_year', 'status', 'fee_paid')
    search_fields = ('student__first_name', 'student__last_name', 'student__student_code')
    raw_id_fields = ('student',)


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'date', 'term', 'display_status', 'notes')
    list_filter = ('date', 'term', 'status', 'academic_year')
    search_fields = ('student__first_name', 'student__last_name', 'student__student_code')
    raw_id_fields = ('student',)

    def display_status(self, obj):
        if obj.status == 'present':
            return format_html('<span style="color: #28a745;">حاضر</span>')
        elif obj.status == 'absent':
            return format_html('<span style="color: #dc3545; font-weight: bold;">غائب</span>')
        return format_html('<span style="color: #fd7e14;">بعذر</span>')
    display_status.short_description = "الحالة"


@admin.register(RemedialFeeSetting)
class RemedialFeeSettingAdmin(admin.ModelAdmin):
    list_display = ('academic_year', 'fee_per_subject')
    list_editable = ('fee_per_subject',)
    search_fields = ('academic_year__name',)


@admin.register(RemedialProgramRecord)
class RemedialProgramRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'academic_year', 'subjects_count', 'total_amount', 'is_paid', 'created_at')
    list_filter = ('academic_year', 'is_paid', 'created_at')
    search_fields = ('student__first_name', 'student__last_name', 'student__student_code')
    readonly_fields = ('total_amount', 'created_by', 'created_at')

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
            fee_setting = RemedialFeeSetting.objects.filter(academic_year=obj.academic_year).first()
            fee = fee_setting.fee_per_subject if fee_setting else 150
            obj.total_amount = obj.subjects_count * fee
        super().save_model(request, obj, form, change)


@admin.register(BusRoute)
class BusRouteAdmin(admin.ModelAdmin):
    list_display = ('name', 'driver_name', 'bus_number', 'capacity', 'monthly_price', 'term_price', 'yearly_price')
    search_fields = ('name', 'driver_name', 'bus_number')
    list_filter = ('capacity',)


@admin.register(BusSubscription)
class BusSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('student', 'route', 'sub_type', 'start_date', 'end_date', 'is_active', 'required_amount', 'remaining_amount')
    list_filter = ('sub_type', 'is_active', 'route')
    search_fields = ('student__first_name', 'student__last_name', 'student__student_code', 'route__name')
    date_hierarchy = 'start_date'
    readonly_fields = ('created_at',)


@admin.register(BusPayment)
class BusPaymentAdmin(admin.ModelAdmin):
    list_display = ('subscription', 'amount_paid', 'payment_date', 'collected_by')
    list_filter = ('payment_date', 'collected_by')
    search_fields = ('subscription__student__first_name', 'subscription__student__last_name', 'subscription__route__name')
    date_hierarchy = 'payment_date'
    readonly_fields = ('payment_date',)


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    list_display = ('is_admission_open',)
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']


@admin.register(Uniform)
class UniformAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'get_item_label', 'grade', 'stock_quantity')
    list_filter = ('item_type', 'grade')
    search_fields = ('subject__name', 'uniform__name')

    def get_item_label(self, obj):
        return obj.display_name
    get_item_label.short_description = "اسم الصنف"

    fieldsets = (
        ('المعلومات الأساسية', {'fields': ('item_type', 'grade')}),
        ('تفاصيل الصنف', {'fields': ('subject', 'uniform')}),
        ('المخزون', {'fields': ('stock_quantity',)}),
    )


@admin.register(GradePackagePrice)
class GradePackagePriceAdmin(admin.ModelAdmin):
    list_display = ['academic_year', 'grade', 'books_price', 'uniform_price']
    list_filter = ['academic_year', 'grade']
    ordering = ['-academic_year', 'grade']

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "academic_year":
            kwargs["queryset"] = db_field.related_model.objects.order_by('-name')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(SubjectPrice)
class SubjectPriceAdmin(admin.ModelAdmin):
    """شاشة تعريفة الأسعار وربط المادة والمدرس بالسعر ونوع الكورس"""
    list_display = ['id', 'subject', 'teacher', 'grade', 'session_type', 'price']
    list_filter = ['grade', 'session_type', 'teacher', 'subject']
    search_fields = ['subject__name', 'teacher__name', 'grade__name']
    list_editable = ['price', 'session_type'] # يتيح لك تعديل السعر ونوع الكورس مباشرة من القائمة!


@admin.register(BookSale)
class BookSaleAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'student_link',
        'item',
        'quantity',
        'total_amount',
        'display_paid_amount',
        'financial_status',
        'is_delivered',
        'sale_date'
    ]
    list_filter = ['status', 'is_delivered', 'sale_date', 'student__academic_year']
    raw_id_fields = ['student', 'item']
    readonly_fields = ['total_amount', 'sale_date', 'display_paid_amount']

    def display_paid_amount(self, obj):
        paid = obj.calculated_paid_amount
        return format_html('<span style="color: #28a745; font-weight: bold;">{} ج.م</span>', paid)
    display_paid_amount.short_description = "المسدد بالخزينة"

    def financial_status(self, obj):
        remaining = obj.remaining_amount
        if remaining <= 0 and obj.total_amount > 0:
            return format_html('<span style="color: #28a745; font-weight: bold;">خالص ✅</span>')
        elif 0 < remaining < obj.total_amount:
            return format_html('<span style="color: #fd7e14; font-weight: bold;">جزئي (باقي {})</span>', remaining)
        return format_html('<span style="color: #dc3545; font-weight: bold;">باقي {} ج.م</span>', remaining)
    financial_status.short_description = "الموقف المالي"

    def student_link(self, obj):
        try:
            url = reverse("admin:students_student_change", args=[obj.student.id])
            return format_html('<a href="{}" style="font-weight:bold; color:#007bff;">{}</a>', url, obj.student.get_full_name())
        except:
            return obj.student.get_full_name()
    student_link.short_description = "الطالب"
    search_fields = ('student__first_name', 'student__last_name', 'student__student_code', 'id')


@admin.register(CoursePayment)
class CoursePaymentAdmin(admin.ModelAdmin):
    list_display = ('get_student', 'get_subject', 'amount_paid', 'payment_date', 'get_status_display', 'collected_by')
    list_filter = ('payment_date', 'course_enrollment__course_info__subject', 'course_enrollment__course_info__teacher')
    search_fields = ('course_enrollment__student__first_name', 'course_enrollment__student__last_name', 'notes')
    raw_id_fields = ('course_enrollment',)
    fieldsets = (
        ('بيانات التحصيل الأساسية', {'fields': ('course_enrollment', 'amount_paid')}),
        ('معلومات إفاضية', {'fields': ('notes', 'collected_by'), 'classes': ('collapse',)}),
    )

    def save_model(self, request, obj, form, change):
        if not obj.collected_by:
            obj.collected_by = request.user
        super().save_model(request, obj, form, change)

    def get_student(self, obj): return obj.course_enrollment.student
    get_student.short_description = 'الطالب'

    def get_subject(self, obj): return obj.course_enrollment.course_info.subject
    get_subject.short_description = 'المادة'

    def get_status_display(self, obj):
        remaining = obj.course_enrollment.remaining_amount
        if remaining <= 0:
            return format_html('<span style="color: #10b981; font-weight: bold;">خالص ✅</span>')
        return format_html('<span style="color: #ef4444; font-weight: bold;">باقي {} ج.م</span>', remaining)
    get_status_display.short_description = 'حالة الاشتراك'


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'phone']
    search_fields = ['name']


@admin.register(CourseGroup)
class CourseGroupAdmin(admin.ModelAdmin):
    # 🟢 1. أعمدة العرض الرئيسية الشاملة لبيانات الاشتراك والماليات
    list_display = (
        'id',
        'get_student_display',
        'get_subject',
        'get_teacher',
        'get_session_type',
        'required_amount',
        'get_total_paid',
        'get_remaining',
        'registration_date'
    )

    # 🟢 2. الحقول الظاهرة عند إضافة أو تعديل اشتراك بداخل الأدمن
    fields = (
        'student',
        'external_student',
        'course_info',
        'total_sessions',
        'required_amount',
        'start_date',
        'notes'
    )

    # 🟢 3. حقول البحث والفلترة والربط السريع
    raw_id_fields = ('student', 'external_student', 'course_info')
    search_fields = (
        'student__first_name',
        'student__last_name',
        'student__student_code',
        'external_student__full_name',
        'course_info__subject__name',
        'course_info__teacher__name'
    )
    list_filter = ('course_info__grade', 'course_info__session_type', 'course_info__teacher', 'registration_date')
    ordering = ('-id',)

    # --- 🟢 دالّات تخصيص العرض والربط بالماليات ---

    def get_student_display(self, obj):
        if obj.student:
            url = reverse("admin:students_student_change", args=[obj.student.id])
            return format_html('<a href="{}" style="font-weight:bold; color:#007bff;">{}</a>', url, obj.student.get_full_name())
        elif obj.external_student:
            return format_html('<span style="color:#fd7e14; font-weight:bold;">{} (خارجي)</span>', obj.external_student.full_name)
        return "غير محدد"
    get_student_display.short_description = 'الطالب'

    def get_subject(self, obj):
        return obj.course_info.subject if obj.course_info else "---"
    get_subject.short_description = 'المادة'

    def get_teacher(self, obj):
        return obj.course_info.teacher if obj.course_info else "---"
    get_teacher.short_description = 'المدرس'

    def get_session_type(self, obj):
        return obj.course_info.get_session_type_display() if obj.course_info else "---"
    get_session_type.short_description = 'نوع الكورس / التدريس'

    def get_total_paid(self, obj):
        paid = obj.total_paid
        return format_html('<span style="color: #28a745; font-weight: bold;">{} ج.م</span>', paid)
    get_total_paid.short_description = 'المحصل فعلياً'

    def get_remaining(self, obj):
        rem = obj.remaining_amount
        if rem <= 0:
            return format_html('<span style="color: #28a745; font-weight: bold;">مسدد ✅</span>')
        return format_html('<span style="color: #dc3545; font-weight: bold;">متبقي {} ج.م</span>', rem)
    get_remaining.short_description = 'الموقف المالي'

    # 🟢 4. حساب ثمن الاشتراك تلقائياً عند الإضافة من الأدمن إن لم يُدخل يدوياً
    def save_model(self, request, obj, form, change):
        if obj.course_info and (not obj.required_amount or obj.required_amount == 0):
            sessions = obj.total_sessions or 4
            price_per_session = Decimal(str(obj.course_info.price)) / Decimal('4')
            obj.required_amount = price_per_session * Decimal(str(sessions))
        super().save_model(request, obj, form, change)

    # 🟢 5. دالة الـ changelist_view الخاصة بك لحساب إجمالي الإيراد المطلوب بأسفل جدول الأدمن
    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            if hasattr(response, 'context_data'):
                qs = response.context_data['cl'].queryset
                total_price = qs.aggregate(total=Sum('required_amount'))['total'] or 0
                extra_context = extra_context or {}
                extra_context['total_price'] = total_price
                response.context_data.update(extra_context)
        except Exception:
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
    list_select_related = ('grade', 'classroom', 'academic_year')
    list_display = (
        'student_code',
        'get_full_name',
        'whatsapp_number',
        'current_year_fees_display',
        'total_paid_display',
        'final_remaining_display',
        'old_debt_display'
    )
    search_fields = ['first_name', 'last_name', 'student_code', 'whatsapp_number', 'phone']
    list_filter = ['grade', 'classroom', 'academic_year']
    list_per_page = 50

    def current_year_fees_display(self, obj): return f"{obj.total_required_amount} ج.م"
    current_year_fees_display.short_description = "إجمالي المطلوب"

    def total_paid_display(self, obj): return f"{obj.current_year_paid} ج.م"
    total_paid_display.short_description = "إجمالي المحصل"

    def final_remaining_display(self, obj):
        val = obj.final_remaining
        if val > 0:
            return format_html('<span style="color: red; font-weight: bold;">{} ج.م</span>', val)
        return f"{val} ج.م"
    final_remaining_display.short_description = "المتبقي النهائي"

    def old_debt_display(self, obj):
        val = getattr(obj, 'previous_debt', 0)
        return f"{val} ج.م"
    old_debt_display.short_description = "مديونية سابقة"
