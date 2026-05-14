from django.db.models.signals import post_save
from django.dispatch import receiver
from finance.models import Payment
from students.models import BookSale
from .models import GeneralLedger


import uuid

@receiver(post_save, sender=Payment)
def sync_payment_to_treasury(sender, instance, created, **kwargs):
    if created:
        # 1. تحديد رقم الإيصال المرجعي
        if instance.receipt_number:
            receipt_ref = str(instance.receipt_number)
        else:
            # إذا لم يكن هناك رقم، ننشئ رقم فريد لمنع التعارض
            receipt_ref = f"REC-{instance.id}-{uuid.uuid4().hex[:6]}"

        # 2. تحديد الفئة (التأكد من وجود الفئة لتجنب الأخطاء)
        category_name = 'إيراد عام'
        if instance.revenue_category:
            category_name = instance.revenue_category.name

        # 3. التحقق المزدوج لمنع التكرار (نستخدم الـ ID الخاص بالـ Payment كمرجع أساسي إن أمكن)
        # أو نعتمد على رقم الإيصال الفعلي
        if instance.receipt_number:
            exists = GeneralLedger.objects.filter(receipt_number=receipt_ref).exists()
        else:
            # إذا كان إيصالاً بدون رقم مرجعي، نتحقق باستخدام الملاحظات التي تحتوي على ID العملية
            exists = GeneralLedger.objects.filter(notes__contains=f"Payment ID: {instance.id}").exists()

        if not exists:
            GeneralLedger.objects.create(
                student=instance.student,
                category=category_name,
                amount=instance.amount_paid,
                receipt_number=receipt_ref,
                collected_by=instance.collected_by,
                notes=f"سداد مصاريف - {category_name} | Payment ID: {instance.id}"
            )

@receiver(post_save, sender=BookSale)
def sync_booksale_to_treasury(sender, instance, created, **kwargs):
    if created and hasattr(instance, 'amount_paid') and instance.amount_paid > 0:
        receipt_ref = f"BK-{instance.id}"
        
        if not GeneralLedger.objects.filter(receipt_number=receipt_ref).exists():
            collector = getattr(instance, 'collected_by', None)
            if not collector and instance.student.all_payments.exists():
                collector = instance.student.all_payments.last().collected_by

            GeneralLedger.objects.create(
                student=instance.student,
                category='books',
                amount=instance.amount_paid,
                receipt_number=receipt_ref,
                collected_by=collector,
                notes=f"تحصيل قيمة كتاب: {instance.book_item.name if hasattr(instance, 'book_item') else 'غير محدد'}"
            )