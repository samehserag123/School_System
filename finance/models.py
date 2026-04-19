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
from django.contrib import admin 

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
                category = self.revenue_category
                is_educational_fee = False
                if category:
                    if "المصروفات" in category.name or (category.parent and "المصروفات" in category.parent.name):
                        is_educational_fee = True
                
                # 1. التوزيع التلقائي الذكي (إذا لم يتم ربط الإيصال يدوياً بقسط محدد)
                if is_new and is_educational_fee and not self.installment:
                    open_installments = StudentInstallment.objects.filter(
                        student=self.student,
                        academic_year=self.academic_year
                    ).order_by('due_date')

                    remaining = self.amount_paid
                    last_inst = None
                    
                    # تسديد الأقساط غير المدفوعة
                    for inst in open_installments.exclude(status='Paid'):
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
                        last_inst = inst
                        
                    # 🔴 معالجة الدفع المقدم (Overpayment): 
                    # لو الطالب دفع مقدم بزيادة عن المطلوب في كل الأقساط، نضع الزيادة في آخر قسط
                    if remaining > 0:
                        last_inst = open_installments.last()
                        if last_inst:
                            last_inst.paid_amount += remaining
                            last_inst.status = 'Paid'
                            last_inst.save()
                    
                    # ربط الإيصال بآخر قسط تأثر بالدفع للتوثيق
                    if last_inst:
                        Payment.objects.filter(pk=self.pk).update(installment=last_inst)

                # 2. التحديث اليدوي (لو تم ربط الإيصال بقسط معين من شاشة الإدارة)
                elif self.installment:
                    inst = self.installment
                    total = Payment.objects.filter(installment=inst).aggregate(models.Sum('amount_paid'))['amount_paid__sum'] or 0
                    inst.paid_amount = total
                    inst.status = 'Paid' if inst.paid_amount >= inst.amount_due else 'Partial'
                    inst.save()

class Expense(models.Model):
    # إضافة خيارات نوع المصروف
    EXPENSE_TYPES = (
        ('petty', 'مصروفات نثرية'),
        ('general', 'مصروفات عمومية'),
    )
    
    title = models.CharField(max_length=200, verbose_name="بيان الصرف")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ")
    
    # 👇 الحقل الجديد المطلوب لحل الخطأ وتصنيف المصروفات 👇
    expense_type = models.CharField(max_length=20, choices=EXPENSE_TYPES, default='petty', verbose_name="نوع المصروف")
    
    expense_date = models.DateTimeField(default=timezone.now, verbose_name="تاريخ الصرف")
    
    # ربط المصروف بالموظف الذي قام بالصرف
    #spent_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="قام بالصرف")
    spent_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
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
                from django.core.exceptions import ValidationError # للتأكد من استيراد دالة الخطأ
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
    STATUS_CHOICES = [
        ('draft', 'مسودة'),
        ('closed', 'مغلق نهائياً'),
    ]

    # الخطأ غالباً هنا: تأكد أن حقل التاريخ لا يحتوي على max_digits أو decimal_places
    month = models.DateField(unique=True, verbose_name="الشهر") 
    
    # هذه الحقول هي فقط التي تقبل max_digits
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="رصيد أول المدة")
    total_revenues = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="إجمالي الإيرادات")
    total_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="إجمالي المصروفات")
    net_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="صافي المركز المالي")
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="الرصيد الختامي")
    
    # حقل الحالة
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='closed', verbose_name="حالة الشهر")
    
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات الإغلاق")
    closed_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإغلاق")
    closed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="المسؤول")

    class Meta:
        ordering = ['-month']
        verbose_name = "إغلاق شهري"
        verbose_name_plural = "الإغلاقات الشهرية"

    def __str__(self):
        return f"إغلاق {self.month.strftime('%B %Y')}"
 
class Coupon(models.Model):
    OFFER_TYPES = [
        ('general', 'كوبون ترويجي عام'),
        ('early_pay', 'خصم تعجيل الدفع (قسط محدد)'),
        ('full_pay', 'خصم السداد الشامل (كامل المديونية)'),
        ('specific_student', 'خصم لطلاب محددين'),
        ('new_student', 'خصم للطلبة الجدد'),
    ]

    DISCOUNT_CHOICES = [
        ('percentage', 'نسبة مئوية'),
        ('fixed', 'مبلغ ثابت'),
    ]

    # 🔥 الأقسام المسموح للكوبون العمل بها (متطابقة مع نظامك)
    VALID_CATEGORIES = [
        ('all', 'شامل جميع الأقسام'),
        ('fees', 'مصروفات دراسيه'),
        ('books', 'كتب وباقات دراسية'),
        ('bus', 'اشتراك باص'),
        ('courses', 'مجموعات وكورسات'),
    ]

    # الحقول الأساسية
    code = models.CharField(max_length=50, unique=True, verbose_name="كود الخصم/العرض")
    offer_type = models.CharField(max_length=30, choices=OFFER_TYPES, default='general', verbose_name="نوع العرض")
    
    # 🔥 الحقل الجديد للقسم
    allowed_category = models.CharField(max_length=20, choices=VALID_CATEGORIES, default='all', verbose_name="صالح للاستخدام في قسم")

    discount_type = models.CharField(max_length=20, choices=DISCOUNT_CHOICES, verbose_name="نوع الخصم")
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="قيمة الخصم")
    
    # حقول التحكم في الصلاحية
    active = models.BooleanField(default=True, verbose_name="نشط")
    start_date = models.DateField(null=True, blank=True, verbose_name="تاريخ بداية العرض")
    expiry_date = models.DateField(null=True, blank=True, verbose_name="تاريخ انتهاء العرض")
    
    # حدود الاستخدام
    times_used = models.PositiveIntegerField(default=0, verbose_name="مرات الاستخدام")
    usage_limit = models.PositiveIntegerField(default=1, verbose_name="الحد الأقصى للاستخدام العام")
    
    # الاستهداف
    target_students = models.ManyToManyField(
        'students.Student', 
        blank=True, 
        related_name="special_coupons",
        verbose_name="الطلاب المستهدفين"
    )

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المنشئ")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "عرض / كوبون خصم"
        verbose_name_plural = "عروض وكوبونات الخصم"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.code} ({self.get_offer_type_display()})"

    def check_validity(self, student=None):
        today = timezone.localdate()
        
        if not self.active: return False
        if self.start_date and today < self.start_date: return False
        if self.expiry_date and today > self.expiry_date: return False
        if self.times_used >= self.usage_limit: return False

        if student:
            if self.offer_type == 'specific_student':
                if not self.target_students.filter(id=student.id).exists():
                    return False
            if self.offer_type == 'new_student':
                limit_date = today - timezone.timedelta(days=30)
                if student.created_at.date() < limit_date:
                    return False

        # السماح للطالب الخارجي بالكوبونات العامة والجديدة
        elif not student and self.offer_type == 'specific_student':
            return False 

        return True