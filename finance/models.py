from django.contrib.auth.models import User # استيراد موديل المستخدمين
from django.conf import settings
from django.db import models
from django.db.models import Sum
from decimal import Decimal
from datetime import date
from django.utils import timezone
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver


# =====================================================
# السنة الدراسية
# =====================================================
# 1. أضف هذا الكلاس الجديد في نهاية ملف models.py
class ReceiptBook(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="المستخدم (المحصل)")
    book_number = models.CharField(max_length=50, verbose_name="رقم الدفتر")
    start_serial = models.PositiveIntegerField(verbose_name="بداية السيريال")
    end_serial = models.PositiveIntegerField(verbose_name="نهاية السيريال")
    is_active = models.BooleanField(default=True, verbose_name="نشط")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "دفتر إيصالات"
        verbose_name_plural = "دفاتر الإيصالات"
        # منع تكرار نفس رقم الدفتر لنفس المستخدم وهو نشط
        constraints = [
            models.UniqueConstraint(fields=['user', 'is_active'], condition=models.Q(is_active=True), name='unique_active_book_per_user')
        ]

    def __str__(self):
        return f"دفتر {self.book_number} - المحصل: {self.user.username} (من {self.start_serial} إلى {self.end_serial})"


# 2. في نفس ملف models.py، ابحث عن كلاس Payment وأضف هذا الحقل الجديد داخله:
# أضف هذا الحقل داخل class Payment(models.Model):
    receipt_number = models.PositiveIntegerField(null=True, blank=True, verbose_name="رقم الإيصال الورقي المرجعي")
    
class AcademicYear(models.Model):
    name = models.CharField(max_length=20)  # مثال: 2025/2026
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return self.name



class DailyClosure(models.Model):
    """
    كلاس إغلاق الخزينة: 
    مسؤول عن تجميع كافة الحركات المالية غير المغلقة وربطها بجرد واحد.
    """
    closure_date = models.DateTimeField(auto_now_add=True)
    closed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    total_cash = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="المبلغ النظري")
    actual_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="المبلغ الفعلي")
    variance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="الفارق")
    closure_id = models.CharField(max_length=20, unique=True, verbose_name="رقم الجرد")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات وتفاصيل الفئات")

    class Meta:
        verbose_name = "إغلاق الخزينة اليومي"
        verbose_name_plural = "إغلاقات الخزينة اليومية"
        ordering = ['-closure_date']

    def save(self, *args, **kwargs):
        # حساب الفارق تلقائياً قبل الحفظ
        self.variance = self.actual_cash - self.total_cash
        
        with transaction.atomic():
            super().save(*args, **kwargs)
            
            # إغلاق كافة الإيصالات والمصروفات المفتوحة وربطها بهذا الجرد لضمان عدم تكرارها
            from .models import Payment, Expense
            Payment.objects.filter(is_closed=False).update(is_closed=True, closure=self)
            Expense.objects.filter(is_closed=False).update(is_closed=True, closure=self)

    def __str__(self):
        return f"جرد رقم: {self.closure_id} - {self.closure_date.strftime('%Y-%m-%d')}"


# class DailyClosure(models.Model):
#     """نموذج إغلاق الخزينة اليومي"""
#     closure_date = models.DateTimeField(auto_now_add=True)
#     closed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
#     total_cash = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="المبلغ النظري")
#     actual_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="المبلغ الفعلي")
#     variance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="الفارق")
#     closure_id = models.CharField(max_length=20, unique=True, verbose_name="رقم الجرد")
#     notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات وتفاصيل الفئات")

#     class Meta:
#         verbose_name = "إغلاق الخزينة اليومي"
#         verbose_name_plural = "إغلاقات الخزينة اليومية"
#         ordering = ['-closure_date']

#     def save(self, *args, **kwargs):
#         # حساب الفارق تلقائياً قبل الحفظ
#         self.variance = self.actual_cash - self.total_cash
        
#         with transaction.atomic():
#             super().save(*args, **kwargs)
            
#             # إغلاق الإيصالات والمصروفات المفتوحة وربطها بهذا الجرد
#             from .models import Payment, Expense
#             Payment.objects.filter(is_closed=False).update(is_closed=True, closure=self)
#             Expense.objects.filter(is_closed=False).update(is_closed=True, closure=self)

#     def __str__(self):
#         return f"جرد رقم: {self.closure_id} - {self.closure_date.strftime('%Y-%m-%d')}"


# class DailyClosure(models.Model):
#     closure_date = models.DateTimeField(auto_now_add=True)
#     closed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
#     # المبلغ النظري (يتم حسابه تلقائياً من الإيصالات غير المغلقة)
#     total_cash = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="المبلغ النظري")
    
#     # المبلغ الفعلي الذي عده الكاشير
#     actual_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="المبلغ الفعلي")
    
#     # الفرق (عجز أو زيادة) يتم حسابه تلقائياً
#     variance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="الفارق")
    
#     closure_id = models.CharField(max_length=20, unique=True, verbose_name="رقم الجرد")
#     notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات وتفاصيل الفئات")

#     class Meta:
#         verbose_name = "إغلاق الخزينة اليومي"
#         verbose_name_plural = "إغلاقات الخزينة اليومية"
#         ordering = ['-closure_date']

#     def save(self, *args, **kwargs):
#         # حساب الفارق تلقائياً قبل الحفظ
#         self.variance = self.actual_cash - self.total_cash
        
#         with transaction.atomic():
#             super().save(*args, **kwargs)
            
#             # 1. إغلاق الإيصالات (موجود مسبقاً في كودك)
#             from .models import Payment
#             unclosed_payments = Payment.objects.filter(is_closed=False)
#             unclosed_payments.update(is_closed=True, closure=self)
            
#             # 2. إغلاق المصروفات (الإضافة الجديدة)
#             unclosed_expenses = Expense.objects.filter(is_closed=False)
#             unclosed_expenses.update(is_closed=True, closure=self)
            
#             print(f"DEBUG: تم إغلاق {unclosed_payments.count()} إيصال و {unclosed_expenses.count()} مصروف للجرد رقم {self.closure_id}")

#     def __str__(self):
#         return f"جرد رقم: {self.closure_id} - {self.closure_date.strftime('%Y-%m-%d')}"

class RevenueCategory(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم الفئة")
    parent = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='subcategories', # ممتاز: يعبر عن الفئات التابعة
        verbose_name="الفئة الرئيسية"
    )

    class Meta:
        verbose_name = "فئة إيراد"
        verbose_name_plural = "فئات الإيرادات"

    def __str__(self):
        # التحسين هنا لضمان سهولة التمييز في القوائم المنسدلة (Dropdowns)
        if self.parent:
            return f"{self.name} (تابع لـ {self.parent.name})"
        return self.name

class GradePriceList(models.Model):
    revenue_category = models.ForeignKey('RevenueCategory', on_delete=models.CASCADE, verbose_name="الفئة/الصنف")
    grade = models.ForeignKey("students.Grade", on_delete=models.CASCADE, verbose_name="الصف الدراسي")
    academic_year = models.ForeignKey('AcademicYear', on_delete=models.CASCADE, verbose_name="العام الدراسي")
    price = models.DecimalField("السعر المحدد لهذا الصف", max_digits=10, decimal_places=2, default=0)

    class Meta:
        unique_together = ('revenue_category', 'grade', 'academic_year')
        verbose_name = "قائمة أسعار الصفوف"

    def __str__(self):
        return f"{self.revenue_category.name} - {self.grade.name} ({self.price} ج.م)"

class InstallmentPlan(models.Model):
    name = models.CharField("اسم الخطة الدراسية", max_length=100)
    # أضفنا السنة الدراسية هنا لربطها في شاشة التسكين
    academic_year = models.ForeignKey('AcademicYear', on_delete=models.CASCADE, verbose_name="السنة الدراسية", null=True)
    total_amount = models.DecimalField("إجمالي مبلغ الخطة", max_digits=10, decimal_places=2, default=0)
    number_of_installments = models.PositiveIntegerField("عدد الأقساط")
    interest_value = models.DecimalField(
        "قيمة الفائدة الإضافية",
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="قيمة فائدة ثابتة تضاف لإجمالي الخطة"
    )

    class Meta:
        verbose_name = "خطة مصروفات"
        verbose_name_plural = "خطط المصروفات"

    def update_total(self):
        """تحديث إجمالي مبلغ الخطة بناءً على مجموع البنود"""
        total = self.items.aggregate(total=models.Sum('amount'))['total'] or 0
        self.total_amount = total + self.interest_value
        self.save(update_fields=['total_amount'])

    def __str__(self):
        return f"{self.name} ({self.total_amount})"

class PlanItem(models.Model):
    plan = models.ForeignKey('InstallmentPlan', on_delete=models.CASCADE, related_name='items')
    name = models.CharField("اسم القسط", max_length=100) # مثل: القسط الأول
    amount = models.DecimalField("المبلغ", max_digits=10, decimal_places=2)
    due_date = models.DateField("تاريخ الاستحقاق")
    order = models.PositiveIntegerField("ترتيب القسط", default=1)

    class Meta:
        ordering = ['order']
        verbose_name = "بند خطة"
        verbose_name_plural = "بنود الخطط"

    def __str__(self):
        return f"{self.name} - {self.amount}"
    
class StudentInstallment(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'قيد الانتظار'),
        ('Partial', 'دفع جزئي'),
        ('Paid', 'تم الدفع'),
        ('Late', 'متأخر'),
    )

    student = models.ForeignKey("students.Student", on_delete=models.CASCADE, related_name="installments")
    installment_plan = models.ForeignKey('InstallmentPlan', on_delete=models.PROTECT)
    academic_year = models.ForeignKey('AcademicYear', on_delete=models.CASCADE)
    
    installment_number = models.PositiveIntegerField("رقم القسط")
    amount_due = models.DecimalField("قيمة القسط الأصلية", max_digits=10, decimal_places=2)
    paid_amount = models.DecimalField("المبلغ المدفوع فعلياً", max_digits=10, decimal_places=2, default=0)
    
    due_date = models.DateField("تاريخ الاستحقاق")
    late_fee = models.DecimalField("غرامة تأخير", max_digits=10, decimal_places=2, default=0)
    status = models.CharField("الحالة", max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "قسط طالب"
        verbose_name_plural = "أقساط الطلاب"
        ordering = ['due_date', 'installment_number']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'academic_year', 'installment_number'],
                name='unique_student_installment_per_year'
            )
        ]

    @property
    def total_required(self):
        """إجمالي المطلوب لهذا القسط (الأصل + الغرامة)"""
        return self.amount_due + self.late_fee

    # أضفنا هذه الدالة كـ method عادية لتسهيل استدعائها في الحسابات
    def remaining_amount(self):
        """المتبقي المطلوب سداده من هذا القسط"""
        remaining = self.total_required - self.paid_amount
        return max(remaining, Decimal("0.00"))

    # هذه الدالة هي التي كانت تسبب الخطأ في صورتك الأخيرة (تم توحيد الاسم)
    def update_status(self):
        """
        تحديث الحالة بناءً على المبالغ والتواريخ.
        تم تحسينها لتجنب استعلام قاعدة البيانات إذا لم تتغير الحالة.
        """
        total_req = self.total_required
        new_status = 'Pending'

        if self.paid_amount >= total_req:
            new_status = 'Paid'
        elif self.paid_amount > 0:
            new_status = 'Partial'
        elif self.due_date < timezone.now().date():
            new_status = 'Late'
        else:
            new_status = 'Pending'

        # التحقق: لا تقم بعمل استعلام تحديث (Update) إلا إذا تغيرت الحالة فعلياً
        if self.status != new_status:
            self.status = new_status
            # استخدام update لحفظ تغيير واحد فقط، أو حفظ الكائن كاملاً
            StudentInstallment.objects.filter(pk=self.pk).update(status=new_status)

    def __str__(self):
        return f"{self.student.get_full_name()} | قسط {self.installment_number} | المتبقي: {self.remaining_amount()} ج.م"

# =====================================================
# حساب الطالب
# =====================================================

class StudentAccount(models.Model):
    student = models.ForeignKey("students.Student", on_delete=models.CASCADE, related_name="accounts")
    academic_year = models.ForeignKey('AcademicYear', on_delete=models.CASCADE, null=True)
    installment_plan = models.ForeignKey('InstallmentPlan', on_delete=models.SET_NULL, null=True, blank=True)
    
    # تمت إضافة الحقل الجديد هنا
    revenue_category = models.ForeignKey(
        'RevenueCategory', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name="بند الإيراد المرتبط"
    )
    
    total_fees = models.DecimalField("إجمالي المصروفات", max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField("الخصم", max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['student', 'academic_year', 'revenue_category']
        verbose_name = "حساب طالب مالي"
        verbose_name_plural = "حسابات الطلاب المالية"
    
    def __str__(self):
        cat_name = f" - {self.revenue_category.name}" if self.revenue_category else ""
        return f"حساب {self.student.get_full_name()}{cat_name}"

    @property
    def net_fees(self):
        # هذه هي الخاصية التي تسبب الخطأ في صفحة التسكين
        return self.total_fees - self.discount

    @property
    def current_year_fees_amount(self):
        account = self.accounts.filter(
            academic_year=self.academic_year
        ).first()
    @property
    def paid_amount_current_year(self):
        from finance.models import Payment
        from django.db.models import Sum
        
        # التأكد من مطابقة السنة والفئة حرفياً
        queryset = Payment.objects.filter(
            student=self.student,
            academic_year=self.academic_year,
            revenue_category__name='المصروفات الاساسيه'
        )
        
        # الطباعة هنا لتراها في الـ Terminal وتعرف هل وجد النظام شيئاً أم لا
        total = queryset.aggregate(Sum('amount_paid'))['amount_paid__sum']
        # print(f"DEBUG: Student {self.student.id} found {queryset.count()} payments, total: {total}")
        
        return total or Decimal("0.00")
    
    @property
    def total_paid(self):
        from finance.models import Payment
        from django.db.models import Sum
        
        # نستخدم id الطالب مباشرة للبحث، ونطبع النتيجة في الـ Console لنرى ماذا يحدث
        qs = Payment.objects.filter(
            student=self.student,
            academic_year=self.academic_year
        )
        total = qs.aggregate(Sum('amount_paid'))['amount_paid__sum']
        
        # طباعة للتصحيح (ستظهر في الـ Terminal الذي يعمل عليه السيرفر)
        print(f"DEBUG: Student {self.student.id} | Total: {total}")
        
        return total or 0
    
    @property
    def total_remaining(self):
        remaining = (self.total_fees - self.discount) - self.total_paid
        # انظر هنا: القوس الأول لـ max والثاني لـ Decimal
        return max(remaining, Decimal("0.00"))
    

    def generate_installments(self):
        """توليد أقساط الطالب مع تصفير المدفوع وتوزيع الخصم"""
        if not self.installment_plan:
            return False

        from .models import StudentInstallment
        plan_items = self.installment_plan.items.all().order_by('due_date')

        if not plan_items:
            return False

        with transaction.atomic():
            # 1. حذف الأقساط القديمة تماماً لإعادة التسكين
            self.student.installments.all().delete()

            num_installments = plan_items.count()
            # نستخدم الخاصية net_fees التي عرفناها في الأعلى
            net_total = self.net_fees 
            
            # حساب قيمة القسط الواحد تقريبياً
            amount_per_installment = (net_total / num_installments).quantize(Decimal('0.01'))
            
            total_allocated = Decimal('0.00')
            new_installments = []
            
            for i, item in enumerate(plan_items):
                if i == num_installments - 1:
                    current_installment_amount = net_total - total_allocated
                else:
                    current_installment_amount = amount_per_installment
                    total_allocated += current_installment_amount

                new_installments.append(
                    StudentInstallment(
                        student=self.student,
                        installment_plan=self.installment_plan,
                        academic_year=self.academic_year or self.student.academic_year,
                        installment_number=i + 1,
                        amount_due=current_installment_amount,
                        paid_amount=Decimal('0.00'),
                        due_date=item.due_date,
                        status='Pending'
                    )
                )
            
            if new_installments:
                StudentInstallment.objects.bulk_create(new_installments)
                
        return True


class Payment(models.Model):
    """نموذج عمليات الدفع وتحصيل الرسوم"""
    installment = models.ForeignKey(
        'StudentInstallment', 
        on_delete=models.CASCADE, 
        related_name="payments",
        null=True, 
        blank=True, 
        help_text="اتركه فارغاً للإيرادات الحرة"
    )
    student = models.ForeignKey(
        "students.Student", 
        on_delete=models.CASCADE, 
        related_name="all_payments",
        null=True, 
        blank=True
    )
    revenue_category = models.ForeignKey(
        'RevenueCategory', 
        on_delete=models.PROTECT, 
        null=True, 
        blank=False,
        verbose_name="فئة الإيراد"
    )
    academic_year = models.ForeignKey(
        'AcademicYear', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        verbose_name="السنة الدراسية"
    )
    amount_paid = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        verbose_name="المبلغ المدفوع"
    )
    payment_date = models.DateField(
        default=timezone.now, 
        verbose_name="تاريخ الدفع"
    )
    collected_by = models.ForeignKey(
        'auth.User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="collected_payments", 
        verbose_name="المحصل (الموظف)"
    )
    is_closed = models.BooleanField(
        default=False, 
        verbose_name="تم تقفيل الخزينة"
    )
    closure = models.ForeignKey(
        'DailyClosure', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="payments",
        verbose_name="رقم الجرد/الإغلاق"
    )
    receipt_number = models.PositiveIntegerField(
        null=True, 
        blank=True, 
        verbose_name="رقم الإيصال المرجعي"
    )
    notes = models.TextField(null=True, blank=True, verbose_name="ملاحظات إضافية")

    class Meta:
        verbose_name = "عملية دفع"
        verbose_name_plural = "عمليات الدفع"
        ordering = ['-payment_date', '-id']

    def clean(self):
        if self.pk:
            original = Payment.objects.get(pk=self.pk)
            if original.is_closed:
                raise ValidationError("🚨 خطأ أمني: هذا الإيصال تم إغلاقه في الخزينة، لا يمكن تعديله.")

    def save(self, *args, **kwargs):
        is_new = not self.pk
        if self.student and not self.academic_year:
            self.academic_year = self.student.academic_year

        with transaction.atomic():
            super(Payment, self).save(*args, **kwargs)
            
            if self.student:
                # 1. جلب بيانات الفئة والفئة الأم
                category = self.revenue_category
                # نتحقق هل اسم الفئة أو اسم الفئة الرئيسية (Parent) يحتوي على كلمة "المصروفات"
                is_educational_fee = False
                if category:
                    # التحقق من الفئة نفسها أو الفئة الأم
                    if "المصروفات" in category.name or (category.parent and "المصروفات" in category.parent.name):
                        is_educational_fee = True
                
                # 2. تحديث القسط المربوط يدوياً
                if self.installment:
                    inst = self.installment
                    total = Payment.objects.filter(installment=inst).aggregate(models.Sum('amount_paid'))['amount_paid__sum'] or 0
                    inst.paid_amount = total
                    inst.status = 'Paid' if inst.paid_amount >= inst.amount_due else 'Partial'
                    inst.save()

                # 3. الخصم التلقائي لأي فئة تابعة للمصروفات
                elif is_new and is_educational_fee:
                    open_installments = StudentInstallment.objects.filter(
                        student=self.student,
                        academic_year=self.academic_year
                    ).exclude(status='Paid').order_by('due_date')

                    remaining = self.amount_paid
                    for inst in open_installments:
                        if remaining <= 0: break
                        needed = inst.amount_due - inst.paid_amount
                        if remaining >= needed:
                            inst.paid_amount = inst.amount_due
                            inst.status = 'Paid'
                            remaining -= needed
                        else:
                            inst.paid_amount += remaining
                            inst.status = 'Partial'
                            remaining = 0
                        inst.save()
                        
                        # ربط الإيصال بالقسط
                        self.installment = inst
                        super(Payment, self).save(update_fields=['installment'])

# class Payment(models.Model):
#     """نموذج عمليات الدفع وتحصيل الرسوم"""
#     installment = models.ForeignKey(
#         'StudentInstallment', 
#         on_delete=models.CASCADE, 
#         related_name="payments",
#         null=True, 
#         blank=True, 
#         help_text="اتركه فارغاً للإيرادات الحرة"
#     )
#     student = models.ForeignKey(
#         "students.Student", 
#         on_delete=models.CASCADE, 
#         related_name="all_payments",
#         null=True, 
#         blank=True
#     )
#     revenue_category = models.ForeignKey(
#         'RevenueCategory', 
#         on_delete=models.PROTECT, 
#         null=True, 
#         blank=False,
#         verbose_name="فئة الإيراد"
#     )
#     academic_year = models.ForeignKey(
#         'AcademicYear', 
#         on_delete=models.CASCADE, 
#         null=True, 
#         blank=True,
#         verbose_name="السنة الدراسية"
#     )
#     amount_paid = models.DecimalField(
#         max_digits=10, 
#         decimal_places=2, 
#         verbose_name="المبلغ المدفوع"
#     )
#     payment_date = models.DateField(
#         default=timezone.now, 
#         verbose_name="تاريخ الدفع"
#     )
#     collected_by = models.ForeignKey(
#         'auth.User', 
#         on_delete=models.SET_NULL, 
#         null=True, 
#         blank=True, 
#         related_name="collected_payments", 
#         verbose_name="المحصل (الموظف)"
#     )
#     is_closed = models.BooleanField(
#         default=False, 
#         verbose_name="تم تقفيل الخزينة"
#     )
#     closure = models.ForeignKey(
#         'DailyClosure', 
#         on_delete=models.SET_NULL, 
#         null=True, 
#         blank=True, 
#         related_name="payments",
#         verbose_name="رقم الجرد/الإغلاق"
#     )
#     receipt_number = models.PositiveIntegerField(
#         null=True, 
#         blank=True, 
#         verbose_name="رقم الإيصال المرجعي"
#     )
#     notes = models.TextField(null=True, blank=True, verbose_name="ملاحظات إضافية")

#     class Meta:
#         verbose_name = "عملية دفع"
#         verbose_name_plural = "عمليات الدفع"
#         ordering = ['-payment_date', '-id']

#     def clean(self):
#         """التحقق من البيانات قبل الحفظ لمنع تعديل المقفل"""
#         if self.pk:
#             original = Payment.objects.get(pk=self.pk)
#             if original.is_closed:
#                 raise ValidationError("🚨 خطأ أمني: هذا الإيصال تم إغلاقه في الخزينة، لا يمكن تعديله نهائياً.")

#     def normalize_arabic(self, text):
#         """دالة داخلية لتوحيد النصوص العربية لضمان دقة البحث"""
#         if not text: return ""
#         text = text.strip()
#         if text.startswith("ال"): text = text[2:]
#         return text.replace('أ','ا').replace('إ','ا').replace('آ','ا').replace('ة','ه').replace('ى','ي')

#     def save(self, *args, **kwargs):
#         is_new = not self.pk
#         # 1. التأكد من ربط السنة الدراسية تلقائياً
#         if self.student and not self.academic_year:
#             self.academic_year = self.student.academic_year
            
        

#         # 2. استخدام transaction لضمان أن العملية (إيصال + خصم مديونية) تتم معاً أو لا تتم
#         with transaction.atomic():
#             # حفظ الإيصال أولاً لإنشائه في قاعدة البيانات
#             super(Payment, self).save(*args, **kwargs)
            
#             # 3. منطق الخصم البرمجي التلقائي (للإيصالات الجديدة فقط)
#             if is_new and self.student:
#                 # دالة لتطبيع النصوص لضمان التعرف على "كتب" و "انشطة" و "دبلوم"
#                 def norm(t):
#                     if not t: return ""
#                     return t.strip().replace('أ','ا').replace('إ','ا').replace('آ','ا').replace('ة','ه').replace('ى','ي')

#                 cat_name = norm(self.revenue_category.name if self.revenue_category else "")
                
#                 # الكلمات المفتاحية التي يجب أن تخصم من المديونية (بناءً على صورتك)
#                 deduction_keywords = ['مصروفات', 'انشطه', 'نشاط', 'كتب', 'منازل', 'دبلوم', 'استماره', 'اساسيه']

#                 if any(key in cat_name for key in deduction_keywords):
#                     from .models import StudentInstallment
                    
#                     # جلب الأقساط المفتوحة للطالب مرتبة من الأقدم للأحدث
#                     open_installments = StudentInstallment.objects.filter(
#                         student=self.student,
#                         academic_year=self.academic_year
#                     ).exclude(status='Paid').order_by('due_date')

#                     remaining_amount = self.amount_paid

#                     for inst in open_installments:
#                         if remaining_amount <= 0:
#                             break
                        
#                         # حساب المبلغ المتبقي في هذا القسط
#                         needed_to_clear_inst = inst.amount_due - inst.paid_amount
                        
#                         if remaining_amount >= needed_to_clear_inst:
#                             # دفع القسط بالكامل والانتقال للي بعده
#                             inst.paid_amount = inst.amount_due
#                             inst.status = 'Paid'
#                             remaining_amount -= needed_to_clear_inst
#                         else:
#                             # دفع جزء من القسط والتوقف
#                             inst.paid_amount += remaining_amount
#                             inst.status = 'Partial'
#                             remaining_amount = 0
                        
#                         # تحديث القسط وربطه بالإيصال
#                         inst.save()
#                         # ربط الإيصال بالقسط الذي خصم منه (لأغراض التقارير)
#                         self.installment = inst
#                         super(Payment, self).save(update_fields=['installment'])

# class Payment(models.Model):
#     """نموذج عمليات الدفع وتحصيل الرسوم"""
#     installment = models.ForeignKey(
#         'StudentInstallment', 
#         on_delete=models.CASCADE, 
#         related_name="payments",
#         null=True, 
#         blank=True, 
#         help_text="اتركه فارغاً للإيرادات الحرة"
#     )
#     student = models.ForeignKey(
#         "students.Student", 
#         on_delete=models.CASCADE, 
#         related_name="all_payments",
#         null=True, 
#         blank=True
#     )
#     revenue_category = models.ForeignKey(
#         'RevenueCategory', 
#         on_delete=models.PROTECT, 
#         null=True, 
#         blank=False,
#         verbose_name="فئة الإيراد"
#     )
#     academic_year = models.ForeignKey(
#         'AcademicYear', 
#         on_delete=models.CASCADE, 
#         null=True, 
#         blank=True,
#         verbose_name="السنة الدراسية"
#     )
#     amount_paid = models.DecimalField(
#         max_digits=10, 
#         decimal_places=2, 
#         verbose_name="المبلغ المدفوع"
#     )
#     payment_date = models.DateField(
#         default=timezone.now, 
#         verbose_name="تاريخ الدفع"
#     )
#     collected_by = models.ForeignKey(
#         User, 
#         on_delete=models.SET_NULL, 
#         null=True, 
#         blank=True, 
#         related_name="collected_payments", 
#         verbose_name="المحصل (الموظف)"
#     )
#     is_closed = models.BooleanField(
#         default=False, 
#         verbose_name="تم تقفيل الخزينة"
#     )
#     closure = models.ForeignKey(
#         'DailyClosure', 
#         on_delete=models.SET_NULL, 
#         null=True, 
#         blank=True, 
#         related_name="payments",
#         verbose_name="رقم الجرد/الإغلاق"
#     )
    
#     receipt_number = models.PositiveIntegerField(
#         null=True, 
#         blank=True, 
#         verbose_name="رقم الإيصال المرجعي"
#     )

#     notes = models.TextField(null=True, blank=True, verbose_name="ملاحظات إضافية")

#     class Meta:
#         verbose_name = "عملية دفع"
#         verbose_name_plural = "عمليات الدفع"
#         ordering = ['-payment_date', '-id']

#     def clean(self):
#         """التحقق من البيانات قبل الحفظ لمنع تعديل المقفل"""
#         if self.pk:
#             original = Payment.objects.get(pk=self.pk)
#             if original.is_closed:
#                 raise ValidationError("🚨 خطأ أمني: هذا الإيصال تم إغلاقه في الخزينة، لا يمكن تعديله نهائياً.")
            
#     def save(self, *args, **kwargs):
#         # 1. تحديد ما إذا كان الإيصال جديداً قبل الحفظ
#         is_new = not self.pk
        
#         # 2. تأمين السنة الدراسية: ربط الدفع بسنة الطالب الحالية تلقائياً
#         if self.student and not self.academic_year:
#             self.academic_year = self.student.academic_year

#         # 3. تشغيل التحقق من البيانات (clean)
#         self.full_clean()

#         # 4. الحفظ في قاعدة البيانات داخل Transaction لضمان سلامة العمليات المتعددة
#         with transaction.atomic():
#             # حفظ إيصال الدفع أولاً
#             super(Payment, self).save(*args, **kwargs)
            
#             # --- [أ] تحديث مديونية الطالب (إصلاح مشكلة الأنشطة والمصاريف) ---
#             if is_new and self.student:
#                 student = self.student
#                 # الخصم من حقل "إجمالي المديونية" (تأكد من وجود الحقل total_debt في موديل الطالب)
#                 if hasattr(student, 'total_debt'):
#                     student.total_debt -= self.amount_paid
                
#                 # الإضافة إلى حقل "إجمالي المدفوعات"
#                 if hasattr(student, 'total_paid'):
#                     student.total_paid += self.amount_paid
                
#                 # حفظ التحديثات في سجل الطالب
#                 student.save()
            
#             # --- [ب] التحديث التلقائي لسجل المخزن (InventoryMaster) ---
#             if self.student and self.revenue_category:
#                 from django.db.models import Sum
#                 from .models import InventoryMaster, DeliveryRecord # استيراد الموديلات المطلوبة

#                 # جلب أصناف المخزن المرتبطة بصف الطالب وسنته
#                 inventory_items = InventoryMaster.objects.filter(
#                     grade=self.student.grade, 
#                     academic_year=self.academic_year
#                 )
                
#                 current_cat_name = self.revenue_category.name
#                 parent_cat_name = self.revenue_category.parent.name if self.revenue_category.parent else ""

#                 for item in inventory_items:
#                     item_name = item.item.name
#                     # فحص العلاقة بين بند التحصيل وصنف المخزن
#                     is_relevant = (item_name in current_cat_name or item_name in parent_cat_name)

#                     if is_relevant:
#                         # حساب المجموع الفعلي للمدفوعات لهذا الصنف
#                         paid_data = Payment.objects.filter(
#                             student=self.student,
#                             academic_year=self.academic_year,
#                             revenue_category__name__icontains=item_name
#                         ).aggregate(total=Sum('amount_paid'))
                        
#                         paid_sum = paid_data['total'] or 0
                        
#                         # إنشاء سجل تسليم إذا غطى المبلغ سعر الصنف
#                         if paid_sum >= item.price and item.price > 0:
#                             DeliveryRecord.objects.get_or_create(
#                                 student=self.student,
#                                 inventory_item=item
#                             )

#     def __str__(self):
#         student_info = self.student.get_full_name() if self.student else "إيراد حر"
#         # تم تعديل هذا السطر ليظهر رقم الإيصال المرجعي بدلاً من ID قاعدة البيانات
#         receipt_ref = f"#{self.receipt_number}" if self.receipt_number else f"ID:{self.pk}"
#         return f"إيصال {receipt_ref} - {student_info} - {self.amount_paid} ج.م"
    

# class Payment(models.Model):
#     """نموذج عمليات الدفع وتحصيل الرسوم"""
#     installment = models.ForeignKey(
#         'StudentInstallment', 
#         on_delete=models.CASCADE, 
#         related_name="payments",
#         null=True, 
#         blank=True, 
#         help_text="اتركه فارغاً للإيرادات الحرة"
#     )
#     student = models.ForeignKey(
#         "students.Student", 
#         on_delete=models.CASCADE, 
#         related_name="all_payments",
#         null=True, 
#         blank=True
#     )
#     revenue_category = models.ForeignKey(
#         'RevenueCategory', 
#         on_delete=models.PROTECT, 
#         null=True, 
#         blank=False,
#         verbose_name="فئة الإيراد"
#     )
#     academic_year = models.ForeignKey(
#         'AcademicYear', 
#         on_delete=models.CASCADE, 
#         null=True, 
#         blank=True,
#         verbose_name="السنة الدراسية"
#     )
#     amount_paid = models.DecimalField(
#         max_digits=10, 
#         decimal_places=2, 
#         verbose_name="المبلغ المدفوع"
#     )
#     payment_date = models.DateField(
#         default=timezone.now, 
#         verbose_name="تاريخ الدفع"
#     )
#     collected_by = models.ForeignKey(
#         User, 
#         on_delete=models.SET_NULL, 
#         null=True, 
#         blank=True, 
#         related_name="collected_payments", 
#         verbose_name="المحصل (الموظف)"
#     )
#     is_closed = models.BooleanField(
#         default=False, 
#         verbose_name="تم تقفيل الخزينة"
#     )
#     closure = models.ForeignKey(
#         'DailyClosure', 
#         on_delete=models.SET_NULL, 
#         null=True, 
#         blank=True, 
#         related_name="payments",
#         verbose_name="رقم الجرد/الإغلاق"
#     )
#     receipt_number = models.PositiveIntegerField(null=True, blank=True, verbose_name="رقم الإيصال الورقي المرجعي")
#     notes = models.TextField(null=True, blank=True, verbose_name="ملاحظات إضافية")

#     class Meta:
#         verbose_name = "عملية دفع"
#         verbose_name_plural = "عمليات الدفع"
#         ordering = ['-payment_date', '-id']

#     def clean(self):
#         """التحقق من البيانات قبل الحفظ لمنع تعديل المقفل"""
#         if self.pk:
#             original = Payment.objects.get(pk=self.pk)
#             if original.is_closed:
#                 raise ValidationError("🚨 خطأ أمني: هذا الإيصال تم إغلاقه في الخزينة، لا يمكن تعديله نهائياً.")
            
#     def save(self, *args, **kwargs):
#         # 1. تحديد ما إذا كان الإيصال جديداً قبل الحفظ
#         is_new = not self.pk
        
#         # 2. تأمين السنة الدراسية: ربط الدفع بسنة الطالب الحالية تلقائياً
#         if self.student and not self.academic_year:
#             self.academic_year = self.student.academic_year

#         # 3. تشغيل التحقق من البيانات (clean)
#         self.full_clean()

#         # 4. الحفظ في قاعدة البيانات داخل Transaction لضمان سلامة العمليات المتعددة
#         with transaction.atomic():
#             # حفظ إيصال الدفع أولاً
#             super(Payment, self).save(*args, **kwargs)
            
#             # --- [أ] تحديث مديونية الطالب (إصلاح مشكلة الأنشطة والمصاريف) ---
#             if is_new and self.student:
#                 student = self.student
#                 # الخصم من حقل "إجمالي المديونية" (تأكد من وجود الحقل total_debt في موديل الطالب)
#                 if hasattr(student, 'total_debt'):
#                     student.total_debt -= self.amount_paid
                
#                 # الإضافة إلى حقل "إجمالي المدفوعات"
#                 if hasattr(student, 'total_paid'):
#                     student.total_paid += self.amount_paid
                
#                 # حفظ التحديثات في سجل الطالب
#                 student.save()
            
#             # --- [ب] التحديث التلقائي لسجل المخزن (InventoryMaster) ---
#             # هذا الجزء ظل كما هو لضمان استمرار عمل نظام الكتب والزي
#             if self.student and self.revenue_category:
#                 from django.db.models import Sum
#                 from .models import InventoryMaster, DeliveryRecord # استيراد الموديلات المطلوبة

#                 # جلب أصناف المخزن المرتبطة بصف الطالب وسنته
#                 inventory_items = InventoryMaster.objects.filter(
#                     grade=self.student.grade, 
#                     academic_year=self.academic_year
#                 )
                
#                 current_cat_name = self.revenue_category.name
#                 parent_cat_name = self.revenue_category.parent.name if self.revenue_category.parent else ""

#                 for item in inventory_items:
#                     item_name = item.item.name
#                     # فحص العلاقة بين بند التحصيل وصنف المخزن
#                     is_relevant = (item_name in current_cat_name or item_name in parent_cat_name)

#                     if is_relevant:
#                         # حساب المجموع الفعلي للمدفوعات لهذا الصنف
#                         paid_data = Payment.objects.filter(
#                             student=self.student,
#                             academic_year=self.academic_year,
#                             revenue_category__name__icontains=item_name
#                         ).aggregate(total=Sum('amount_paid'))
                        
#                         paid_sum = paid_data['total'] or 0
                        
#                         # إنشاء سجل تسليم إذا غطى المبلغ سعر الصنف
#                         if paid_sum >= item.price and item.price > 0:
#                             DeliveryRecord.objects.get_or_create(
#                                 student=self.student,
#                                 inventory_item=item
#                             )

#     def __str__(self):
#         student_info = self.student.get_full_name() if self.student else "إيراد حر"
#         return f"إيصال {self.pk or 'جديد'} - {student_info} - {self.amount_paid} ج.م"
    
        
# class Payment(models.Model):
#     # 1. الروابط الأساسية
#     installment = models.ForeignKey(
#         'StudentInstallment', 
#         on_delete=models.CASCADE, 
#         related_name="payments",
#         null=True, 
#         blank=True, 
#         help_text="اتركه فارغاً للإيرادات الحرة"
#     )
#     student = models.ForeignKey(
#         "students.Student", 
#         on_delete=models.CASCADE, 
#         related_name="all_payments",
#         null=True, 
#         blank=True
#     )
#     revenue_category = models.ForeignKey(
#         'RevenueCategory', 
#         on_delete=models.PROTECT, 
#         null=True, 
#         blank=False,
#         verbose_name="فئة الإيراد"
#     )
#     academic_year = models.ForeignKey(
#         'AcademicYear', 
#         on_delete=models.CASCADE, 
#         null=True, 
#         blank=True,
#         verbose_name="السنة الدراسية"
#     )

#     # 2. البيانات المالية
#     amount_paid = models.DecimalField(
#         max_digits=10, 
#         decimal_places=2, 
#         verbose_name="المبلغ المدفوع"
#     )
#     payment_date = models.DateField(
#         default=timezone.now, 
#         verbose_name="تاريخ الدفع"
#     )
    
#     # 3. بيانات الخزينة والرقابة
#     collected_by = models.ForeignKey(
#         User, 
#         on_delete=models.SET_NULL, 
#         null=True, 
#         blank=True, 
#         related_name="collected_payments", 
#         verbose_name="المحصل (الموظف)"
#     )
#     is_closed = models.BooleanField(
#         default=False, 
#         verbose_name="تم تقفيل الخزينة"
#     )
#     closure = models.ForeignKey(
#         'DailyClosure', 
#         on_delete=models.SET_NULL, 
#         null=True, 
#         blank=True, 
#         related_name="payments",
#         verbose_name="رقم الجرد/الإغلاق"
#     )
    
#     receipt_number = models.PositiveIntegerField(null=True, blank=True, verbose_name="رقم الإيصال الورقي المرجعي")

#     notes = models.TextField(null=True, blank=True, verbose_name="ملاحظات إضافية")

#     class Meta:
#         verbose_name = "عملية دفع"
#         verbose_name_plural = "عمليات الدفع"
#         ordering = ['-payment_date', '-id']

#     def clean(self):
#         """التحقق من البيانات قبل الحفظ لمنع تعديل المقفل"""
#         if self.pk:
#             original = Payment.objects.get(pk=self.pk)
#             if original.is_closed:
#                 raise ValidationError("🚨 خطأ أمني: هذا الإيصال تم إغلاقه في الخزينة، لا يمكن تعديله نهائياً.")
            
#     def save(self, *args, **kwargs):
#         # 1. تأمين السنة الدراسية: ربط الدفع بسنة الطالب الحالية تلقائياً
#         if self.student and not self.academic_year:
#             self.academic_year = self.student.academic_year

#         # 2. تشغيل التحقق من البيانات (clean)
#         self.full_clean()

#         # 3. الحفظ في قاعدة البيانات داخل Transaction
#         with transaction.atomic():
#             # حفظ إيصال الدفع (استخدام الصيغة الأكثر استقراراً لـ super)
#             super(Payment, self).save(*args, **kwargs)
            
#             # 4. التحديث التلقائي لسجل المخزن (InventoryMaster)
#             if self.student and self.revenue_category:
#                 from django.db.models import Sum
                
#                 # جلب أصناف المخزن المرتبطة بصف الطالب وسنته
#                 inventory_items = InventoryMaster.objects.filter(
#                     grade=self.student.grade, 
#                     academic_year=self.academic_year
#                 )
                
#                 current_cat_name = self.revenue_category.name
#                 parent_cat_name = self.revenue_category.parent.name if self.revenue_category.parent else ""

#                 for item in inventory_items:
#                     item_name = item.item.name
#                     is_relevant = (item_name in current_cat_name or item_name in parent_cat_name)

#                     if is_relevant:
#                         # حساب المجموع الفعلي للمدفوعات لهذا الصنف
#                         paid_data = Payment.objects.filter(
#                             student=self.student,
#                             academic_year=self.academic_year,
#                             revenue_category__name__icontains=item_name
#                         ).aggregate(total=Sum('amount_paid'))
                        
#                         paid_sum = paid_data['total'] or 0
                        
#                         # إنشاء سجل تسليم إذا غطى المبلغ سعر الصنف
#                         if paid_sum >= item.price and item.price > 0:
#                             DeliveryRecord.objects.get_or_create(
#                                 student=self.student,
#                                 inventory_item=item
#                             )

#     def __str__(self):
#         student_info = self.student.get_full_name() if self.student else "إيراد حر"
#         return f"إيصال {self.pk or 'جديد'} - {student_info} - {self.amount_paid} ج.م"
    

class Expense(models.Model):
    title = models.CharField(max_length=200, verbose_name="بيان الصرف")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ")
    expense_date = models.DateTimeField(default=timezone.now, verbose_name="تاريخ الصرف")
    # ربط المصروف بالموظف الذي قام بالصرف
    spent_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="قام بالصرف")
    
    # ربط المصروف بالجرد اليومي (الخزينة)
    is_closed = models.BooleanField(default=False, verbose_name="تم ضمه للجرد")
    closure = models.ForeignKey(
        'DailyClosure', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="expenses",
        verbose_name="رقم الجرد"
    )
    
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")

    class Meta:
        verbose_name = "مصروف"
        verbose_name_plural = "المصروفات"
        ordering = ['-expense_date']

    def clean(self):
        if self.pk:
            original = Expense.objects.get(pk=self.pk)
            if original.is_closed:
                raise ValidationError("🚨 لا يمكن تعديل مصروف تم إغلاقه في الجرد.")

    def __str__(self):
        return f"{self.title} - {self.amount} ج.م"

 
class ItemDefinition(models.Model):
    name = models.CharField("اسم الصنف (مثل: كتاب لغة عربية)", max_length=200)
    
    class Meta:
        verbose_name = "تعريف صنف"
        verbose_name_plural = "تعريفات الأصناف"

    def __str__(self):
        return self.name

# 2. المخزن العام المعدل (الذي سيربط الأصناف بالصفوف والسنوات)
class InventoryMaster(models.Model):
    item = models.ForeignKey(ItemDefinition, on_delete=models.CASCADE, verbose_name="الصنف")
    grade = models.ForeignKey("students.Grade", on_delete=models.CASCADE, verbose_name="الصف الدراسي")
    academic_year = models.ForeignKey('AcademicYear', on_delete=models.CASCADE, verbose_name="السنة الدراسية")
    
    #price = models.DecimalField("سعر الصنف", max_digits=10, decimal_places=2)
    total_quantity = models.PositiveIntegerField("الكمية المتاحة في المخزن")

    class Meta:
        verbose_name = "تعريف مخزن (صنف)"
        verbose_name_plural = "المخزن العام (الأصناف)"
        unique_together = ('item', 'grade', 'academic_year') 

    def get_remaining_stock(self):
        # المتبقي = الكمية الكلية - عدد من استلموا فعلياً
        delivered_count = self.deliveries.count()
        return self.total_quantity - delivered_count

    def __str__(self):
        return f"{self.item.name} - {self.grade} | المتبقي: {self.get_remaining_stock()}"

# 3. سجل الاستلام (تأكد من تعديل الـ __str__ ليتناسب مع التغيير)

class DeliveryRecord(models.Model):
    student = models.ForeignKey("students.Student", on_delete=models.CASCADE, verbose_name="الطالب")
    inventory_item = models.ForeignKey(InventoryMaster, on_delete=models.CASCADE, related_name='deliveries', verbose_name="الصنف")
    
    delivery_date = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التسليم")
    
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name="الموظف المسؤول عن التسليم"
    )
    
    # إضافة حقل للملاحظات لتوثيق أي تفاصيل خاصة بالتسليم (مثلاً: استلم ولي الأمر)
    notes = models.TextField(null=True, blank=True, verbose_name="ملاحظات التسليم")
    
    # إضافة حقل لتتبع حالة التجهيز إذا لزم الأمر لاحقاً
    is_received = models.BooleanField(default=True, verbose_name="تم الاستلام فعلياً")

    class Meta:
        unique_together = ('student', 'inventory_item')
        verbose_name = "سجل تسليم طالب"
        verbose_name_plural = "سجلات استلام الطلاب"
        ordering = ['-delivery_date'] # ترتيب السجلات من الأحدث للأقدم

    def __str__(self):
        return f"{self.student.get_full_name()} | {self.inventory_item.item.name} | {self.delivery_date.strftime('%Y-%m-%d')}"
class MonthlyClosure(models.Model):
    month = models.DateField()
    total_collected = models.DecimalField(max_digits=10, decimal_places=2)
    total_remaining = models.DecimalField(max_digits=10, decimal_places=2)
    closed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Closure - {self.month.strftime('%B %Y')}"

class Coupon(models.Model):
    code = models.CharField(max_length=20, unique=True)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    expiry_date = models.DateField()
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def is_valid(self):
        return self.active and self.expiry_date >= timezone.now().date()
    
    def __str__(self):
        return self.code

