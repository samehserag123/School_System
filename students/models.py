from django.db import models
import random
from django.utils import timezone
from django.core.validators import RegexValidator, MinLengthValidator
from django.db.models import Sum
from audit.models import AuditLog
from decimal import Decimal
# ملاحظة: إذا كان numbers_only معرفاً في ملف خاص (مثلاً validators.py داخل نفس التطبيق)
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
    def get_old_debt_amount(self):
        from finance.models import StudentAccount, Payment
        old_fees = StudentAccount.objects.filter(student=self).exclude(academic_year=self.academic_year).aggregate(total=models.Sum('total_fees'))['total'] or 0
        old_paid = Payment.objects.filter(student=self).exclude(academic_year=self.academic_year).aggregate(total=models.Sum('amount_paid'))['total'] or 0
        return Decimal(str(max(old_fees - old_paid, 0)))

    @property
    def total_old_debt(self):
        return Decimal(str(self.previous_debt or 0)) + Decimal(str(self.get_old_debt_amount or 0))
    
    # @property
    # def total_old_debt(self):
    #     # رجعها لأبسط صورة ممكنة عشان السيستم يفتح
    #     return float(self.previous_debt or 0) + float(self.get_old_debt_amount or 0)

    @property
    def current_year_fees_amount(self):
        from finance.models import StudentAccount
        account = StudentAccount.objects.filter(student=self, academic_year=self.academic_year).first()
        return Decimal(str(account.total_fees if account else 0))

    @property
    def total_paid_amount(self):
        from finance.models import Payment, RevenueCategory
        from django.db.models import Sum
        from decimal import Decimal

        try:
            # 1. البحث عن الفئة بشكل مرن (يتجاهل الهمزات أو المسافات الزائدة أحياناً)
            # أو الأفضل: category = RevenueCategory.objects.get(id=1) لو أنت ضامن الـ ID
            category = RevenueCategory.objects.get(name__icontains="المصروفات الاساسيه")
            
            # 2. الفلترة مع التأكد من السنة الدراسية للطالب
            total = Payment.objects.filter(
                student=self, 
                academic_year=self.academic_year, # السنة المسكن عليها الطالب حالياً
                revenue_category=category
            ).aggregate(total=Sum('amount_paid'))['total'] or 0
            
            return Decimal(str(total))
            
        except (RevenueCategory.DoesNotExist, RevenueCategory.MultipleObjectsReturned):
            # في حالة عدم وجود الفئة أو وجود أكثر من واحدة بنفس الاسم
            return Decimal("0.00")
        
    
    @property
    def current_remaining_amount(self):
        # هذه الخاصية تغنيك عن الحساب في ملف HTML وتمنع الخطأ
        return self.current_year_fees_amount - self.total_paid_amount

    @property
    def has_old_debt(self):
        return self.total_old_debt > Decimal('0')

    @property
    def full_name(self):
        return self.get_full_name()

    @property
    def name(self):
        return self.get_full_name()
    
    @property
    def is_new_student(self):
        return self.enrollment_status == "New"