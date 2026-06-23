from django.db import transaction
from django.utils import timezone
from .models import StudentRefund, StudentInstallment, StudentAccount
from students.models import Student

def process_student_withdrawal(student_id, refund_amount, admin_user, reason="سحب ملف نهائي"):
    from students.models import Student
    from finance.models import StudentInstallment, StudentRefund
    from django.db import transaction
    from django.utils import timezone
    
    student = Student.objects.get(id=student_id)
    current_year = student.academic_year

    with transaction.atomic():
        # 1. إنشاء إذن الصرف (الاسترداد)
        if refund_amount > 0:
            StudentRefund.objects.create(
                student=student,
                academic_year=current_year,
                amount=refund_amount,
                reason=reason,
                processed_by=admin_user,
                refund_date=timezone.now().date()
            )

        # 2. 🚀 سحب الأموال المستردة من الأقساط (لكي تنقص إيرادات الداشبورد)
        remaining_to_refund = refund_amount
        if remaining_to_refund > 0:
            paid_insts = list(StudentInstallment.objects.filter(
                student=student, academic_year=current_year, paid_amount__gt=0
            ).order_by('-due_date'))

            insts_to_refund = []
            for inst in paid_insts:
                if remaining_to_refund <= 0: break
                if inst.paid_amount >= remaining_to_refund:
                    inst.paid_amount -= remaining_to_refund
                    remaining_to_refund = 0
                else:
                    remaining_to_refund -= inst.paid_amount
                    inst.paid_amount = 0
                insts_to_refund.append(inst)
            
            if insts_to_refund:
                StudentInstallment.objects.bulk_update(insts_to_refund, ['paid_amount'])

        # 3. 🚀 إسقاط المديونية وتصفير كل المطلوب
        all_insts = list(StudentInstallment.objects.filter(
            student=student, academic_year=current_year
        ))

        insts_to_update = []
        for inst in all_insts:
            inst.amount_due = inst.paid_amount # المطلوب = المدفوع
            inst.late_fee = 0
            inst.status = 'Paid' # إغلاق القسط تماماً
            insts_to_update.append(inst)

        if insts_to_update:
            StudentInstallment.objects.bulk_update(insts_to_update, ['amount_due', 'late_fee', 'status'])

        # 4. إيقاف تفعيل الطالب
        student.is_active = False
        student.save(update_fields=['is_active'])

        return True