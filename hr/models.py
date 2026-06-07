from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import User
from datetime import datetime, timedelta
from django.utils import timezone

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

# 3. ملف الموظف الاحترافي الشامل
class Employee(models.Model):
    emp_id = models.CharField(max_length=50, unique=True, verbose_name="كود البصمة الرقمي")
    name = models.CharField(max_length=100, verbose_name="اسم الموظف بالكامل")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, verbose_name="القسم التابع له")
    attendance_rule = models.ForeignKey(AttendanceRule, on_delete=models.PROTECT, verbose_name="لائحة العمل المطبقة")
    
    is_active = models.BooleanField(default=True, verbose_name="على رأس العمل حالياً")
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="الراتب الأساسي التعاقدي")
    
    # رصيد الإجازات الفعلي التراكمي
    annual_balance = models.FloatField(default=21.0, verbose_name="رصيد الإجازات السنوية")
    casual_balance = models.FloatField(default=7.0, verbose_name="رصيد الإجازات العارضة")
    sick_balance = models.FloatField(default=30.0, verbose_name="رصيد الإجازات المرضية المتاحة")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.emp_id}] {self.name}"

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
        ('holiday', 'عطلة نهاية أسبوع / رسمية'),
    ]
    
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='daily_attendance_records')
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
    
# 5. محرك طلبات الإجازات الاحترافي مع صد حركات كسر الأرصدة بالسالب
class LeaveRequest(models.Model):
    TYPES = [('annual', 'سنوية'), ('casual', 'عارضة'), ('sick', 'مرضية'), ('unpaid', 'بدون أجر')]
    STATUS = [('pending', 'قيد الانتظار والمراجعة'), ('approved', 'موافق عليها ومخصومة'), ('rejected', 'مرفوضة قطعيّاً')]
    
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.CharField(max_length=10, choices=TYPES, verbose_name="نوع الإجازة المطلوبة")
    start_date = models.DateField(verbose_name="تاريخ بداية الإجازة")
    end_date = models.DateField(verbose_name="تاريخ نهاية الإجازة")
    reason = models.TextField(null=True, blank=True, verbose_name="السبب المذكور للطلب")
    status = models.CharField(max_length=10, choices=STATUS, default='pending', verbose_name="حالة الطلب الإدارية")
    
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def duration_days(self):
        if self.end_date and self.start_date:
            return (self.end_date - self.start_date).days + 1
        return 0

    def clean(self):
        from django.core.exceptions import ValidationError
        # منع التقديم بالخطأ إذا تجاوز الأيام المتاحة قبل الحفظ الفعلي
        if self.status == 'pending':
            days = self.duration_days
            if self.leave_type == 'annual' and days > self.employee.annual_balance:
                raise ValidationError(f"رصيد الموظف السنوي الحالي ({self.employee.annual_balance} يوم) لا يكفي لتغطية طلب الإجازة ({days} يوم).")
            if self.leave_type == 'casual' and days > self.employee.casual_balance:
                raise ValidationError(f"رصيد الموظف من العارضة الحالي ({self.employee.casual_balance} يوم) لا يكفي.")

    def save(self, *args, **kwargs):
        # تتبع وتأمين العمليات: الخصم التلقائي عند التحول لـ Approved وتفادي تكرار الخصم الإجرائي
        if self.pk:
            old_record = LeaveRequest.objects.get(pk=self.pk)
            if old_record.status != 'approved' and self.status == 'approved':
                days = self.duration_days
                if self.leave_type == 'annual':
                    self.employee.annual_balance -= days
                elif self.leave_type == 'casual':
                    self.employee.casual_balance -= days
                elif self.leave_type == 'sick':
                    self.employee.sick_balance -= days
                self.employee.save()
        super().save(*args, **kwargs)