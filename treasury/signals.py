from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Sum
from finance.models import Payment  # استيراد من تطبيق المالية
from students.models import BookSale # استيراد من تطبيق الطلاب
from .models import GeneralLedger   # موديل الخزينة المجمعة

# أولاً: مراقبة مدفوعات المصاريف الدراسية
@receiver(post_save, sender=Payment)
def sync_payment_to_treasury(sender, instance, created, **kwargs):
    if created:  # التسجيل فقط عند إنشاء إيصال جديد
        GeneralLedger.objects.create(
            student=instance.student,
            category='fees',
            amount=instance.amount_paid,
            receipt_number=f"PAY-{instance.id}",
            collected_by=instance.collected_by,
            notes=f"سداد مصاريف - {instance.revenue_category.name}"
        )

# ثانياً: مراقبة مبيعات الكتب (إذا تم تحصيل مبلغ)
@receiver(post_save, sender=BookSale)
def sync_booksale_to_treasury(sender, instance, created, **kwargs):
    if created and hasattr(instance, 'amount_paid') and instance.amount_paid > 0:
        GeneralLedger.objects.create(
            student=instance.student,
            category='books',
            amount=instance.amount_paid,
            receipt_number=f"BK-{instance.id}",
            collected_by=instance.student.all_payments.last().collected_by if instance.student.all_payments.exists() else None,
            notes=f"تحصيل قيمة: {instance.book_item.name}"
        )