from django.contrib.auth.models import User
from django.db import models, transaction
import random
from django.utils import timezone
from django.core.validators import RegexValidator, MinLengthValidator
from audit.models import AuditLog
from django.db.models import Sum, Q
from decimal import Decimal
from django.db import models, transaction


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
    STATUS_CHOICES = [("New", "مستجد"), ("Transferred", "منقول"), ("Home", "عمال"), ("Promoted", "ناجح ومنقول")]
    GENDER_CHOICES = [('Male', 'بنين'), ('Female', 'بنات')]
    SPECIALIZATION_CHOICES = [
        ("General", "شعبة عامة"), ("Restaurant", "مطعم"), ("Kitchen", "مطبخ"),
        ("Guidance", "ارشاد"), ("Internal", "اشراف داخلي"), ("Computer", "حاسب الي"),
    ]

    # --- البيانات الأساسية ---
    image = models.ImageField("صورة الطالب", upload_to="students/", null=True, blank=True)
    # جعلنا رقم القيد اختيارياً وغير فريد (أو فريد مع السماح بالقيم الفارغة)
    registration_number = models.CharField("رقم القيد", max_length=50, blank=True, null=True)
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
    student_code = models.CharField("كود الطالب", max_length=20, unique=True, editable=False, blank=True, null=True)

    # --- البيانات الشخصية ---
    date_of_birth = models.DateField("تاريخ الميلاد", null=True, blank=True)
    birth_place = models.CharField("محل الميلاد", max_length=150, blank=True, null=True)
    
    # إضافة null و blank للنوع
    gender = models.CharField(
        "النوع", 
        max_length=10, 
        choices=GENDER_CHOICES, 
        null=True, 
        blank=True
    )
    
    religion = models.CharField("الديانة", max_length=20, choices=RELIGION_CHOICES, null=True, blank=True)
    nationality = models.CharField("الجنسية", max_length=100, default="مصري", null=True, blank=True)
    address = models.TextField("العنوان", blank=True, null=True)

    mother_name = models.CharField("اسم الأم", max_length=150, null=True, blank=True)
    phone = models.CharField("رقم التليفون", max_length=40, null=True, blank=True)
    father_job = models.CharField(max_length=100, verbose_name="وظيفة الأب", blank=True, null=True)
    # --- الحالة الأكاديمية ---
    # جعل حالة القيد اختيارية
    enrollment_status = models.CharField("حالة القيد", max_length=20, choices=STATUS_CHOICES, null=True, blank=True)
    
    # الدمج (BooleanField يفضل أن يكون له default لكن وضعنا null=True ليكون اختيارياً تماماً)
    integration_status = models.BooleanField("موقف الدمج", default=False, null=True, blank=True)
    
    specialization = models.CharField("التخصص", max_length=30, choices=SPECIALIZATION_CHOICES, blank=True, null=True)
    
    previous_debt = models.DecimalField("مديونية سابقة مرحلة", max_digits=10, decimal_places=2, default=0)
    last_promotion_date = models.DateField(null=True, blank=True)
    
    grade = models.ForeignKey("students.Grade", on_delete=models.PROTECT, null=True, verbose_name="الصف الدراسي")
    classroom = models.ForeignKey("students.Classroom", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الفصل")    
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

    
    # students/models.py

    @property
    def final_remaining(self):
        from decimal import Decimal
        # 1. المديونية المرحلة
        old_debt = Decimal(str(self.previous_debt or 0))
        
        # 2. صافي مصاريف السنة الحالية
        acc = self.accounts.filter(academic_year=self.academic_year).last()
        current_fees = Decimal('0.00')
        if acc:
            current_fees = Decimal(str(acc.total_fees or 0)) - Decimal(str(acc.discount or 0))

        # 3. استخدام الدالة الموحدة للمدفوعات (التي تجمع كل بنود المصاريف)
        total_paid = self.current_year_paid 

        # المعادلة الموحدة
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
    
    item_type = models.CharField("نوع الصنف", max_length=10, choices=ITEM_TYPE_CHOICES, default='book')
    subject = models.ForeignKey('Subject', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المادة (للكتب)")
    uniform = models.ForeignKey('Uniform', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الزي (للملابس)")
    grade = models.ForeignKey('Grade', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الصف الدراسي")    
    
    # ⚠️ هذا الحقل يمثل الرصيد الذي بدأت به (الافتتاحي) ولن ينقص أبداً
    stock_quantity = models.PositiveIntegerField("الرصيد الافتتاحي", default=0)

    class Meta:
        unique_together = ('item_type', 'subject', 'uniform', 'grade')
        verbose_name = "صنف مخزني (جرد)"
        verbose_name_plural = "المخزن (الجرد التفصيلي)"
        ordering = ['id']

    @property
    def display_name(self):
        """الاسم الذي سيظهر في التقارير والـ View"""
        if self.item_type == 'book' and self.subject:
            return f"كتاب {self.subject.name}"
        elif self.item_type == 'uniform' and self.uniform:
            return f"{self.uniform.name}"
        return "صنف غير محدد"

    @property
    def total_incoming(self):
        # استخدام aggregate هنا آمن لأنه يعمل على QuerySet منفصل لهذا الصنف فقط
        from django.db.models import Sum
        restocks_qty = self.restocks.aggregate(total=Sum('quantity'))['total'] or 0
        return self.stock_quantity + restocks_qty

    @property
    def total_sold_count(self):
        """إجمالي المنصرف (المبيعات)"""
        from django.db.models import Sum
        return self.booksale_set.aggregate(total=Sum('quantity'))['total'] or 0

    @property
    def remaining_qty(self):
        """الرصيد الحالي الفعلي المتبقي في الرفوف"""
        return self.total_incoming - self.total_sold_count

    def __str__(self):
        # استخدام display_name الجديد لتعريف الكائن
        return f"{self.display_name} - {self.grade.name if self.grade else 'عام'}"
            

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


# 5. أسعار المجموعات والكورسات (الدروس)
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
        verbose_name_plural = "أسعار المجموعات والاشتراكات"
        unique_together = ('teacher', 'subject', 'grade', 'session_type')

    def __str__(self):
        # ✅ التعديل هنا: استخدام self.teacher.name بدلاً من first_name
        return f"{self.subject.name} - {self.teacher.name} ({self.get_session_type_display()})"

# 6. إذن استلام الكتب والزي (الربط بين الطالب والمخزن والمالية)


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
    is_delivered = models.BooleanField("تم الاستلام من المخزن؟", default=False)
    sale_date = models.DateTimeField("تاريخ الحركة", auto_now_add=True)

    class Meta:
        verbose_name = "إذن استلام ومبيعات"
        verbose_name_plural = "إذونات الاستلام والمبيعات"

    @property
    def calculated_paid_amount(self):
        """يبحث في الخزينة العامة عن أي مبالغ مسجلة برقم هذا الإذن #ID"""
        from treasury.models import GeneralLedger
        total = GeneralLedger.objects.filter(
            notes__icontains=f"#{self.id}"
        ).aggregate(total=Sum('amount'))['total'] or 0
        return Decimal(str(total))

    @property
    def remaining_amount(self):
        """حساب المتبقي الحقيقي"""
        return self.total_amount - self.calculated_paid_amount

    def save(self, *args, **kwargs):
        # 1. جلب الموظف الحالي (يتم تمريره من الـ View عبر _current_user)
        current_user = getattr(self, '_current_user', None)
        
        # 2. حساب الإجمالي تلقائياً من باقة الصف إذا لم يتم إدخاله يدوياً
        if not self.total_amount:
            try:
                # استيراد محلي لتجنب مشاكل الاعتماد الدائري
                from .models import GradePackagePrice 
                package = GradePackagePrice.objects.get(
                    grade=self.student.grade, 
                    academic_year=self.student.academic_year
                )
                # تحديد السعر بناءً على نوع الصنف (كتاب أم زي)
                price = package.books_price if self.item.item_type == 'book' else package.uniform_price
                self.total_amount = price * self.quantity
            except:
                self.total_amount = 0

        # 3. الحفظ الأساسي للعملية (ضروري للحصول على ID لاستخدامه في الخزينة)
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # 4. الربط الآلي مع الخزينة العامة عند وجود مبلغ مدفوع (السداد الفوري)
        if is_new and self.pay_now > 0:
            # استيراد الموديل المتاح فقط لتجنب ImportError الخاص بـ Category
            from treasury.models import GeneralLedger
            
            # إنشاء قيد في الخزينة العامة
            GeneralLedger.objects.create(
                student=self.student,
                # تم إلغاء حقل category هنا لتجنب خطأ الاستيراد الذي واجهته
                amount=self.pay_now,
                # الربط السحري: نضع رقم الإذن في الملاحظات مسبوقاً بـ # ليقرأه الإيصال تلقائياً
                notes=f"سداد آلي لإذن استلام رقم #{self.id}", 
                receipt_number=f"BS-{self.id}",
                collected_by=current_user
            )

        # 5. تحديث الحالة النهائية للإذن بناءً على ما تم دفعه فعلياً في الخزينة
        # نستخدم calculated_paid_amount التي تبحث في الخزينة برقم الإذن #
        actual_paid = self.calculated_paid_amount
        
        if actual_paid >= self.total_amount and self.total_amount > 0:
            new_status = 'delivered' if self.is_delivered else 'paid'
        elif actual_paid > 0:
            new_status = 'pending' # دفع جزئي
        else:
            new_status = 'pending' # لم يتم الدفع
        
        # تحديث الحالة في قاعدة البيانات مباشرة لتجنب تكرار دالة save
        if new_status != self.status:
            type(self).objects.filter(id=self.id).update(status=new_status)

    @property
    def status_label(self):
        """عرض حالة السداد نصياً بناءً على المتبقي الحقيقي"""
        remaining = self.remaining_amount
        if remaining <= 0 and self.total_amount > 0:
            return "تم السداد بالكامل"
        elif remaining < self.total_amount:
            return "سداد جزئي"
        return "لم يتم السداد"

    def __str__(self):
        """تعريف الاسم الذي يظهر في لوحة التحكم"""
        return f"{self.student.get_full_name()} - {self.item.display_name}"
    

# models.py
class ExternalStudent(models.Model):
    full_name = models.CharField("اسم الطالب", max_length=200)
    #national_id = models.CharField("الرقم القومي", max_length=14, unique=True)
    phone_number = models.CharField("رقم التليفون", max_length=15)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name
    

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
    date = models.DateTimeField("تاريخ ووقت التحصيل", auto_now_add=True)
    collected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="الموظف المستلم")
    notes = models.TextField("ملاحظات إضافية", blank=True, null=True)

    class Meta:
        verbose_name = "إيراد متنوع"
        verbose_name_plural = "الإيرادات المتنوعة"
        ordering = ['-date']

    def __str__(self):
        return f"{self.title} - {self.amount} ج.م"
    
    
    
    
