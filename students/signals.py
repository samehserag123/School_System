from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import BookSale
from finance.models import Payment, RevenueCategory

@receiver(post_save, sender=BookSale)
def sync_book_sale_to_finance(sender, instance, created, **kwargs):
    # نرحل فقط العمليات التي تحتوي على مبلغ مدفوع
    if instance.paid_amount > 0:
        category_name = "مصروفات كتب دراسية" if instance.item.item_type == 'book' else "مصروفات زي مدرسي"
        category, _ = RevenueCategory.objects.get_or_create(name=category_name)
        
        # إنشاء إيصال في جدول Payment (المصب الأول)
        Payment.objects.update_or_create(
            notes=f"سداد آلي لعملية صرف رقم #{instance.id}",
            defaults={
                'student': instance.student,
                'academic_year': instance.student.academic_year,
                'amount_paid': instance.paid_amount,
                'revenue_category': category,
                'payment_date': instance.sale_date,
                'collected_by': instance.collected_by,
            }
        )