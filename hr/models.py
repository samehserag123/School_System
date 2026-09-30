from django.db import models, transaction  # 🟢 إضافة transaction
from django.core.exceptions import ValidationError # 🟢 إضافة ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import User
from datetime import datetime, date, time, timedelta  # تأكد من استيراد time
from decimal import Decimal
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db.models import Sum, Q, Prefetch, F, IntegerField, ExpressionWrapper
import calendar  # 🟢 إضافة استيراد المكتبة
# 1. الأقسام والإدارات الهيكلية


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم القسم")
    manager = models.ForeignKey('Employee', on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_departments')

    def __str__(self):
        return self.name


# 2. نظام لوائح الدوام المطور وفائق المرونة (قالب المناوبات المرنة والمحددة)
class AttendanceRule(models.Model):
    SHIFT_TYPES = [
        ('fixed', 'دوام ثابت بمواعيد صارمة'),
        ('flexible', 'دوام مرن (عدد ساعات مستهدفة يومياً)'),
        ('open', 'مفتوح (بدون قيود حضور وانصراف - للإدارة العليا)'),
    ]

    name = models.CharField(max_length=100, verbose_name="اسم قاعدة الدوام")
    shift_type = models.CharField(max_length=15, choices=SHIFT_TYPES, default='fixed', verbose_name="نوع الوردية/الدوام")

    # لمواعيد الدوام الثابت
    work_start_time = models.TimeField(null=True, blank=True, verbose_name="موعد الحضور الرسمي")
    work_end_time = models.TimeField(null=True, blank=True, verbose_name="موعد الانصراف الرسمي")

    # للدوام المرن
    target_work_hours = models.FloatField(default=8.0, verbose_name="عدد الساعات المستهدفة يومياً (للصنف المرن)")

    # سماحيات وتدرج اللوائح
    grace_period = models.PositiveIntegerField(default=15, verbose_name="فترة السماح بالدقائق (لا يحسب عليها تأخير)")
    max_late_allowed_minutes = models.PositiveIntegerField(default=120, verbose_name="أقصى مدة تأخير مسموح بها قبل اعتباره غياب نصف يوم")

    # مضاعفات ومعاملات الاحتساب المالي
    late_deduction_multiplier = models.FloatField(default=1.0, verbose_name="معامل خصم التأخير (ساعة التأخير بـ X ساعة)")
    overtime_multiplier_normal = models.FloatField(default=1.5, verbose_name="معامل الإضافي في الأيام العادية")
    overtime_multiplier_weekend = models.FloatField(default=2.0, verbose_name="معامل الإضافي في العطلات والإجازات")
    absent_deduction_days = models.FloatField(default=1.0, verbose_name="جزاء الغياب بدون إذن (اليوم بـ X يوم من الراتب)")

    # تحديد أيام العمل الأسبوعية ديناميكياً
    monday = models.BooleanField(default=True, verbose_name="الاثنين")
    tuesday = models.BooleanField(default=True, verbose_name="الثلاثاء")
    wednesday = models.BooleanField(default=True, verbose_name="الأربعاء")
    thursday = models.BooleanField(default=True, verbose_name="الخميس")
    friday = models.BooleanField(default=False, verbose_name="الجمعة")
    saturday = models.BooleanField(default=False, verbose_name="السبت")
    sunday = models.BooleanField(default=True, verbose_name="الأحد")

    class Meta:
        verbose_name = "لائحة حضور وانصراف"
        verbose_name_plural = "لوائح الحضور والانصراف"

    def __str__(self):
        return f"{self.name} ({self.get_shift_type_display()})"

    def is_working_day(self, date_obj):
        day_name = date_obj.strftime('%A').lower()
        return getattr(self, day_name, False)







def get_leave_year_start(reference_date=None):
    """
    يحدد تاريخ بداية سنة الإجازات الحالية (26/8) بناءً على تاريخ مرجعي.
    لو النهاردة قبل 26/8 من السنة الحالية -> السنة بدأت من 26/8 السنة اللي فاتت.
    """
    ref = reference_date or date.today()
    boundary = date(ref.year, 8, 26)
    if ref >= boundary:
        return boundary
    return date(ref.year - 1, 8, 26)


def full_months_between(start_date, end_date, anchor_day=26):
    """
    يحسب عدد 'الشهور الكاملة' بين تاريخين، حيث يوم الاستحقاق الثابت هو 26 من كل شهر.
    """
    if not start_date or end_date < start_date:
        return 0

    months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)

    # لو لسه معدّيناش يوم 26 من الشهر الحالي، منحسبوش الشهر ده كامل
    if end_date.day < anchor_day:
        months -= 1

    return max(0, months)


def calculate_monthly_leave_rate(hire_date, reference_date=None):
    """
    يحدد معدل الاستحقاق الشهري حسب سنوات الخبرة:
    أقل من 10 سنين -> 1.75 يوم/شهر (21 يوم/سنة)
    10 سنين فأكتر  -> 2.5 يوم/شهر (30 يوم/سنة)
    """
    ref = reference_date or date.today()
    if not hire_date:
        return 1.75

    tenure_years = (ref - hire_date).days / 365.25
    return 2.5 if tenure_years >= 10 else 1.75


def calculate_accrued_annual_leave(employee, reference_date=None):
    """
    الرصيد المتراكم فعلياً لحد أي تاريخ (افتراضياً: النهاردة)،
    بناءً على أقرب نقطة بين بداية سنة الإجازات وتاريخ تعيين الموظف.
    """
    ref = reference_date or date.today()
    year_start = get_leave_year_start(ref)

    if employee.hire_date and employee.hire_date > year_start:
        accrual_start = employee.hire_date
    else:
        accrual_start = year_start

    if accrual_start > ref:
        return 0.0

    months = full_months_between(accrual_start, ref)
    monthly_rate = calculate_monthly_leave_rate(employee.hire_date, ref)

    return round(months * monthly_rate, 2)



class Employee(models.Model):
    emp_id = models.CharField(max_length=50, unique=True, verbose_name="كود البصمة الرقمي")
    name = models.CharField(max_length=100, verbose_name="اسم الموظف بالكامل")

    # 🟢 إضافة القيمة الافتراضية 1/1/2026
    hire_date = models.DateField(
        "تاريخ التعيين / المباشرة",
        default=date(2026, 1, 1),
        null=True,
        blank=True
    )
    department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True, verbose_name="القسم التابع له")
    attendance_rule = models.ForeignKey('AttendanceRule', on_delete=models.PROTECT, verbose_name="لائحة العمل المطبقة")

    is_active = models.BooleanField(default=True, verbose_name="على رأس العمل حالياً")
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="الراتب الأساسي التعاقدي")

    is_insured = models.BooleanField(default=False, verbose_name="خاضع للتأمينات الاجتماعية؟")
    insurance_number = models.CharField(max_length=50, null=True, blank=True, verbose_name="الرقم التأميني")
    insurance_basic_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="الأجر الأساسي التأميني")
    insurance_variable_allowance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="البدلات التأمينية / الأجر المتغير")
    insurance_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="قيمة الاستقطاع التأميني (حصة الموظف)")
    initial_annual_balance = models.DecimalField(max_digits=5, decimal_places=2, default=0, blank=True, verbose_name="رصيد الإجازات المبدئي")
    annual_balance = models.FloatField(default=15.0, verbose_name="رصيد الاعتيادية")
    casual_balance = models.FloatField(default=6.0, verbose_name="رصيد الإجازات العارضة")
    sick_balance = models.FloatField(default=30.0, verbose_name="رصيد الإجازات المرضية المتاحة")

    hr_managers = models.ManyToManyField(
        User,
        blank=True,
        related_name='assigned_employees',
        verbose_name="مسؤولي الـ HR المخصصين لهذا الموظف"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.emp_id}] {self.name}"

    @property
    def remaining_annual_balance(self):
        """
        الرصيد المتبقي الفعلي = (المتراكم شهرياً تلقائياً + أي تعديل يدوي إضافي)
                                  - (أيام الإجازات السنوية المعتمدة/المعلّقة)

        ملحوظة: initial_annual_balance بقى حقل "تعديل يدوي اختياري" فقط
        (مثلاً لترحيل رصيد قديم من نظام سابق أو تصحيح استثنائي)،
        مش المصدر الأساسي للرصيد بعد دلوقتي.
        """
        from django.db.models import Sum

        accrued = calculate_accrued_annual_leave(self)
        manual_adjustment = float(self.initial_annual_balance or 0)

        used_days = self.leaverequest_set.filter(
            leave_type='annual',
            status__in=['approved', 'pending']
        ).aggregate(total=Sum('duration_days'))['total'] or 0

        return round(accrued + manual_adjustment - used_days, 2)

    @property
    def daily_wage(self):
        """قاعدة الـ 30 يوم الثابتة لحساب الأجر اليومي"""
        if self.base_salary:
            return Decimal(str(self.base_salary)) / Decimal('30.0')
        return Decimal('0.00')

    def get_active_days_in_month(self, target_year, target_month):
        """حساب أيام العمل الفعلية في شهر محدد (للموظف الجديد والقديم)"""
        _, last_day = calendar.monthrange(target_year, target_month)
        month_start = date(target_year, target_month, 1)
        month_end = date(target_year, target_month, last_day)

        if self.hire_date and self.hire_date > month_end:
            return 0

        if not self.hire_date or self.hire_date <= month_start:
            return 30

        actual_worked_days = (month_end - self.hire_date).days + 1
        return min(actual_worked_days, 30)

    def check_is_working_day(self, target_date):
        """
        دالة تفحص ما إذا كان اليوم يوم عمل.
        الأولوية لجدول الورديات (ShiftRoster). إذا لم يوجد، يتم الرجوع للائحة الافتراضية.
        """
        roster = self.rosters.filter(date=target_date).first()
        if roster:
            return roster.is_working

        if self.attendance_rule:
            return self.attendance_rule.is_working_day(target_date)
        return False

    @property
    def casual_taken_this_month(self):
        """إجمالي أيام العارضة المستهلكة في الشهر الحالي"""
        if hasattr(self, 'annotated_casual_taken'):
            return getattr(self, 'annotated_casual_taken') or 0.0

        now = timezone.now()
        leaves = self.leave_requests.filter(
            leave_type='casual',
            start_date__year=now.year,
            start_date__month=now.month,
            status='approved'
        )
        return sum(leave.duration_days for leave in leaves)

    @property
    def annual_taken_this_month(self):
        """إجمالي أيام السنوية المستهلكة في الشهر الحالي"""
        if hasattr(self, 'annotated_annual_taken'):
            return getattr(self, 'annotated_annual_taken') or 0.0

        now = timezone.now()
        leaves = self.leave_requests.filter(
            leave_type='annual',
            start_date__year=now.year,
            start_date__month=now.month,
            status='approved'
        )
        return sum(leave.duration_days for leave in leaves)


# 4. سجل البصمة الخام
class FingerprintLog(models.Model):
    emp_id = models.CharField(max_length=50, verbose_name="رقم البصمة")
    timestamp = models.DateTimeField(verbose_name="وقت البصمة")
    device_id = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        verbose_name = "سجل البصمة الخام"
        unique_together = ('emp_id', 'timestamp')

# 4. سجل الحضور المعالج والمدقق مالياً بدقة فائقة
class DailyAttendance(models.Model):
    STATUS_CHOICES = [
        ('present', 'حاضر (دوام كامل)'),
        ('half_day_absent', 'غياب نصف يوم'),
        ('absent', 'غائب بدون إذن'),
        ('leave', 'إجازة معتمدة'),
        ('mission', 'مأمورية رسمية'), # 👈 حالة المأمورية الجديدة
        ('holiday', 'عطلة رسمية / استثنائية'),  # 🟢 هذا هو السطر الجديد
    ]
    # administrative_penalty_days = models.FloatField(default=0.0, verbose_name="أيام الجزاء الإداري الصارم")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='daily_attendance_records')
    administrative_penalty_days = models.FloatField(default=0.0, verbose_name="أيام الجزاء الإداري الصارم")
    is_manual_override = models.BooleanField(default=False, verbose_name="تعديل يدوي (جزاء تحايل / انصراف يدوي)")
    # is_manual_override = models.BooleanField(default=False, verbose_name="تعديل يدوي (جزاء تحايل / انصراف يدوي)")
    date = models.DateField(verbose_name="تاريخ اليوم")
    check_in = models.TimeField(null=True, blank=True, verbose_name="وقت الدخول الفعلي")
    check_out = models.TimeField(null=True, blank=True, verbose_name="وقت الخروج الفعلي")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='absent')

    # تفاصيل الأداء والمدد الزمنية
    actual_work_hours = models.FloatField(default=0.0, verbose_name="ساعات العمل الفعلية المقضاة")
    late_minutes = models.IntegerField(default=0, verbose_name="دقائق التأخير")
    overtime_hours = models.FloatField(default=0.0, verbose_name="ساعات الإضافي المستحقة")

    # التسويات المالية المباشرة
    deduction_hours = models.FloatField(default=0.0, verbose_name="ساعات الخصم من الراتب (بسبب التأخير)")
    absence_deduction_days = models.FloatField(default=0.0, verbose_name="أيام الخصم المباشر (بسبب الغياب)")

    # تدقيق السجلات والأمن الإداري
    is_processed = models.BooleanField(default=False, verbose_name="تم ترحيله للحسابات الختامية للراتب")
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الموظف المسؤول عن الاعتماد المالي")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('employee', 'date')
        verbose_name = "سجل حضور يومي معالج"
        verbose_name_plural = "سجلات الحضور اليومية المعالجة"

    def __str__(self):
        return f"{self.employee.name} | {self.date} | {self.get_status_display()}"


# في ملف models.py داخل كلاس MissionRequest

from datetime import timedelta
from django.db import models, transaction
from django.core.exceptions import ValidationError


class MissionRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'قيد الانتظار'),
        ('approved', 'معتمد'),
        ('rejected', 'مرفوض'),
    ]

    employee = models.ForeignKey(
        'Employee',
        on_delete=models.CASCADE,
        related_name='missions',
        verbose_name="الموظف"
    )
    start_date = models.DateField(verbose_name="تاريخ بداية المأمورية")
    end_date = models.DateField(verbose_name="تاريخ نهاية المأمورية")
    reason = models.TextField(verbose_name="وجهة وتفاصيل المأمورية")
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="الحالة"
    )

    class Meta:
        verbose_name = "طلب مأمورية"
        verbose_name_plural = "طلبات المأموريات"
        ordering = ['-start_date']

    def __str__(self):
        return f"مأمورية {self.employee} ({self.start_date} إلى {self.end_date})"

    def clean(self):
        """التحقق من صحة التواريخ قبل الحفظ"""
        super().clean()
        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                raise ValidationError({'end_date': "تاريخ نهاية المأمورية لا يمكن أن يكون قبل تاريخ البداية."})

    @transaction.atomic
    def save(self, *args, **kwargs):
        # 1. تتبع حالة المأمورية والتواريخ القديمة في حال التعديل
        old_instance = None
        if self.pk:
            old_instance = MissionRequest.objects.filter(pk=self.pk).first()

        # تشغيل التحقق من البيانات (Validation)
        self.full_clean()

        # حفظ الكائن أولاً
        super().save(*args, **kwargs)

        # استيراد محلي للنموذج لتجنب Circular Import
        from .models import DailyAttendance

        # 2. معالجة إلغاء الاعتماد أو تغيير التواريخ لمأمورية كانت معتمدة سابقاً
        if old_instance and old_instance.status == 'approved':
            # إذا تغيرت الحالة من 'معتمد' إلى حالة أخرى، أو تغير نطاق التواريخ
            if self.status != 'approved' or old_instance.start_date != self.start_date or old_instance.end_date != self.end_date:
                self._revert_attendance_records(
                    employee=old_instance.employee,
                    start_date=old_instance.start_date,
                    end_date=old_instance.end_date
                )

        # 3. في حال كان القرار الحالي هو الاعتماد (Approved)
        if self.status == 'approved':
            current_date = self.start_date
            while current_date <= self.end_date:
                DailyAttendance.objects.update_or_create(
                    employee=self.employee,
                    date=current_date,
                    defaults={
                        'status': 'mission',
                        'late_minutes': 0,
                        'deduction_hours': 0.0,
                        'administrative_penalty_days': 0.0,
                        'absence_deduction_days': 0.0,
                    }
                )
                current_date += timedelta(days=1)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        employee = self.employee
        start_date = self.start_date
        end_date = self.end_date

        # تنفيذ الحذف الفعلي
        super().delete(*args, **kwargs)

        # إعادة ضبط سجلات الحضور إذا كانت المأمورية المحذوفة معتمدة
        if self.status == 'approved':
            self._revert_attendance_records(employee, start_date, end_date)

    @staticmethod
    def _revert_attendance_records(employee, start_date, end_date):
        """دالة مساعدة لإعادة ضبط سجلات الحضور عند تغيير/حذف/رفض مأمورية معتمدة"""
        from .models import DailyAttendance

        attendance_records = DailyAttendance.objects.filter(
            employee=employee,
            date__range=[start_date, end_date],
            status='mission'
        )

        for record in attendance_records:
            # إذا ثبت وجود بصمة حضور أو انصراف فعلية في هذا اليوم
            if record.check_in or record.check_out:
                record.status = 'present'
            else:
                record.status = 'absent'

            record.save()


from datetime import time
from django.db import models, transaction
from django.core.exceptions import ValidationError

class PermissionRequest(models.Model):
    STATUS = [
        ('pending', 'قيد الانتظار'),
        ('approved', 'معتمد'),
        ('rejected', 'مرفوض'),
    ]

    employee = models.ForeignKey('Employee', on_delete=models.CASCADE, related_name='permissions')
    date = models.DateField(verbose_name="تاريخ الإذن")
    departure_time = models.TimeField(null=True, blank=True, verbose_name="وقت الخروج (يجب أن يكون بعد 2 ظهراً)")
    reason = models.TextField(verbose_name="سبب الاستئذان")
    status = models.CharField(max_length=10, choices=STATUS, default='pending', verbose_name="الحالة")

    class Meta:
        verbose_name = "طلب إذن"
        verbose_name_plural = "طلبات الأذونات"

    def clean(self):
        super().clean()

        # 1. التأكد من عدم تجاوز حد الإذن الشهري (مرة واحدة شهرياً)
        if self.employee and self.date and self.status in ['pending', 'approved']:
            count = PermissionRequest.objects.filter(
                employee=self.employee,
                date__year=self.date.year,
                date__month=self.date.month,
                status__in=['pending', 'approved']
            ).exclude(pk=self.pk).count()

            if count >= 1:
                raise ValidationError("عذراً، استنفد الموظف رصيد الأذونات المسموح به (مرة واحدة شهرياً).")

        # 2. التحقق من وقت المغادرة (بعد 2:00 ظهراً)
        if self.departure_time and self.departure_time < time(14, 0):
            raise ValidationError({
                'departure_time': "مرفوض إدارياً: قانون العمل الداخلي يمنع إصدار أي إذن خروج للموظف قبل الساعة 2:00 ظهراً."
            })

    @transaction.atomic
    def save(self, *args, **kwargs):
        old_instance = None
        if self.pk:
            old_instance = PermissionRequest.objects.filter(pk=self.pk).first()

        self.full_clean()
        super().save(*args, **kwargs)

        # الوصول لموديل الحضور (افترضنا وجوده في نفس الملف أو تم استيراده في أعلى الملف)
        # إذا كان في تطبيق آخر استخدم: from django.apps import apps; DailyAttendance = apps.get_model('app_label', 'DailyAttendance')

        # عند اعتماد الإذن: تصفير التأخيرات والجزاءات
        if self.status == 'approved':
            attendance, _ = DailyAttendance.objects.get_or_create(
                employee=self.employee,
                date=self.date,
                defaults={'status': 'present'}
            )
            attendance.late_minutes = 0
            attendance.deduction_hours = 0.0
            attendance.administrative_penalty_days = 0.0
            if attendance.status == 'absent' and (attendance.check_in or attendance.check_out):
                attendance.status = 'present'
            attendance.save()

        # إلغاء الاعتماد أو الرفض بعد القبول
        elif old_instance and old_instance.status == 'approved' and self.status != 'approved':
            try:
                attendance = DailyAttendance.objects.get(employee=self.employee, date=self.date)
                if not attendance.check_in and not attendance.check_out:
                    attendance.status = 'absent'
                attendance.save()  # تنبيه: يجب أن تحتوي دالة save في DailyAttendance على إعادة حساب الجزاءات
            except DailyAttendance.DoesNotExist:
                pass

    @transaction.atomic
    def delete(self, *args, **kwargs):
        emp = self.employee
        p_date = self.date
        was_approved = (self.status == 'approved')

        super().delete(*args, **kwargs)

        if was_approved:
            try:
                attendance = DailyAttendance.objects.get(employee=emp, date=p_date)
                if not attendance.check_in and not attendance.check_out:
                    attendance.status = 'absent'
                attendance.save()
            except DailyAttendance.DoesNotExist:
                pass


class LeaveRequest(models.Model):
    TYPES = [
        ('annual', 'سنوية'),
        ('casual', 'عارضة'),
        ('sick', 'مرضية'),
        ('exceptional', 'استثنائية (مدفوعة الأجر)')
    ]
    STATUS = [
        ('pending', 'قيد الانتظار والمراجعة'),
        ('approved', 'موافق عليها ومخصومة'),
        ('rejected', 'مرفوضة قطعيّاً')
    ]

    employee = models.ForeignKey('Employee', on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.CharField(max_length=20, choices=TYPES, verbose_name="نوع الإجازة المطلوبة")
    start_date = models.DateField(verbose_name="تاريخ بداية الإجازة")
    end_date = models.DateField(verbose_name="تاريخ نهاية الإجازة")
    reason = models.TextField(null=True, blank=True, verbose_name="السبب المذكور للطلب")
    status = models.CharField(max_length=10, choices=STATUS, default='pending', verbose_name="حالة الطلب الإداري")

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def duration_days(self):
        """حساب عدد أيام الإجازة الشاملة للطلب الحالي."""
        if not (self.start_date and self.end_date) or self.start_date > self.end_date:
            return 0
        return (self.end_date - self.start_date).days + 1

    def clean(self):
        # 1. 🟢 درع الحماية والتحقق من صحة المدخلات الأساسية
        if not hasattr(self, 'employee') or self.employee_id is None:
            raise ValidationError("يرجى اختيار الموظف أولاً.")

        if not self.start_date or not self.end_date:
            raise ValidationError("يرجى تحديد تاريخ بداية ونهاية الإجازة بشكل صحيح.")

        if self.start_date > self.end_date:
            raise ValidationError("تاريخ نهاية الإجازة لا يمكن أن يكون قبل تاريخ البداية.")

        # 2. 🟢 فحص التداخل الأيامي (استعلام سريع بشرط .exists())
        overlapping_qs = LeaveRequest.objects.filter(
            employee_id=self.employee_id,
            status__in=['pending', 'approved'],
            start_date__lte=self.end_date,
            end_date__gte=self.start_date
        )
        if self.pk:
            overlapping_qs = overlapping_qs.exclude(pk=self.pk)

        if overlapping_qs.exists():
            raise ValidationError("يوجد طلب إجازة آخر متداخل مع هذه الفترة لهذا الموظف.")

        # 3. 🟢 منع الإجازات المتتالية (جلب تواريخ فقط دون كائنات كاملة)
        prev_day = self.start_date - timedelta(days=1)
        next_day = self.end_date + timedelta(days=1)

        adjacent_qs = LeaveRequest.objects.filter(
            employee_id=self.employee_id,
            status__in=['pending', 'approved']
        ).filter(Q(end_date=prev_day) | Q(start_date=next_day))

        if self.pk:
            adjacent_qs = adjacent_qs.exclude(pk=self.pk)

        for adj_start, adj_end in adjacent_qs.values_list('start_date', 'end_date'):
            if adj_end == prev_day:
                raise ValidationError("لا يجوز تقديم إجازتين متتاليتين؛ يجب وجود يوم عمل واحد على الأقل كفصل بين الإجازات.")
            if adj_start == next_day:
                raise ValidationError("لا يجوز تقديم إجازة متصلة بإجازة مسجلة تليها مباشرة؛ يجب وجود يوم عمل واحد على الأقل كفصل بين الإجازات.")

        # 4. 🟢 منع التحايل عبر العطلة الأسبوعية
        last_end_qs = LeaveRequest.objects.filter(
            employee_id=self.employee_id,
            status__in=['pending', 'approved'],
            end_date__lt=self.start_date
        )
        if self.pk:
            last_end_qs = last_end_qs.exclude(pk=self.pk)

        last_end_date = last_end_qs.order_by('-end_date').values_list('end_date', flat=True).first()

        if last_end_date and last_end_date.weekday() == 3:  # 3 = الخميس
            gap_days = (self.start_date - last_end_date).days
            if self.start_date.weekday() in [5, 6] and gap_days <= 3:
                raise ValidationError(
                    f"تنبيه منع التحايل: يوجد إجازة سابقة تنتهي الخميس ({last_end_date.strftime('%Y-%m-%d')}). "
                    "لا يجوز تقديم إجازة جديدة السبت أو الأحد منفصلة لتفادي خصم العطلة الأسبوعية؛ يجب دمج الطلبين."
                )

        next_start_qs = LeaveRequest.objects.filter(
            employee_id=self.employee_id,
            status__in=['pending', 'approved'],
            start_date__gt=self.end_date
        )
        if self.pk:
            next_start_qs = next_start_qs.exclude(pk=self.pk)

        next_start_date = next_start_qs.order_by('start_date').values_list('start_date', flat=True).first()

        if next_start_date and self.end_date.weekday() == 3:
            gap_days = (next_start_date - self.end_date).days
            if next_start_date.weekday() in [5, 6] and gap_days <= 3:
                raise ValidationError(
                    f"تنبيه منع التحايل: لا يجوز تسجيل إجازة تنتهي الخميس مع وجود إجازة مسجلة تبدأ يوم ({next_start_date.strftime('%Y-%m-%d')}). "
                    "يجب دمج الطلبين في طلب واحد يشمل يومي الجمعة والسبت."
                )

        # 5. 🟢 فحص الأرصدة والسقف الأقصى (حساب فائق السرعة عبر values_list)
        if self.status in ['pending', 'approved']:
            days = self.duration_days
            current_year = self.start_date.year

            if self.leave_type == 'casual':
                casual_qs = LeaveRequest.objects.filter(
                    employee_id=self.employee_id,
                    leave_type='casual',
                    status__in=['pending', 'approved'],
                    start_date__year=current_year
                )
                if self.pk:
                    casual_qs = casual_qs.exclude(pk=self.pk)

                # جلب التواريخ فقط من قاعدة البيانات وحساب مجموع الأيام في Python مباشرة
                used_casual = sum((end - start).days + 1 for start, end in casual_qs.values_list('start_date', 'end_date'))

                if (used_casual + days) > 6:
                    raise ValidationError(
                        f"عفواً، تم تجاوز الحد الأقصى المسموح به للإجازات العارضة (6 أيام سنوياً). "
                        f"الأيام المستخدمة سابقاً: {used_casual} يوم، والطلب الحالي: {days} يوم."
                    )
                if days > self.employee.casual_balance:
                    raise ValidationError(f"رصيد العارضة الحالي ({self.employee.casual_balance} يوم) لا يكفي.")

            elif self.leave_type == 'annual':
                annual_qs = LeaveRequest.objects.filter(
                    employee_id=self.employee_id,
                    leave_type='annual',
                    status__in=['pending', 'approved'],
                    start_date__year=current_year
                )
                if self.pk:
                    annual_qs = annual_qs.exclude(pk=self.pk)

                used_annual = sum((end - start).days + 1 for start, end in annual_qs.values_list('start_date', 'end_date'))

                if (used_annual + days) > 15:
                    raise ValidationError(
                        f"عفواً، تم تجاوز الحد الأقصى المسموح به للإجازات الاعتيادية (15 يوم سنوياً). "
                        f"الأيام المستخدمة سابقاً: {used_annual} يوم، والطلب الحالي: {days} يوم."
                    )
                if days > self.employee.annual_balance:
                    raise ValidationError(
                        f"الرصيد السنوي الحالي ({self.employee.annual_balance} يوم) لا يكفي لخصم الفترة الإجمالية ({days} يوم)."
                    )

    def save(self, *args, **kwargs):
        with transaction.atomic():
            days = self.duration_days
            is_new_record = self.pk is None

            if not is_new_record:
                old_record = LeaveRequest.objects.select_for_update().get(pk=self.pk)

                # 1. التحول من أي حالة إلى approved (خصم الأيام كاملة)
                if old_record.status != 'approved' and self.status == 'approved':
                    self._update_employee_balance(days, operation='deduct')

                # 2. التحول من approved إلى أي حالة أخرى (استرداد الأيام كاملة)
                elif old_record.status == 'approved' and self.status != 'approved':
                    self._update_employee_balance(old_record.duration_days, operation='refund')

                # 3. 🟢 التعديل على إجازة معتمدة بالفعل (تعديل الأيام بالزيادة أو النقصان)
                elif old_record.status == 'approved' and self.status == 'approved':
                    diff_days = days - old_record.duration_days
                    if diff_days > 0:
                        # زيادة الأيام -> خصم الفارق
                        self._update_employee_balance(diff_days, operation='deduct')
                    elif diff_days < 0:
                        # تقليل الأيام -> استرداد الفارق
                        self._update_employee_balance(abs(diff_days), operation='refund')
            else:
                # إنشاء طلب جديد بحالة approved مباشرة
                if self.status == 'approved':
                    self._update_employee_balance(days, operation='deduct')

            super().save(*args, **kwargs)

    def _update_employee_balance(self, days, operation='deduct'):
        multiplier = -1 if operation == 'deduct' else 1
        days_to_apply = days * multiplier

        # تحديث ذرّي (Atomic Update) في قاعدة البيانات
        if self.leave_type == 'annual':
            Employee.objects.filter(pk=self.employee_id).update(
                annual_balance=F('annual_balance') + days_to_apply
            )
        elif self.leave_type == 'casual':
            Employee.objects.filter(pk=self.employee_id).update(
                casual_balance=F('casual_balance') + days_to_apply
            )
        elif self.leave_type == 'sick':
            Employee.objects.filter(pk=self.employee_id).update(
                sick_balance=F('sick_balance') + days_to_apply
            )

        # تحديث كائن الموظف المقترن في الذاكرة لتفادي حفظ بيانات قديمة لاحقاً
        if hasattr(self, 'employee') and self.employee:
            self.employee.refresh_from_db()



# class LeaveRequest(models.Model):
#     TYPES = [
#         ('annual', 'سنوية'),
#         ('casual', 'عارضة'),
#         ('sick', 'مرضية'),
#         ('exceptional', 'استثنائية (مدفوعة الأجر)')
#     ]
#     STATUS = [
#         ('pending', 'قيد الانتظار والمراجعة'),
#         ('approved', 'موافق عليها ومخصومة'),
#         ('rejected', 'مرفوضة قطعيّاً')
#     ]

#     employee = models.ForeignKey('Employee', on_delete=models.CASCADE, related_name='leave_requests')
#     leave_type = models.CharField(max_length=20, choices=TYPES, verbose_name="نوع الإجازة المطلوبة")  # 🟢 تم التعديل إلى 20
#     start_date = models.DateField(verbose_name="تاريخ بداية الإجازة")
#     end_date = models.DateField(verbose_name="تاريخ نهاية الإجازة")
#     reason = models.TextField(null=True, blank=True, verbose_name="السبب المذكور للطلب")
#     status = models.CharField(max_length=10, choices=STATUS, default='pending', verbose_name="حالة الطلب الإدارية")

#     created_at = models.DateTimeField(auto_now_add=True)

#     @property
#     def duration_days(self):
#         """
#         حساب عدد أيام الإجازة:
#         إذا كانت الإجازة تتخللها/تتصل عبر عطلة أسبوعية (جمعة وسبت)،
#         يتم احتساب الجمعة والسبت ضمن أيام الإجازة المخصومة من الرصيد الاعتيادي.
#         """
#         if self.end_date and self.start_date:
#             total_days = (self.end_date - self.start_date).days + 1

#             # 🟢 إذا كانت الإجازة اعتيادية وتمتد عبر الويك إند (تغطي الخميس والأحد)
#             # مثال: من الخميس إلى الأحد = 4 أيام (الخميس، الجمعة، السبت، الأحد)
#             return total_days
#         return 0

#     def clean(self):
#         from datetime import timedelta, date
#         from django.utils import timezone
#         from django.core.exceptions import ValidationError
#         from django.db.models import Q

#         # 1. 🟢 درع الحماية: التأكد من وجود البيانات الأساسية قبل استعلام قاعدة البيانات
#         if not hasattr(self, 'employee') or self.employee_id is None:
#             return
#         if not self.start_date or not self.end_date:
#             return

#         # 2. 🟢 فحص التواريخ المعكوسة (حماية من الأيام بالسالب)
#         if self.start_date > self.end_date:
#             raise ValidationError("تاريخ نهاية الإجازة لا يمكن أن يكون قبل تاريخ البداية.")

#         # ==========================================
#         # 🌟 القوانين الإدارية (معطلة مؤقتاً لتسجيل المتأخرات)
#         # ==========================================
#         # today = timezone.localdate()

#         # # قانون الاعتيادي: التقديم قبلها بـ 3 أيام على الأقل
#         # if self.leave_type == 'annual':
#         #     if self.start_date < today + timedelta(days=3):
#         #         raise ValidationError("قانون إداري: لا يجوز عمل إجازة اعتيادية إلا قبل موعدها بـ 3 أيام على الأقل.")

#         # # قانون العارضة: لا تتجاوز 3 أيام بأثر رجعي، ولا يجوز طلبها للمستقبل
#         # if self.leave_type == 'casual':
#         #     if self.start_date > today:
#         #         raise ValidationError("قانون إداري: الإجازة العارضة للظروف الطارئة فقط ولا يجوز طلبها لتواريخ مستقبلية.")
#         #     if self.start_date < today - timedelta(days=3):
#         #         raise ValidationError("قانون إداري: لقد انتهت مهلة السماح (3 أيام) لتسجيل هذه الإجازة العارضة.")

#         # 3. فحص التداخل
#         overlapping_requests = LeaveRequest.objects.filter(
#             employee=self.employee,
#             status__in=['pending', 'approved']
#         ).filter(
#             Q(start_date__lte=self.end_date) & Q(end_date__gte=self.start_date)
#         )

#         if self.pk:
#             overlapping_requests = overlapping_requests.exclude(pk=self.pk)

#         if overlapping_requests.exists():
#             raise ValidationError("يوجد طلب إجازة آخر متداخل مع هذه الفترة لهذا الموظف.")

#         # 3.5 🟢 قانون العارضة: حد أقصى يوم واحد إجازة عارضة خلال دورة الرواتب (من 26 إلى 25)
#         if self.leave_type == 'casual':
#             if self.start_date.day >= 26:
#                 cycle_start = date(self.start_date.year, self.start_date.month, 26)
#                 if self.start_date.month == 12:
#                     cycle_end = date(self.start_date.year + 1, 1, 25)
#                 else:
#                     cycle_end = date(self.start_date.year, self.start_date.month + 1, 25)
#             else:
#                 cycle_end = date(self.start_date.year, self.start_date.month, 25)
#                 if self.start_date.month == 1:
#                     cycle_start = date(self.start_date.year - 1, 12, 26)
#                 else:
#                     cycle_start = date(self.start_date.year, self.start_date.month - 1, 26)

#             other_casual_in_cycle = LeaveRequest.objects.filter(
#                 employee=self.employee,
#                 leave_type='casual',
#                 status__in=['pending', 'approved'],
#                 start_date__gte=cycle_start,
#                 start_date__lte=cycle_end,
#             )
#             if self.pk:
#                 other_casual_in_cycle = other_casual_in_cycle.exclude(pk=self.pk)

#             total_casual_days_in_cycle = sum(l.duration_days for l in other_casual_in_cycle) + self.duration_days
#             if total_casual_days_in_cycle > 1:
#                 raise ValidationError(
#                     f"لا يُسمح بأخذ إجازة عارضة أكثر من يوم واحد خلال الفترة من "
#                     f"{cycle_start.strftime('%Y-%m-%d')} إلى {cycle_end.strftime('%Y-%m-%d')}."
#                 )

#         # ==========================================
#         # 🟢 1. تعديل قانون منع التحايل بالتجزئة (الجمعة والسبت)
#         # ==========================================
#         # حظر تقديم إجازتين منفصلتين (واحدة تنتهي الخميس وأخرى تبدأ الأحد)
#         # ==========================================
#         # 🟢 منع التحايل عبر العطلة الأسبوعية (الجمعة والسبت)
#         # ==========================================

#         # 1️⃣ الفحص للأمام: هل يوجد إجازة سابقة انتهت الخميس والطلب الحالي يبدأ السبت أو الأحد؟
#         last_leave = LeaveRequest.objects.filter(
#             employee=self.employee,
#             status__in=['pending', 'approved'],
#             end_date__lt=self.start_date,
#         )
#         if self.pk:
#             last_leave = last_leave.exclude(pk=self.pk)
#         last_leave = last_leave.order_by('-end_date').first()

#         if last_leave and last_leave.end_date.weekday() == 3:  # الخميس
#             gap_days = (self.start_date - last_leave.end_date).days
#             # السبت (فجوة يومين) أو الأحد (فجوة 3 أيام)
#             if self.start_date.weekday() in [5, 6] and gap_days <= 3:
#                 raise ValidationError(
#                     f"تحذير منع التحايل: يوجد إجازة سابقة تنتهي الخميس ({last_leave.end_date.strftime('%Y-%m-%d')}). "
#                     "لا يجوز تقديم إجازة جديدة السبت أو الأحد منفصلة لتفادي خصم العطلة الأسبوعية."
#                 )

#         # 2️⃣ الفحص للخلف: إذا كان الطلب الحالي ينتهي يوم الخميس، وهناك إجازة مسجلة تبدأ السبت أو الأحد
#         next_leave = LeaveRequest.objects.filter(
#             employee=self.employee,
#             status__in=['pending', 'approved'],
#             start_date__gt=self.end_date,
#         )
#         if self.pk:
#             next_leave = next_leave.exclude(pk=self.pk)
#         next_leave = next_leave.order_by('start_date').first()

#         if next_leave and self.end_date.weekday() == 3:  # طلب الحالي ينتهي الخميس
#             gap_days = (next_leave.start_date - self.end_date).days
#             if next_leave.start_date.weekday() in [5, 6] and gap_days <= 3:
#                 raise ValidationError(
#                     f"تحذير منع التحايل: لا يجوز تسجيل إجازة تنتهي الخميس وجود إجازة أخرى تبدأ يوم ({next_leave.start_date.strftime('%Y-%m-%d')}). "
#                     "يجب دمجهما في طلب واحد شامل للجمعة والسبت."
#                 )

#         # 2. فحص التداخل
#         overlapping_requests = LeaveRequest.objects.filter(
#             employee=self.employee,
#             status__in=['pending', 'approved']
#         ).filter(
#             Q(start_date__lte=self.end_date) & Q(end_date__gte=self.start_date)
#         )

#         if self.pk:
#             overlapping_requests = overlapping_requests.exclude(pk=self.pk)

#         if overlapping_requests.exists():
#             raise ValidationError("يوجد طلب إجازة آخر متداخل مع هذه الفترة لهذا الموظف.")

#         # 3. فحص الأرصدة المتاحة للطلبات الجديدة
#         if self.status == 'pending':
#             days = self.duration_days
#             if self.leave_type == 'annual' and days > self.employee.annual_balance:
#                 raise ValidationError(f"الرصيد السنوي الحالي ({self.employee.annual_balance} يوم) لا يكفي لخصم الفترة الإجمالية شاملة العطلات ({days} يوم).")
#             if self.leave_type == 'casual' and days > self.employee.casual_balance:
#                 raise ValidationError(f"رصيد العارضة الحالي ({self.employee.casual_balance}) لا يكفي.")

#     def save(self, *args, **kwargs):
#         with transaction.atomic():
#             days = self.duration_days
#             is_new_record = self.pk is None

#             if not is_new_record:
#                 old_record = LeaveRequest.objects.select_for_update().get(pk=self.pk)

#                 # 🟢 الحالة الأولى: الموافقة على طلب كان قيد الانتظار (خصم الرصيد)
#                 if old_record.status != 'approved' and self.status == 'approved':
#                     self._update_employee_balance(days, operation='deduct')

#                 # 🟢 الحالة الثانية: التراجع عن إجازة تمت الموافقة عليها (استرداد الرصيد)
#                 elif old_record.status == 'approved' and self.status != 'approved':
#                     self._update_employee_balance(old_record.duration_days, operation='refund')

#             else:
#                 # 🟢 الحالة الثالثة: إنشاء طلب جديد بحالة "موافق عليها" مباشرة (خصم فوري)
#                 if self.status == 'approved':
#                     self._update_employee_balance(days, operation='deduct')

#             super().save(*args, **kwargs)

#     def _update_employee_balance(self, days, operation='deduct'):
#         """دالة مساعدة لإدارة الأرصدة (خصم أو استرداد) لتجنب تكرار الكود"""
#         multiplier = -1 if operation == 'deduct' else 1
#         days_to_apply = days * multiplier

#         if self.leave_type == 'annual':
#             self.employee.annual_balance = F('annual_balance') + days_to_apply
#         elif self.leave_type == 'casual':
#             self.employee.casual_balance = F('casual_balance') + days_to_apply
#         elif self.leave_type == 'sick':
#             self.employee.sick_balance = F('sick_balance') + days_to_apply

#         self.employee.save(update_fields=['annual_balance', 'casual_balance', 'sick_balance'])
#         self.employee.refresh_from_db()



class ShiftRoster(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='rosters')
    date = models.DateField(verbose_name="التاريخ")
    is_working = models.BooleanField(default=True, verbose_name="يوم عمل؟")

    shift_start = models.TimeField(null=True, blank=True, verbose_name="بداية الوردية الاستثنائية")
    shift_end = models.TimeField(null=True, blank=True, verbose_name="نهاية الوردية الاستثنائية")

    class Meta:
        unique_together = ('employee', 'date')
        verbose_name = "جدول وردية"
        verbose_name_plural = "جداول الورديات"

    def __str__(self):
        return f"{self.employee.name} - {self.date} - {'عمل' if self.is_working else 'إجازة'}"


class FinancialAdjustment(models.Model):
    ADJUSTMENT_TYPES = (
        ('addition', 'إضافة مالية (مكافأة / استثناء / حافز)'),
        ('deduction', 'استقطاع مالي (سلفة / عهدة / غرامة)'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='adjustments', verbose_name="الموظف")
    date = models.DateField(default=timezone.now, verbose_name="تاريخ التسوية")
    adjustment_type = models.CharField(max_length=20, choices=ADJUSTMENT_TYPES, verbose_name="نوع الحركة")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ (ج.م)")
    reason = models.TextField(verbose_name="سبب الاعتماد (التوجيهات)")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employee.name} - {self.get_adjustment_type_display()} - {self.amount} ج.م"


class PublicHoliday(models.Model):
    name = models.CharField(max_length=150, verbose_name="اسم العطلة (مثل: عيد الفطر، إجازة استثنائية)")
    start_date = models.DateField(verbose_name="تاريخ بداية العطلة")
    end_date = models.DateField(verbose_name="تاريخ نهاية العطلة")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات إضافية")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.start_date} إلى {self.end_date})"

    # دالة ذكية لحساب عدد أيام الإجازة
    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1


class PenaltyRecord(models.Model):
    """
    🟢 موديل توقيع الجزاء الإداري
    يسمح للمدير بتوقيع جزاء على موظف مع تحديد نوع الجزاء وسببه، وترك عدد أيام
    الخصم لتقدير المدير حسب خطورة المخالفة (بدل رقم ثابت مبرمج مسبقاً).
    """
    PENALTY_TYPES = (
        ('lateness', 'تكرار التأخير عن الحضور'),
        ('unauthorized_exit', 'الخروج بدون إذن (تحايل)'),
        ('negligence', 'إهمال في العمل'),
        ('misconduct', 'مخالفة سلوكية / أدبية'),
        ('violation', 'مخالفة للوائح الداخلية'),
        ('other', 'أخرى (يُذكر السبب بالتفصيل)'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='penalties', verbose_name="الموظف")
    # date = models.DateField(default=timezone.now, verbose_name="تاريخ توقيع الجزاء")
    date = models.DateField(default=timezone.localdate, verbose_name="تاريخ توقيع الجزاء")
    penalty_type = models.CharField(max_length=30, choices=PENALTY_TYPES, verbose_name="نوع الجزاء")
    deduction_days = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0)],
        verbose_name="عدد أيام الخصم (يحددها المدير حسب خطورة المخالفة)"
    )
    reason = models.TextField(verbose_name="سبب الجزاء وتفاصيله")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المدير الموقّع للجزاء")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name = "جزاء إداري"
        verbose_name_plural = "الجزاءات الإدارية"

    def __str__(self):
        return f"{self.employee.name} - {self.get_penalty_type_display()} - خصم {self.deduction_days} يوم"
