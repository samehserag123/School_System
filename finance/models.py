from django.conf import settings
from django.db import models
from django.db.models import Sum
from decimal import Decimal
from datetime import date
from django.utils import timezone
#from .models import Installment
#from .models import StudentInstallment
# =====================================================
# السنة الدراسية
# =====================================================

class AcademicYear(models.Model):
    name = models.CharField(max_length=20)  # مثال: 2025/2026
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return self.name


# =====================================================
# خطة التقسيط
# =====================================================

class InstallmentPlan(models.Model):
    name = models.CharField(max_length=100)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    number_of_installments = models.PositiveIntegerField()

    interest_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="قيمة فائدة ثابتة تضاف لكل قسط"
    )

    def __str__(self):
        return self.name


# =====================================================
# حساب الطالب
# =====================================================

class StudentAccount(models.Model):

    student = models.OneToOneField(
        "students.Student",
        on_delete=models.CASCADE,
        related_name="account"
    )

    installment_plan = models.ForeignKey(
        InstallmentPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    total_fees = models.DecimalField(
        "إجمالي المصروفات",
        max_digits=10,
        decimal_places=2,
        default=0
    )

    discount = models.DecimalField(
        "الخصم",
        max_digits=10,
        decimal_places=2,
        default=0
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "حساب طالب"
        verbose_name_plural = "حسابات الطلاب"

    def __str__(self):
        return f"حساب {self.student}"

    @property
    def net_fees(self):
        return self.total_fees - self.discount
    
    @property
    def total_paid(self):
        return sum(i.amount for i in self.installments.filter(is_paid=True))

    @property
    def total_remaining(self):
        return self.net_fees - self.total_paid


# =====================================================
# الأقساط الفعلية للطالب
# =====================================================

class StudentInstallment(models.Model):

    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Partial', 'Partial'),
        ('Paid', 'Paid'),
        ('Late', 'Late'),
    )

    student = models.ForeignKey(
        "students.Student",
        on_delete=models.CASCADE,
        related_name="installments"
    )

    installment_plan = models.ForeignKey(
        InstallmentPlan,
        on_delete=models.PROTECT
    )

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE
    )

    installment_number = models.PositiveIntegerField()
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()

    late_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='Pending'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_date']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'academic_year', 'installment_number'],
                name='unique_student_installment_per_year'
            )
        ]

    # =========================
    # الحسابات
    # =========================

    def total_paid(self):
        total = self.payments.aggregate(total=Sum('amount_paid'))['total']
        return total or Decimal("0.00")

    def remaining_amount(self):
        return (self.amount_due + self.late_fee) - self.total_paid()

    # =========================
    # تحديث الحالة
    # =========================

    def update_status(self):
        remaining = self.remaining_amount()

        if remaining <= 0:
            self.status = 'Paid'
        elif self.total_paid() > 0:
            self.status = 'Partial'
        elif self.due_date < date.today():
            self.status = 'Late'
        else:
            self.status = 'Pending'

        self.save(update_fields=['status'])

    def __str__(self):
        return f"{self.student} - قسط {self.installment_number}"


# =====================================================
# المدفوعات
# =====================================================

class RevenueCategory(models.Model):
    name = models.CharField(max_length=100)
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
        related_name="revenue_categories"
    )

    def __str__(self):
        return f"{self.name} - {self.academic_year.name}"


class Payment(models.Model):
    installment = models.ForeignKey(
        StudentInstallment,
        on_delete=models.CASCADE,
        related_name="payments"
    )

    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE
    )

    revenue_category = models.ForeignKey(
        RevenueCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.installment.update_status()

    def __str__(self):
        return f"{self.installment.student} - {self.amount_paid}"


# =====================================================
# إغلاق شهري
# =====================================================

class MonthlyClosure(models.Model):
    month = models.DateField()  # مثال: 2026-02-01
    total_collected = models.DecimalField(max_digits=10, decimal_places=2)
    total_remaining = models.DecimalField(max_digits=10, decimal_places=2)
    closed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Closure - {self.month.strftime('%B %Y')}"


# =====================================================
# كوبونات خصم
# =====================================================

class Coupon(models.Model):
    code = models.CharField(max_length=20, unique=True)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    expiry_date = models.DateField()
    active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )

    def __str__(self):
        return self.code