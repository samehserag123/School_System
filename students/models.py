from django.contrib.auth.models import User
from django.db import models, transaction
import random
from django.utils import timezone
from django.core.validators import RegexValidator, MinLengthValidator
from audit.models import AuditLog
from django.db.models import Sum, Q
from decimal import Decimal
from django.db import models, transaction
from dateutil.relativedelta import relativedelta


# --- خيارات الفترات الزمنية ---
TERM_CHOICES = [
    ('term1', 'الترم الأول'),
    ('term2', 'الترم الثاني'),
    ('second_session', 'الدور الثاني (ملاحق)'),
]

MONTH_CHOICES = [
    ('10', 'أكتوبر'), ('11', 'نوفمبر'), ('12', 'ديسمبر'),
    ('2', 'فبراير'), ('3', 'مارس'), ('4', 'أبريل'),
]

# --- 1. جدول الغياب والحضور اليومي ---
class AttendanceRecord(models.Model):
    ATTENDANCE_STATUS = [
        ('present', 'حاضر'),
        ('absent', 'غائب'),
        ('excused', 'غياب بعذر'),
    ]

    student = models.ForeignKey('Student', on_delete=models.CASCADE, related_name='attendances', verbose_name="الطالب")
    academic_year = models.ForeignKey('finance.AcademicYear', on_delete=models.CASCADE, verbose_name="العام الدراسي")
    date = models.DateField("تاريخ اليوم", default=timezone.now)
    term = models.CharField("الترم", max_length=20, choices=TERM_CHOICES, default='term1')
    status = models.CharField("الحالة", max_length=10, choices=ATTENDANCE_STATUS, default='present')
    notes = models.CharField("ملاحظات", max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "سجل غياب"
        verbose_name_plural = "سجلات الغياب"
        unique_together = ('student', 'date') # لمنع تكرار تسجيل الغياب لنفس الطالب في نفس اليوم

    def __str__(self):
        return f"{self.student.first_name} - {self.date} - {self.get_status_display()}"


# --- 2. جدول إعادة القيد (للطلاب المفصولين بسبب الغياب) ---
class ReEnrollmentRecord(models.Model):
    STATUS_CHOICES = [
        ('dismissed', 'مفصول لتخطي الغياب'),
        ('re_enrolled', 'تم إعادة القيد'),
    ]
    student = models.ForeignKey('Student', on_delete=models.CASCADE, related_name='reenrollments', verbose_name="الطالب")
    academic_year = models.ForeignKey('finance.AcademicYear', on_delete=models.CASCADE, verbose_name="العام الدراسي")
    dismissal_date = models.DateField("تاريخ الفصل", auto_now_add=True)
    reenrollment_date = models.DateField("تاريخ إعادة القيد", blank=True, null=True)
    status = models.CharField("الحالة", max_length=20, choices=STATUS_CHOICES, default='dismissed')
    fee_paid = models.BooleanField("تم دفع رسوم الإعادة؟", default=False)

    class Meta:
        verbose_name = "سجل إعادة قيد"
        verbose_name_plural = "سجلات إعادة القيد"

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.get_status_display()}"



# --- 3. إعدادات المادة (توسيع لموديل Subject الحالي) ---
class SubjectConfig(models.Model):
    # 🚀 تم التعديل من OneToOneField إلى ForeignKey لربط المادة بأكثر من صف وسنة دراسية
    subject = models.ForeignKey('Subject', on_delete=models.CASCADE, verbose_name="المادة", related_name="configs")
    academic_year = models.ForeignKey('finance.AcademicYear', on_delete=models.CASCADE, verbose_name="العام الدراسي")
    grade = models.ForeignKey('Grade', on_delete=models.CASCADE, verbose_name="الصف الدراسي")

    # توزيع الدرجات المعتمد باللائحة
    max_cultural = models.DecimalField("النهاية العظمى (ثقافي/نظري)", max_digits=5, decimal_places=2, default=50)
    max_practical = models.DecimalField("النهاية العظمى (عملي)", max_digits=5, decimal_places=2, default=50)
    passing_score = models.DecimalField("درجة النجاح الكلية (النهاية الصغرى)", max_digits=5, decimal_places=2, default=50)

    class Meta:
        verbose_name = "توزيع درجات المادة"
        verbose_name_plural = "توزيع درجات المواد"
        unique_together = ('subject', 'grade', 'academic_year') # ضمان عدم تكرار الإعداد للمادة لنفس الصف في نفس السنة

    @property
    def total_max_score(self):
        return self.max_cultural + self.max_practical

    def __str__(self):
        return f"توزيع {self.subject.name} - {self.grade.name}"


class StudentControlSheet(models.Model):
    SUBJECT_STATUS_CHOICES = [
        ('passed', 'ناجح ومجتاز ✅'),
        ('second_session', 'له دور ثانٍ (ملحق) ⚠️'),
        ('failed', 'راسب وباقٍ للإعادة ❌'),
    ]

    student = models.ForeignKey('Student', on_delete=models.CASCADE, related_name='control_records', verbose_name="الطالب")
    subject = models.ForeignKey('Subject', on_delete=models.CASCADE, verbose_name="المادة")
    academic_year = models.ForeignKey('finance.AcademicYear', on_delete=models.CASCADE, verbose_name="العام الدراسي")

    # --- درجات الترم الأول ---
    term1_cultural = models.DecimalField("ترم أول - نظري", max_digits=5, decimal_places=2, default=0)
    term1_practical = models.DecimalField("ترم أول - عملي", max_digits=5, decimal_places=2, default=0)
    term1_is_absent = models.BooleanField("غياب الترم الأول؟", default=False)

    # --- درجات الترم الثاني ---
    term2_cultural = models.DecimalField("ترم ثاني - نظري", max_digits=5, decimal_places=2, default=0)
    term2_practical = models.DecimalField("ترم ثاني - عملي", max_digits=5, decimal_places=2, default=0)
    term2_is_absent = models.BooleanField("غياب الترم الثاني؟", default=False)

    # --- الدور الثاني (الملاحق) ---
    second_session_cultural = models.DecimalField("دور ثانٍ - نظري", max_digits=5, decimal_places=2, default=0)
    second_session_practical = models.DecimalField("دور ثانٍ - عملي", max_digits=5, decimal_places=2, default=0)
    second_session_is_absent = models.BooleanField("غياب الدور الثاني؟", default=False)

    # حالة المادة النهائية داخل الكنترول
    status = models.CharField("الحالة النهائية للمادة", max_length=20, choices=SUBJECT_STATUS_CHOICES, default='second_session')

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "سجل الكنترول السنوي"
        verbose_name_plural = "شيت الكنترول العام (النتائج النهائية)"
        unique_together = ('student', 'subject', 'academic_year') # قفل الكنترول: سطر واحد لكل طالب في المادة سنوياً

    @property
    def term1_total(self):
        """إجمالي درجات الترم الأول"""
        if self.term1_is_absent:
            return Decimal('0.00')
        return self.term1_cultural + self.term1_practical

    @property
    def term2_total(self):
        """إجمالي درجات الترم الثاني"""
        if self.term2_is_absent:
            return Decimal('0.00')
        return self.term2_cultural + self.term2_practical

    @property
    def total_year_score(self):
        """المجموع التراكمي للترمين قبل الدور الثاني"""
        return self.term1_total + self.term2_total

    @property
    def second_session_total(self):
        """إجمالي درجات الدور الثاني"""
        if self.second_session_is_absent:
            return Decimal('0.00')
        return self.second_session_cultural + self.second_session_practical

    def auto_calculate_status(self):
        """دالة ذكية تحسب حالة المادة تلقائياً بناءً على درجات الطالب والحد الأدنى للنجاح"""
        try:
            config = SubjectConfig.objects.filter(
                subject=self.subject,
                grade=self.student.grade,
                academic_year=self.academic_year
            ).first()

            if not config:
                return 'second_session'

            # 1. حالة فحص الدور الأول (ترم 1 + ترم 2)
            if not self.term2_is_absent and self.total_year_score >= config.passing_score:
                return 'passed'

            # 2. حالة فحص الدور الثاني (الملاحق) إذا كان قد رسب بالدور الأول
            if self.second_session_total >= config.passing_score and not self.second_session_is_absent:
                return 'passed'
            elif self.second_session_is_absent or (self.second_session_total < config.passing_score and self.second_session_total > 0):
                return 'failed' # راسب نهائياً وباقي للإعادة في المادة

            return 'second_session' # منتظر امتحان الدور الثاني
        except:
            return self.status

    def save(self, *args, **kwargs):
        # احتساب الحالة تلقائياً قبل الحفظ في الداتابيز
        self.status = self.auto_calculate_status()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"كنترول: {self.student.first_name} - {self.subject.name} ({self.get_status_display()})"




# --- 4. جدول رصد الدرجات (يشمل الشهور، التيرمات، الملاحق) ---
class ExamResult(models.Model):
    EXAM_TYPES = [
        ('month', 'امتحان شهر'),
        ('term', 'امتحان نهاية ترم'),
        ('second_session', 'امتحان دور ثاني'),
    ]

    student = models.ForeignKey('Student', on_delete=models.CASCADE, related_name='exam_results', verbose_name="الطالب")
    subject = models.ForeignKey('Subject', on_delete=models.CASCADE, verbose_name="المادة")
    academic_year = models.ForeignKey('finance.AcademicYear', on_delete=models.CASCADE, verbose_name="العام الدراسي")

    exam_type = models.CharField("نوع الامتحان", max_length=20, choices=EXAM_TYPES, default='term')
    term = models.CharField("الترم", max_length=20, choices=TERM_CHOICES)
    month = models.CharField("الشهر (للامتحانات الشهرية)", max_length=10, choices=MONTH_CHOICES, blank=True, null=True)

    cultural_score = models.DecimalField("درجة النظري (ثقافي)", max_digits=5, decimal_places=2, default=0)
    practical_score = models.DecimalField("درجة العملي", max_digits=5, decimal_places=2, default=0)

    is_absent = models.BooleanField("غائب في الامتحان؟", default=False)

    class Meta:
        verbose_name = "نتيجة امتحان"
        verbose_name_plural = "رصد الدرجات"
        # ضمان عدم رصد درجة لنفس الطالب في نفس المادة لنفس الترم ونفس الشهر مرتين
        unique_together = ('student', 'subject', 'academic_year', 'exam_type', 'term', 'month')

    @property
    def total_score(self):
        if self.is_absent:
            return 0
        return self.cultural_score + self.practical_score

    def __str__(self):
        exam_name = self.get_month_display() if self.exam_type == 'month' else self.get_term_display()
        return f"{self.student.first_name} - {self.subject.name} - {exam_name}"


class SystemSettings(models.Model):
    is_admission_open = models.BooleanField(default=True, verbose_name="فتح باب التقديم (إظهار زر الإضافة)")

    class Meta:
        verbose_name = "إعدادات النظام"
        verbose_name_plural = "إعدادات النظام"

    def __str__(self):
        return "حالة التقديم"



numbers_only = RegexValidator(
    regex=r'^\d+$',
    message='يجب إدخال أرقام فقط.'
)
class Grade(models.Model):
    name = models.CharField("اسم الصف", max_length=100)

    class Meta:
        verbose_name = "صف دراسي"
        verbose_name_plural = "الصفوف الدراسية"

    def __str__(self):
        return self.name


class Classroom(models.Model):
    name = models.CharField("اسم الفصل", max_length=100)
    grade = models.ForeignKey("students.Grade", on_delete=models.CASCADE)

    class Meta:
        verbose_name = "فصل"
        verbose_name_plural = "الفصول"

    def __str__(self):
        return f"{self.grade.name} - {self.name}"


# مفترض وجود هذا الـ Validator مسبقاً في مشروعك
numbers_only = RegexValidator(r'^[0-9]*$', 'يسمح بالأرقام فقط.')



class Student(models.Model):
    # --- الخيارات (Choices) ---
    RELIGION_CHOICES = [("Muslim", "مسلم"), ("Christian", "مسيحي")]

    # 🟢 جميع حالات القيد الشاملة
    STATUS_CHOICES = [
        ("New", "مستجد"),
        ("Promoted", "منقول"),
        ("Retained", "باق"),
        ("Transferred", "محول"),
        ("Dismissed", "مفصول"),
        ("First_Round", "دور أول"),
        ("Second_Round", "دور ثان"),
        ("Graduated", "إتمام مرحلة"),
    ]

    INITIAL_STATUS_CHOICES = STATUS_CHOICES

    GENDER_CHOICES = [('Male', 'بنين'), ('Female', 'بنات')]
    SPECIALIZATION_CHOICES = [
        ("General", "شعبة عامة"),
        ("Host", "فني مضيف"),
        ("Chef", "فن طاهي"),
        ("Internal", "مشرف غرف"),
        ("Kitchen", "مطبخ"),
        ("Restaurant", "مطعم"),
        ("Tourism_Services", "خدمات سياحية"),
    ]

    phone_validator = RegexValidator(
        regex=r'^01[0-9]{9}$',
        message="يجب إدخال رقم موبايل مصري صحيح مكون من 11 رقم"
    )

    national_id_validator = RegexValidator(
        regex=r'^\d{14}$',
        message="الرقم القومي يجب أن يتكون من 14 رقماً فقط."
    )

    # --- البيانات الأساسية ---
    image = models.ImageField("صورة الطالب", upload_to="students/", null=True, blank=True)
    registration_number = models.CharField("رقم القيد", max_length=50, blank=True, null=True)
    first_name = models.CharField("الاسم الأول", max_length=100, db_index=True)
    last_name = models.CharField("اسم العائلة", max_length=100, db_index=True)
    national_id = models.CharField("الرقم القومي", max_length=14, validators=[national_id_validator], unique=True, null=True, blank=True)
    student_code = models.CharField("كود الطالب", max_length=20, unique=True, editable=False, blank=True, null=True)

    # --- البيانات الشخصية ---
    date_of_birth = models.DateField("تاريخ الميلاد", null=True, blank=True)
    birth_place = models.CharField("محل الميلاد", max_length=150, blank=True, null=True)
    gender = models.CharField("النوع", max_length=10, choices=GENDER_CHOICES, null=True, blank=True, db_index=True)
    religion = models.CharField("الديانة", max_length=20, choices=RELIGION_CHOICES, null=True, blank=True, db_index=True)
    nationality = models.CharField("الجنسية", max_length=100, default="مصري", null=True, blank=True)
    address = models.TextField("العنوان", blank=True, null=True)
    study_type = models.CharField('نوع الدراسة', max_length=20, choices=[('Regular', 'انتظام'), ('Workers', 'عمال')], default='Regular', db_index=True)
    mother_name = models.CharField("اسم الأم", max_length=150, null=True, blank=True)
    phone = models.CharField("رقم التليفون", max_length=40, null=True, blank=True)
    whatsapp_number = models.CharField(max_length=11, validators=[phone_validator], verbose_name="رقم الواتساب", blank=True, null=True)
    father_job = models.CharField(max_length=100, verbose_name="وظيفة الأب", blank=True, null=True)

    # --- الحالة الأكاديمية وحالة القيد ---
    # 🟢 1. حالة فتح الملف لأول مرة (ثابتة لا تتغير مع الترحيل)
    initial_status = models.CharField("حالة القيد عند فتح الملف", max_length=20, choices=INITIAL_STATUS_CHOICES, default="New", null=True, blank=True)

    # 🟢 2. حالة الطالب الحالية (تتحدث آلياً مع الترحيل السنوي والكنترول)
    enrollment_status = models.CharField("حالة الطالب الحالية", max_length=20, choices=STATUS_CHOICES, default="New", null=True, blank=True)

    enrollment_notes = models.CharField("ملاحظات حالة القيد", max_length=255, blank=True, null=True)
    integration_status = models.BooleanField("موقف الدمج", default=False, null=True, blank=True, db_index=True)
    specialization = models.CharField("التخصص", max_length=30, choices=SPECIALIZATION_CHOICES, blank=True, null=True, db_index=True)

    # 🟢 3. رسوم فتح الملف والإعفاء منها (تُحسب مرة واحدة فقط عند فتح الملف)
    is_application_fee_exempt = models.BooleanField("معافى من رسوم فتح الملف", default=False)
    application_fee_amount = models.DecimalField("رسوم فتح الملف المسجلة", max_digits=10, decimal_places=2, default=0)

    previous_debt = models.DecimalField("مديونية سابقة مرحلة", max_digits=10, decimal_places=2, default=0)
    last_promotion_date = models.DateField(null=True, blank=True)

    grade = models.ForeignKey("students.Grade", on_delete=models.PROTECT, null=True, verbose_name="الصف الدراسي")
    classroom = models.ForeignKey("students.Classroom", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الفصل")
    academic_year = models.ForeignKey("finance.AcademicYear", on_delete=models.CASCADE, verbose_name="السنة الدراسية", related_name="students")

    is_active = models.BooleanField("نشط", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # حقول الحظر الذكي لبوابة الأمن
    is_blocked_at_gate = models.BooleanField("محظور من الدخول يدوياً", default=False)
    gate_block_reason = models.CharField("سبب حظر البوابة", max_length=255, blank=True, null=True)
    gate_blocked_from = models.DateField("تاريخ بدء الحظر", null=True, blank=True)
    gate_blocked_to = models.DateField("تاريخ نهاية الحظر", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "طالب"
        verbose_name_plural = "الطلاب"
        indexes = [
            models.Index(fields=['first_name', 'id']),
        ]

    # ----------------------------------------------------------------
    # 2. الدوال الأساسية (Standard Methods)
    # ----------------------------------------------------------------
    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        first = self.first_name if self.first_name else ""
        last = self.last_name if self.last_name else ""
        full = f"{first} {last}".strip()
        return full if full else f"طالب رقم {self.student_code}"

    def generate_unique_code(self):
        year_prefix = str(timezone.now().year)
        while True:
            random_num = str(random.randint(1000, 9999))
            code = f"{year_prefix}{random_num}"
            if not Student.objects.filter(student_code=code).exists():
                return code

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        # 1. توليد كود الطالب أوتوماتيكياً
        if not self.student_code:
            self.student_code = self.generate_unique_code()

        # 2. عند إنشاء الطالب لأول مرة فقط (فتح الملف)
        if is_new:
            # مزامنة حالة القيد الحالية مع حالة التقديم
            if self.initial_status and not self.enrollment_status:
                self.enrollment_status = self.initial_status
            elif self.enrollment_status and not self.initial_status:
                self.initial_status = self.enrollment_status

            # معالجة رسوم فتح الملف (تأخذ رسوم السنة الحالية وتُحفظ كقيمة ثابتة للطالب)
            if self.is_application_fee_exempt:
                self.application_fee_amount = Decimal('0.00')
            else:
                if self.application_fee_amount == Decimal('0.00') and self.academic_year:
                    # جلب قيمة رسوم فتح الملف المحددة في موديل السنة الدراسية إن وجدت
                    year_fee = getattr(self.academic_year, 'application_fee', Decimal('0.00'))
                    self.application_fee_amount = Decimal(str(year_fee))

        super().save(*args, **kwargs)

    # ----------------------------------------------------------------
    # 3. الدوال الحسابية والخاصيات (Properties)
    # ----------------------------------------------------------------
    @property
    def total_absolute_remaining(self):
        from django.db.models import Sum
        from finance.models import Payment

        old_debt = Decimal(str(self.previous_debt or 0))
        app_fee = Decimal(str(self.application_fee_amount or 0))

        total_fees_all_years = Decimal('0.00')
        for acc in self.accounts.all():
            total_fees_all_years += (Decimal(str(acc.total_fees or 0)) - Decimal(str(acc.discount or 0)))

        total_paid_ever = Payment.objects.filter(student=self).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
        total_paid_ever = Decimal(str(total_paid_ever))

        remaining = (old_debt + app_fee + total_fees_all_years) - total_paid_ever
        return max(remaining, Decimal('0.00'))

    @property
    def total_required_amount(self):
        return self.current_year_fees_amount

    @property
    def current_year_paid(self):
        from finance.models import Payment
        from django.db.models import Sum, Q
        total = Payment.objects.filter(
            student=self,
            academic_year=self.academic_year
        ).filter(
            Q(revenue_category__name__icontains="اساس") |
            Q(revenue_category__name__icontains="مصروف") |
            Q(revenue_category__name__icontains="ملف")
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        return Decimal(str(total))

    @property
    def final_remaining(self):
        old_debt = Decimal(str(self.previous_debt or 0))
        app_fee = Decimal(str(self.application_fee_amount or 0))

        acc = self.accounts.filter(academic_year=self.academic_year).last()
        current_fees = Decimal('0.00')
        if acc:
            current_fees = Decimal(str(acc.total_fees or 0)) - Decimal(str(acc.discount or 0))

        total_paid = self.current_year_paid
        remaining = (old_debt + app_fee + current_fees) - total_paid
        return max(remaining, Decimal('0.00'))

    def calculated_remaining(self):
        return self.final_remaining

    @property
    def calculated_previous_debt(self):
        return max(Decimal('0.00'), Decimal(str(self.previous_debt or 0)))

    @property
    def total_balance_due(self):
        from django.db.models import Sum
        total_required = Decimal(str(self.previous_debt or 0)) + Decimal(str(self.application_fee_amount or 0)) + self.current_year_fees_amount
        current_year_paid = self.all_payments.filter(
            academic_year=self.academic_year
        ).aggregate(total=Sum('amount_paid'))['total'] or 0

        return total_required - Decimal(str(current_year_paid))

    @property
    def current_year_fees_amount(self):
        account = self.accounts.filter(academic_year=self.academic_year).first()
        if account:
            return Decimal(str(account.total_fees or 0))
        return Decimal("0.00")

    @property
    def full_name(self):
        return self.get_full_name()

    @property
    def name(self):
        return self.get_full_name()

    @property
    def current_account(self):
        return self.accounts.filter(academic_year=self.academic_year).first()


# class Student(models.Model):
#     # --- الخيارات (Choices) ---
#     RELIGION_CHOICES = [("Muslim", "مسلم"), ("Christian", "مسيحي")]
#     STATUS_CHOICES = [
#         ("New", "مستجد"),
#         ("Promoted", "منقول"),
#         ("Retained", "باق"),
#         ("Transferred", "محول"),
#         ("Dismissed", "مفصول"),
#         ("First_Round", "دور أول"),
#         ("Second_Round", "دور ثان"),
#         ("Graduated", "إتمام مرحلة"),
#     ]
#     GENDER_CHOICES = [('Male', 'بنين'), ('Female', 'بنات')]
#     SPECIALIZATION_CHOICES = [
#     ("General", "شعبة عامة"),
#     ("Host", "فني مضيف"),           # مفتاح فريد خاص بـ فني مضيف
#     ("Chef", "فن طاهي"),            # مفتاح فريد خاص بـ فن طاهي
#     ("Internal", "مشرف غرف"),
#     ("Kitchen", "مطبخ"),
#     ("Restaurant", "مطعم"),         # مفتاح فريد خاص بـ مطعم
#     ("Tourism_Services", "خدمات سياحية"),
# ]

#     phone_validator = RegexValidator(
#         regex=r'^01[0-9]{9}$',
#         message="يجب إدخال رقم موبايل مصري صحيح مكون من 11 رقم"
#     )

#     # --- البيانات الأساسية ---
#     image = models.ImageField("صورة الطالب", upload_to="students/", null=True, blank=True)
#     # جعلنا رقم القيد اختيارياً وغير فريد (أو فريد مع السماح بالقيم الفارغة)
#     registration_number = models.CharField("رقم القيد", max_length=50, blank=True, null=True)
#     first_name = models.CharField("الاسم الأول", max_length=100, db_index=True)
#     last_name = models.CharField("اسم العائلة", max_length=100, db_index=True)

#     # 1. إضافة الرقم القومي مع التحقق (14 رقم فقط)
#     national_id_validator = RegexValidator(
#         regex=r'^\d{14}$',
#         message="الرقم القومي يجب أن يتكون من 14 رقماً فقط."
#     )
#     national_id = models.CharField(
#         "الرقم القومي", max_length=14, validators=[national_id_validator],
#         unique=True, null=True, blank=True
#     )

#     # 2. كود الطالب (تلقائي)
#     student_code = models.CharField("كود الطالب", max_length=20, unique=True, editable=False, blank=True, null=True)

#     # --- البيانات الشخصية ---
#     date_of_birth = models.DateField("تاريخ الميلاد", null=True, blank=True)
#     birth_place = models.CharField("محل الميلاد", max_length=150, blank=True, null=True)

#     # إضافة null و blank للنوع
#     gender = models.CharField("النوع", max_length=10, choices=GENDER_CHOICES, null=True, blank=True, db_index=True)
#     religion = models.CharField("الديانة", max_length=20, choices=RELIGION_CHOICES, null=True, blank=True, db_index=True)
#     nationality = models.CharField("الجنسية", max_length=100, default="مصري", null=True, blank=True)
#     address = models.TextField("العنوان", blank=True, null=True)
#     study_type = models.CharField('نوع الدراسة', max_length=20, choices=[('Regular', 'انتظام'), ('Workers', 'عمال')], default='Regular', db_index=True)
#     mother_name = models.CharField("اسم الأم", max_length=150, null=True, blank=True)
#     phone = models.CharField("رقم التليفون", max_length=40, null=True, blank=True)
#     whatsapp_number = models.CharField(
#         max_length=11,
#         validators=[phone_validator],
#         verbose_name="رقم الواتساب",
#         blank=True,
#         null=True
#     )
#     father_job = models.CharField(max_length=100, verbose_name="وظيفة الأب", blank=True, null=True)
#     # --- الحالة الأكاديمية ---
#     # جعل حالة القيد اختيارية
#     enrollment_status = models.CharField("حالة القيد", max_length=20, choices=STATUS_CHOICES, null=True, blank=True)
#     enrollment_notes = models.CharField("ملاحظات حالة القيد", max_length=255, blank=True, null=True)

#     # الدمج (BooleanField يفضل أن يكون له default لكن وضعنا null=True ليكون اختيارياً تماماً)
#     integration_status = models.BooleanField("موقف الدمج", default=False, null=True, blank=True, db_index=True)

#     specialization = models.CharField("التخصص", max_length=30, choices=SPECIALIZATION_CHOICES, blank=True, null=True, db_index=True)
#     previous_debt = models.DecimalField("مديونية سابقة مرحلة", max_digits=10, decimal_places=2, default=0)
#     last_promotion_date = models.DateField(null=True, blank=True)

#     grade = models.ForeignKey("students.Grade", on_delete=models.PROTECT, null=True, verbose_name="الصف الدراسي")
#     classroom = models.ForeignKey("students.Classroom", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الفصل")
#     academic_year = models.ForeignKey("finance.AcademicYear", on_delete=models.CASCADE, verbose_name="السنة الدراسية", related_name="students")

#     is_active = models.BooleanField("نشط", default=True)
#     created_at = models.DateTimeField(auto_now_add=True)

#     # حقول الحظر الذكي لبوابة الأمن
#     is_blocked_at_gate = models.BooleanField("محظور من الدخول يدوياً", default=False)
#     gate_block_reason = models.CharField("سبب حظر البوابة", max_length=255, blank=True, null=True)
#     gate_blocked_from = models.DateField("تاريخ بدء الحظر", null=True, blank=True)
#     gate_blocked_to = models.DateField("تاريخ نهاية الحظر", null=True, blank=True)

#     class Meta:
#         ordering = ["-created_at"]
#         verbose_name = "طالب"
#         verbose_name_plural = "الطلاب"
#         # الفهرس المشترك للترتيب السريع في شاشة القائمة
#         indexes = [
#             models.Index(fields=['first_name', 'id']),
#         ]

#     # ----------------------------------------------------------------
#     # 2. الدوال الأساسية (Standard Methods)
#     # ----------------------------------------------------------------
#     def __str__(self):
#         # اعتماد الدالة الرئيسية لعرض الطالب في القوائم ولوحة التحكم
#         return self.get_full_name()

#     @property
#     def total_absolute_remaining(self):
#         from decimal import Decimal
#         from django.db.models import Sum
#         from finance.models import Payment  # استيراد الموديل مباشرة

#         # 1. المديونية القديمة
#         old_debt = Decimal(str(self.previous_debt or 0))

#         # 2. إجمالي كل رسوم السنوات
#         total_fees_all_years = Decimal('0.00')
#         # ملحوظة: تأكد أن الـ related_name في StudentAccount هو 'accounts'
#         for acc in self.accounts.all():
#             total_fees_all_years += (Decimal(str(acc.total_fees or 0)) - Decimal(str(acc.discount or 0)))

#         # 3. الحل النهائي: البحث عن المدفوعات باسم الحقل مباشرة
#         total_paid_ever = Payment.objects.filter(student=self).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
#         total_paid_ever = Decimal(str(total_paid_ever))

#         remaining = (old_debt + total_fees_all_years) - total_paid_ever
#         return max(remaining, Decimal('0.00'))


#     def get_full_name(self):
#         # معالجة آمنة للحقول الفارغة لمنع ظهور None
#         first = self.first_name if self.first_name else ""
#         last = self.last_name if self.last_name else ""
#         full = f"{first} {last}".strip()

#         # إذا كان الاسم فارغاً، نرجع كود الطالب
#         return full if full else f"طالب رقم {self.student_code}"

#     def save(self, *args, **kwargs):
#         # توليد كود الطالب تلقائياً عند الإضافة لأول مرة فقط
#         if not self.student_code:
#             self.student_code = self.generate_unique_code()
#         super().save(*args, **kwargs)

#     def generate_unique_code(self):
#         # توليد كود يبدأ بسنة الالتحاق + رقم عشوائي (مثال: 20260001)
#         year_prefix = str(timezone.now().year)
#         while True:
#             random_num = str(random.randint(1000, 9999))
#             code = f"{year_prefix}{random_num}"
#             if not Student.objects.filter(student_code=code).exists():
#                 return code


#     @property
#     def total_required_amount(self):
#         # ❌ متضيفش previous_debt هنا
#         return self.current_year_fees_amount
#         # 1. إجمالي المطلوب (السنة دي + المديونية اللي اترحلّت في الحقل)



#     @property
#     def current_year_paid(self):
#         from finance.models import Payment
#         from django.db.models import Sum, Q
#         total = Payment.objects.filter(
#             student=self,
#             academic_year=self.academic_year # شرط السنة الحالية
#         ).filter(
#             Q(revenue_category__name__icontains="اساس") |
#             Q(revenue_category__name__icontains="مصروف")
#         ).aggregate(total=Sum('amount_paid'))['total'] or 0
#         return Decimal(str(total))


#     # students/models.py

#     @property
#     def final_remaining(self):
#         from decimal import Decimal
#         # 1. المديونية المرحلة (القديمة)
#         old_debt = Decimal(str(self.previous_debt or 0))

#         # 2. صافي مصاريف السنة الحالية (المصاريف - الخصم)
#         acc = self.accounts.filter(academic_year=self.academic_year).last()
#         current_fees = Decimal('0.00')
#         if acc:
#             # طرح الخصم من إجمالي المصاريف
#             current_fees = Decimal(str(acc.total_fees or 0)) - Decimal(str(acc.discount or 0))

#         # 3. إجمالي المدفوعات المسجلة للسنة الحالية
#         total_paid = self.current_year_paid

#         # المعادلة: (قديم + جديد) - مدفوع
#         remaining = (old_debt + current_fees) - total_paid
#         return max(remaining, Decimal('0.00'))

#     # إضافة "Alias" أو اسم مستعار للدالة ليتوافق مع الكود القديم إذا أردت
#     def calculated_remaining(self):
#         return self.final_remaining

#         @property
#         def calculated_previous_debt(self):
#             from decimal import Decimal

#             return max(Decimal('0.00'), Decimal(str(self.previous_debt or 0)))



#     @property
#     def total_balance_due(self):
#         from decimal import Decimal
#         from django.db.models import Sum

#         total_required = Decimal(str(self.previous_debt or 0)) + self.current_year_fees_amount

#         current_year_paid = self.all_payments.filter(
#             academic_year=self.academic_year
#         ).aggregate(total=Sum('amount_paid'))['total'] or 0

#         return total_required - Decimal(str(current_year_paid))


#     @property
#     def current_year_fees_amount(self):
#         """جلب إجمالي المصروفات المطلوبة من حساب الطالب للسنة الحالية"""
#         from finance.models import StudentAccount
#         from decimal import Decimal

#         # البحث عن حساب الطالب المرتبط بالسنة الدراسية الحالية
#         account = self.accounts.filter(academic_year=self.academic_year).first()

#         if account:
#             # نستخدم Decimal لضمان دقة الحسابات المالية ومنع أخطاء التقريب
#             return Decimal(str(account.total_fees or 0))

#         # لو الطالب مش متسكن له حساب، نرجع صفر عشان السيستم ما يضربش
#         return Decimal("0.00")

#     @property
#     def full_name(self):
#         return self.get_full_name()

#     @property
#     def name(self):
#         return self.get_full_name()

#     @property
#     def current_account(self):
#         return self.accounts.filter(academic_year=self.academic_year).first()


# ----------------------------------------------------------------
# الجداول الجديدة: المدرسين، المواد، والكورسات
# ----------------------------------------------------------------
class RemedialFeeSetting(models.Model):
    """
    جدول مخصص للأدمن لتحديد سعر مادة البرنامج العلاجي لكل عام دراسي
    """
    # نستخدم 'finance.AcademicYear' بدلاً من 'AcademicYear' فقط
    academic_year = models.OneToOneField('finance.AcademicYear', on_delete=models.CASCADE, verbose_name="العام الدراسي")
    fee_per_subject = models.DecimalField(max_digits=10, decimal_places=2, default=150.00, verbose_name="رسوم المادة الواحدة")

    def __str__(self):
        return f"رسوم العلاجي - {self.academic_year.name}"

class RemedialProgramRecord(models.Model):
    """
    جدول لتسجيل الطلاب في البرنامج العلاجي (من قبل شئون الطلاب)
    """
    student = models.ForeignKey('Student', on_delete=models.CASCADE, verbose_name="الطالب")
    # نستخدم 'finance.AcademicYear' هنا أيضاً
    academic_year = models.ForeignKey('finance.AcademicYear', on_delete=models.CASCADE, verbose_name="العام الدراسي")
    subjects_count = models.PositiveIntegerField(default=1, verbose_name="عدد المواد المتخلف عنها")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="إجمالي الرسوم المطلوبة")
    is_paid = models.BooleanField(
        default=False,
        verbose_name="تم السداد؟",
        db_index=True  # 🟢 إضافة الفهرس هنا لتسريع فلترة المسدد وغير المسدد
    )
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")

    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, verbose_name="مسجل البيان")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.subjects_count} مواد"

class Teacher(models.Model):
    name = models.CharField("اسم المدرس", max_length=150)
    phone = models.CharField("رقم الهاتف", max_length=20, validators=[numbers_only], blank=True, null=True)
    is_active = models.BooleanField("نشط", default=True)

    class Meta:
        verbose_name = "مدرس"
        verbose_name_plural = "اسماء المدرسون"

    def __str__(self):
        return self.name


# 1. المواد الدراسية
class Subject(models.Model):
    name = models.CharField("اسم المادة الدراسية", max_length=100, unique=True)

    class Meta:
        verbose_name = "مادة دراسية"
        verbose_name_plural = "المواد الدراسية"

    def __str__(self):
        return self.name

# 2. الزي المدرسي
class Uniform(models.Model):
    name = models.CharField("نوع الزي", max_length=100, unique=True)

    class Meta:
        verbose_name = "الزي"
        verbose_name_plural = "الزي المدرسي"

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    ITEM_TYPE_CHOICES = [
        ('book', 'كتاب دراسي'),
        ('uniform', 'زي مدرسي'),
    ]

    item_type = models.CharField("نوع الصنف", max_length=10, choices=ITEM_TYPE_CHOICES, default='book', db_index=True)
    subject = models.ForeignKey('Subject', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المادة (للكتب)")
    uniform = models.ForeignKey('Uniform', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الزي (للملابس)")
    grade = models.ForeignKey('Grade', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الصف الدراسي")

    # ⚠️ هذا الحقل يمثل الرصيد الذي بدأت به (الافتتاحي)
    stock_quantity = models.PositiveIntegerField("الرصيد الافتتاحي", default=0)

    class Meta:
        unique_together = ('item_type', 'subject', 'uniform', 'grade')
        verbose_name = "صنف مخزني (جرد)"
        verbose_name_plural = "المخزن (الجرد التفصيلي)"
        ordering = ['id']

    @property
    def display_name(self):
        """عرض الاسم الرسمي الذكي للصنف وتجنب عبارة 'صنف غير محدد' نهائياً"""
        if self.item_type == 'book':
            if self.subject:
                return f"كتاب {self.subject.name}"
            elif self.grade:
                return f"الكتب الدراسية ({self.grade.name})"
            return "الكتب الدراسية"
        elif self.item_type == 'uniform':
            if self.uniform:
                return f"{self.uniform.name}"
            elif self.grade:
                return f"الزي المدرسي ({self.grade.name})"
            return "الزي المدرسي"
        return "مقررات ومستلزمات دراسية"

    @property
    def item_type_label(self):
        """تسمية نصية صريحة لنوع الصنف"""
        return "الكتب الدراسية" if self.item_type == 'book' else "الزي المدرسي"

    @property
    def total_incoming(self):
        """إجمالي الوارد (الرصيد الافتتاحي + التوريدات الإضافية)"""
        from django.db.models import Sum
        restocks_qty = self.restocks.aggregate(total=Sum('quantity'))['total'] or 0
        return self.stock_quantity + restocks_qty

    @property
    def total_sold_count(self):
        """إجمالي المنصرف (المبيعات والإذونات)"""
        from django.db.models import Sum
        return self.booksale_set.aggregate(total=Sum('quantity'))['total'] or 0

    @property
    def remaining_qty(self):
        """الرصيد الحالي الفعلي المتبقي في الرفوف"""
        return max(0, self.total_incoming - self.total_sold_count)

    def __str__(self):
        grade_str = f" - {self.grade.name}" if self.grade else ""
        return f"{self.display_name}{grade_str}"


# سجل عمليات التوريد (الوارد)
class InventoryRestock(models.Model):
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='restocks')
    quantity = models.PositiveIntegerField(verbose_name="الكمية الموردة")
    restock_date = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التوريد")
    note = models.CharField(max_length=255, blank=True, verbose_name="ملاحظات (مثل اسم المورد)")

    def __str__(self):
        return f"وارد: {self.quantity} لـ {self.item}"


# 4. أسعار الباقات المالية لكل صف
class GradePackagePrice(models.Model):
    academic_year = models.ForeignKey('finance.AcademicYear', on_delete=models.CASCADE, verbose_name="السنة الدراسية")
    grade = models.ForeignKey('Grade', on_delete=models.CASCADE, verbose_name="الصف الدراسي")
    books_price = models.DecimalField("سعر باقة الكتب الإجمالي", max_digits=10, decimal_places=2, default=0)
    uniform_price = models.DecimalField("سعر باقة الزي الإجمالي", max_digits=10, decimal_places=2, default=0)

    class Meta:
        # منع تكرار السعر لنفس الصف في نفس السنة
        unique_together = ('academic_year', 'grade')
        verbose_name = "سعر باقة الصف"
        verbose_name_plural = "أسعار باقات الصفوف"

    def __str__(self):
        return f"أسعار {self.grade.name} - {self.academic_year.name}"


# 5. أسعار المجموعات والكورسات (التعريفة المالية)
class SubjectPrice(models.Model):
    SESSION_TYPE_CHOICES = [
        ('group', 'مجموعة (Group)'),
        ('individual', 'كورس (فردي)'),
        ('online', 'أونلاين (Online)'),
        ('revision', 'مراجعة نهائية'),
        ('vip', 'خاص (VIP)'),
    ]

    teacher = models.ForeignKey('Teacher', on_delete=models.CASCADE, verbose_name="المدرس")
    subject = models.ForeignKey('Subject', on_delete=models.CASCADE, verbose_name="المادة")
    grade = models.ForeignKey('Grade', on_delete=models.CASCADE, verbose_name="الصف الدراسي")
    session_type = models.CharField("نوع الكورس / التدريس", max_length=20, choices=SESSION_TYPE_CHOICES, default='group')
    price = models.DecimalField("سعر الكورس / الباقة", max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "تعريفة سعر كورس / مجموعة"
        verbose_name_plural = "أسعار المجموعات والاشتراكات (ربط السعر الكورس)"
        unique_together = ('teacher', 'subject', 'grade', 'session_type')

    def __str__(self):
        return f"{self.subject.name} - {self.teacher.name} ({self.get_session_type_display()}) - {self.price} ج.م"


class BookSale(models.Model):
    STATUS_CHOICES = [
        ('pending', 'لم يكتمل السداد'),
        ('paid', 'تم السداد بالكامل'),
        ('delivered', 'تم التسليم فعلياً'),
    ]

    student = models.ForeignKey('Student', on_delete=models.CASCADE, verbose_name="الطالب")
    item = models.ForeignKey('InventoryItem', on_delete=models.CASCADE, verbose_name="الصنف")
    quantity = models.PositiveIntegerField("الكمية", default=1)

    total_amount = models.DecimalField("الإجمالي المطلوب", max_digits=10, decimal_places=2, default=0)

    # حقل "المبلغ المدفوع الآن" - يستخدم لاستلام المبلغ من شاشة الصرف مباشرة
    pay_now = models.DecimalField("المبلغ المدفوع الآن", max_digits=10, decimal_places=2, default=0)

    status = models.CharField("حالة الحركة", max_length=20, choices=STATUS_CHOICES, default='pending')

    is_delivered = models.BooleanField("تم الاستلام من المخزن؟", default=False, db_index=True)
    delivered_at = models.DateTimeField("تاريخ التسليم الفعلي", null=True, blank=True)
    delivered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="الموظف المسلم",
        related_name="delivered_sales"
    )

    sale_date = models.DateTimeField(
        "تاريخ الحركة",
        auto_now_add=True,
        db_index=True  # 🟢 إضافة الفهرس لتسريع الـ ORDER BY
    )

    class Meta:
        verbose_name = "إذن استلام ومبيعات"
        verbose_name_plural = "إذونات الاستلام والمبيعات"

    @property
    def calculated_paid_amount(self):
        """حساب إجمالي المدفوعات المسجلة في الخزينة برقم هذا الإذن #ID"""
        if not self.pk:
            return Decimal('0.00')

        from treasury.models import GeneralLedger
        from django.db.models import Sum

        total = GeneralLedger.objects.filter(
            notes__icontains=f"#{self.pk}"
        ).aggregate(total=Sum('amount'))['total'] or 0
        return Decimal(str(total))

    @property
    def remaining_amount(self):
        """حساب المتبقي الحقيقي للباقة بدون تسريب أو مديونيات مزدوجة"""
        total = Decimal(str(self.total_amount or 0))
        if total <= Decimal('0.00'):
            return Decimal('0.00')

        if self.student and self.item:
            item_type = self.item.item_type
            sales_same_type = BookSale.objects.filter(student=self.student, item__item_type=item_type)
            total_paid_for_type = sum(s.calculated_paid_amount for s in sales_same_type)

            # إذا سدد الطالب سعر الباقة بالكامل في الخزينة
            if total_paid_for_type >= total:
                return Decimal('0.00')

            return max(Decimal('0.00'), total - total_paid_for_type)

        return max(Decimal('0.00'), total - self.calculated_paid_amount)

    def mark_as_delivered(self, user):
        """تأكيد التسليم الفعلي من أمين المخزن وتوثيق الموظف والوقت"""
        self.is_delivered = True
        self.delivered_at = timezone.now()
        self.delivered_by = user
        if self.remaining_amount <= 0 and self.total_amount > 0:
            self.status = 'delivered'
        self.save()

    def save(self, *args, **kwargs):
        # 1. جلب الموظف الحالي الممرر عبر الـ View (إن وجد)
        current_user = getattr(self, '_current_user', None)

        # 2. جلب سعر الباقة أوتوماتيكياً من صف الطالب بأسلوب آمن يمنع خطأ DoesNotExist
        if not self.total_amount or Decimal(str(self.total_amount)) == Decimal('0.00'):
            try:
                from .models import GradePackagePrice
                package = GradePackagePrice.objects.filter(
                    grade=self.student.grade,
                    academic_year=self.student.academic_year
                ).first()

                if package:
                    price = package.books_price if self.item.item_type == 'book' else package.uniform_price
                    self.total_amount = Decimal(str(price or 0)) * self.quantity
                else:
                    self.total_amount = Decimal('0.00')
            except Exception:
                self.total_amount = Decimal('0.00')

        # 3. الحفظ الأساسي لتوليد المفتاح الرئيسي ID لاستخدامه في شجرة الخزينة
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # 4. الربط الآلي مع الخزينة العامة عند إدخال مبلغ محصل فورياً
        pay_now_val = Decimal(str(getattr(self, 'pay_now', 0) or 0))
        if is_new and pay_now_val > Decimal('0.00'):
            from treasury.models import GeneralLedger

            GeneralLedger.objects.create(
                student=self.student,
                amount=pay_now_val,
                notes=f"سداد آلي لإذن استلام رقم #{self.pk}",
                receipt_number=f"BS-{self.pk}",
                collected_by=current_user
            )

        # 5. تحديث الحالة النهائية للإذن ومزامنتها في الذاكرة وقاعدة البيانات
        actual_paid = self.calculated_paid_amount

        if self.is_delivered:
            new_status = 'delivered'
        elif actual_paid >= self.total_amount and self.total_amount > 0:
            new_status = 'paid'
        else:
            new_status = 'pending'

        if new_status != self.status:
            self.status = new_status
            type(self).objects.filter(pk=self.pk).update(status=new_status)

    @property
    def status_label(self):
        """عرض حالة السداد والتسليم نصياً بأسلوب واضح لتقارير والواجهات"""
        if self.is_delivered:
            return "تم التسليم من المخزن ✅"

        remaining = self.remaining_amount
        if remaining <= 0 and self.total_amount > 0:
            return "تم السداد بالكامل (جاهز للتسليم)"
        elif self.calculated_paid_amount > 0:
            return f"سداد جزئي (متبقي {remaining} ج.م)"
        return "لم يتم السداد"

    def __str__(self):
        item_name = self.item.display_name if self.item else "صنف غير محدد"
        return f"{self.student.get_full_name()} - {item_name}"


class ExternalStudent(models.Model):
    full_name = models.CharField("اسم الطالب", max_length=200)
    phone_number = models.CharField("رقم التليفون", max_length=15)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # سنضيف رقم الهاتف بجانب الاسم لتمييزهم في لوحة التحكم
        return f"{self.full_name} - {self.phone_number}"

class CourseGroup(models.Model):
    student = models.ForeignKey(
        'Student',
        on_delete=models.CASCADE,
        null=True,  # 🟢 إضافة هذه
        blank=True, # 🟢 إضافة هذه
        verbose_name="الطالب المدرسي",
        related_name="enrolled_courses"
    )
    # حقل الطالب الخارجي (الذي أضفناه سابقاً)
    external_student = models.ForeignKey(
        'ExternalStudent',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="الطالب الخارجي"
    )
    course_info = models.ForeignKey('SubjectPrice', on_delete=models.PROTECT, verbose_name="بيانات الكورس والسعر")
    registration_date = models.DateField("تاريخ الاشتراك", auto_now_add=True)
    notes = models.TextField("ملاحظات إضافية", blank=True, null=True)
    required_amount = models.DecimalField("المبلغ المطلوب", max_digits=10, decimal_places=2, default=0.00)
    total_sessions = models.PositiveIntegerField("إجمالي عدد الحصص المتفق عليها", default=8)
    # حقل اختياري لتحديد موعد البدء الفعلي
    start_date = models.DateField("تاريخ بدء الحصص", default=timezone.now)

    class Meta:
        verbose_name = "تسجيل كورس لطالب"
        verbose_name_plural = "سجل اشتراكات الطلاب"

    # --- الدوال الحسابية والذكية ---

    @property
    def total_paid(self):
        """يجمع كل المبالغ المدفوعة لهذا الكورس من جدول التحصيلات"""
        return self.payments.aggregate(total=Sum('amount_paid'))['total'] or 0
    @property
    def remaining_amount(self):
        """يحسب المتبقي بناءً على المبلغ المطلوب فعلياً (المربوط بعدد الحصص)"""
        return self.required_amount - self.total_paid
    @property
    def attended_sessions_count(self):
        """حساب عدد الحصص التي حضرها الطالب فعلياً"""
        return self.sessions.filter(attendance_status='attended').count()
    @property
    def remaining_sessions(self):
        """حساب عدد الحصص المتبقية للطالب بناءً على إجمالي الحصص المتفق عليها"""
        return max(0, self.total_sessions - self.attended_sessions_count)
    @property
    def session_status_label(self):
        """تنبيه نصي بحالة الحصص لراحة المستخدم"""
        rem = self.remaining_sessions
        if rem == 0:
            return "انتهت الحصص (يجب التجديد) ⚠️"
        return f"متبقي {rem} حصة"
    @property
    def payment_status(self):
        """تحديد حالة الدفع بناءً على المبلغ المطلوب المخصص"""
        remaining = self.remaining_amount
        if remaining <= 0:
            return "خالص ✅"
        return f"باقي {remaining} ج.م"
    def __str__(self):
        """تعديل لعرض اسم الطالب المدرسي أو الخارجي بشكل صحيح"""
        # التحقق من وجود طالب مدرسي أولاً، وإلا استخدام اسم الطالب الخارجي
        student_name = self.student.get_full_name() if self.student else self.external_student.full_name
        return f"{student_name} - {self.course_info.subject.name}"

class StudentSession(models.Model):
    """الجدول الجديد لتسجيل كل حصة وتاريخها"""
    STATUS_CHOICES = [
        ('attended', 'حضر'),
        ('absent', 'غائب'),
        ('cancelled', 'ملغاة من المركز'),
    ]

    course_enrollment = models.ForeignKey(CourseGroup, on_delete=models.CASCADE, related_name="sessions")
    session_date = models.DateField("تاريخ الحصة", default=timezone.now)
    attendance_status = models.CharField("حالة الحضور", max_length=20, choices=STATUS_CHOICES, default='attended')
    notes = models.CharField("ملاحظات/تقييم الحصة", max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "حصة طالب"
        verbose_name_plural = "تتبع حصص الطلاب"
        # منع تكرار تسجيل حضور لنفس الطالب في نفس الكورس بنفس التاريخ
        unique_together = ('course_enrollment', 'session_date')

    def __str__(self):
        return f"حصة {self.course_enrollment.student.first_name} - {self.session_date}"


# 2. الكلاس الجديد: سجل تحصيلات الكورسات (الخزينة المنفصلة)
class CoursePayment(models.Model):
    # نربطه بالاشتراك (CourseGroup) وليس بالطالب مباشرة لتعرف هذا المبلغ دفع لأي مادة
    course_enrollment = models.ForeignKey(CourseGroup, on_delete=models.CASCADE, verbose_name="الاشتراك", related_name="payments")
    amount_paid = models.DecimalField("المبلغ المدفوع حالياً", max_digits=10, decimal_places=2)
    payment_date = models.DateTimeField("تاريخ ووقت التحصيل", auto_now_add=True)
    collected_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المحصل")
    notes = models.TextField("ملاحظات الدفع", blank=True, null=True)

    class Meta:
        verbose_name = "عملية تحصيل كورس"
        verbose_name_plural = "3. سجل تحصيلات الكورسات (الخزينة)"

    def __str__(self):
        return f"تحصيل {self.amount_paid} من {self.course_enrollment.student}"



# أضف هذه الدوال داخل كلاس Student في ملف models.py
    @property
    def book_sales_summary(self):
        """تعطي ملخصاً للطالب: هل عليه مبالغ متأخرة في الكتب/الزي؟"""
        sales = self.booksale_set.all()
        total_required = sum(s.total_amount for s in sales)
        total_paid = sum(s.paid_amount for s in sales)
        pending_delivery = sales.filter(is_delivered=False, status='paid').count()

        return {
            'total_due': total_required - total_paid,
            'pending_items_count': pending_delivery, # أشياء دفع ثمنها ولم يستلمها
        }


class BusRoute(models.Model):
    """جدول خطوط الباصات"""
    name = models.CharField("اسم الخط / المنطقة", max_length=150, unique=True)
    driver_name = models.CharField("اسم السائق", max_length=100, blank=True, null=True)
    driver_phone = models.CharField("هاتف السائق", max_length=20, blank=True, null=True)
    bus_number = models.CharField("رقم اللوحة", max_length=50, blank=True, null=True)
    capacity = models.PositiveIntegerField("سعة الباص (عدد الكراسي)", default=20)

    # أسعار الخط (يمكن تركها 0 وتحديد السعر وقت الاشتراك)
    monthly_price = models.DecimalField("السعر الشهري", max_digits=10, decimal_places=2, default=0)
    term_price = models.DecimalField("سعر التيرم", max_digits=10, decimal_places=2, default=0)
    yearly_price = models.DecimalField("السعر السنوي", max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = "خط باص"
        verbose_name_plural = "خطوط الباصات"

    @property
    def current_occupancy(self):
        """يحسب عدد الطلاب المشتركين حالياً في هذا الخط"""
        return self.subscriptions.filter(is_active=True).count()

    def __str__(self):
        return f"{self.name} (سعة: {self.capacity})"


class BusSubscription(models.Model):
    """جدول اشتراكات الطلاب في الباص"""
    SUBSCRIPTION_TYPES = [
        ('monthly', 'شهري'),
        ('term', 'تيرم (فصل دراسي)'),
        ('yearly', 'سنوي (عام كامل)'),
        ('custom', 'مخصص'),
    ]

    student = models.ForeignKey('Student', on_delete=models.CASCADE, verbose_name="الطالب", related_name="bus_subscriptions")
    route = models.ForeignKey(BusRoute, on_delete=models.PROTECT, verbose_name="خط الباص", related_name="subscriptions")
    sub_type = models.CharField("نوع الاشتراك", max_length=20, choices=SUBSCRIPTION_TYPES, default='monthly')

    start_date = models.DateField("تاريخ بداية الاشتراك")
    end_date = models.DateField("تاريخ نهاية الاشتراك")

    required_amount = models.DecimalField("المبلغ المطلوب", max_digits=10, decimal_places=2)
    is_active = models.BooleanField("حالة الاشتراك (فعال)", default=True)
    notes = models.TextField("ملاحظات", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "اشتراك باص"
        verbose_name_plural = "اشتراكات الباص"
        ordering = ['-created_at']

    @property
    def total_paid(self):
        """إجمالي المدفوع لهذا الاشتراك (بافتراض وجود موديل BusPayment مشابه لـ CoursePayment)"""
        # يمكنك ربطه بجدول الخزينة الخاص بك، هنا وضعنا دالة جاهزة للعمل
        return self.payments.aggregate(total=Sum('amount_paid'))['total'] or 0

    @property
    def remaining_amount(self):
        """المبلغ المتبقي"""
        return self.required_amount - self.total_paid

    @property
    def payment_status_label(self):
        if self.remaining_amount <= 0:
            return "مسدد بالكامل"
        elif self.total_paid > 0:
            return "سداد جزئي"
        return "لم يتم السداد"

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.route.name}"


class BusPayment(models.Model):
    """سجل تحصيلات الباص (الخزينة)"""
    subscription = models.ForeignKey(BusSubscription, on_delete=models.CASCADE, verbose_name="الاشتراك", related_name="payments")
    amount_paid = models.DecimalField("المبلغ المدفوع", max_digits=10, decimal_places=2)
    payment_date = models.DateTimeField("تاريخ التحصيل", auto_now_add=True)
    collected_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "تحصيل باص"
        verbose_name_plural = "تحصيلات الباص"

# ... existing code ...
class MiscellaneousRevenue(models.Model):
    """جدول الإيرادات المتنوعة (أخرى)"""
    REVENUE_TYPES = [
        ('canteen', 'إيجار كانتين'),
        ('donation', 'تبرعات'),
        ('activities', 'رسوم أنشطة / رحلات'),
        ('papers', 'رسوم استخراج أوراق'),
        ('other', 'أخرى متنوعة'),
    ]

    title = models.CharField("بيان الإيراد", max_length=200)
    revenue_type = models.CharField("تصنيف الإيراد", max_length=50, choices=REVENUE_TYPES, default='other')
    amount = models.DecimalField("المبلغ المورد", max_digits=12, decimal_places=2)
    date = models.DateField(auto_now_add=True, verbose_name="تاريخ الإيراد", db_index=True)
    collected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="الموظف المستلم")
    notes = models.TextField("ملاحظات إضافية", blank=True, null=True)

    class Meta:
        verbose_name = "إيراد متنوع"
        verbose_name_plural = "الإيرادات المتنوعة"
        ordering = ['-date']

    def __str__(self):
        return f"{self.title} - {self.amount} ج.م"





# --- جداول الكنترول وشئون الطلاب الجديدة المضافة حديثاً ---

class StudentControlSheet(models.Model):
    SUBJECT_STATUS_CHOICES = [
        ('passed', 'ناجح ومجتاز ✅'),
        ('second_session', 'له دور ثانٍ (ملحق) ⚠️'),
        ('failed', 'راسب وباقٍ للإعادة ❌'),
    ]

    student = models.ForeignKey('Student', on_delete=models.CASCADE, related_name='control_records', verbose_name="الطالب")
    subject = models.ForeignKey('Subject', on_delete=models.CASCADE, verbose_name="المادة")
    academic_year = models.ForeignKey('finance.AcademicYear', on_delete=models.CASCADE, verbose_name="العام الدراسي")

    term1_cultural = models.DecimalField("ترم أول - نظري", max_digits=5, decimal_places=2, default=0)
    term1_practical = models.DecimalField("ترم أول - عملي", max_digits=5, decimal_places=2, default=0)
    term1_is_absent = models.BooleanField("غياب الترم الأول؟", default=False)

    term2_cultural = models.DecimalField("ترم ثاني - نظري", max_digits=5, decimal_places=2, default=0)
    term2_practical = models.DecimalField("ترم ثاني - عملي", max_digits=5, decimal_places=2, default=0)
    term2_is_absent = models.BooleanField("غياب الترم الثاني؟", default=False)

    second_session_cultural = models.DecimalField("دور ثانٍ - نظري", max_digits=5, decimal_places=2, default=0)
    second_session_practical = models.DecimalField("دور ثانٍ - عملي", max_digits=5, decimal_places=2, default=0)
    second_session_is_absent = models.BooleanField("غياب الدور الثاني؟", default=False)

    status = models.CharField("الحالة النهائية للمادة", max_length=20, choices=SUBJECT_STATUS_CHOICES, default='second_session')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "سجل الكنترول السنوي"
        verbose_name_plural = "شيت الكنترول العام (النتائج النهائية)"
        unique_together = ('student', 'subject', 'academic_year')

    @property
    def term1_total(self):
        if self.term1_is_absent: return Decimal('0.00')
        return self.term1_cultural + self.term1_practical

    @property
    def term2_total(self):
        if self.term2_is_absent: return Decimal('0.00')
        return self.term2_cultural + self.term2_practical

    @property
    def total_year_score(self):
        return self.term1_total + self.term2_total

    @property
    def second_session_total(self):
        if self.second_session_is_absent: return Decimal('0.00')
        return self.second_session_cultural + self.second_session_practical

    def auto_calculate_status(self):
        try:
            config = SubjectConfig.objects.filter(subject=self.subject, grade=self.student.grade, academic_year=self.academic_year).first()
            if not config: return 'second_session'
            if not self.term2_is_absent and self.total_year_score >= config.passing_score: return 'passed'
            if self.second_session_total >= config.passing_score and not self.second_session_is_absent: return 'passed'
            elif self.second_session_is_absent or (self.second_session_total < config.passing_score and self.second_session_total > 0): return 'failed'
            return 'second_session'
        except: return self.status

    def save(self, *args, **kwargs):
        self.status = self.auto_calculate_status()
        super().save(*args, **kwargs)


class StudentAcademicHistory(models.Model):
    student = models.ForeignKey('Student', on_delete=models.CASCADE, related_name='academic_histories', verbose_name="الطالب")
    academic_year = models.ForeignKey('finance.AcademicYear', on_delete=models.CASCADE, verbose_name="العام الدراسي المخزن")
    grade = models.ForeignKey('Grade', on_delete=models.PROTECT, verbose_name="الصف الدراسي حينها")
    classroom = models.ForeignKey('Classroom', on_delete=models.SET_NULL, null=True, verbose_name="الفصل")
    final_result = models.CharField("النتيجة النهائية للعام", max_length=20, choices=[('Promoted', 'ناجح ومنقول 🎓'), ('Failed', 'راسب وباقٍ للإعادة ❌')], default='Promoted')
    total_attendance_percentage = models.DecimalField("نسبة الحضور الإجمالية %", max_digits=5, decimal_places=2, default=100.00)
    notes = models.TextField("تقرير شئون الطلاب السنوي", blank=True, null=True)

    class Meta:
        verbose_name = "أرشيف سنة دراسية لطالب"
        verbose_name_plural = "سجلات شئون الطلاب التاريخية"
        unique_together = ('student', 'academic_year')



# =================================================================
# 🎯 منظومة الكنترول المطورة: أرقام الجلوس، السرية، واللجان الذكية
# =================================================================

class ControlRoomConfig(models.Model):
    """
    جدول رئيس الكنترول للتحكم في سعة اللجان قبل توليد أرقام الجلوس
    """
    academic_year = models.OneToOneField('finance.AcademicYear', on_delete=models.CASCADE, verbose_name="العام الدراسي")
    students_per_committee = models.PositiveIntegerField("سعة اللجنة (عدد الطلاب في الفصل الواحد)", default=20)

    class Meta:
        verbose_name = "إعدادات سعة لجان الكنترول"
        verbose_name_plural = "إعدادات سعة لجان الكنترول"

    def __str__(self):
        return f"إعدادات اللجان لعام - {self.academic_year.name}"


class StudentTermControlNumber(models.Model):
    """
    جدول الكنترول السنوي لرصد أرقام الجلوس، الأرقام السرية، ورقم اللجنة والمقعد
    """
    TERM_CHOICES = [
        ('term1', 'الترم الأول'),
        ('term2', 'الترم الثاني'),
        ('second_session', 'الدور الثاني (ملاحق)'),
    ]

    student = models.ForeignKey('Student', on_delete=models.CASCADE, related_name='control_numbers', verbose_name="الطالب")
    academic_year = models.ForeignKey('finance.AcademicYear', on_delete=models.CASCADE, verbose_name="العام الدراسي")
    term = models.CharField("الترم / الفترة", max_length=20, choices=TERM_CHOICES)

    # حقول الترقيم والتوزيع
    seating_number = models.CharField("رقم الجلوس", max_length=4, blank=True, null=True, db_index=True)
    secret_number = models.CharField("الرقم السري", max_length=6, blank=True, null=True, db_index=True)

    # حقول التحكم في اللجان والفصول (التعديل الجديد)
    committee_number = models.PositiveIntegerField("لجنة رقم", blank=True, null=True, db_index=True)
    seat_number_in_committee = models.PositiveIntegerField("رقم المقعد داخل اللجنة", blank=True, null=True)

    class Meta:
        verbose_name = "رقم جلوس وسري ولجنة للطالب"
        verbose_name_plural = "شيت أرقام الجلوس واللجان الشامل"
        unique_together = ('student', 'academic_year', 'term')

    def __str__(self):
        return f"{self.student.get_full_name()} - لجنة: {self.committee_number} - جلوس: {self.seating_number}"

    @classmethod
    @transaction.atomic
    def generate_numbers_for_term(cls, academic_year, term):
        """
        الخوارزمية الماسية لتوليد أرقام الجلوس والسرية وتوزيع اللجان حسب السعة:
        1. تفصل انتظام وعمال للصف الأول والثاني، وتدمج الصف الثالث بالكامل.
        2. تعزل طلاب الدمج تماماً في مسلسلات لجان مستقلة (6001، 7001، 8001).
        3. تقسم الطلاب (بنين أولاً لجنة، ثم بنات لجنة) ولا تخلطهم في المقاعد.
        4. تعتمد على تقنية الـ Bulk Create لحفظ آلاف الطلاب في أقل من ثانيتين منقذة للسيرفر.
        """
        import random
        from .models import Student

        # 🟢 تنظيف وتصفير أرقام الجلوس القديمة لنفس الترم والعام لمنع أخطاء التداخل وإتاحة التوليد النظيف المكرر
        cls.objects.filter(academic_year=academic_year, term=term).delete()

        # 1. جلب سعة اللجنة المحددة من الإعدادات كعدد صحيح
        config = ControlRoomConfig.objects.filter(academic_year=academic_year).first()
        capacity = int(config.students_per_committee) if config else 20

        students_qs = Student.objects.filter(academic_year=academic_year, is_active=True)
        if term == 'second_session':
            students_qs = students_qs.filter(enrollment_status__in=['Failed', 'Retained'])

        # عزل الدمج عن الطلاب العاديين لضمان استقلال لجانهم
        normal_students = students_qs.filter(integration_status=False)
        integration_students = students_qs.filter(integration_status=True)

        # -------------------------------------------------------------
        # الجزء الأول: الطلاب العاديين (كل صف يبدأ برقم جلوس ولجنة رقم 1 خاصة به)
        # -------------------------------------------------------------

        # الصف الأول - انتظام (عادي) -> جلوس من 1001
        cls._assign_sequential_logic(
            normal_students.filter(grade__name__contains="الأول", study_type='Regular'),
            academic_year, term, start_seating=1001, start_committee=1, capacity=capacity
        )

        # الصف الثاني - انتظام (عادي) -> جلوس من 2001
        cls._assign_sequential_logic(
            normal_students.filter(grade__name__contains="الثاني", study_type='Regular'),
            academic_year, term, start_seating=2001, start_committee=1, capacity=capacity
        )

        # الصف الأول - عمال (عادي) -> جلوس من 3001
        cls._assign_sequential_logic(
            normal_students.filter(grade__name__contains="الأول", study_type='Workers'),
            academic_year, term, start_seating=3001, start_committee=1, capacity=capacity
        )

        # الصف الثاني - عمال (عادي) -> جلوس من 4001
        cls._assign_sequential_logic(
            normal_students.filter(grade__name__contains="الثاني", study_type='Workers'),
            academic_year, term, start_seating=4001, start_committee=1, capacity=capacity
        )

        # الصف الثالث - مشترك عادي (انتظام + عمال معاً) -> جلوس من 5001
        cls._assign_sequential_logic(
            normal_students.filter(grade__name__contains="الثالث"),
            academic_year, term, start_seating=5001, start_committee=1, capacity=capacity
        )

        # -------------------------------------------------------------
        # الجزء الثاني: طلاب الدمج (معزولين في لجان منفصلة تماماً)
        # -------------------------------------------------------------

        # الصف الأول - دمج -> جلوس من 6001
        cls._assign_sequential_logic(
            integration_students.filter(grade__name__contains="الأول"),
            academic_year, term, start_seating=6001, start_committee=1, capacity=capacity
        )

        # الصف الثاني - دمج -> جلوس من 7001
        cls._assign_sequential_logic(
            integration_students.filter(grade__name__contains="الثاني"),
            academic_year, term, start_seating=7001, start_committee=1, capacity=capacity
        )

        # الصف الثالث - دمج مشترك بالكامل -> جلوس من 8001
        cls._assign_sequential_logic(
            integration_students.filter(grade__name__contains="الثالث"),
            academic_year, term, start_seating=8001, start_committee=1, capacity=capacity
        )

    @classmethod
    def _assign_sequential_logic(cls, queryset, academic_year, term, start_seating, start_committee, capacity):
        """دالة المعالجة الفائقة والفرز لعدم خلط الجنسين في المقاعد واللجان نهائياً وبسرعة فائقة"""
        import random

        if not queryset.exists():
            return

        # 🟢 توسيع نطاق الأرقام السرية لـ 5 أرقام (90,000 احتمال) لحل مشكلة الـ Infinite Loop والتعليق نهائياً
        used_secrets = set(cls.objects.filter(academic_year=academic_year, term=term).values_list('secret_number', flat=True))

        # 💎 تطبيق الشرط الماسي الفعلي (عزل كتل البنين عن البنات لضمان استقلال غرف اللجان وعدم الاختلاط)
        boys = queryset.filter(gender__in=['Male', 'M', 'ذكر', 'بنين']).order_by('first_name', 'last_name')
        girls = queryset.filter(gender__in=['Female', 'F', 'أنثى', 'بنات']).order_by('first_name', 'last_name')

        current_seating = int(start_seating)
        current_committee = int(start_committee)
        seat_index = 1

        records_to_create = []

        # 1. تسكين البنين أولاً متسلسلين
        for student in boys:
            while True:
                potential_secret = f"S{random.randint(10000, 99999)}"
                if potential_secret not in used_secrets:
                    used_secrets.add(potential_secret)
                    secret_num = potential_secret
                    break

            records_to_create.append(cls(
                student=student,
                academic_year=academic_year,
                term=term,
                seating_number=f"{current_seating:04d}",
                secret_number=secret_num,
                committee_number=int(current_committee),
                seat_number_in_committee=int(seat_index)
            ))
            current_seating += 1
            seat_index += 1
            if seat_index > capacity:
                current_committee += 1
                seat_index = 1

        # 🚨 القفل الماسي لمنع الخلط: إذا انتهى كشف البنين واللجنة الأخيرة لم تكتمل بالكامل (غير فارغة)،
        # نقوم بقفلها فوراً وترحيل كشف البنات ليبدأ من لجنة جديدة مستقلة تماماً ومقعد رقم 1!
        if seat_index > 1:
            current_committee += 1
            seat_index = 1

        # 2. تسكين البنات في اللجان المستقلة التالية
        for student in girls:
            while True:
                potential_secret = f"S{random.randint(10000, 99999)}"
                if potential_secret not in used_secrets:
                    used_secrets.add(potential_secret)
                    secret_num = potential_secret
                    break

            records_to_create.append(cls(
                student=student,
                academic_year=academic_year,
                term=term,
                seating_number=f"{current_seating:04d}",
                secret_number=secret_num,
                committee_number=int(current_committee),
                seat_number_in_committee=int(seat_index)
            ))
            current_seating += 1
            seat_index += 1
            if seat_index > capacity:
                current_committee += 1
                seat_index = 1

        # 🚀 الصاروخ: شحن وحفظ مئات أو آلاف سجلات الطلاب دفعة واحدة وبسرعة البرق
        cls.objects.bulk_create(records_to_create)

# =========================================================
# 🏛️ منظومة الأكاديمية والدبلومات المطورة (14 شهراً / تيرمات ومواد ودكاترة)
# =========================================================

# 1. الدكاترة والمحاضرون
class AcademyDoctor(models.Model):
    name = models.CharField("اسم الدكتور / المحاضر", max_length=150, db_index=True)
    specialty = models.CharField("التخصص الأكاديمي", max_length=150, blank=True, null=True)
    phone = models.CharField("رقم الهاتف", max_length=20, blank=True, null=True)

    class Meta:
        verbose_name = "دكتور / محاضر أكاديمي"
        verbose_name_plural = "1. الدكاترة والمحاضرون"

    def __str__(self):
        return f"د. {self.name}"


# 2. القسم / الدبلومة الشاملة
class AcademyCourse(models.Model):
    name = models.CharField("اسم القسم / الدبلومة", max_length=200, db_index=True)
    duration_months = models.PositiveIntegerField("مدة الدراسة الشاملة بالشهور", default=14)
    total_terms = models.PositiveIntegerField("عدد التيرمات / الفصول الدراسية", default=4)
    base_price = models.DecimalField("السعر الموحد للدبلومة", max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "قسم / دبلومة أكاديمية"
        verbose_name_plural = "2. الأقسام والدبلومات"

    def __str__(self):
        return self.name


# 3. دليل المواد الأكاديمية العام
class AcademySubject(models.Model):
    name = models.CharField("اسم المادة الأكاديمية", max_length=150, unique=True, db_index=True)
    code = models.CharField("كود المادة", max_length=20, blank=True, null=True)

    class Meta:
        verbose_name = "مادة أكاديمية"
        verbose_name_plural = "3. دليل المواد الأكاديمية"

    def __str__(self):
        return self.name


# 4. الخطة الدراسية وتسكين المواد والدكاترة بالتيرمات
class AcademyTermSubject(models.Model):
    TERM_CHOICES = [
        (1, 'التيرم الأول (الشهور 1-3)'),
        (2, 'التيرم الثاني (الشهور 4-6)'),
        (3, 'التيرم الثالث (الشهور 7-9)'),
        (4, 'التيرم الرابع (الشهور 10-12)'),
        (5, 'التدريب العملي والامتياز (الشهور 13-14)'),
    ]

    course = models.ForeignKey(AcademyCourse, on_delete=models.CASCADE, related_name='term_subjects', verbose_name="القسم / الدبلومة", db_index=True)
    term_number = models.PositiveSmallIntegerField("التيرم / الفصل الدراسي", choices=TERM_CHOICES, default=1, db_index=True)
    subject = models.ForeignKey(AcademySubject, on_delete=models.CASCADE, verbose_name="المادة الدراسية", db_index=True)
    doctor = models.ForeignKey(AcademyDoctor, on_delete=models.CASCADE, verbose_name="الدكتور المحاضر للمادة", db_index=True)

    class Meta:
        verbose_name = "تسكين مادة ودكتور بالتيرم"
        verbose_name_plural = "4. الخطة الدراسية وتسكين المواد والدكاترة"
        unique_together = ('course', 'term_number', 'subject', 'doctor')
        indexes = [
            models.Index(fields=['course', 'term_number']),
        ]

    def __str__(self):
        return f"{self.course.name} - تيرم {self.term_number}: {self.subject.name} (د. {self.doctor.name})"


# 5. تسجيل الطالب بالقسم/الدبلومة (الاشتراك الفعلي)
class AcademyEnrollment(models.Model):
    student = models.ForeignKey('Student', on_delete=models.CASCADE, verbose_name="الطالب المتدرب", db_index=True)
    course = models.ForeignKey(AcademyCourse, on_delete=models.CASCADE, verbose_name="القسم / الدبلومة", db_index=True)
    enrollment_date = models.DateField("تاريخ بدء الدراسة", default=timezone.now, db_index=True)
    custom_price = models.DecimalField("سعر مخصص للطالب (اختياري)", max_digits=10, decimal_places=2, null=True, blank=True)
    is_graduated = models.BooleanField("تم منحه الشهادة الرسمية؟", default=False, db_index=True)
    certificate_issued_date = models.DateField("تاريخ إصدار الشهادة", null=True, blank=True)

    class Meta:
        verbose_name = "اشتراك طالب بأكاديمية"
        verbose_name_plural = "5. اشتراكات الطلاب بالأكاديمية"
        unique_together = ('student', 'course')
        indexes = [
            models.Index(fields=['student', 'course']),
            models.Index(fields=['enrollment_date', 'is_graduated']),
        ]

    @property
    def final_price(self):
        return self.custom_price if self.custom_price is not None else self.course.base_price

    @property
    def expected_graduation_date(self):
        """حساب تاريخ التخرج المتوقع أوتوماتيكياً بعد 14 شهراً"""
        return self.enrollment_date + relativedelta(months=self.course.duration_months)

    def __str__(self):
        return f"{self.student.first_name} - {self.course.name}"


# 6. جدول المحاضرات للحضور والغياب
class AcademyLecture(models.Model):
    term_subject = models.ForeignKey(AcademyTermSubject, on_delete=models.CASCADE, related_name='lectures', verbose_name="المادة والمحاضر بالتيرم", db_index=True, null=True, blank=True)
    title = models.CharField("عنوان المحاضرة", max_length=200)
    lecture_date = models.DateField("تاريخ المحاضرة", default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "محاضرة أكاديمية"
        verbose_name_plural = "6. محاضرات التيرمات"

    def __str__(self):
        return f"{self.title}"


# 7. رصد الحضور التفصيلي للطالب
class AcademyAttendance(models.Model):
    STATUS = [('present', 'حاضر'), ('absent', 'غائب')]
    enrollment = models.ForeignKey(AcademyEnrollment, on_delete=models.CASCADE, related_name='attendances', db_index=True)
    lecture = models.ForeignKey(AcademyLecture, on_delete=models.CASCADE, db_index=True)
    status = models.CharField("حالة الحضور", max_length=10, choices=STATUS, default='present', db_index=True)

    class Meta:
        verbose_name = "حضور محاضرة"
        verbose_name_plural = "7. سجل حضور المحاضرات"
        unique_together = ('enrollment', 'lecture')
        indexes = [
            models.Index(fields=['enrollment', 'status']),
        ]

    def __str__(self):
        return f"{self.enrollment.student.first_name} - {self.lecture.title}"



class PendingAdmissionNotification(models.Model):
    full_name_ar = models.CharField("اسم الطالب", max_length=250)
    national_id = models.CharField("الرقم القومي", max_length=14, unique=True)
    phone = models.CharField("رقم التليفون", max_length=20)
    whatsapp_number = models.CharField("رقم الواتساب", max_length=20)
    gender = models.CharField("النوع", max_length=10)
    birth_date = models.DateField("تاريخ الميلاد", null=True, blank=True)
    birth_governorate = models.CharField("المحافظة", max_length=100, null=True, blank=True)
    address = models.TextField("العنوان")
    current_qualification = models.CharField("المؤهل", max_length=150, null=True, blank=True)

    # 🟢 إضافة حقول الميديا المستهدفة لاستقبال الملفات
    student_photo = models.ImageField("صورة الطالب", upload_to="pending_students/", null=True, blank=True)
    parent_id_photo = models.ImageField("بطاقة ولي الأمر", upload_to="pending_docs/", null=True, blank=True)
    birth_certificate = models.FileField("شهادة الميلاد", upload_to="pending_docs/", null=True, blank=True)
    qualification_photo = models.FileField("بيان النجاح", upload_to="pending_docs/", null=True, blank=True)

    is_processed = models.BooleanField("تم تسجيله رسمياً", default=False)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "إشعار طلب التحاق"
        verbose_name_plural = "إشعارات طلبات الالتحاق المعتمدة"
        ordering = ['-received_at']

    def __str__(self):
        return self.full_name_ar
