from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Payment, StudentAccount 

from .models import StudentInstallment
from django.db.models import Sum
from decimal import Decimal


@receiver([post_save, post_delete], sender=Payment)
def update_student_account_balance_live(sender, instance, **kwargs):
    """
    حارس المديونية الحية: بمجرد إضافة، تعديل، أو حذف أي إيصال (حتى من الأدمن)
    نقوم بإخطار النظام بإعادة التحديث دون العبث بالـ properties لتجنب الـ No Setter Bug.
    """
    student = instance.student
    year = instance.academic_year
    
    if not student or not year:
        return

    # 1. جلب حساب الطالب المالي لهذه السنة
    st_account = StudentAccount.objects.filter(student=student, academic_year=year).first()
    
    # 2. إذا كان الحساب موجوداً، نقوم بعمل حفظ عادي لتحديث السجلات المرتبطة به إن وجدت
    if st_account:
        # نقوم بالحفظ بشكل آمن تماماً بدون محاولة الكتابة في الـ properties
        st_account.save()

    # 🎯 تم حذف الجزء الخاص بـ student.final_remaining = ... و student.save() تماماً
    # لأن 'final_remaining' عبارة عن @property في موديل الطالب وتحسب نفسها ذاتياً في القوالب والواجهات.


@receiver(post_delete, sender=Payment)
def update_student_account_on_delete(sender, instance, **kwargs):
    """
    بمجرد حذف إيصال دفع، نقوم بإعادة تحديث كافة الحسابات المادية للطالب
    في جميع السنوات الدراسية بترتيبها الصحيح لضمان ترحيل المبالغ وتحديث العدادات بدقة وسرعة.
    """
    if instance.student:
        try:
            # 1. جلب حسابات الطالب مرتبة من الأقدم للأحدث لضمان صحة ترحيل الديون القديمة
            all_accounts = StudentAccount.objects.filter(
                student=instance.student
            ).order_by('academic_year__start_date')
            
            if all_accounts.exists():
                for st_account in all_accounts:
                    # ⚡ نداء دالة الحسابات الداخلية للموديل برمجياً بدون عمل save() كامل يتعب السيرفر
                    if hasattr(st_account, 'recalculate_balances'):
                        st_account.recalculate_balances() 
                    
                    # ⚡ تحديث قاعدة البيانات بضربة واحدة سريعة ومباشرة تمنع الـ Infinite Loops
                    StudentAccount.objects.filter(id=st_account.id).update(
                        previous_debt=st_account.previous_debt,
                        total_fees=st_account.total_fees,
                        discount=st_account.discount,
                        # ضيف هنا أي حقول مادية تانية بتتغير لما الإيصال بيتحذف
                    )
            
        except Exception as e:
            print(f"Error in post_delete signal: {e}")
            
        
        
@receiver(post_delete, sender=Payment)
def update_student_account_on_delete(sender, instance, **kwargs):
    """
    بمجرد حذف إيصال دفع من الأدمن، نقوم بإعادة تحديث كافة الحسابات المادية للطالب
    في جميع السنوات الدراسية بترتيبها الصحيح لضمان ترحيل المبالغ وتحديث العدادات الحالية بدقة.
    """
    if instance.student:
        try:
            # 🎯 الإصلاح: استخدام order_by بدلاً من order_index لترتيب السنوات تصاعدياً من الأقدم للأحدث
            all_accounts = StudentAccount.objects.filter(
                student=instance.student
            ).order_by('academic_year__start_date')
            
            if all_accounts.exists():
                # تحديث كل سنة تتابعياً لكي تسمع الديون المرحّلة في السنوات التالية
                for st_account in all_accounts:
                    st_account.save()
            else:
                # حماية إضافية: إذا لم يعمل الترتيب لأي سبب، نحدث الحسابات المتاحة بشكل مباشر
                for st_account in StudentAccount.objects.filter(student=instance.student):
                    st_account.save()
                    
        except Exception as e:
            # طباعة الخطأ في تيرمينال Docker إذا حدثت أي مشكلة للمعاينة
            print(f"Error in post_delete signal: {e}")