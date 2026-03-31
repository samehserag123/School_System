from django.db import models

class Department(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم القسم")
    description = models.TextField(null=True, blank=True, verbose_name="وصف القسم")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "قسم"
        verbose_name_plural = "الأقسام"


class Employee(models.Model):
    DAYS_OF_WEEK = [
        ('Sunday', 'الأحد'),
        ('Monday', 'الإثنين'),
        ('Tuesday', 'الثلاثاء'),
        ('Wednesday', 'الأربعاء'),
        ('Thursday', 'الخميس'),
        ('Friday', 'الجمعة'),
        ('Saturday', 'السبت'),
    ]

    emp_id = models.CharField(max_length=50, unique=True, verbose_name="رقم البصمة")
    name = models.CharField(max_length=100, verbose_name="اسم الموظف")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="القسم")
    job_title = models.CharField(max_length=100, null=True, blank=True, verbose_name="المسمى الوظيفي")
    contract_date = models.DateField(null=True, blank=True, verbose_name="تاريخ التعاقد")
    
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="الراتب الأساسي")
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="أجر الساعة")
    
    social_insurance = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="قيمة التأمينات الاجتماعية")
    medical_insurance = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="قيمة التأمين الطبي")
    penalties = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="الجزاءات")
    loans = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="السلفيات") 
    
    annual_leave_balance = models.IntegerField(default=21, verbose_name="رصيد الإجازات السنوية")
    casual_leave_balance = models.IntegerField(default=6, verbose_name="رصيد الإجازات العارضة")
    weekly_day_off = models.CharField(max_length=20, choices=DAYS_OF_WEEK, default='Friday', verbose_name="يوم الإجازة الأسبوعية (Day Off)")

    def __str__(self):
        return f"{self.name} - {self.emp_id}"

    class Meta:
        verbose_name = "موظف"
        verbose_name_plural = "الموظفين"

# ================= الجدول الجديد: أرشيف المرتبات =================
class PayrollArchive(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, verbose_name="الموظف")
    month = models.IntegerField(verbose_name="شهر الاستحقاق")
    year = models.IntegerField(verbose_name="سنة الاستحقاق")
    
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="الأساسي وقتها")
    days_present = models.IntegerField(verbose_name="أيام الحضور")
    # الحقل الجديد لحفظ الإجازات في الأرشيف
    lateness_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="خصم التأخير")
    leaves_taken = models.IntegerField(verbose_name="إجازات الشهر", default=0)
    absent_days = models.IntegerField(verbose_name="الغياب الفعلي")
    absence_deduction = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="خصم الغياب")
    penalties = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="الجزاءات المخصومة")
    loans = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="السلف المخصومة")
    insurances = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="التأمينات المخصومة")
    net_salary = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="صافي الراتب المستحق")
    archived_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الترحيل")

    class Meta:
        verbose_name = "سجل مرتب مرحل"
        verbose_name_plural = "أرشيف المرتبات"
        unique_together = ('employee', 'month', 'year')

    def __str__(self):
        return f"مرتب {self.employee.name} - {self.month}/{self.year}"
    

# أضف هذا في نهاية ملف hr/models.py
class Leave(models.Model):
    LEAVE_TYPES = [
        ('Annual', 'إجازة سنوية'),
        ('Casual', 'إجازة عارضة'),
        ('Sick', 'إجازة مرضية'),
        ('Unpaid', 'إجازة بدون أجر'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, verbose_name="الموظف")
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPES, verbose_name="نوع الإجازة")
    start_date = models.DateField(verbose_name="من تاريخ")
    end_date = models.DateField(verbose_name="إلى تاريخ")
    days = models.IntegerField(verbose_name="عدد الأيام")
    notes = models.TextField(null=True, blank=True, verbose_name="ملاحظات/السبب")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"إجازة {self.employee.name} - {self.days} أيام"

    class Meta:
        verbose_name = "إجازة"
        verbose_name_plural = "سجل الإجازات"