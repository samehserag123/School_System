from django.db import models
from django.contrib.auth.models import User
from django.conf import settings

class GeneralLedger(models.Model):
    # تصنيفات واضحة لكل أنواع الدخل
    ENTRY_TYPES = [
        ('fees', 'مصروفات دراسية'),
        ('books', 'كتب وباقات دراسية'),
        ('bus', 'اشتراك باص'),
        ('other', 'إيرادات متنوعة'),
    ]

    date = models.DateTimeField("تاريخ ووقت الحركة", auto_now_add=True)
    student = models.ForeignKey("students.Student", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الطالب")
    category = models.CharField("نوع الإيراد", max_length=20, choices=ENTRY_TYPES)
    amount = models.DecimalField("المبلغ المورد", max_digits=12, decimal_places=2)
    
    # ربط برقم الإيصال لسهولة المراجعة
    receipt_number = models.CharField(
        "رقم الإيصال المرجعي", 
        max_length=50, 
        unique=True  # 🛡️ هذا هو "القفل" الحقيقي لمنع التكرار
    )
    collected_by = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name="الموظف المستلم")
    notes = models.TextField("ملاحظات إضافية", blank=True, null=True)

    # --- الحقول المضافة للربط مع نظام الجرد الجديد ---
    is_closed = models.BooleanField(
        "تم الإغلاق بالجرد", 
        default=False, 
        help_text="تحدد ما إذا كانت هذه الحركة قد تم ترحيلها في جرد يومي سابق"
    )
    closure = models.ForeignKey(
        'finance.DailyClosure', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="ledger_entries",
        verbose_name="رقم الجرد/الإغلاق"
    )

    class Meta:
        verbose_name = "حركة خزينة مجمعة"
        verbose_name_plural = "الخزينة العامة (دفتر اليومية)"
        ordering = ['-date']

    def __str__(self):
        return f"{self.get_category_display()} - {self.amount} ج.م"