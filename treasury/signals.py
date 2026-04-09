from django.db.models.signals import post_save
from django.dispatch import receiver
from finance.models import Payment
from students.models import BookSale
from .models import GeneralLedger

# أولاً: مزامنة المدفوعات الدراسية (تأكد أنها لا تتكرر)
@receiver(post_save, sender=Payment)
def sync_payment_to_treasury(sender, instance, created, **kwargs):
    if created:
        # 🛡️ توحيد المسمى ليكون REC ليطابق تسجيل السيستم
        receipt_ref = f"REC-{instance.id}" 
        
        # البحث هل تم تسجيل هذا الإيصال مسبقاً؟
        if not GeneralLedger.objects.filter(receipt_number=receipt_ref).exists():
            GeneralLedger.objects.create(
                student=instance.student,
                category='fees',
                amount=instance.amount_paid,
                receipt_number=receipt_ref,
                collected_by=instance.collected_by,
                notes=f"سداد مصاريف - {instance.revenue_category.name}"
            )
            
# ثانياً: مزامنة مبيعات الكتب (دالة واحدة فقط ومنظمة)
@receiver(post_save, sender=BookSale)
def sync_booksale_to_treasury(sender, instance, created, **kwargs):
    # التسجيل فقط عند الإنشاء وإذا كان هناك مبلغ مدفوع فعلاً
    if created and hasattr(instance, 'amount_paid') and instance.amount_paid > 0:
        receipt_ref = f"BK-{instance.id}"
        
        # البحث هل تم تسجيل هذا الإيصال مسبقاً؟ (هذا هو الأمان ضد الزيادة الوهمية)
        if not GeneralLedger.objects.filter(receipt_number=receipt_ref).exists():
            # محاولة تحديد الموظف: إما من عملية البيع نفسها أو من المستخدم الحالي
            # ملاحظة: يفضل أن يكون موديل BookSale يحتوي على حقل collected_by مباشرة
            collector = None
            if hasattr(instance, 'collected_by'):
                collector = instance.collected_by
            elif instance.student.all_payments.exists():
                collector = instance.student.all_payments.last().collected_by

            GeneralLedger.objects.create(
                student=instance.student,
                category='books',
                amount=instance.amount_paid,
                receipt_number=receipt_ref,
                collected_by=collector,
                notes=f"تحصيل قيمة كتاب: {instance.book_item.name}"
            )