from django.db import models
import random
from django.utils import timezone
from django.core.validators import RegexValidator, MinLengthValidator
from audit.models import AuditLog
from django.db.models import Sum, Q
from decimal import Decimal# ملاحظة: إذا كان numbers_only معرفاً في ملف خاص (مثلاً validators.py داخل نفس التطبيق)
# تأكد من استيراده هنا.
# من .validators import numbers_only
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
    STATUS_CHOICES = [("New", "مستجد"), ("Transferred", "منقول"), ("Home", "عمال"), ("Promoted", "ناجح ومنقول")]
    GENDER_CHOICES = [('Male', 'ذكر'), ('Female', 'أنثى')]
    SPECIALIZATION_CHOICES = [
        ("General", "شعبة عامة"), ("Restaurant", "مطعم"), ("Kitchen", "مطبخ"),
        ("Guidance", "ارشاد"), ("Internal", "اشراف داخلي"), ("Computer", "حاسب الي"),
    ]

    # --- البيانات الأساسية ---
    image = models.ImageField("صورة الطالب", upload_to="students/", null=True, blank=True)
    registration_number = models.CharField("رقم القيد", max_length=50, unique=True, blank=True, null=True)
    
    first_name = models.CharField("الاسم الأول", max_length=100)
    last_name = models.CharField("اسم العائلة", max_length=100)
    
    # 1. إضافة الرقم القومي مع التحقق (14 رقم فقط)
    national_id_validator = RegexValidator(
        regex=r'^\d{14}$',
        message="الرقم القومي يجب أن يتكون من 14 رقماً فقط."
    )
    national_id = models.CharField(
        "الرقم القومي", 
        max_length=14, 
        validators=[national_id_validator],
        unique=True,
        null=True, blank=True
    )

    # 2. كود الطالب (تلقائي)
    student_code = models.CharField("كود الطالب", max_length=20, unique=True, editable=False)

    # ... باقي الحقول (grade, academic_year, إلخ) ...
    date_of_birth = models.DateField("تاريخ الميلاد", null=True, blank=True)
    birth_place = models.CharField("محل الميلاد", max_length=150, blank=True, null=True)
    
    gender = models.CharField(
        "النوع", 
        max_length=10, 
        choices=GENDER_CHOICES, 
        null=True, 
        blank=True
    )
    
    religion = models.CharField("الديانة", max_length=20, null=True, blank=True, choices=RELIGION_CHOICES)
    nationality = models.CharField("الجنسية", max_length=100, default="مصري")
    address = models.TextField("العنوان", blank=True, null=True)

    mother_name = models.CharField("اسم الأم", max_length=150, null=True, blank=True)
    phone = models.CharField("رقم التليفون", max_length=20, null=True, blank=True)

    # --- الحالة الأكاديمية ---
    enrollment_status = models.CharField("حالة القيد", max_length=20, choices=STATUS_CHOICES, default="New")
    integration_status = models.BooleanField("موقف الدمج", default=False)
    specialization = models.CharField("التخصص", max_length=30, choices=SPECIALIZATION_CHOICES, blank=True, null=True)
    
    previous_debt = models.DecimalField("مديونية سابقة مرحلة", max_digits=10, decimal_places=2, default=0)
    last_promotion_date = models.DateField(null=True, blank=True)
    
    grade = models.ForeignKey("students.Grade", on_delete=models.PROTECT, null=True, verbose_name="الصف الدراسي")
    classroom = models.ForeignKey("students.Classroom", on_delete=models.PROTECT, null=True, blank=True, verbose_name="الفصل")
    
    academic_year = models.ForeignKey("finance.AcademicYear", on_delete=models.CASCADE, verbose_name="السنة الدراسية", related_name="students")

    is_active = models.BooleanField("نشط", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ["-created_at"]
        verbose_name = "طالب"
        verbose_name_plural = "الطلاب"

    # ----------------------------------------------------------------
    # 2. الدوال الأساسية (Standard Methods)
    # ----------------------------------------------------------------
    def __str__(self):
        # اعتماد الدالة الرئيسية لعرض الطالب في القوائم ولوحة التحكم
        return self.get_full_name()

    def get_full_name(self):
        # معالجة آمنة للحقول الفارغة لمنع ظهور None
        first = self.first_name if self.first_name else ""
        last = self.last_name if self.last_name else ""
        full = f"{first} {last}".strip()
        
        # إذا كان الاسم فارغاً، نرجع كود الطالب
        return full if full else f"طالب رقم {self.student_code}"

    def save(self, *args, **kwargs):
        # توليد كود الطالب تلقائياً عند الإضافة لأول مرة فقط
        if not self.student_code:
            self.student_code = self.generate_unique_code()
        super().save(*args, **kwargs)

    def generate_unique_code(self):
        # توليد كود يبدأ بسنة الالتحاق + رقم عشوائي (مثال: 20260001)
        year_prefix = str(timezone.now().year)
        while True:
            random_num = str(random.randint(1000, 9999))
            code = f"{year_prefix}{random_num}"
            if not Student.objects.filter(student_code=code).exists():
                return code
    
    
    @property
    def total_required_amount(self):
        # ❌ متضيفش previous_debt هنا
        return self.current_year_fees_amount
        # 1. إجمالي المطلوب (السنة دي + المديونية اللي اترحلّت في الحقل)
    
    @property
    def current_year_paid(self):
        from finance.models import Payment
        from django.db.models import Sum, Q
        total = Payment.objects.filter(
            student=self,
            academic_year=self.academic_year # شرط السنة الحالية
        ).filter(
            Q(revenue_category__name__icontains="اساس") | 
            Q(revenue_category__name__icontains="مصروف")
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        return Decimal(str(total))

    
    @property
    def final_remaining(self):
        from decimal import Decimal
        from django.db.models import Sum

        # 1. المديونية اللي اتررحلت من السنة اللي فاتت (الصافي فقط)
        old_debt = Decimal(str(self.previous_debt or 0))
        
        # 2. مصاريف السنة دي فقط (صافي بعد الخصم)
        acc = self.accounts.filter(academic_year=self.academic_year).last()
        current_fees = Decimal('0.00')
        if acc:
            current_fees = Decimal(str(acc.total_fees or 0)) - Decimal(str(acc.discount or 0))

        # 3. 🔥 التعديل هنا: نخصم فقط المدفوعات التابعة لـ "المصروفات الاساسيه"
        # عشان "خامات المطبخ" أو "الباص" ملمسوش مديونية الطالب الدراسية
        current_year_payments = self.all_payments.filter(
            academic_year=self.academic_year,
            revenue_category__name="المصروفات الاساسيه"  # مطابقة حرفية لاسم البند عندك
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        total_paid = Decimal(str(current_year_payments))

        # المعادلة: (المديونية المرحلة + مصاريف السنة) - مدفوعات المصاريف الدراسية فقط
        return (old_debt + current_fees) - total_paid


    @property
    def calculated_previous_debt(self):
        from decimal import Decimal

        return max(Decimal('0.00'), Decimal(str(self.previous_debt or 0)))
    
    @property
    def total_balance_due(self):
        from decimal import Decimal
        from django.db.models import Sum

        total_required = Decimal(str(self.previous_debt or 0)) + self.current_year_fees_amount

        current_year_paid = self.all_payments.filter(
            academic_year=self.academic_year
        ).aggregate(total=Sum('amount_paid'))['total'] or 0

        return total_required - Decimal(str(current_year_paid))
    
        
    @property
    def current_year_fees_amount(self):
        """جلب إجمالي المصروفات المطلوبة من حساب الطالب للسنة الحالية"""
        from finance.models import StudentAccount
        from decimal import Decimal

        # البحث عن حساب الطالب المرتبط بالسنة الدراسية الحالية
        account = self.accounts.filter(academic_year=self.academic_year).first()
        
        if account:
            # نستخدم Decimal لضمان دقة الحسابات المالية ومنع أخطاء التقريب
            return Decimal(str(account.total_fees or 0))
        
        # لو الطالب مش متسكن له حساب، نرجع صفر عشان السيستم ما يضربش
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
    
   
# ----------------------------------------------------------------
# الجداول الجديدة: المدرسين، المواد، والكورسات
# ----------------------------------------------------------------

class Teacher(models.Model):
    name = models.CharField("اسم المدرس", max_length=150)
    phone = models.CharField("رقم الهاتف", max_length=20, validators=[numbers_only], blank=True, null=True)
    is_active = models.BooleanField("نشط", default=True)

    class Meta:
        verbose_name = "مدرس"
        verbose_name_plural = "المدرسون"

    def __str__(self):
        return self.name


class Subject(models.Model):
    name = models.CharField("اسم المادة الدراسية", max_length=100, unique=True)

    class Meta:
        verbose_name = "مادة دراسية"
        verbose_name_plural = "المواد الدراسية"

    def __str__(self):
        return self.name



# 1. الكلاس الجديد (تعريفة أسعار المواد)
class SubjectPrice(models.Model):
    SESSION_TYPE_CHOICES = [
        ('individual', 'كورس (فردي)'),
        ('group', 'مجموعة (Group)'),
    ]

    teacher = models.ForeignKey('Teacher', on_delete=models.CASCADE, verbose_name="المدرس")
    subject = models.ForeignKey('Subject', on_delete=models.CASCADE, verbose_name="المادة")
    grade = models.ForeignKey('Grade', on_delete=models.CASCADE, verbose_name="الصف الدراسي")
    session_type = models.CharField("نوع التدريس", max_length=20, choices=SESSION_TYPE_CHOICES, default='group')
    price = models.DecimalField("السعر", max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "تعريفة سعر مادة"
        verbose_name_plural = "1. قائمة أسعار المواد (إعدادات)"
        unique_together = ('teacher', 'subject', 'grade', 'session_type') # لمنع تكرار نفس التسعيرة

    # داخل كلاس SubjectPrice في models.py
    def __str__(self):
        return f"{self.subject.name} - {self.teacher.name} ({self.get_session_type_display()}) - {self.price} ج.م"


# 2. تعديل كلاس CourseGroup (تسجيل اشتراك الطالب)

class CourseGroup(models.Model):
    student = models.ForeignKey('Student', on_delete=models.CASCADE, verbose_name="الطالب", related_name="enrolled_courses")
    course_info = models.ForeignKey('SubjectPrice', on_delete=models.PROTECT, verbose_name="بيانات الكورس والسعر")
    registration_date = models.DateField("تاريخ الاشتراك", auto_now_add=True)
    notes = models.TextField("ملاحظات إضافية", blank=True, null=True)

    class Meta:
        verbose_name = "تسجيل كورس لطالب"
        verbose_name_plural = "2. سجل اشتراكات الطلاب"

    # --- دوال حسابية ذكية ---
    
    @property
    def total_paid(self):
        """يجمع كل المبالغ المدفوعة لهذا الكورس من جدول التحصيلات المنفصل"""
        return self.payments.aggregate(total=Sum('amount_paid'))['total'] or 0

    @property
    def remaining_amount(self):
        """يحسب المتبقي (سعر الكورس - إجمالي المدفوع)"""
        return self.course_info.price - self.total_paid

    @property
    def payment_status(self):
        """تحديد حالة الدفع نصياً"""
        remaining = self.remaining_amount
        if remaining <= 0:
            return "خالص ✅"
        return f"باقي {remaining} ج.م"

    def __str__(self):
        return f"{self.student} - {self.course_info.subject.name}"


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