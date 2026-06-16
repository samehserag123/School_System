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
    

    is_discount = models.BooleanField(
        "هل الحركة عبارة عن خصم/كوبون؟", 
        default=False,
        db_index=True  # إضافة Index هنا تسرع عملية الفلترة جداً
    )

    # --- الحقول المضافة للربط مع نظام الجرد الجديد ---
    is_closed = models.BooleanField(
        "تم الإغلاق بالجرد", 
        default=False, 
        db_index=True,  # 🟢 إضافة هذا السطر ستضاعف سرعة البحث 100 مرة
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
    


from django.utils import timezone

class Product(models.Model):
    serial_number = models.CharField(max_length=50, unique=True, verbose_name="الرقم المسلسل")
    product_name = models.CharField(max_length=100, verbose_name="اسم المنتج")
    is_original = models.BooleanField(default=True, verbose_name="أصلي؟")
    
    # حقول التعطيل المؤقت
    is_active = models.BooleanField(default=True, verbose_name="نشط (الـ QR يعمل)")
    disabled_until = models.DateTimeField(null=True, blank=True, verbose_name="تعطيل مؤقت حتى تاريخ")

    # العداد الإجمالي
    scan_count = models.PositiveIntegerField(default=0, verbose_name="عدد مرات المسح الإجمالية")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإضافة")

    @property
    def is_currently_disabled(self):
        if not self.is_active:
            return True
        if self.disabled_until and timezone.now() < self.disabled_until:
            return True
        return False

    def __str__(self):
        return f"{self.product_name} - {self.serial_number}"

    class Meta:
        verbose_name = "منتج"
        verbose_name_plural = "المنتجات"


# الجدول الجديد لتسجيل تاريخ ووقت كل مسحة بالتفصيل
class ScanHistory(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="scans", verbose_name="المنتج")
    scanned_at = models.DateTimeField(default=timezone.now, verbose_name="تاريخ ووقت المسح")
    
    # اختياري: يمكنك تسجيل الـ IP أو المتصفح إذا أردت معرفة هل هو نفس الشخص أم لا
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="عنوان الـ IP")

    class Meta:
        verbose_name = "تاريخ المسح"
        verbose_name_plural = "تواريخ المسح للمنتجات"
        ordering = ['-scanned_at'] # لترتيب المسحات من الأحدث للأقدم

    def __str__(self):
        return f"مسحة لـ {self.product.product_name} في {self.scanned_at.strftime('%Y-%m-%d %H:%M:%S')}"