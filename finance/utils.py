from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from .models import StudentInstallment, AcademicYear


def get_active_year():
    return AcademicYear.objects.filter(is_active=True).first()


def generate_installments_for_student(student):

    plan = student.installment_plan
    if not plan:
        return

    if plan.number_of_installments <= 0:
        raise ValueError("عدد الأقساط لا يمكن أن يكون صفر")

    if StudentInstallment.objects.filter(student=student).exists():
        return

    academic_year = student.academic_year

    with transaction.atomic():

        total_amount = Decimal(plan.total_amount)
        interest = Decimal(plan.interest_value or 0)

        discount = Decimal("0.00")
        if hasattr(student, "coupon") and student.coupon:
            if student.coupon.is_valid():
                discount = Decimal(student.coupon.discount_value)

        net_total = total_amount - discount
        if net_total < 0:
            net_total = Decimal("0.00")

        # إضافة الفائدة مرة واحدة فقط
        total_with_interest = net_total + interest

        base_amount = (total_with_interest / plan.number_of_installments).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        start_date = timezone.now().date()

        total_created = Decimal("0.00")

        for i in range(plan.number_of_installments):

            due_date = start_date + relativedelta(months=i)

            installment_value = base_amount

            # ضبط آخر قسط لتفادي فرق الكسور
            if i == plan.number_of_installments - 1:
                installment_value = (
                    total_with_interest - total_created
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            StudentInstallment.objects.create(
                student=student,
                installment_plan=plan,
                academic_year=academic_year,
                installment_number=i + 1,
                amount_due=installment_value,
                due_date=due_date,
                late_fee=Decimal("0.00"),
                status="Pending"
            )

            total_created += installment_value