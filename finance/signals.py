# from django.db.models.signals import post_save
# from django.dispatch import receiver
# from students.models import Student
# from .models import StudentAccount
# from decimal import Decimal

# @receiver(post_save, sender=Student)
# def create_student_account(sender, instance, created, **kwargs):
#     if created:
#         # استخدام get_or_create يمنع تعطل النظام إذا كان الحساب موجوداً مسبقاً لسبب ما
#         StudentAccount.objects.get_or_create(
#             student=instance,
#             defaults={
#                 'total_fees': Decimal("0.00"),
#                 'discount': Decimal("0.00")
#             }
#         )