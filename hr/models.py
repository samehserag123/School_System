from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import datetime, timedelta

# 1. الإدارات
class Department(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم القسم")
    manager = models.ForeignKey('Employee', on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_departments')

    def __str__(self):
        return self.name

# 2. القواعد العامة والتخصيصات (مفتاح المرونة)
class AttendanceRule(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم القاعدة (مثلاً: دوام صباحي، مرن، مؤقت)")
    
    # مواعيد العمل
    work_start_time = models.TimeField(verbose_name="موعد الحضور الرسمي")
    work_end_time = models.TimeField(verbose_name="موعد الانصراف الرسمي")
    
    # قوانين التأخير والإضافي
    grace_period = models.PositiveIntegerField(default=15, verbose_name="فترة السماح (بالدقائق)")
    deduction_multiplier = models.FloatField(default=1.0, verbose_name="معامل الخصم (ساعة التأخير بـ X ساعة)")
    overtime_multiplier = models.FloatField(default=1.5, verbose_name="معامل الإضافي (ساعة الإضافي بـ X ساعة)")

    # مرونة حساب الغياب والإجازات
    absent_deduction_days = models.FloatField(default=1.0, verbose_name="خصم الغياب (اليوم بـ X يوم)")
    requires_fingerprint = models.BooleanField(default=True, verbose_name="هل الموظف ملزم بالبصمة؟ (للإدارة العليا مثلاً)")

    # تحديد أيام العمل (True يعني يوم عمل، False يعني يوم إجازة)
    monday = models.BooleanField(default=True, verbose_name="الاثنين")
    tuesday = models.BooleanField(default=True, verbose_name="الثلاثاء")
    wednesday = models.BooleanField(default=True, verbose_name="الأربعاء")
    thursday = models.BooleanField(default=True, verbose_name="الخميس")
    friday = models.BooleanField(default=False, verbose_name="الجمعة")
    saturday = models.BooleanField(default=False, verbose_name="السبت")
    sunday = models.BooleanField(default=True, verbose_name="الأحد")

    class Meta:
        verbose_name = "قاعدة حضور"
        verbose_name_plural = "قواعد الحضور"

    def __str__(self):
        return self.name

    def is_working_day(self, date_obj):
        day_name = date_obj.strftime('%A').lower()
        return getattr(self, day_name, False)

# 3. الموظف
class Employee(models.Model):
    emp_id = models.CharField(max_length=50, unique=True, verbose_name="رقم البصمة")
    name = models.CharField(max_length=100, verbose_name="اسم الموظف")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, verbose_name="القسم")
    
    # ربط الموظف بنظامه الخاص
    attendance_rule = models.ForeignKey(AttendanceRule, on_delete=models.PROTECT, verbose_name="نظام الحضور المطبق")
    
    is_active = models.BooleanField(default=True, verbose_name="على رأس العمل")
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="الراتب الأساسي")
    
    # أرصدة الإجازات السنوية المخصصة لهذا الموظف
    annual_balance = models.FloatField(default=21, verbose_name="رصيد سنوي")
    casual_balance = models.FloatField(default=6, verbose_name="رصيد عارضة")

    def __str__(self):
        return self.name

# 4. سجل البصمة الخام
class FingerprintLog(models.Model):
    emp_id = models.CharField(max_length=50, verbose_name="رقم البصمة")
    timestamp = models.DateTimeField(verbose_name="وقت البصمة")
    device_id = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        verbose_name = "سجل البصمة الخام"
        unique_together = ('emp_id', 'timestamp')

# 5. الحضور والانصراف المعالج (تمت إضافة الحقول المالية والخصومات المباشرة)
class DailyAttendance(models.Model):
    STATUS_CHOICES = [
        ('present', 'حاضر'),
        ('absent', 'غائب'),
        ('leave', 'إجازة'),
        ('holiday', 'عطلة رسمية'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    date = models.DateField()
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    
    late_minutes = models.IntegerField(default=0, verbose_name="دقائق التأخير")
    overtime_hours = models.FloatField(default=0, verbose_name="ساعات الإضافي")
    
    # حقول احترافية تُحسب تلقائياً بناءً على قاعدة الموظف
    deduction_hours = models.FloatField(default=0.0, verbose_name="ساعات الخصم المستحقة")
    is_processed = models.BooleanField(default=False, verbose_name="تمت المعالجة المالية")

    class Meta:
        unique_together = ('employee', 'date')

    def __str__(self):
        return f"{self.employee.name} - {self.date} - {self.get_status_display()}"

# 6. سجل الإجازات الاحترافي مع خصم الرصيد تلقائياً
class LeaveRequest(models.Model):
    TYPES = [('annual', 'سنوية'), ('casual', 'عارضة'), ('sick', 'مرضي'), ('unpaid', 'بدون أجر')]
    STATUS = [('pending', 'قيد الانتظار'), ('approved', 'مقبولة'), ('rejected', 'مرفوضة')]
    
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    leave_type = models.CharField(max_length=10, choices=TYPES)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS, default='pending')
    
    @property
    def duration(self):
        return (self.end_date - self.start_date).days + 1

    def save(self, *map, **kwargs):
        # منطق احترافي: خصم تلقائي من رصيد الموظف عند الموافقة على الإجازة
        if self.pk:
            old_status = LeaveRequest.objects.get(pk=self.pk).status
            if old_status != 'approved' and self.status == 'approved':
                if self.leave_type == 'annual':
                    self.employee.annual_balance -= self.duration
                elif self.leave_type == 'casual':
                    self.employee.casual_balance -= self.duration
                self.employee.save()
        super().save(*map, **kwargs)