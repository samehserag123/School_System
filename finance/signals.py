# finance/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Payment
# التعديل هنا: الاستيراد من تطبيق treasury
from treasury.models import GeneralLedger 

@receiver(post_save, sender=Payment)
def sync_payment_to_general_ledger(sender, instance, created, **kwargs):
    if created:
        # تحديد التصنيف بناءً على اسم الفئة في تطبيق المالية
        cat_name = instance.revenue_category.name if instance.revenue_category else ""
        
        # الربط مع ENTRY_TYPES الموجودة في موديل treasury
        category = 'fees'
        if any(word in cat_name for word in ["كتب", "زي", "باقة", "مخزن"]):
            category = 'books'
        elif "باص" in cat_name or "اتوبيس" in cat_name:
            category = 'bus'
        
        # إنشاء السجل في الخزينة المجمعة (تطبيق treasury)
        GeneralLedger.objects.create(
            student=instance.student,
            category=category,
            amount=instance.amount_paid,
            receipt_number=f"REC-{instance.id}",
            collected_by=instance.collected_by,
            notes=instance.notes or f"سداد {cat_name}"
        )