from django.db import models
from django.contrib.auth.models import User
from django.conf import settings



class GeneralLedger(models.Model):
    date = models.DateTimeField("تاريخ ووقت الحركة", auto_now_add=True)
    student = models.ForeignKey("students.Student", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الطالب")
    
    # 🔴 تم حل المشكلة هنا: تكبير الحقل لـ 100 حرف وإزالة القيود (choices) 
    # لكي يقبل الأسماء العربية الطويلة الممررة من الـ views
    category = models.CharField("نوع الإيراد", max_length=100)
    
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
        return f"{self.category} - {self.amount} ج.م"    
    


from django.db import models
import uuid

class Product(models.Model):
    # الرقم المسلسل هو المفتاح الأساسي للبحث (مثل: 652435889493)
    serial_number = models.CharField(max_length=50, unique=True, verbose_name="الرقم المسلسل")
    product_name = models.CharField(max_length=100, verbose_name="اسم المنتج")
    is_original = models.BooleanField(default=True, verbose_name="أصلي؟")
    
    # عداد المسح لحماية المنتج من التزوير المكرر
    scan_count = models.PositiveIntegerField(default=0, verbose_name="عدد مرات المسح")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإضافة")

    def __str__(self):
        return f"{self.product_name} - {self.serial_number}"

    class Meta:
        verbose_name = "منتج"
        verbose_name_plural = "المنتجات"