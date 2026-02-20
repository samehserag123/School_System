from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum
from django.db.models.functions import TruncMonth, TruncDay
from django.utils import timezone
from django.contrib import messages
from django.http import HttpResponse
from datetime import timedelta
import json
from .models import Payment, StudentInstallment, MonthlyClosure
from students.models import Student
from .utils import get_active_year
from rest_framework.views import APIView
from rest_framework.response import Response
from reportlab.pdfgen import canvas

from .models import StudentAccount
from .utils import generate_installments_for_account

#def my_view(request):
    #from .models import StudentInstallment

def overdue_report(request):

    from .models import StudentInstallment

    overdue = StudentInstallment.objects.filter(
    due_date__lt=timezone.now().date(),
    status='Late'
)

    return render(request, "finance/overdue_report.html", {
        "installments": overdue
    })

def generate_installments_view(request, account_id):

    account = get_object_or_404(StudentAccount, id=account_id)

    generate_installments_for_account(account)

    return redirect('account_detail', account_id=account.id)

class DashboardSummaryAPI(APIView):
    def get(self, request):
        active_year = get_active_year()

        if not active_year:
            return Response({"error": "No active academic year found."})

        today = timezone.now().date()

        total_students = Student.objects.filter(
            academic_year=active_year
        ).count()

        total_today = Payment.objects.filter(
            academic_year=active_year,
            payment_date=today
        ).aggregate(total=Sum('amount_paid'))['total'] or 0

        total_collected = Payment.objects.filter(
            academic_year=active_year
        ).aggregate(total=Sum('amount_paid'))['total'] or 0

        installments = StudentInstallment.objects.filter(
            academic_year=active_year
        )

        total_remaining = sum(i.remaining_amount() for i in installments)

        overdue_installments = StudentInstallment.objects.filter(
            academic_year=active_year,
            due_date__lt=today
        ).exclude(status='Late').count()
        recent_payments = Payment.objects.filter(
            academic_year=active_year
        ).select_related('installment__student').order_by('-payment_date')[:5]

        recent_list = []
        for payment in recent_payments:
            recent_list.append({
                "student_name": f"{payment.installment.student.first_name} {payment.installment.student.last_name}",
                "amount_paid": payment.amount_paid,
                "date": payment.payment_date.strftime("%Y-%m-%d")
            })

        return Response({
            "total_students": total_students,
            "total_today": total_today,
            "total_collected": total_collected,
            "total_remaining": total_remaining,
            "overdue_installments": overdue_installments,
            "recent_payments": recent_list
        })



# =========================================
# 🔒 Close Month
# =========================================
def close_month(request):
    today = timezone.now().date()
    first_day = today.replace(day=1)

    # منع الإقفال المكرر
    if MonthlyClosure.objects.filter(month=first_day).exists():
        messages.error(request, "تم إقفال هذا الشهر بالفعل")
        return redirect('finance_dashboard')

    # إجمالي التحصيل هذا الشهر
    total_collected = Payment.objects.filter(
        payment_date__year=today.year,
        payment_date__month=today.month
    ).aggregate(total=Sum('amount_paid'))['total'] or 0

    # إجمالي المتأخرات
    installments = StudentInstallment.objects.all()
    total_remaining = sum(i.remaining_amount() for i in installments)


    # حفظ الإقفال
    MonthlyClosure.objects.create(
        month=first_day,
        total_collected=total_collected,
        total_remaining=total_remaining
    )

    messages.success(request, "تم إقفال الشهر بنجاح ✅")
    return redirect('finance_dashboard')


# =========================================
# 📊 Advanced Financial Dashboard
# =========================================
def finance_dashboard(request):
    active_year = get_active_year()

    if not active_year:
        return render(request, "finance/dashboard.html", {
            "error": "No active academic year found."
        })

    today = timezone.now().date()

    # تحصيل اليوم
    total_today = Payment.objects.filter(
        academic_year=active_year,
        payment_date=today
    ).aggregate(total=Sum('amount_paid'))['total'] or 0

    # إجمالي المطلوب
    total_due = StudentInstallment.objects.filter(
        academic_year=active_year
    ).aggregate(total=Sum('amount_due'))['total'] or 0

    # إجمالي المدفوع
    total_paid = Payment.objects.filter(
        academic_year=active_year
    ).aggregate(total=Sum('amount_paid'))['total'] or 0

    total_remaining = total_due - total_paid

    # التحصيل الشهري
    monthly_data = (
        Payment.objects
        .filter(academic_year=active_year)
        .annotate(month=TruncMonth('payment_date'))
        .values('month')
        .annotate(total=Sum('amount_paid'))
        .order_by('month')
    )

    months = []
    monthly_totals = []

    for item in monthly_data:
        months.append(item['month'].strftime('%b %Y'))
        monthly_totals.append(float(item['total']))

    # آخر 7 أيام
    last_7_days = today - timedelta(days=6)

    daily_data = (
        Payment.objects
        .filter(
            academic_year=active_year,
            payment_date__gte=last_7_days
        )
        .annotate(day=TruncDay('payment_date'))
        .values('day')
        .annotate(total=Sum('amount_paid'))
        .order_by('day')
    )

    days = []
    daily_totals = []

    for item in daily_data:
        days.append(item['day'].strftime('%d-%m'))
        daily_totals.append(float(item['total']))

    # آخر المدفوعات
    recent_payments = Payment.objects.filter(
        academic_year=active_year
    ).select_related('installment__student').order_by('-payment_date')[:5]

    context = {
        'active_year': active_year,
        'total_today': total_today,
        'total_remaining': total_remaining,
        'months': json.dumps(months),
        'monthly_totals': json.dumps(monthly_totals),
        'days': json.dumps(days),
        'daily_totals': json.dumps(daily_totals),
        'recent_payments': recent_payments,
    }

    return render(request, 'finance/dashboard.html', context)


# =========================================
# 🧾 Print Receipt PDF
# =========================================
def print_receipt(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="receipt.pdf"'

    p = canvas.Canvas(response)

    p.drawString(100, 800, "Payment Receipt")
    p.drawString(100, 780, f"Student: {payment.installment.student}")
    p.drawString(100, 760, f"Installment No: {payment.installment.installment_number}")
    p.drawString(100, 740, f"Amount Paid: {payment.amount_paid}")
    p.drawString(100, 720, f"Date: {payment.payment_date}")

    p.showPage()
    p.save()

    return response
