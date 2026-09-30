from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
import uuid
from django.db.models import F
# ==========================================
# 1. إعدادات المخازن والأقسام
# ==========================================
class Warehouse(models.Model):
    name = models.CharField("اسم المستودع", max_length=100, unique=True, db_index=True)
    location = models.CharField("الموقع/المبنى", max_length=150, blank=True, null=True)
    is_active = models.BooleanField("نشط", default=True, db_index=True)

    class Meta:
        verbose_name = "مستودع"
        verbose_name_plural = "1. المستودعات"

    def __str__(self):
        return self.name

class ItemCategory(models.Model):
    name = models.CharField("اسم التصنيف", max_length=100, db_index=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subcategories', verbose_name="التصنيف الأب")

    class Meta:
        verbose_name = "تصنيف مخزني"
        verbose_name_plural = "2. شجرة الأصناف"

    def __str__(self):
        return f"{self.name} (تابع لـ {self.parent.name})" if self.parent else self.name


class ItemMaster(models.Model):
    ITEM_TYPES = [
        ('saleable', 'مخزون للبيع (كتب/زي)'),
        ('consumable', 'مخزون استهلاكي (مطبخ/نظافة)'),
        ('asset', 'أصول ثابتة (تخت/أجهزة)'),
    ]

    TRACKING_CHOICES = [
        ('none', 'بدون تتبع خاص'),
        ('batch', 'تتبع برقم التشغيلة وصلاحية (ل للمطعم)'),
        ('serial', 'تتبع بالسيريال نمبر (للأصول والأجهزة)'),
    ]

    sku = models.CharField("كود الصنف (SKU/Barcode)", max_length=50, unique=True, blank=True, db_index=True)
    name = models.CharField("اسم الصنف", max_length=200, db_index=True)
    category = models.ForeignKey(ItemCategory, on_delete=models.PROTECT, verbose_name="التصنيف", db_index=True)
    item_type = models.CharField("طبيعة الصنف", max_length=20, choices=ITEM_TYPES, default='saleable', db_index=True)

    # 🟢 الربط الديناميكي مع جدول وحدات القياس
    unit_of_measure = models.ForeignKey(
        'UnitOfMeasure',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="وحدة القياس"
    )

    tracking_type = models.CharField("نوع التتبع", max_length=20, choices=TRACKING_CHOICES, default='none')
    reorder_level = models.DecimalField("حد الطلب (الحد الأدنى)", max_digits=10, decimal_places=2, default=0)

    linked_subject = models.ForeignKey('students.Subject', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المادة الدراسية (للكتب)")
    linked_grade = models.ForeignKey('students.Grade', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الصف (للكتب والزي)")

    class Meta:
        verbose_name = "بطاقة صنف"
        verbose_name_plural = "3. بطاقات الأصناف (دليل المواد)"

    def save(self, *args, **kwargs):
        if not self.sku or not str(self.sku).strip():
            last_item = ItemMaster.objects.order_by('id').last()
            next_id = (last_item.id + 1) if last_item else 1
            generated_sku = f"SKU-{next_id:04d}"
            while ItemMaster.objects.filter(sku=generated_sku).exists():
                next_id += 1
                generated_sku = f"SKU-{next_id:04d}"
            self.sku = generated_sku
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.sku}] {self.name}"


# class ItemMaster(models.Model):
#     ITEM_TYPES = [
#         ('saleable', 'مخزون للبيع (كتب/زي)'),
#         ('consumable', 'مخزون استهلاكي (مطبخ/نظافة)'),
#         ('asset', 'أصول ثابتة (تخت/أجهزة)'),
#     ]

#     UNIT_CHOICES = [
#         ('piece', 'قطعة / عدد'),
#         ('kg', 'كيلوجرام'),
#         ('gram', 'جرام'),
#         ('liter', 'لتر'),
#         ('pack', 'عبوة / كرتونة'),
#     ]

#     TRACKING_CHOICES = [
#         ('none', 'بدون تتبع خاص'),
#         ('batch', 'تتبع برقم التشغيلة وصلاحية (للمطعم)'),
#         ('serial', 'تتبع بالسيريال نمبر (للأصول والأجهزة)'),
#     ]

#     # إضافة db_index=True لسرعة البحث في القوائم المنسدلة
#     sku = models.CharField("كود الصنف (SKU/Barcode)", max_length=50, unique=True, blank=True, db_index=True)
#     name = models.CharField("اسم الصنف", max_length=200, db_index=True)
#     category = models.ForeignKey(ItemCategory, on_delete=models.PROTECT, verbose_name="التصنيف", db_index=True)
#     item_type = models.CharField("طبيعة الصنف", max_length=20, choices=ITEM_TYPES, default='saleable', db_index=True)
#     unit_of_measure = models.CharField("وحدة القياس", max_length=20, choices=UNIT_CHOICES, default='piece')
#     tracking_type = models.CharField("نوع التتبع", max_length=20, choices=TRACKING_CHOICES, default='none')

#     # تنبيه النواقص
#     reorder_level = models.DecimalField("حد الطلب (الحد الأدنى)", max_digits=10, decimal_places=2, default=0)

#     # 🔗 الربط مع النظام القديم (اختياري للكتب والزي فقط)
#     linked_subject = models.ForeignKey('students.Subject', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المادة الدراسية (للكتب)")
#     linked_grade = models.ForeignKey('students.Grade', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الصف (للكتب والزي)")

#     class Meta:
#         verbose_name = "بطاقة صنف"
#         verbose_name_plural = "3. بطاقات الأصناف (دليل المواد)"

#     def save(self, *args, **kwargs):
#         if not self.sku or not str(self.sku).strip():
#             last_item = ItemMaster.objects.order_by('id').last()
#             next_id = (last_item.id + 1) if last_item else 1
#             generated_sku = f"SKU-{next_id:04d}"
#             while ItemMaster.objects.filter(sku=generated_sku).exists():
#                 next_id += 1
#                 generated_sku = f"SKU-{next_id:04d}"
#             self.sku = generated_sku
#         super().save(*args, **kwargs)

#     def __str__(self):
#         return f"[{self.sku}] {self.name}"

# ==========================================
# 3. جدول حركات المخزون (القلب النابض للنظام)
# ==========================================


class StockTransaction(models.Model):
    MOVEMENT_TYPES = [
        ('IN_OPENING', 'رصيد افتتاحي'),
        ('IN_PURCHASE', 'وارد مشتريات'),
        ('IN_RETURN', 'وارد مرتجع (من طالب أو قسم)'),
        ('OUT_STUDENT', 'منصرف لطالب (بيع/تسليم)'),
        ('OUT_DEPT', 'منصرف لقسم (تشغيل مطبخ/نظافة)'),
        ('OUT_WASTE', 'منصرف هالك / تالف'),
        ('TRANSFER', 'تحويل بين المستودعات'),
        ('ADJUST', 'تسوية جردية (عجز/زيادة)'),
    ]

    # 🚀 معالجة الطول والفرادة (مع إضافة null/blank لتجنب Duplicate Entry '')
    transaction_code = models.CharField(
        "رقم الحركة",
        max_length=100,
        unique=True,
        blank=True,
        null=True,
        editable=False,
        db_index=True
    )
    movement_type = models.CharField("نوع الحركة", max_length=20, choices=MOVEMENT_TYPES, db_index=True)

    item = models.ForeignKey(ItemMaster, on_delete=models.PROTECT, verbose_name="الصنف", db_index=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, verbose_name="المستودع", db_index=True)

    quantity = models.DecimalField("الكمية", max_digits=12, decimal_places=2)

    # 🔗 الربط الذكي بالأنظمة الأخرى
    student = models.ForeignKey('students.Student', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="صرف لطالب")
    department = models.CharField("القسم المستلم (للمطعم/النظافة)", max_length=100, blank=True, null=True)
    finance_receipt = models.ForeignKey('finance.Payment', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="رقم الإيصال المالي")

    batch_number = models.CharField("رقم التشغيلة / الباتش", max_length=50, blank=True, null=True, db_index=True)
    expiry_date = models.DateField("تاريخ الصلاحية", blank=True, null=True, db_index=True)
    serial_number = models.CharField("السيريال نمبر (للأصول)", max_length=100, blank=True, null=True, db_index=True)

    date = models.DateTimeField("تاريخ الحركة", default=timezone.now, db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name="أمين المخزن")
    notes = models.TextField("ملاحظات", blank=True, null=True)

    class Meta:
        verbose_name = "حركة مخزنية"
        verbose_name_plural = "4. الحركات المخزنية (وارد ومنصرف)"
        ordering = ['-date']

    def save(self, *args, **kwargs):
        # ⚡ 1. توليد كود الحركة بأقل استعلامات ممكنة دون استدعاء self.item من الـ DB
        if not self.transaction_code:
            item_id_str = str(self.item_id) if self.item_id else "0"
            unique_suffix = uuid.uuid4().hex[:6].upper()
            # استخدام timestamp مختصر وسريع
            self.transaction_code = f"TRX-{timezone.now().strftime('%Y%m%d%H%M%S')}-{item_id_str}-{unique_suffix}"

        # ⚡ 2. التحقق من الرصيد والتحويلات داخل Atomic Transaction لضمان السرعة ومنع Lock التزامن
        is_outgoing = self.movement_type in ['OUT_STUDENT', 'OUT_DEPT', 'OUT_WASTE', 'TRANSFER']

        with transaction.atomic():
            if is_outgoing:
                current_stock = StockBalance.get_stock(self.item_id, self.warehouse_id)
                if self.quantity > current_stock:
                    warehouse_name = getattr(self.warehouse, 'name', '') if hasattr(self, '_warehouse_cache') else 'المستودع'
                    raise ValidationError(f"🛑 الرصيد غير كافٍ في {warehouse_name}. المتاح: {current_stock}، والمطلوب صرفه: {self.quantity}")

            # ⚡ 3. حفظ الحركة أولاً
            super().save(*args, **kwargs)

            # ⚡ 4. التحديث التراكمي الجزئي بدلاً من إعادة الحساب الكامل للجدول
            # يُفضل دائماً القسيمة أو التحديث المباشر للمخزن المربوط
            StockBalance.update_balance(self.item_id, self.warehouse_id, delta_quantity=self.get_signed_quantity())

    def get_signed_quantity(self):
        """إرجاع الكمية موجبة أو سالبة حسب نوع الحركة للتحديث السريع"""
        if self.movement_type in ['OUT_STUDENT', 'OUT_DEPT', 'OUT_WASTE', 'TRANSFER']:
            return -abs(self.quantity)
        return abs(self.quantity)


# class StockTransaction(models.Model):
#     MOVEMENT_TYPES = [
#         ('IN_OPENING', 'رصيد افتتاحي'),
#         ('IN_PURCHASE', 'وارد مشتريات'),
#         ('IN_RETURN', 'وارد مرتجع (من طالب أو قسم)'),
#         ('OUT_STUDENT', 'منصرف لطالب (بيع/تسليم)'),
#         ('OUT_DEPT', 'منصرف لقسم (تشغيل مطبخ/نظافة)'),
#         ('OUT_WASTE', 'منصرف هالك / تالف'),
#         ('TRANSFER', 'تحويل بين المستودعات'),
#         ('ADJUST', 'تسوية جردية (عجز/زيادة)'),
#     ]

#     transaction_code = models.CharField("رقم الحركة", max_length=50, unique=True, editable=False, db_index=True)
#     movement_type = models.CharField("نوع الحركة", max_length=20, choices=MOVEMENT_TYPES, db_index=True)

#     item = models.ForeignKey(ItemMaster, on_delete=models.PROTECT, verbose_name="الصنف", db_index=True)
#     warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, verbose_name="المستودع", db_index=True)

#     quantity = models.DecimalField("الكمية", max_digits=12, decimal_places=2)

#     # 🔗 الربط الذكي بالأنظمة الأخرى (أب المخازن)
#     student = models.ForeignKey('students.Student', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="صرف لطالب")
#     department = models.CharField("القسم المستلم (للمطعم/النظافة)", max_length=100, blank=True, null=True)
#     finance_receipt = models.ForeignKey('finance.Payment', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="رقم الإيصال المالي")

#     batch_number = models.CharField("رقم التشغيلة / الباتش", max_length=50, blank=True, null=True, db_index=True)
#     expiry_date = models.DateField("تاريخ الصلاحية", blank=True, null=True, db_index=True)
#     serial_number = models.CharField("السيريال نمبر (للأصول)", max_length=100, blank=True, null=True, db_index=True)

#     # الفهرسة للتاريخ تسرع التقارير بشكل هائل
#     date = models.DateTimeField("تاريخ الحركة", default=timezone.now, db_index=True)
#     created_by = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name="أمين المخزن")
#     notes = models.TextField("ملاحظات", blank=True, null=True)

#     class Meta:
#         verbose_name = "حركة مخزنية"
#         verbose_name_plural = "4. الحركات المخزنية (وارد ومنصرف)"
#         ordering = ['-date']

#     def save(self, *args, **kwargs):
#         if not self.transaction_code:
#             import uuid
#             # 🩹 إضافة الميكروثانية + جزء عشوائي قصير يمنع أي تعارض حتى لو اتسجلت
#             # أكتر من حركة لنفس الصنف في نفس الثانية بالظبط (زي أصناف فاتورة واحدة)
#             unique_suffix = uuid.uuid4().hex[:6]
#             self.transaction_code = f"TRX-{timezone.now().strftime('%Y%m%d%H%M%S%f')}-{self.item.id}-{unique_suffix}"

#         if self.movement_type in ['OUT_STUDENT', 'OUT_DEPT', 'OUT_WASTE', 'TRANSFER']:
#             current_stock = StockBalance.get_stock(self.item, self.warehouse)
#             if self.quantity > current_stock:
#                 raise ValidationError(f"🛑 الرصيد غير كافٍ في {self.warehouse.name}. المتاح: {current_stock}، والمطلوب صرفه: {self.quantity}")

#         super().save(*args, **kwargs)
#         StockBalance.update_balance(self.item, self.warehouse)

# ==========================================
# 4. جدول الأرصدة الحية (لتسريع فتح الشاشات)
# ==========================================
class StockBalance(models.Model):
    item = models.ForeignKey(ItemMaster, on_delete=models.CASCADE, db_index=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, db_index=True)
    quantity_on_hand = models.DecimalField("الرصيد المتاح", max_digits=12, decimal_places=2, default=0)

    class Meta:
        unique_together = ('item', 'warehouse')
        verbose_name = "رصيد حالي"
        verbose_name_plural = "5. الأرصدة الحالية في المستودعات"

    @classmethod
    def get_stock(cls, item, warehouse):
        balance, _ = cls.objects.get_or_create(item=item, warehouse=warehouse)
        return balance.quantity_on_hand

    @classmethod
    def update_balance(cls, item_id, warehouse_id, delta_quantity):
        """
        تحديث الرصيد بلحظة وبسرعة فائقة (Atomic Update)
        - delta_quantity: تكون موجبة للوارد، وسالبة للمنصرف
        """
        # جلب أو إنشاء سجل الرصيد للتركيبة (item_id + warehouse_id)
        balance_record, created = cls.objects.get_or_create(
            item_id=item_id,
            warehouse_id=warehouse_id,
            defaults={'quantity_on_hand': Decimal('0.00')}
        )

        # تحديث الحقل بداخل قاعدة البيانات مباشرة بدون إعادة حساب الجدول كاملاً
        cls.objects.filter(id=balance_record.id).update(
            quantity_on_hand=F('quantity_on_hand') + Decimal(str(delta_quantity))
        )

    @classmethod
    def recalculate_from_scratch(cls, item_id, warehouse_id):
        """
        دالة جرد طوارئ / صيانة: تُستخدم فقط عند الحاجة لتسوية الجرد
        أو إعادة الحساب من الصفر في استعلام واحد متكامل.
        """
        totals = StockTransaction.objects.filter(
            item_id=item_id, warehouse_id=warehouse_id
        ).aggregate(
            in_qty=models.Sum(
                'quantity',
                filter=models.Q(movement_type__in=['IN_OPENING', 'IN_PURCHASE', 'IN_RETURN', 'ADJUST'])
            ),
            out_qty=models.Sum(
                'quantity',
                filter=models.Q(movement_type__in=['OUT_STUDENT', 'OUT_DEPT', 'OUT_WASTE', 'TRANSFER'])
            )
        )

        in_qty = totals['in_qty'] or Decimal('0.00')
        out_qty = totals['out_qty'] or Decimal('0.00')
        net_balance = in_qty - out_qty

        balance_record, _ = cls.objects.get_or_create(item_id=item_id, warehouse_id=warehouse_id)
        balance_record.quantity_on_hand = net_balance
        balance_record.save()

# ==========================================
# 5. نظام الموردين (Suppliers)
# ==========================================
class Supplier(models.Model):
    name = models.CharField(max_length=255, verbose_name="اسم المورد / الشركة", db_index=True)
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="رقم الهاتف")
    address = models.TextField(blank=True, null=True, verbose_name="العنوان")

    # أرصدة حسابات المورد الدائنة والمدينة
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="الرصيد الافتتاحي (دائن)")
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="الرصيد الحالي", db_index=True)

    is_active = models.BooleanField(default=True, verbose_name="نشط", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مورد"
        verbose_name_plural = "6. الموردين"
        ordering = ['name']

    def __str__(self):
        return self.name


# ==========================================
# 6. فواتير المشتريات (Purchase Invoices)
# ==========================================
class PurchaseInvoice(models.Model):
    STATUS_CHOICES = (
        ('draft', 'مسودة (لم تعتمد)'),
        ('approved', 'معتمدة (مرحلة للمخزن)'),
        ('cancelled', 'ملغاة'),
    )

    invoice_number = models.CharField(max_length=50, unique=True, verbose_name="رقم الفاتورة", db_index=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices', verbose_name="المورد", db_index=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='purchase_invoices', verbose_name="المستودع المستلم")

    date = models.DateField(default=timezone.now, verbose_name="تاريخ الفاتورة", db_index=True)

    # الإجماليات (محسوبة مسبقاً لسرعة العرض دون عمليات رياضية)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="إجمالي الفاتورة")
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="الخصم")
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="الصافي")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft', verbose_name="حالة الفاتورة", db_index=True)
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="سجلت بواسطة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "فاتورة مشتريات"
        verbose_name_plural = "7. فواتير المشتريات"
        ordering = ['-date', '-id']

    def __str__(self):
        supplier_name = self.supplier.name if self.supplier else "شراء نقدي / عام"
        return f"فاتورة {self.invoice_number} - {supplier_name}"


class PurchaseInvoiceItem(models.Model):
    invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.CASCADE, related_name='items', verbose_name="الفاتورة", db_index=True)
    item = models.ForeignKey(ItemMaster, on_delete=models.PROTECT, related_name='purchase_history', verbose_name="الصنف", db_index=True)
    grade = models.ForeignKey('students.Grade', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الصف الدراسي")
    quantity = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="الكمية")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="سعر الشراء للوحدة")
    total_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="إجمالي السطر")

    class Meta:
        verbose_name = "صنف بالفاتورة"
        verbose_name_plural = "أصناف الفاتورة"

    def save(self, *args, **kwargs):
        # حساب الإجمالي التلقائي للسطر قبل الحفظ
        self.total_price = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item.name} - {self.quantity}"


# ==========================================
# 7. نظام وحدات القياس والتحويلات (Material Control)
# ==========================================
class UnitOfMeasure(models.Model):
    name = models.CharField("اسم الوحدة", max_length=50, unique=True, db_index=True)
    symbol = models.CharField("الرمز المرجعي", max_length=20, blank=True, null=True)

    class Meta:
        verbose_name = "وحدة قياس"
        verbose_name_plural = "8. وحدات القياس"

    def __str__(self):
        return self.name

class ItemUnitConversion(models.Model):
    item = models.ForeignKey(ItemMaster, on_delete=models.CASCADE, related_name='conversions', verbose_name="الصنف")
    from_unit = models.ForeignKey(UnitOfMeasure, on_delete=models.CASCADE, related_name='convert_from', verbose_name="من وحدة (وحدة الشراء)")
    to_unit = models.ForeignKey(UnitOfMeasure, on_delete=models.CASCADE, related_name='convert_to', verbose_name="إلى وحدة (وحدة الصرف/التشغيل)")
    conversion_rate = models.DecimalField("معامل التحويل", max_digits=10, decimal_places=4)

    class Meta:
        verbose_name = "معامل تحويل"
        verbose_name_plural = "9. معاملات تحويل الوحدات"
        unique_together = ('item', 'from_unit', 'to_unit')

    def __str__(self):
        return f"1 {self.from_unit.name} = {self.conversion_rate} {self.to_unit.name}"