from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from .models import StudentInstallment, AcademicYear

def get_active_year():
    from .models import AcademicYear
    # 1. البحث عن السنة المحددة كـ "نشطة"
    active_year = AcademicYear.objects.filter(is_active=True).first()
    
    # 2. حماية من الأصفار: إذا لم توجد سنة نشطة، جلب أحدث سنة تم إنشاؤها
    if not active_year:
        active_year = AcademicYear.objects.all().order_by('-name').first()
        
    return active_year

def generate_installments_for_student(student):
    """
    توليد الأقساط المالية للطالب بناءً على الخطة المسكن عليها.
    """
    
    # 1. التأكد من وجود حساب مالي للطالب
    if not hasattr(student, "account") or not student.account:
        print(f"DEBUG: Student {student} has no account.")
        return

    # 2. التأكد من وجود خطة تقسيط مرتبطة بالحساب
    plan = student.account.installment_plan
    if not plan:
        print(f"DEBUG: No installment plan for student {student}.")
        return

    # 3. التحقق من عدد الأقساط
    if plan.number_of_installments <= 0:
        raise ValueError("عدد الأقساط في الخطة لا يمكن أن يكون صفر أو أقل.")

    # 4. تحديد السنة الدراسية
    academic_year = student.academic_year or get_active_year()

    with transaction.atomic():
        # --- إجراء احترازي: حذف أي أقساط معلقة قديمة لتجنب التكرار ---
        StudentInstallment.objects.filter(
            student=student, 
            academic_year=academic_year, 
            status="Pending"
        ).delete()

        # --- حساب المبالغ بدقة Decimal ---
        total_amount = Decimal(str(plan.total_amount))
        interest = Decimal(str(plan.interest_value or 0))

        # حساب الخصم
        discount = Decimal("0.00")
        if hasattr(student, "coupon") and student.coupon:
            if student.coupon.is_valid():
                discount = Decimal(str(student.coupon.discount_value))

        net_total = total_amount - discount
        if net_total < 0:
            net_total = Decimal("0.00")

        total_with_interest = net_total + interest

        # حساب القسط الأساسي مع تقريب الكسور
        base_amount = (total_with_interest / plan.number_of_installments).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        start_date = timezone.now().date()
        total_created = Decimal("0.00")

        # --- حلقة إنشاء الأقساط ---
        for i in range(plan.number_of_installments):
            due_date = start_date + relativedelta(months=i)
            
            # معالجة فرق الكسور في آخر قسط
            if i == plan.number_of_installments - 1:
                installment_value = total_with_interest - total_created
            else:
                installment_value = base_amount

            StudentInstallment.objects.create(
                student=student,
                installment_plan=plan,
                academic_year=academic_year,
                installment_number=i + 1,
                amount_due=installment_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                due_date=due_date,
                late_fee=Decimal("0.00"),
                status="Pending"
            )

            total_created += installment_value
            
        print(f"SUCCESS: Generated {plan.number_of_installments} installments for {student}")