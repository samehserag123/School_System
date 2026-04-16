from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

# 1. الإدارات
class Department(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم القسم")
    manager = models.ForeignKey('Employee', on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_departments')

    def __str__(self):
        return self.name

# 2. القواعد العامة (هنا تضع قوانين الشركة)
class AttendanceRule(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم القاعدة (مثلاً: الدوام الصباحي)")
    
    # مواعيد العمل
    work_start_time = models.TimeField(verbose_name="موعد الحضور الرسمي")
    work_end_time = models.TimeField(verbose_name="موعد الانصراف الرسمي")
    
    # قوانين التأخير والإضافي
    grace_period = models.PositiveIntegerField(default=15, verbose_name="فترة السماح (بالدقائق)")
    deduction_multiplier = models.FloatField(default=1.0, verbose_name="معامل الخصم (ساعة التأخير بـ X ساعة)")
    overtime_multiplier = models.FloatField(default=1.5, verbose_name="معامل الإضافي (ساعة الإضافي بـ X ساعة)")

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
        """وظيفة ذكية للتحقق هل التاريخ الممرر هو يوم عمل في هذه القاعدة أم لا"""
        day_name = date_obj.strftime('%A').lower()  # يعطي اسم اليوم بالإنجليزية lowercase
        return getattr(self, day_name, False)

# 3. الموظف (تم تحديثه ليدعم الحالات الخاصة)
class Employee(models.Model):
    emp_id = models.CharField(max_length=50, unique=True, verbose_name="رقم البصمة")
    name = models.CharField(max_length=100, verbose_name="اسم الموظف")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, verbose_name="القسم")
    
    # ربط الموظف بقاعدة حضور محددة (الحالة الخاصة)
    attendance_rule = models.ForeignKey(AttendanceRule, on_delete=models.PROTECT, verbose_name="نظام الحضور المطبق")
    
    is_active = models.BooleanField(default=True, verbose_name="على رأس العمل")
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="الراتب الأساسي")
    
    # أرصدة الإجازات
    annual_balance = models.FloatField(default=21)
    casual_balance = models.FloatField(default=6)

    def __str__(self):
        return self.name

# 4. سجل البصمة الخام (لرفع الملف بسهولة)
class FingerprintLog(models.Model):
    emp_id = models.CharField(max_length=50, verbose_name="رقم البصمة")
    timestamp = models.DateTimeField(verbose_name="وقت البصمة")
    device_id = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        verbose_name = "سجل البصمة الخام"
        # لمنع تكرار نفس البصمة عند رفع الملف مرتين
        unique_together = ('emp_id', 'timestamp')

# 5. الحضور والانصراف (الناتج المعالج)
class DailyAttendance(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    date = models.DateField()
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=[
        ('present', 'حاضر'),
        ('absent', 'غائب'),
        ('leave', 'إجازة'),
        ('holiday', 'عطلة رسمية'),
    ])
    late_minutes = models.IntegerField(default=0)
    overtime_hours = models.FloatField(default=0)

    class Meta:
        unique_together = ('employee', 'date')

# 6. سجل الإجازات الاحترافي
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