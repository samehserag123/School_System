from django.contrib.auth.views import LoginView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.utils.safestring import mark_safe
from django.contrib import messages
from django.db import transaction, connection, IntegrityError
from django.db.models import Sum, Count, Q, F, DecimalField, Max, Value, OuterRef, Subquery, Exists
from django.core.cache import cache
from django.urls import reverse

from django.db.models.functions import TruncMonth, Coalesce
from .models import ReceiptBook # تأكد من وجود هذا الاستيراد في أعلى الملف
import pytz
# 3. Time & Math
from django.utils import timezone
from django.contrib.auth.decorators import user_passes_test
from decimal import Decimal,InvalidOperation
import json

# 4. Authentication & Security
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required

# 5. REST Framework
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from reportlab.pdfgen import canvas
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

from .models import (
    AcademicYear,
    DailyClosure,
    DeliveryRecord,
    InstallmentPlan,
    InventoryMaster,
    MonthlyClosure,
    Payment,
    Expense,
    RevenueCategory,
    StudentAccount,
    StudentInstallment,
)
from students.models import Student, Grade 
from .utils import get_active_year, generate_installments_for_student
from django.db import models
# تأكد من استيراد الموديلات الخاصة بك
from django.contrib import messages
# دالة للتحقق من صلاحية المدير
from django.db import IntegrityError
from itertools import chain
from treasury.models import GeneralLedger # استيراد الموديل الموحد
# finance/views.py
# --- اترك هذا فقط في منطقة الوقت ---
from django.utils import timezone
from datetime import datetime, timedelta 

from .models import Coupon 

from django.db import transaction
from .models import StudentAccount


# ✅ 1. كلاس تسجيل الدخول (يجب أن يكون هنا)
class MyLoginView(LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True       

# ✅ 2. دالة التحقق من المدير (تأكد من شرط authenticated)
def is_manager(user):
    # يجب التأكد أن المستخدم سجل دخوله أولاً لتجنب الأخطاء
    return user.is_authenticated and (user.is_superuser or user.is_staff)


@user_passes_test(lambda u: u.is_superuser)
def close_month(request):
    # 1. الحسابات الزمنية
    today = timezone.now().date()
    first_day_this_month = today.replace(day=1)
    last_month = (first_day_this_month - timedelta(days=1)).replace(day=1)

    # تحديد حدود النطاق الزمني للشهر المراد إغلاقه لضمان أقصى سرعة في قاعدة البيانات
    start_date = last_month                  # بداية الشهر المغلق (مثال: 2026-05-01)
    end_date = first_day_this_month          # بداية الشهر الحالي (مثال: 2026-06-01) - نستخدم أصغر من (<)

    # 2. منع التكرار
    if MonthlyClosure.objects.filter(month=last_month).exists():
        messages.info(request, "هذا الشهر تم إغلاقه بالفعل.")
        return redirect('finance_dashboard')

    # ==============================================================
    # 3. التحقق من الحركات المعلقة (🟢 تم تحسين الاستعلامات باستخدام النطاق الزمني)
    # ==============================================================
    pending_revenues_count = Payment.objects.filter(
        payment_date__gte=start_date,
        payment_date__lt=end_date,
        is_closed=False  
    ).count()

    pending_expenses_count = Expense.objects.filter(
        expense_date__gte=start_date,
        expense_date__lt=end_date,
        is_closed=False  
    ).count()

    has_pending = (pending_revenues_count > 0) or (pending_expenses_count > 0)

    if request.method == "POST":
        if has_pending:
            messages.error(request, f"لا يمكن إغلاق الشهر! يوجد {pending_revenues_count} إيراد معلق و {pending_expenses_count} مصروف معلق لم يتم تقفيلهم في الجرد.")
            return redirect('close_month') 

        # 4. حساب الإيرادات (🟢 الحركات المقفلة فقط ضمن النطاق الزمني المفهرس)
        revenues = Payment.objects.filter(
            payment_date__gte=start_date,
            payment_date__lt=end_date,
            is_closed=True
        ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')

        # 5. حساب المصروفات (🟢 المصروفات المقفلة فقط ضمن النطاق الزمني المفهرس)
        expenses = Expense.objects.filter(
            expense_date__gte=start_date,
            expense_date__lt=end_date,
            is_closed=True
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # 6. جلب الرصيد السابق
        previous_closure = MonthlyClosure.objects.order_by('-month').first()
        opening_bal = previous_closure.closing_balance if previous_closure else Decimal('0.00')

        # 7. الحفظ والترحيل المالي المعتمد
        MonthlyClosure.objects.create(
            month=last_month,
            opening_balance=opening_bal,
            total_revenues=revenues,
            total_expenses=expenses,
            net_balance=Decimal(revenues) - Decimal(expenses),
            closing_balance=Decimal(opening_bal) + (Decimal(revenues) - Decimal(expenses)),
            status='closed',
            closed_by=request.user
        )
        
        messages.success(request, f"تم إغلاق شهر {last_month.strftime('%B %Y')} بنجاح.")
        return redirect('finance_dashboard')

    # ==========================================
    # جزء العرض البرمجي عند فتح الصفحة (GET)
    # ==========================================
    context = {
        'suggested_month': last_month,
        'has_pending': has_pending,
        'pending_revenues_count': pending_revenues_count,
        'pending_expenses_count': pending_expenses_count,
    }
    
    return render(request, 'finance/close_month.html', context)

# @user_passes_test(lambda u: u.is_superuser)
# def close_month(request):
#     # 1. الحسابات الزمنية
#     today = timezone.now().date()
#     first_day_this_month = today.replace(day=1)
#     last_month = (first_day_this_month - timedelta(days=1)).replace(day=1)

#     # 2. منع التكرار
#     if MonthlyClosure.objects.filter(month=last_month).exists():
#         messages.info(request, "هذا الشهر تم إغلاقه بالفعل.")
#         return redirect('finance_dashboard')

#     # ==========================================
#     # 3. التحقق من الحركات المعلقة (التي لم تدخل جرد يومي)
#     # ==========================================
#     # الاعتماد على حقل is_closed=False لمعرفة الحركات المعلقة
#     pending_revenues_count = Payment.objects.filter(
#         payment_date__year=last_month.year,
#         payment_date__month=last_month.month,
#         is_closed=False  # حركة غير مقفلة
#     ).count()

#     pending_expenses_count = Expense.objects.filter(
#         expense_date__year=last_month.year, 
#         expense_date__month=last_month.month,
#         is_closed=False  # مصروف غير مقفل
#     ).count()

#     has_pending = (pending_revenues_count > 0) or (pending_expenses_count > 0)

#     if request.method == "POST":
#         # منع الحفظ إذا كان هناك حركات معلقة (أمان إضافي للباك-إند)
#         if has_pending:
#             messages.error(request, f"لا يمكن إغلاق الشهر! يوجد {pending_revenues_count} إيراد معلق و {pending_expenses_count} مصروف معلق لم يتم تقفيلهم في الجرد.")
#             return redirect('close_month') # تأكد من أن اسم الرابط صحيح في urls.py

#         # 4. حساب الإيرادات (للحركات المقفلة فقط is_closed=True)
#         revenues = Payment.objects.filter(
#             payment_date__year=last_month.year,
#             payment_date__month=last_month.month,
#             is_closed=True
#         ).aggregate(total=Sum('amount_paid'))['total'] or 0

#         # 5. حساب المصروفات (للحركات المقفلة فقط is_closed=True)
#         expenses = Expense.objects.filter(
#             expense_date__year=last_month.year, 
#             expense_date__month=last_month.month,
#             is_closed=True
#         ).aggregate(total=Sum('amount'))['total'] or 0

#         # 6. جلب الرصيد السابق
#         previous_closure = MonthlyClosure.objects.order_by('-month').first()
#         opening_bal = previous_closure.closing_balance if previous_closure else 0

#         # ... (باقي الكود داخل شرط POST) ...
        
#         # 7. الحفظ
#         MonthlyClosure.objects.create(
#             month=last_month,
#             opening_balance=opening_bal,
#             total_revenues=revenues,
#             total_expenses=expenses,
#             net_balance=revenues - expenses,
#             closing_balance=opening_bal + (revenues - expenses),
#             status='closed',
#             closed_by=request.user
#         )
        
#         # رسالة النجاح والتحويل تكون هنا فقط (داخل الـ POST)
#         messages.success(request, f"تم إغلاق شهر {last_month.strftime('%B %Y')} بنجاح.")
#         return redirect('finance_dashboard')

#     # ==========================================
#     # هذا الجزء خارج الـ POST (يعمل عند فتح الصفحة فقط)
#     # ==========================================
#     context = {
#         'suggested_month': last_month,
#         'has_pending': has_pending,
#         'pending_revenues_count': pending_revenues_count,
#         'pending_expenses_count': pending_expenses_count,
#     }
    
#     # ❌ احذف السطرين اللذين وضعتهما هنا:
#     # messages.success(request, f"تم إغلاق شهر {last_month.strftime('%B %Y')} بنجاح.")
#     # return redirect('finance_dashboard')

#     # ✅ واستبدلهما بهذا السطر لكي تفتح الصفحة:
#     return render(request, 'finance/close_month.html', context)

@staff_member_required
def finance_analytics_view(request):
    # 1. معالجة التواريخ والفلاتر
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    preset = request.GET.get('preset', 'this_month')
    
    today = timezone.now().date()
    if preset == 'today':
        start_date = end_date = today
    elif preset == 'this_month':
        start_date = today.replace(day=1)
        end_date = today
    elif preset == 'this_year':
        start_date = today.replace(month=1, day=1)
        end_date = today
    
    # تحويل النصوص إلى تواريخ حقيقية
    start_dt = timezone.make_aware(datetime.combine(datetime.strptime(str(start_date), '%Y-%m-%d'), datetime.min.time())) if start_date else today.replace(day=1)
    end_dt = timezone.make_aware(datetime.combine(datetime.strptime(str(end_date), '%Y-%m-%d'), datetime.max.time())) if end_date else timezone.now()

    # 2. حساب رصيد أول المدة (من آخر إغلاق شهري قبل تاريخ البداية)
    last_closure = MonthlyClosure.objects.filter(month__lt=start_dt.date()).order_by('-month').first()
    opening_balance = last_closure.closing_balance if last_closure else Decimal('0.00')

    # 3. جلب البيانات المالية للفترة المختارة
    ledger_qs = GeneralLedger.objects.filter(date__range=[start_dt, end_dt])
    expense_qs = Expense.objects.filter(expense_date__range=[start_dt, end_dt])

    total_revenues = ledger_qs.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    total_expenses = expense_qs.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    net_period = total_revenues - total_expenses
    
    # الإجمالي الفعلي (أول المدة + صافي الفترة)
    final_balance = opening_balance + net_period

    # 4. تحليل الإيرادات والمصروفات حسب الفئة للرسم البياني والجداول
    revenue_by_cat = ledger_qs.values('category').annotate(total=Sum('amount')).order_by('-total')
    
    # 👇 تمت إضافة تجميع المصروفات هنا 👇
    expense_by_cat = expense_qs.values('expense_type').annotate(total=Sum('amount')).order_by('-total')
    
    context = {
        'start_date': start_dt.date(),
        'end_date': end_dt.date(),
        'opening_balance': opening_balance,
        'total_revenues': total_revenues,
        'total_expenses': total_expenses,
        'net_period': net_period,
        'final_balance': final_balance,
        'revenue_by_cat': revenue_by_cat,
        'expense_by_cat': expense_by_cat, # 👇 وتم تمريرها هنا للـ HTML 👇
        'preset': preset,
    }
    return render(request, 'finance/analytics.html', context)



from datetime import timedelta

@login_required
def my_treasury_view(request):
    from treasury.models import GeneralLedger
    from finance.models import Expense, StudentRefund # 🟢 إضافة استيراد المرتجعات

    # 1. 🟢 تحديد بداية ونهاية اليوم محلياً لإنقاذ قاعدة البيانات من تحويل التوقيت
    now = timezone.localtime()  # جلب الوقت الحالي (بتوقيت القاهرة)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    # 2. 🟢 بناء الاستعلامات باستخدام السحر الجديد (__gte و __lt) بدلاً من __date
    # هذا سيجعل الاستعلام الأحمر يختفي تماماً ويهبط من 1170ms إلى 2ms
    
    # --- استعلام الإيرادات ---
    revenues_query = GeneralLedger.objects.filter(
        collected_by=request.user,
        is_closed=False,
        is_discount=False,
        date__gte=start_of_day,  # أكبر من أو يساوي بداية اليوم
        date__lt=end_of_day      # أصغر من بداية الغد
    )
    
    # --- استعلام المصروفات ---
    expenses_query = Expense.objects.filter(
        spent_by=request.user,
        is_closed=False,
        expense_date__gte=start_of_day,
        expense_date__lt=end_of_day
    )

    # 🟢 --- استعلام المرتجعات (سحب الملفات) ---
    refunds_query = StudentRefund.objects.filter(
        processed_by=request.user,
        is_closed=False,
        refund_date__gte=start_of_day,
        refund_date__lt=end_of_day
    )

    # 3. حساب الإجماليات بسرعة خاطفة
    total_revenue_gross = revenues_query.aggregate(total=Sum('amount'))['total'] or 0
    total_expense = expenses_query.aggregate(total=Sum('amount'))['total'] or 0
    total_refunds = refunds_query.aggregate(total=Sum('amount'))['total'] or 0 # 🟢 تجميع المرتجعات

    # 🚀 التعديل السحري هنا: خصم المرتجعات من إجمالي الإيرادات (المربع الأخضر)
    total_revenue = total_revenue_gross - total_refunds

    # 🟢 تعديل معادلة الصافي (المربع الأزرق): الإيرادات الصافية ناقص المصروفات
    net_total = total_revenue - total_expense

    # 4. 🟢 تقليص الاستهلاك (CPU): جلب أحدث 50 حركة فقط للجداول
    # مع استخدام select_related لربط بيانات الطالب ومنع الـ N+1 (الاستعلام الأزرق)
    recent_revenues = revenues_query.select_related('student').defer(
        'student__image', 'student__address', 'student__birth_place', 'student__mother_name', 'student__father_job'
    ).order_by('-date')[:50]

    recent_expenses = expenses_query.order_by('-expense_date')[:50]

    context = {
        'total_revenue': total_revenue, # 👈 الآن هذا المتغير يحمل الرقم الصافي (2003000)
        'total_expense': total_expense,
        'total_refunds': total_refunds, 
        'net_total': net_total,
        'recent_revenues': recent_revenues,
        'recent_expenses': recent_expenses,
    }
    return render(request, 'finance/my_treasury.html', context)

# @login_required
# def my_treasury_view(request):
#     # 1. 🟢 تحديد بداية ونهاية اليوم محلياً لإنقاذ قاعدة البيانات من تحويل التوقيت
#     now = timezone.localtime()  # جلب الوقت الحالي (بتوقيت القاهرة)
#     start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
#     end_of_day = start_of_day + timedelta(days=1)

#     # 2. 🟢 بناء الاستعلامات باستخدام السحر الجديد (__gte و __lt) بدلاً من __date
#     # هذا سيجعل الاستعلام الأحمر يختفي تماماً ويهبط من 1170ms إلى 2ms
    
#     # --- استعلام الإيرادات ---
#     revenues_query = GeneralLedger.objects.filter(
#         collected_by=request.user,
#         is_closed=False,
#         is_discount=False,
#         date__gte=start_of_day,  # أكبر من أو يساوي بداية اليوم
#         date__lt=end_of_day      # أصغر من بداية الغد
#     )
    
#     # --- استعلام المصروفات ---
#     expenses_query = Expense.objects.filter(
#         spent_by=request.user,
#         is_closed=False,
#         expense_date__gte=start_of_day,
#         expense_date__lt=end_of_day
#     )

#     # 3. حساب الإجماليات بسرعة خاطفة
#     total_revenue = revenues_query.aggregate(total=Sum('amount'))['total'] or 0
#     total_expense = expenses_query.aggregate(total=Sum('amount'))['total'] or 0
#     net_total = total_revenue - total_expense

#     # 4. 🟢 تقليص الاستهلاك (CPU): جلب أحدث 50 حركة فقط للجداول
#     # مع استخدام select_related لربط بيانات الطالب ومنع الـ N+1 (الاستعلام الأزرق)
#     recent_revenues = revenues_query.select_related('student').defer(
#         'student__image', 'student__address', 'student__birth_place', 'student__mother_name', 'student__father_job'
#     ).order_by('-date')[:50]

#     recent_expenses = expenses_query.order_by('-expense_date')[:50]

#     context = {
#         'total_revenue': total_revenue,
#         'total_expense': total_expense,
#         'net_total': net_total,
#         'recent_revenues': recent_revenues,
#         'recent_expenses': recent_expenses,
#     }
#     return render(request, 'finance/my_treasury.html', context)


@staff_member_required
def daily_closures_archive(request):
    # جلب كافة عمليات الإغلاق مرتبة من الأحدث للأقدم
    closures = DailyClosure.objects.all().order_by('-closure_date')
    return render(request, 'finance/closures_archive.html', {'closures': closures})


# @staff_member_required
# @transaction.atomic
# def close_daily_accounts_view(request):
#     """
#     الدالة النهائية لإغلاق الخزينة
#     """
#     if request.method == "POST":
#         now_time = timezone.localtime(timezone.now())
        
#         open_payments = Payment.objects.filter(is_closed=False)
#         open_expenses = Expense.objects.filter(is_closed=False)
        
#         # [1] توسيع كلمات الاستبعاد لتشمل احتمالات الأخطاء الإملائية الشائعة
#         open_ledger = GeneralLedger.objects.filter(is_closed=False).exclude(
#             Q(category__icontains='fees') | 
#             Q(category__icontains='مصروف') |
#             Q(category__icontains='دراس') |  # تلتقط "دراسي" و "دراسية"
#             Q(category__icontains='تحصيل') |
#             Q(category__icontains='كورس') |
#             Q(category__icontains='طالب') |  # إضافة كلمة طالب
#             Q(category__icontains='قسط')
#         )

#         # [2] حساب الإجماليات
#         total_p = open_payments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
#         total_l = open_ledger.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
#         total_e = open_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        
#         theoretical_total = (total_p + total_l) - total_e

#         # 🚨 [تتبع الأخطاء] 🚨
#         # هذه الأسطر ستطبع لك في شاشة الـ Terminal (CMD) الأرقام بالتفصيل
#         # لتعرف بالضبط أي جدول يحتوي على الرقم الزائد
#         print("\n" + "="*30)
#         print("📊 تفاصيل إغلاق الخزينة للتحقق:")
#         print(f"1. إجمالي مدفوعات الطلاب (Payment): {total_p}")
#         print(f"2. إيرادات أخرى متفرقة (Ledger): {total_l}")
#         print(f"3. المصروفات النقدية (Expense): {total_e}")
#         print(f"-> الرصيد الدفتري المحسوب: {theoretical_total}")
#         print("="*30 + "\n")

#         try:
#             actual_input = request.POST.get('total_actual_hidden', '0')
#             actual_total = Decimal(actual_input) if actual_input else Decimal('0.00')
#         except (ValueError, TypeError, Decimal.InvalidOperation):
#             actual_total = Decimal('0.00')
            
#         closure = DailyClosure.objects.create(
#             closed_by=request.user,
#             total_cash=theoretical_total,
#             actual_cash=actual_total,
#             closure_id=f"CL-{now_time.strftime('%Y%m%d%H%M%S')}",
#             closure_date=now_time 
#         )
        
#         open_payments.update(is_closed=True, closure=closure)
#         open_expenses.update(is_closed=True, closure=closure)
#         GeneralLedger.objects.filter(is_closed=False).update(is_closed=True, closure=closure)

#         closure.total_cash = theoretical_total
#         closure.variance = actual_total - theoretical_total
#         closure.save()

#         # تم إزالة كافة الرسائل هنا، العودة ستكون صامتة
#         return redirect('daily_cashier_summary')

#     return redirect('daily_cashier_summary')

@staff_member_required
def closure_detail(request, closure_id):
    """عرض تفاصيل الجرد وفصل الجداول للتوضيح"""
    closure = get_object_or_404(DailyClosure, closure_id=closure_id)
    
    related_payments = closure.payments.all() 
    related_ledger = GeneralLedger.objects.filter(closure=closure)
    related_expenses = closure.expenses.all()

    return render(request, 'finance/closure_detail.html', {
        'closure': closure,
        'payments': related_payments,
        'ledger_entries': related_ledger,
        'expenses': related_expenses,
    })    
# استبدل دالة add_expense_view الحالية في ملف views.py بهذا الكود



@login_required
def add_expense_view(request):
    from finance.models import Expense, ExpenseItem
    from decimal import Decimal
    from django.shortcuts import render, redirect
    from django.contrib import messages

    # 1. استقبال مسار العودة (next)
    next_url = request.GET.get('next') or request.POST.get('next')

    if request.method == "POST":
        # استقبال الحقول الجديدة من الفورم
        expense_item_id = request.POST.get('expense_item') # البند المختار من القائمة
        title = request.POST.get('title')                 # البيان المكتوب يدوياً
        invoice_number = request.POST.get('invoice_number') # رقم الفاتورة
        amount = request.POST.get('amount')
        notes = request.POST.get('notes', '')
        expense_type = request.POST.get('expense_type', 'petty') 
        
        # التأكد من وجود (بيان أو بند مختار) مع وجود المبلغ
        if (title or expense_item_id) and amount:
            try:
                # جلب كائن البند المختار إن وجد
                selected_item = None
                if expense_item_id:
                    selected_item = ExpenseItem.objects.filter(id=expense_item_id).first()

                # إنشاء سجل المصروف بالحقول الجديدة
                Expense.objects.create(
                    expense_item=selected_item,
                    title=title,
                    invoice_number=invoice_number,
                    amount=Decimal(amount),
                    spent_by=request.user,
                    notes=notes,
                    expense_type=expense_type
                )
                messages.success(request, f"تم تسجيل المصروف بقيمة {amount} ج.م بنجاح.")
                
                # التوجيه بناءً على مسار العودة
                if next_url:
                    return redirect(next_url)
                return redirect('daily_cashier_summary') 
                    
            except Exception as e:
                messages.error(request, f"حدث خطأ أثناء الحفظ: {str(e)}")
        else:
            messages.warning(request, "يرجى تحديد بند الصرف وقيمة المبلغ.")
    
    # === في حالة الـ GET ===
    exp_type = request.GET.get('type', 'petty')
    
    # 2. جلب كافة بنود المصروفات النشطة لعرضها في القائمة المنسدلة (Dropdown)
    active_items = ExpenseItem.objects.filter(is_active=True)
    
    context = {
        'next_url': next_url,
        'expense_items': active_items  # تمرير القائمة للقالب
    }
    
    # تحديد القالب المناسب بناءً على النوع
    template_name = 'finance/add_expense_genral.html' if exp_type == 'general' else 'finance/add_expense.html'
    
    return render(request, template_name, context)    
    
def student_has_old_debt(student):
    return student.previous_debt > 0

@user_passes_test(is_manager, login_url='/login/')
def pay_old_debt(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    
    if request.method == 'POST':
        try:
            # الحصول على المبلغ من النموذج
            amount_str = request.POST.get('amount', '0')
            amount = Decimal(amount_str)
            
            # التحقق من أن المبلغ لا يتجاوز المديونية المتبقية
            if amount > 0 and amount <= student.previous_debt:
                # خصم المبلغ من المديونية القديمة المرحلة
                student.previous_debt -= amount
                student.save()
                
                messages.success(request, f"تم سداد مبلغ {amount} ج.م بنجاح من المديونية القديمة.")
            elif amount > student.previous_debt:
                messages.error(request, f"خطأ: المبلغ المدخل أكبر من المديونية المتبقية ({student.previous_debt} ج.م).")
            else:
                messages.error(request, "يجب إدخال مبلغ أكبر من صفر.")
                
        except (InvalidOperation, ValueError, TypeError):
            messages.error(request, "قيمة المبلغ غير صحيحة، يرجى إدخال أرقام فقط.")
            
        return redirect('student_statement_print', student_id=student.id)
    
    # في حالة GET: عرض صفحة السداد
    return render(request, 'finance/pay_debt.html', {'student': student})


from django.contrib.auth.decorators import login_required
@login_required
def student_statement_print(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    
    # 1. تحديد السنة الدراسية الحالية النشطة في النظام
    current_year = AcademicYear.objects.filter(is_active=True).first()
    
    # 2. حساب المديونية القديمة من السنوات السابقة فقط
    previous_accounts = StudentAccount.objects.filter(student=student).exclude(academic_year=current_year)
    
    # التعديل هنا: نقوم بتجميع الحقول الأساسية المتوفرة في قاعدة البيانات
    prev_totals = previous_accounts.aggregate(
        total_fees_sum=Sum('total_fees'),
        discount_sum=Sum('discount')
    )
    total_previous_fees = prev_totals['total_fees_sum'] or Decimal('0.00')
    total_previous_discount = prev_totals['discount_sum'] or Decimal('0.00')
    
    # الصافي للسنوات السابقة = إجمالي الرسوم القديمة - الخصومات القديمة
    net_previous_fees = total_previous_fees - total_previous_discount
    
    # مجموع ما تم دفعه فعلياً في السنوات السابقة
    total_previous_paid = Payment.objects.filter(
        student=student, 
        is_cancelled=False
    ).exclude(academic_year=current_year).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    
    # صافي المديونية القديمة المتبقية والمرحّلة
    previous_debt = max(Decimal('0.00'), net_previous_fees - total_previous_paid)

    # 3. مستحقات ومطلوبات العام الحالي فقط
    current_account = StudentAccount.objects.filter(student=student, academic_year=current_year).first()
    if current_account:
        # التعديل هنا: نحسب الصافي برمجياً من الحقول المتاحة للحساب الحالي
        current_required = current_account.total_fees - current_account.discount
    else:
        current_required = Decimal('0.00')
    
    # غرامات التأخير للعام الحالي (يمكنك تركها 0 أو ربطها بالمنطق الخاص بك)
    late_fees = Decimal('0.00') 

    # 4. جدول الحركات: جلب مدفوعات العام الحالي فقط غير الملغاة لتعرض في الجدول
    all_history = Payment.objects.filter(
        student=student, 
        academic_year=current_year, 
        is_cancelled=False
    ).order_by('payment_date')
    
    # إجمالي المدفوع للعام الحالي فقط
    current_paid = all_history.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')

    # 5. الحساب النهائي لإجمالي المتبقي المستحق المطلوب من الطالب
    # (القديم + مطلوب الحالي + الغرامات) - مدفوع الحالي
    remaining_balance = (previous_debt + current_required + late_fees) - current_paid

    # 6. كشوف الأقساط للعام الحالي فقط
    installments = StudentInstallment.objects.filter(
        student=student, 
        academic_year=current_year
    ).order_by('due_date')
    
    total_due_installments = installments.aggregate(total=Sum('amount_due'))['total'] or Decimal('0.00')
    total_paid_installments = installments.aggregate(total=Sum('paid_amount'))['total'] or Decimal('0.00')
    remaining_installments = total_due_installments - total_paid_installments

    context = {
        'student': student,
        'all_history': all_history,              # يعرض إيصالات العام الحالي فقط بالجدول
        'installments': installments,
        'previous_debt': previous_debt,          # مديونية سنوات سابقة
        'current_required': current_required,    # أصل مصروفات العام الحالي
        'late_fees': late_fees,                  # غرامات العام الحالي
        'current_paid': current_paid,            # إجمالي المسدد (العام الحالي)
        'total_paid': current_paid,              # لضمان التوافق الكامل مع متغيرات الـ template
        'remaining_balance': remaining_balance,  # إجمالي المتبقي المستحق النهائي
        'total_due_installments': total_due_installments,
        'total_paid_installments': total_paid_installments,
        'remaining_installments': remaining_installments,
    }
    
    return render(request, 'finance/student_statement_print.html', context)


@login_required
def print_debts_report_view(request):
    """
    النسخة المستقرة والنهائية لتقرير المديونيات الجاهز للطباعة الفورية.
    تعتمد على عزل برمي كامل ومطلق للطلاب غير المسكنين ماليًا.
    """
    filter_type = request.GET.get('filter', 'all')
    year_id = request.GET.get('academic_year')
    grade_id = request.GET.get('grade')
    search_query = request.GET.get('q')

    if not year_id:
        active_year = AcademicYear.objects.filter(is_active=True).first()
        year_id = active_year.id if active_year else None
    else:
        active_year = AcademicYear.objects.filter(id=year_id).first()

    # استعلام الطلاب النشطين
    students_qs = Student.objects.filter(is_active=True).select_related('grade', 'academic_year')

    if year_id:
        students_qs = students_qs.filter(academic_year_id=year_id)
    if grade_id:
        students_qs = students_qs.filter(grade_id=grade_id)
    if search_query:
        students_qs = students_qs.filter(
            Q(first_name__icontains=search_query) | Q(last_name__icontains=search_query)
        )

    # 🛑 جدار الحماية النهائي: إذا كان الفلتر للمسددين أو المدينين، نستبعد تماماً أي طالب ليس لديه سجل مالي حقيقي
    if filter_type in ['cleared', 'delayed']:
        assigned_student_ids = list(StudentAccount.objects.filter(academic_year_id=year_id).values_list('student_id', flat=True))
        students_qs = students_qs.filter(id__in=assigned_student_ids)

    # حساب المجاميع المالية داخل قاعدة البيانات دفعة واحدة لسرعة الأداء
    account_subquery = StudentAccount.objects.filter(
        student=OuterRef('pk'),
        academic_year_id=year_id
    ).values('student').annotate(
        required=Coalesce(Sum(F('total_fees') - F('discount')), Value(0, output_field=DecimalField()))
    ).values('required')

    payments_subquery = Payment.objects.filter(
        student=OuterRef('pk'),
        academic_year_id=year_id,
        is_cancelled=False
    ).values('student').annotate(
        paid=Coalesce(Sum('amount_paid'), Value(0, output_field=DecimalField()))
    ).values('paid')

    students_qs = students_qs.annotate(
        current_required=Coalesce(Subquery(account_subquery), Value(0, output_field=DecimalField())),
        total_paid=Coalesce(Subquery(payments_subquery), Value(0, output_field=DecimalField())),
        prev_debt=Coalesce(F('previous_debt'), Value(0, output_field=DecimalField()))
    )

    report_data = []
    total_report_debts = Decimal('0.00')

    for student in students_qs:
        remaining_balance = (student.prev_debt + student.current_required) - student.total_paid
        if remaining_balance < 0:
            remaining_balance = Decimal('0.00')

        # الفلترة الدقيقة حسب المبالغ المالية الفعلية للطلاب المسكنين
        if filter_type == 'delayed' and remaining_balance <= 0:
            continue
        elif filter_type == 'cleared' and remaining_balance > 0:
            continue

        grade_name = student.grade.name if student.grade else 'غير محدد'
        if hasattr(student, 'specialty') and student.specialty:
            specialty = student.specialty
        elif "-" in grade_name:
            specialty = grade_name.split("-")[-1].strip()
        else:
            specialty = "عام"

        report_data.append({
            'student_name': student.get_full_name(),
            'specialty': specialty,
            'grade': grade_name,
            'remaining_balance': remaining_balance
        })
        total_report_debts += remaining_balance

    context = {
        'report_data': report_data,
        'total_report_debts': total_report_debts,
        'filter_type': filter_type,
        'active_year': active_year,
        'today': timezone.now().date(),
        'students_count': len(report_data)
    }
    return render(request, 'finance/print_debts_report.html', context)



@login_required
@user_passes_test(lambda u: u.is_superuser) # حماية للأدمن فقط
def student_inventory_view(request, student_id):
    """
    تم تحويل هذه الدالة من (مخزن العهدة) إلى (غرفة سحب الملفات وتصفير الديون)
    """
    student = get_object_or_404(Student, id=student_id)
    current_year = student.academic_year

    # حساب ما دفعه الطالب لعرضه للأدمن
    total_paid = Payment.objects.filter(
        student=student, academic_year=current_year, is_cancelled=False
    ).aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')

    if request.method == "POST":
        refund_amount = Decimal(request.POST.get('refund_amount', '0'))
        reason = request.POST.get('reason', 'سحب ملف نهائي')

        try:
            # 🚀 استدعاء دالة تسوية الحسابات الشاملة
            process_student_withdrawal(
                student_id=student.id, 
                refund_amount=refund_amount, 
                admin_user=request.user, 
                reason=reason
            )

            messages.success(request, f"✅ تم سحب ملف الطالب ותصفير مديونيته بنجاح. المبلغ المسترد: {refund_amount} ج.م")
            
            # مسح الكاش لكي تتحدث العدادات فوراً
            cache.clear()
            return redirect('student_list')
            
        except Exception as e:
            messages.error(request, f"❌ حدث خطأ: {e}")

    # التوجيه لنفس ملف الـ HTML الذي قمت بتصميمه مؤخراً
    return render(request, 'finance/student_inventory.html', {
        'student': student,
        'total_paid': total_paid
    })


@login_required
@transaction.atomic # لضمان عدم حدوث استلام إذا فشل الحفظ
def mark_item_delivered(request, item_id):
    """
    الدالة الحارسة: تمنع الاستلام إلا بعد التأكد من سداد كامل قيمة البند
    والتأكد من وجود رصيد كافٍ في المخزن العام.
    """
    if request.method == "POST":
        # 1. جلب بيانات البند المالي من المخزن العام (InventoryMaster)
        master_item = get_object_or_404(InventoryMaster, id=item_id)
        student_id = request.POST.get('student_id')
        
        if not student_id:
            return JsonResponse({'status': 'error', 'message': 'بيانات الطالب غير موجودة'}, status=400)
        
        # 2. التحقق من وجود رصيد في المخزن (المتبقي = الكلي - من استلموا)
        if master_item.get_remaining_stock() <= 0:
            return JsonResponse({'status': 'error', 'message': 'عفواً! هذا البند نفد من المخزن.'}, status=400)
            
        # 3. التحقق المالي (هل الطالب سدد كامل قيمة هذا البند؟)
        # نجمع كل ما دفعه الطالب في فئة هذا البند تحديداً (مثلاً: كتب)
        category_name = master_item.get_category_display()
        
        total_paid = Payment.objects.filter(
            student_id=student_id,
            revenue_category__name__icontains=category_name
        ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
        
        # 4. منع التسليم إذا كان المبلغ المدفوع أقل من السعر الرسمي
        if total_paid < master_item.price:
            remaining = master_item.price - total_paid
            return JsonResponse({
                'status': 'error', 
                'message': f'لا يمكن التسليم! الطالب لم يسدد كامل الرسوم. المتبقي: {remaining} ج.م'
            }, status=400)
        
        # 5. تنفيذ عملية التسليم بإنشاء سجل في (DeliveryRecord)
        try:
            DeliveryRecord.objects.create(
                student_id=student_id,
                inventory_item=master_item
            )
            return JsonResponse({
                'status': 'success', 
                'message': f'تم تسجيل استلام {category_name} بنجاح ✅'
            })
        except Exception:
            return JsonResponse({
                'status': 'error', 
                'message': 'حدث خطأ: ربما استلم الطالب هذا الصنف مسبقاً!'
            }, status=400)
            
    return JsonResponse({'status': 'error', 'message': 'طلب غير مسموح به'}, status=405)

@login_required
def mass_assign_plans(request):

    active_year = AcademicYear.objects.filter(is_active=True).first()
    if not active_year:
        return JsonResponse({
            "status": "error", 
            "message": "لا توجد سنة نشطة"
        }, status=400)

    students = Student.objects.filter(is_active=True)
    initialized_count = 0

    for student in students:
        _, created = StudentAccount.objects.update_or_create(
            student=student,
            academic_year=active_year,  # ✅ الصح
            defaults={
                "total_fees": 0
            }
        )
        if created:
            initialized_count += 1

    return JsonResponse({
        "status": "success",
        "message": f"تم إنشاء {initialized_count} حساب"
    })

    
def payments_archive(request):
    # 1. استقبال الفلتر
    category_name = request.GET.get('cat')
    
    # 2. جلب البيانات الأساسية
    payments = Payment.objects.all().order_by('-payment_date')
    categories = RevenueCategory.objects.all()

    # 3. الفلترة الذكية (استخدام icontains لجعل البحث مرن مع المسافات أو الهمزات)
    if category_name:
        payments = payments.filter(revenue_category__name__icontains=category_name)

    # 4. حساب الإحصائيات
    total_archived = payments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
    
    # استخدام timezone.now().date() هو الحل الصحيح لحقل الـ DateField
    today_count = payments.filter(payment_date=timezone.now().date()).count()

    return render(request, 'finance/payments_archive.html', {
        'payments': payments,
        'categories': categories,
        'total_archived': total_archived,
        'today_count': today_count,
        'selected_category': category_name
    })

@shared_task
def notify_admin_of_late_payments():
    # جلب كافة الأقساط المتأخرة التي لم تُدفع
    late_installments = StudentInstallment.objects.filter(
        due_date__lt=timezone.now().date(),
        status__in=['Late', 'Pending', 'Partial']
    ).select_related('student')

    if not late_installments.exists():
        return "لا يوجد متأخرات اليوم."

    # تجهيز محتوى الرسالة
    message = "قائمة الطلاب المتأخرين عن السداد اليوم:\n\n"
    for inst in late_installments:
        message += f"- الطالب: {inst.student.get_full_name()} | المبلغ: {inst.remaining_amount()} ج.م\n"

    # إرسال الإيميل للمدير (تأكد من إعدادات الـ SMTP في settings)
    send_mail(
        'تقرير المتأخرات اليومي',
        message,
        'system@school.com',
        [settings.ADMIN_EMAIL],
        fail_silently=False,
    )
    return f"تم إرسال تنبيه بـ {late_installments.count()} قسط متأخر."

def get_optimized_dashboard_stats(year):
    # جلب كافة الصفوف مع حساب إجمالي المطلوب والمحصل لكل صف في استعلام واحد
    grade_analysis = Grade.objects.annotate(
        # Coalesce تستخدم لوضع 0 بدل الـ None إذا لم توجد بيانات
        total_target=Coalesce(Sum(
            'student__account__net_fees', 
            filter=Q(student__academic_year=year)
        ), 0.0),
        
        total_collected=Coalesce(Sum(
            'student__account__total_paid', 
            filter=Q(student__academic_year=year)
        ), 0.0)
    ).values('name', 'total_target', 'total_collected')

    return list(grade_analysis)


from django.contrib import messages
from django.shortcuts import redirect
from django.db import transaction

@login_required
@user_passes_test(lambda u: u.is_superuser)
def bulk_promote_students(request):
    if request.method == 'POST':
        # 1. جلب البيانات من الطلب
        all_ids_str = request.POST.get('all_selected_ids', '')
        target_year_id = request.POST.get('target_year')
        target_grade_id = request.POST.get('target_grade')

        # 2. تحديد الطلاب المستهدفين
        if all_ids_str and all_ids_str.strip():
            # إذا كان هناك طلاب مختارين يدوياً (عبر الصفحات)
            student_ids = [sid for sid in all_ids_str.split(',') if sid.strip()]
            eligible_students = Student.objects.filter(id__in=student_ids, is_active=True)
        else:
            # الحل الجذري: إذا لم يتم اختيار أحد، نعتبر أن المستخدم يريد ترحيل "كل" الطلاب الظاهرين في الفلتر الحالي
            # يمكنك تعديل هذا الفلتر ليناسب السنة الحالية التي تظهر في شاشتك (2023/2024)
            eligible_students = Student.objects.filter(is_active=True) 

        if not eligible_students.exists() or not target_year_id or not target_grade_id:
            messages.error(request, "⚠️ يرجى اختيار الطلاب (أو التأكد من وجود طلاب نشطين) وتحديد السنة والصف.")
            return redirect(request.META.get('HTTP_REFERER', 'student_list'))

        success_count = 0
        fail_count = 0

        try:
            with transaction.atomic():
                for student in eligible_students:
                    if promote_student_action(student.id, target_year_id, target_grade_id):
                        success_count += 1
                    else:
                        fail_count += 1
            
            if success_count > 0:
                messages.success(request, f"🚀 تم ترحيل {success_count} طالب بنجاح للسنة الجديدة.")
            
            if fail_count > 0:
                messages.warning(request, f"⚠️ فشل ترحيل {fail_count} طالب (مسجلين مسبقاً في السنة المستهدفة).")
                    
        except Exception as e:
            messages.error(request, f"❌ حدث خطأ غير متوقع: {str(e)}")

    return redirect('student_list')


@staff_member_required
def admin_cancel_receipt(request, pk):
    # 1. التحقق من أن المستخدم هو Superuser (مدير نظام) لزيادة الأمان
    if not request.user.is_superuser:
        messages.error(request, "عذراً، هذه الصلاحية متوفرة لمدير النظام فقط.")
        return redirect(request.META.get('HTTP_REFERER', 'quick_collection'))

    payment = get_object_or_404(Payment, pk=pk)
    
    if request.method == "POST":
        reason = request.POST.get('reason')
        
        # 2. التحقق من وجود سبب للإلغاء
        if not reason or len(reason).strip() < 5:
            messages.error(request, "يجب ذكر سبب مقنع للإلغاء (على الأقل 5 أحرف).")
            return redirect(request.META.get('HTTP_REFERER', 'quick_collection'))
            
        try:
            with transaction.atomic():
                # استدعاء دالة الإلغاء التي قمنا بتعديلها في الـ Model
                payment.cancel_payment(request.user, reason)
                
                # تأكيد النجاح
                messages.success(
                    request, 
                    f"تم إلغاء الإيصال رقم {payment.receipt_number} بنجاح. "
                    f"تم تصفير المبلغ وإعادة المستحقات لمديونية الطالب."
                )
        except Exception as e:
            messages.error(request, f"خطأ تقني أثناء الإلغاء: {str(e)}")
            
    return redirect(request.META.get('HTTP_REFERER', 'quick_collection'))

# تأكد من وجود هذه الاستيرادات في أعلى الملف إذا لم تكن موجودة


from datetime import timedelta


@staff_member_required
@transaction.atomic
def close_daily_accounts_view(request):
    """إغلاق الخزينة الموحد (طلاب + خزينة + مصروفات + مرتجعات)"""
    if request.method == "POST":
        now_time = timezone.now()
        
        from treasury.models import GeneralLedger
        from finance.models import Payment, Expense, StudentRefund, DailyClosure
        
        try:
            # 1. جلب العمليات المفتوحة
            open_student_payments = Payment.objects.filter(is_closed=False)
            open_ledger_entries = GeneralLedger.objects.filter(is_closed=False).exclude(category='fees')
            open_expenses = Expense.objects.filter(is_closed=False)
            open_refunds = StudentRefund.objects.filter(is_closed=False) # 🟢 المرتجعات المفتوحة

            # 2. حساب الإجماليات
            total_student = open_student_payments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
            total_ledger = open_ledger_entries.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
            total_expenses = open_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
            total_refunds = open_refunds.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
            
            # 🟢 المعادلة: (إجمالي المقبوضات) - (إجمالي المصروفات + إجمالي المرتجعات)
            theoretical_total = (total_student + total_ledger) - (total_expenses + total_refunds)
            
            # إذا كانت الخزينة فارغة تماماً ولا يوجد أي حركة
            if theoretical_total <= 0 and not open_expenses.exists() and not open_refunds.exists():
                messages.info(request, "ℹ️ الخزينة فارغة، لا توجد حركات مالية مفتوحة لإغلاقها اليوم.")
                return redirect('daily_cashier_summary')

            # 3. حساب الفعلي من الفئات النقدية
            actual_total = Decimal('0.00')
            denominations = []
            for key, value in request.POST.items():
                if key.startswith('denom_'):
                    count = int(value) if value and value.isdigit() else 0
                    if count > 0:
                        face_value = Decimal(key.replace('denom_', ''))
                        actual_total += (face_value * count)
                        denominations.append(f"{face_value}x{count}")
            
            # 🚀 حماية حقل النقدية الإضافية من الخطأ إذا تُرك فارغاً
            extra_cash_raw = request.POST.get('extra_cash', '0').strip()
            if extra_cash_raw:
                actual_total += Decimal(extra_cash_raw)
                
            variance = actual_total - theoretical_total
            
            # 4. إنشاء سجل الجرد
            closure_id = f"CL-{now_time.strftime('%Y%m%d%H%M')}"
            closure = DailyClosure.objects.create(
                closed_by=request.user,
                total_cash=theoretical_total,
                actual_cash=actual_total,
                variance=variance,
                closure_id=closure_id,
                notes=f"الفئات: {' | '.join(denominations)} -- ملاحظات: {request.POST.get('notes', '')}"
            )
            
            # 5. القفل النهائي لجميع المصادر وربطها بسجل الجرد الموحد
            open_student_payments.update(closure=closure, is_closed=True)
            open_expenses.update(closure=closure, is_closed=True)
            open_ledger_entries.update(closure=closure, is_closed=True) 
            open_refunds.update(closure=closure, is_closed=True) # 🟢 قفل المرتجعات
            
            # 🚀 إظهار رسالة النجاح للمحاسب
            messages.success(request, f"✅ تم إغلاق الخزينة بنجاح وتصفير العهدة! (رقم الجرد: {closure_id})")
            
        except Exception as e:
            messages.error(request, f"❌ حدث خطأ غير متوقع أثناء إغلاق الخزينة: {str(e)}")
            
        return redirect('daily_cashier_summary')
    
    return redirect('daily_cashier_summary')


# @staff_member_required
# @transaction.atomic
# def close_daily_accounts_view(request):
#     """إغلاق الخزينة الموحد (طلاب + مصروفات + مرتجعات) - بصمت تام"""
#     if request.method == "POST":
#         now_time = timezone.now()
        
#         from treasury.models import GeneralLedger
#         from finance.models import Payment, Expense, StudentRefund, DailyClosure
        
#         # 1. جلب العمليات المفتوحة
#         open_student_payments = Payment.objects.filter(is_closed=False)
#         open_ledger_entries = GeneralLedger.objects.filter(is_closed=False).exclude(category='fees')
#         open_expenses = Expense.objects.filter(is_closed=False)
#         open_refunds = StudentRefund.objects.filter(is_closed=False) # 🟢 المرتجعات المفتوحة

#         # 2. حساب الإجماليات
#         total_student = open_student_payments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
#         total_ledger = open_ledger_entries.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
#         total_expenses = open_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
#         total_refunds = open_refunds.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        
#         # 🟢 المعادلة: (إجمالي المقبوضات) - (إجمالي المصروفات + إجمالي المرتجعات)
#         theoretical_total = (total_student + total_ledger) - (total_expenses + total_refunds)
        
#         if theoretical_total <= 0 and not open_expenses.exists() and not open_refunds.exists():
#             return redirect('daily_cashier_summary')

#         actual_total = Decimal('0.00')
#         denominations = []
#         for key, value in request.POST.items():
#             if key.startswith('denom_'):
#                 count = int(value or 0)
#                 if count > 0:
#                     try:
#                         face_value = Decimal(key.replace('denom_', ''))
#                         actual_total += (face_value * count)
#                         denominations.append(f"{face_value}x{count}")
#                     except: continue
        
#         actual_total += Decimal(request.POST.get('extra_cash', '0'))
#         variance = actual_total - theoretical_total
        
#         closure_id = f"CL-{now_time.strftime('%Y%m%d%H%M')}"
#         closure = DailyClosure.objects.create(
#             closed_by=request.user,
#             total_cash=theoretical_total,
#             actual_cash=actual_total,
#             variance=variance,
#             closure_id=closure_id,
#             notes=f"الفئات: {' | '.join(denominations)} -- ملاحظات: {request.POST.get('notes', '')}"
#         )
        
#         # 5. القفل النهائي لجميع المصادر
#         open_student_payments.update(closure=closure, is_closed=True)
#         open_expenses.update(closure=closure, is_closed=True)
#         open_ledger_entries.update(closure=closure, is_closed=True) 
#         open_refunds.update(closure=closure, is_closed=True) # 🟢 قفل المرتجعات
        
#         return redirect('daily_cashier_summary')
    
#     return redirect('daily_cashier_summary')


@login_required
def daily_cashier_summary(request): 
    from treasury.models import GeneralLedger
    from finance.models import Expense, StudentRefund 
    from django.db.models import Sum, Count
    from django.utils import timezone
    from datetime import timedelta
    from decimal import Decimal
    
    now = timezone.localtime()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    revenues_query = GeneralLedger.objects.filter(is_closed=False, is_discount=False, date__gte=start_of_day, date__lt=end_of_day)
    expenses_query = Expense.objects.filter(is_closed=False, expense_date__gte=start_of_day, expense_date__lt=end_of_day)
    
    # جلب المرتجعات (سحب الملفات) المفتوحة
    refunds_query = StudentRefund.objects.filter(is_closed=False)

    total_revenues_gross = revenues_query.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_expenses = expenses_query.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_refunds = refunds_query.aggregate(total=Sum('amount'))['total'] or Decimal('0.00') 
    
    # الخصم من الإجمالي العام للمربعات العلوية
    total_revenues = total_revenues_gross - total_refunds
    total_day = total_revenues - total_expenses

    # =========================================================
    # 🚀 التعديل الجديد: تصفية عهدة كل موظف (الأدمن وغيره) بدقة
    # =========================================================
    cashiers_dict = {}

    # 1. تجميع مقبوضات كل موظف
    for row in revenues_query.values('collected_by__username', 'collected_by__first_name', 'collected_by__last_name').annotate(total_amount=Sum('amount'), receipts_count=Count('id')):
        username = row['collected_by__username']
        cashiers_dict[username] = {
            'collected_by__username': username,
            'collected_by__first_name': row['collected_by__first_name'],
            'collected_by__last_name': row['collected_by__last_name'],
            'total_amount': row['total_amount'] or Decimal('0.00'),
            'receipts_count': row['receipts_count'] or 0
        }

    # 2. خصم المرتجعات من الموظف الذي قام بردها (السحب)
    for row in refunds_query.values('processed_by__username', 'processed_by__first_name', 'processed_by__last_name').annotate(refund_total=Sum('amount')):
        username = row['processed_by__username']
        if username not in cashiers_dict:
            # في حالة أن الموظف قام بعمل مرتجع فقط ولم يقبض أي إيراد اليوم
            cashiers_dict[username] = {
                'collected_by__username': username,
                'collected_by__first_name': row['processed_by__first_name'],
                'collected_by__last_name': row['processed_by__last_name'],
                'total_amount': Decimal('0.00'),
                'receipts_count': 0
            }
        # خصم مبلغ المرتجع من عهدة هذا الموظف
        cashiers_dict[username]['total_amount'] -= (row['refund_total'] or Decimal('0.00'))

    # 3. تحويل القاموس إلى قائمة وترتيبها حسب العهدة الأعلى
    cashiers_summary = sorted(cashiers_dict.values(), key=lambda x: x['total_amount'], reverse=True)
    # =========================================================

    expenses_list = expenses_query.select_related('spent_by')[:50]
    
    context = {
        'today': now.date(),
        'total_revenues': total_revenues,
        'total_expenses': total_expenses,
        'total_refunds': total_refunds, 
        'total_day': total_day,
        'cashiers_summary': cashiers_summary, # 👈 إرسال القائمة المدمجة والمفلترة
        'expenses': expenses_list,
    }
    return render(request, 'finance/daily_summary.html', context)

# @login_required
# def daily_cashier_summary(request): # أو حسب اسم الدالة لديك
#     # 1. ضبط النطاق الزمني لمنع كارثة AT TIME ZONE
#     now = timezone.localtime()
#     start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
#     end_of_day = start_of_day + timedelta(days=1)

#     # 2. جلب الإيرادات (المقبوضات)
#     revenues_query = GeneralLedger.objects.filter(
#         is_closed=False,
#         is_discount=False,
#         date__gte=start_of_day,
#         date__lt=end_of_day
#     )
    
#     # 3. جلب المصروفات (المدفوعات)
#     expenses_query = Expense.objects.filter(
#         is_closed=False,
#         expense_date__gte=start_of_day,
#         expense_date__lt=end_of_day
#     )

#     # 4. حساب الإجماليات
#     total_revenues = revenues_query.aggregate(total=Sum('amount'))['total'] or 0
#     total_expenses = expenses_query.aggregate(total=Sum('amount'))['total'] or 0
#     total_day = total_revenues - total_expenses

#     # 5. 🟢 السحر الحقيقي (Aggregation): تجميع عهد المحصلين داخل قاعدة البيانات مباشرة!
#     cashiers_summary = revenues_query.values(
#         'collected_by__username', 
#         'collected_by__first_name', 
#         'collected_by__last_name'
#     ).annotate(
#         total_amount=Sum('amount'),
#         receipts_count=Count('id')
#     ).order_by('-total_amount')

#     # 6. جلب المصروفات للعرض السريع
#     expenses_list = expenses_query.select_related('spent_by')[:50]

#     context = {
#         'today': now.date(),
#         'total_revenues': total_revenues,
#         'total_expenses': total_expenses,
#         'total_day': total_day,
#         'cashiers_summary': cashiers_summary, # نرسل التجميع الجاهز للـ HTML
#         'expenses': expenses_list,
#     }
#     return render(request, 'finance/daily_summary.html', context)



from .services import process_student_withdrawal

@login_required
@user_passes_test(lambda u: u.is_superuser) # 🔒 حماية صارمة: لا يفتح هذه الصفحة إلا الأدمن
def withdraw_student(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    current_year = student.academic_year

    # حساب ما دفعه الطالب لعرضه للأدمن
    total_paid = Payment.objects.filter(
        student=student, academic_year=current_year, is_cancelled=False
    ).aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')

    if request.method == "POST":
        refund_amount = Decimal(request.POST.get('refund_amount', '0'))
        reason = request.POST.get('reason', 'سحب ملف نهائي')

        try:
            # 🚀 استدعاء دالتك السحرية التي تقوم بكل العمل في الخلفية
            process_student_withdrawal(
                student_id=student.id, 
                refund_amount=refund_amount, 
                admin_user=request.user, 
                reason=reason
            )

            messages.success(request, f"✅ تم سحب ملف الطالب وتصفير مديونيته بنجاح. المبلغ المسترد: {refund_amount} ج.م")
            
            # مسح الكاش لكي تتحدث العدادات فوراً
            cache.clear()
            return redirect('student_list')
            
        except Exception as e:
            messages.error(request, f"❌ حدث خطأ: {e}")

    return render(request, 'students/withdraw_student.html', {
        'student': student,
        'total_paid': total_paid
    })
    
@login_required
def quick_collection(request):
    # 1. جلب الفئات والسنة بشكل خفيف ومتوافق مع الكاش المحلي للمتغيرات
    years = AcademicYear.objects.all().order_by('-is_active', '-name')
    categories = RevenueCategory.objects.all()
    
    next_url = request.GET.get('next') or request.POST.get('next')
    current_page = request.GET.get('page_num') or request.POST.get('page_num') or '1'
    
    # تحسين الفلترة للحصول على الفئة الافتراضية
    default_category = categories.filter(
        Q(name__icontains="اساسيه") | Q(name__icontains="أسا") | Q(name__icontains="مصروف")
    ).first() or categories.first()
    
    selected_year = request.GET.get('academic_year')
    url_student_id_raw = request.GET.get('student_id') or request.GET.get('student')
    url_student_id = int(url_student_id_raw) if url_student_id_raw and url_student_id_raw.isdigit() else None
    
    students_list = Student.objects.none()
    if url_student_id:
        students_list = Student.objects.filter(id=url_student_id).only('id', 'first_name', 'last_name', 'student_code')

    # 2. حساب المسلسل القادم وقراءة الدفتر النشط (مرة واحدة لـ GET و POST)
    active_book = ReceiptBook.objects.filter(user=request.user, is_active=True).first()
    next_serial = None
    
    if active_book:
        max_used = Payment.objects.filter(
            collected_by=request.user, 
            receipt_number__gte=active_book.start_serial, 
            receipt_number__lte=active_book.end_serial
        ).aggregate(max=Max('receipt_number'))['max']
        
        if max_used:
            if max_used >= active_book.end_serial:
                next_serial = active_book.end_serial
            else:
                next_serial = max_used + 1
        else:
            next_serial = active_book.start_serial

    remaining_balance = Decimal('0.00')
    total_required = Decimal('0.00')
    total_paid = Decimal('0.00')
    total_discount = Decimal('0.00')
    
    if url_student_id:
        # 💡 تم استبدال الكويري المكررة ببحث مباشر في الذاكرة المحلية لمتغير years
        active_year_obj = next((y for y in years if y.is_active), None)
        year_filter = selected_year or (active_year_obj.id if active_year_obj else None)
        
        if year_filter:
            st_account = StudentAccount.objects.filter(student_id=url_student_id, academic_year_id=year_filter).first()
            if st_account:
                # 💡 تم حذف st_account.refresh_from_db() لتوفير كويري ثقيلة
                for field_name in ['required_amount', 'total_amount', 'required_fees', 'total_required', 'amount']:
                    total_required = getattr(st_account, field_name, Decimal('0.00')) or Decimal('0.00')
                    if total_required > 0: break
                
                total_paid = getattr(st_account, 'paid_amount', Decimal('0.00')) or Decimal('0.00')
                total_discount = getattr(st_account, 'discount_amount', Decimal('0.00')) or Decimal('0.00')
                try: remaining_balance = Decimal(str(st_account.total_remaining))
                except AttributeError: remaining_balance = getattr(st_account, 'remaining_balance', Decimal('0.00')) or Decimal('0.00')
            else:
                student_obj = Student.objects.filter(id=url_student_id).first()
                if student_obj:
                    total_required = getattr(student_obj, 'required_amount', Decimal('0.00')) or getattr(student_obj, 'total_required', Decimal('0.00')) or Decimal('0.00')
                    try: remaining_balance = Decimal(str(student_obj.absolute_remaining))
                    except AttributeError: remaining_balance = getattr(student_obj, 'remaining_balance', Decimal('0.00')) or Decimal('0.00')
                    total_paid = total_required - remaining_balance

    if remaining_balance < 0: remaining_balance = Decimal('0.00')

    # 3. معالجة طلب الـ POST وحفظ البيانات والتحقق الفعلي عند الإدخال
    if request.method == "POST":
        if not active_book:
            messages.error(request, "عذراً، لا يوجد دفتر إيصالات نشط حالياً!")
            return redirect(request.META.get('HTTP_REFERER', 'quick_collection'))

        p_student_id = request.POST.get('student')
        category_id = request.POST.get('category')
        amount_raw = request.POST.get('amount')
        receipt_number = request.POST.get('receipt_number')
        raw_year_id = request.POST.get('academic_year')
        p_academic_year_id = int(raw_year_id) if (raw_year_id and raw_year_id.isdigit()) else None
        discount_amount = Decimal(request.POST.get('hidden_discount_value', '0'))

        if p_student_id and category_id and amount_raw:
            try:
                # 💡 عزل الـ atomic هنا فقط لضمان سلامة العمليات المالية دون قفل دائم لقاعدة البيانات
                with transaction.atomic():
                    category = get_object_or_404(RevenueCategory, id=category_id)
                    student = get_object_or_404(Student, id=p_student_id)
                    amount_to_pay = Decimal(amount_raw)
                    final_academic_year_id = p_academic_year_id or (student.academic_year.id if student.academic_year else None)

                    final_receipt_no = int(receipt_number) if receipt_number and receipt_number.isdigit() else None
                    
                    if final_receipt_no:
                        if final_receipt_no < active_book.start_serial or final_receipt_no > active_book.end_serial:
                            messages.error(request, f"رقم الإيصال ({final_receipt_no}) خارج نطاق دفترك المعتمد ({active_book.start_serial} - {active_book.end_serial})!")
                            return redirect(request.META.get('HTTP_REFERER', 'quick_collection'))
                    else:
                        messages.error(request, "خطأ في رقم الإيصال.")
                        return redirect(request.META.get('HTTP_REFERER', 'quick_collection'))

                    try:
                        payment = Payment.objects.create(
                            academic_year_id=final_academic_year_id, student=student, revenue_category=category,
                            amount_paid=amount_to_pay, payment_date=timezone.now().date(), collected_by=request.user,
                            receipt_number=final_receipt_no, notes=request.POST.get('notes', '')
                        )
                    except IntegrityError as e:
                        if 'receipt_number' in str(e):
                            with connection.cursor() as cursor:
                                cursor.execute("SELECT MAX(receipt_number) FROM finance_payment")
                                max_val = cursor.fetchone()[0] or 0
                                new_number = max_val + 1
                            
                            if new_number > active_book.end_serial:
                                messages.error(request, "خطأ حرج: الرقم التسلسلي التالي يتجاوز حدود نهاية هذا الدفتر!")
                                return redirect(request.META.get('HTTP_REFERER', 'quick_collection'))

                            payment = Payment.objects.create(
                                academic_year_id=final_academic_year_id, student=student, revenue_category=category,
                                amount_paid=amount_to_pay, payment_date=timezone.now().date(), collected_by=request.user,
                                receipt_number=new_number, notes=request.POST.get('notes', '') + " (تصحيح آلي)"
                            )
                            final_receipt_no = new_number
                        else: 
                            raise e

                    # تحديث سريع ومباشر لحالة الدفتر بدون تحميل كائن كامل للذاكرة
                    if final_receipt_no and final_receipt_no >= active_book.end_serial:
                        ReceiptBook.objects.filter(id=active_book.id).update(is_active=False)
                        messages.warning(request, "تنبيه: تم استخدام آخر إيصال وإغلاق الدفتر بنجاح.")

                    if discount_amount > 0:
                        discount_cat, _ = RevenueCategory.objects.get_or_create(name="خصم مصروفات (كوبون)")
                        Payment.objects.create(
                            academic_year_id=final_academic_year_id, student=student, revenue_category=discount_cat, 
                            amount_paid=discount_amount, payment_date=timezone.now().date(), collected_by=request.user,
                            receipt_number=None, notes=f"خصم تابع للإيصال رقم {final_receipt_no}"
                        )

                    # 🎯 حساب متبقي الحساب فوراً بعد التحصيل (مباشرة وبدون الـ refresh المكرر)
                    remaining_after = Decimal('0.00')
                    st_account_after = StudentAccount.objects.filter(student=student, academic_year_id=final_academic_year_id).first()
                    if st_account_after:
                        try: remaining_after = Decimal(str(st_account_after.total_remaining))
                        except Exception: remaining_after = getattr(st_account_after, 'remaining_balance', Decimal('0.00')) or Decimal('0.00')
                    
                    if remaining_after < 0: remaining_after = Decimal('0.00')

                    messages.success(request, f"✅ تم تحصيل {amount_to_pay} ج.م بنجاح. رقم الإيصال: {final_receipt_no}")

                    # 🌟 التوجيه الذكي بناءً على المتبقي
                    if remaining_after <= 0:
                        return redirect(reverse('student_list') + f'?page=1&highlight={p_student_id}')

                    return redirect(reverse('quick_collection') + f"?student_id={p_student_id}&page_num={current_page}")

            except Exception as e:
                messages.error(request, f"خطأ: {str(e)}")

    # 💡 تحسين جلب آخر إيصال باستخدام .only() لتسريع الأداء وتوفير الميموري
    last_payment = Payment.objects.filter(collected_by=request.user).order_by('-id').only('id', 'receipt_number', 'amount_paid').first()
    
    return render(request, 'finance/quick_collection.html', {
        'years': years, 'categories': categories, 'students': students_list,
        'default_category': default_category, 'selected_year': selected_year,
        'selected_student_id': url_student_id, 'active_book': active_book, 'next_serial': next_serial,
        'next_url': next_url, 'last_payment': last_payment, 'remaining_balance': remaining_balance,
        'total_required': total_required, 'total_paid': total_paid, 'total_discount': total_discount,
        'current_page': current_page
    })
    
    
# @login_required
# @transaction.atomic
# def quick_collection(request):
#     # 1. جلب البيانات الأساسية بسرعة مع الترتيب المفهرس
#     years = AcademicYear.objects.all().order_by('-is_active', '-name')
#     categories = RevenueCategory.objects.all()
    
#     next_url = request.GET.get('next') or request.POST.get('next')
#     current_page = request.GET.get('page_num') or request.POST.get('page_num') or '1'
    
#     # تأمين جلب الفئة الافتراضية بجميع مسمياتها
#     default_category = categories.filter(name__icontains="اساسيه").first() or \
#                        categories.filter(name__icontains="أسا").first() or \
#                        categories.filter(name__icontains="مصروف").first() or \
#                        categories.first()
    
#     selected_year = request.GET.get('academic_year')
#     url_student_id_raw = request.GET.get('student_id') or request.GET.get('student')
#     url_student_id = int(url_student_id_raw) if url_student_id_raw and url_student_id_raw.isdigit() else None
    
#     students_query = Student.objects.all()
#     if selected_year: 
#         students_query = students_query.filter(academic_year_id=selected_year)
    
#     students_list = students_query.only(
#         'id', 'first_name', 'last_name', 'student_code', 'national_id'
#     ).order_by('first_name')

#     # 2. حساب المسلسل القادم لدفتر الإيصالات
#     active_book = ReceiptBook.objects.filter(user=request.user, is_active=True).first()
#     next_serial = None
#     if active_book:
#         from django.db.models import Max
#         max_used = Payment.objects.filter(
#             collected_by=request.user, 
#             receipt_number__gte=active_book.start_serial, 
#             receipt_number__lte=active_book.end_serial
#         ).aggregate(max=Max('receipt_number'))['max']
        
#         if max_used:
#             # خاصية هامة: إذا تخطى السيريال نطاق الدفتر يتم غلقه تلقائياً لحماية الموظف
#             if max_used >= active_book.end_serial:
#                 active_book.is_active = False
#                 active_book.save()
#                 active_book = None
#                 messages.warning(request, "تنبيه: دفتر الإيصالات الحالي قد انتهى بالكامل! يرجى فتح دفتر جديد.")
#             else:
#                 next_serial = max_used + 1
#         else:
#             next_serial = active_book.start_serial

#     # إعداد العدادات المالية الافتراضية السريعة O(1)
#     remaining_balance = Decimal('0.00')
#     total_required = Decimal('0.00')
#     total_paid = Decimal('0.00')
#     total_discount = Decimal('0.00')
    
#     # 3. معالجة طلب الـ GET وعرض بيانات الطالب المالية بأمان تام (للقراءة فقط)
#     if url_student_id:
#         year_filter = selected_year or (years.filter(is_active=True).first().id if years.filter(is_active=True).exists() else None)
        
#         if year_filter:
#             st_account = StudentAccount.objects.filter(student_id=url_student_id, academic_year_id=year_filter).first()
            
#             if st_account:
#                 st_account.refresh_from_db()
                
#                 for field_name in ['required_amount', 'total_amount', 'required_fees', 'total_required', 'amount']:
#                     total_required = getattr(st_account, field_name, Decimal('0.00')) or Decimal('0.00')
#                     if total_required > 0:
#                         break
                
#                 total_paid = getattr(st_account, 'paid_amount', Decimal('0.00')) or Decimal('0.00')
#                 total_discount = getattr(st_account, 'discount_amount', Decimal('0.00')) or Decimal('0.00')
                
#                 # جلب قيمة المتبقي للقراءة فقط لمنع استدعاء أي Setter خاطئ
#                 try:
#                     remaining_balance = Decimal(str(st_account.total_remaining))
#                 except AttributeError:
#                     remaining_balance = getattr(st_account, 'remaining_balance', Decimal('0.00')) or Decimal('0.00')
#             else:
#                 student_obj = Student.objects.filter(id=url_student_id).first()
#                 if student_obj:
#                     total_required = getattr(student_obj, 'required_amount', Decimal('0.00')) or \
#                                      getattr(student_obj, 'total_required', Decimal('0.00')) or Decimal('0.00')
#                     try:
#                         remaining_balance = Decimal(str(student_obj.absolute_remaining))
#                     except AttributeError:
#                         remaining_balance = getattr(student_obj, 'remaining_balance', Decimal('0.00')) or Decimal('0.00')
#                     total_paid = total_required - remaining_balance

#     if remaining_balance < 0:
#         remaining_balance = Decimal('0.00')

#     # 4. معالجة طلب الـ POST وحفظ التحصيل والخصومات
#     if request.method == "POST":
#         p_student_id = request.POST.get('student')
#         category_id = request.POST.get('category')
#         amount_raw = request.POST.get('amount')
#         receipt_number = request.POST.get('receipt_number')
        
#         raw_year_id = request.POST.get('academic_year')
#         p_academic_year_id = int(raw_year_id) if (raw_year_id and raw_year_id.isdigit()) else None
#         discount_amount = Decimal(request.POST.get('hidden_discount_value', '0'))

#         if p_student_id and category_id and amount_raw:
#             try:
#                 category = get_object_or_404(RevenueCategory, id=category_id)
#                 student = get_object_or_404(Student, id=p_student_id)
#                 amount_to_pay = Decimal(amount_raw)
                
#                 final_academic_year_id = p_academic_year_id or (student.academic_year.id if student.academic_year else None)

#                 category_name_clean = category.name.replace("أ", "ا").replace("إ", "ا").replace("ة", "ه")
#                 final_category = category
#                 if any(k in category_name_clean for k in ["اداريه", "فتح ملف", "ايراد حر"]):
#                     final_category, _ = RevenueCategory.objects.get_or_create(name="إيراد حر (رسوم إدارية)")

#                 # تأمين وحماية: التحقق من أن الرقم المدخل لا يتخطى حدود الدفتر النشط حالياً
#                 final_receipt_no = int(receipt_number) if receipt_number and receipt_number.isdigit() else None
#                 if active_book and final_receipt_no:
#                     if final_receipt_no < active_book.start_serial or final_receipt_no > active_book.end_serial:
#                         messages.error(request, f"خطأ: رقم الإيصال {final_receipt_no} خارج نطاق الدفتر الحالي ({active_book.start_serial} - {active_book.end_serial})")
#                         return redirect(request.META.get('HTTP_REFERER', 'quick_collection'))

#                 try:
#                     payment = Payment.objects.create(
#                         academic_year_id=final_academic_year_id,
#                         student=student,
#                         revenue_category=final_category,
#                         amount_paid=amount_to_pay,
#                         payment_date=timezone.now().date(),
#                         collected_by=request.user,
#                         receipt_number=final_receipt_no,
#                         notes=request.POST.get('notes', '')
#                     )
#                 except IntegrityError as e:
#                     if 'receipt_number' in str(e):
#                         with connection.cursor() as cursor:
#                             cursor.execute("SELECT MAX(receipt_number) FROM finance_payment")
#                             max_val = cursor.fetchone()[0] or 0
#                             new_number = max_val + 1
                        
#                         payment = Payment.objects.create(
#                             academic_year_id=final_academic_year_id,
#                             student=student,
#                             revenue_category=final_category,
#                             amount_paid=amount_to_pay,
#                             payment_date=timezone.now().date(),
#                             collected_by=request.user,
#                             receipt_number=new_number,
#                             notes=request.POST.get('notes', '') + " (تصحيح آلي)"
#                         )
#                         receipt_number = new_number
#                     else:
#                         raise e

#                 if discount_amount > 0:
#                     discount_cat, _ = RevenueCategory.objects.get_or_create(name="خصم مصروفات (كوبون)")
#                     Payment.objects.create(
#                         academic_year_id=final_academic_year_id,
#                         student=student,
#                         revenue_category=discount_cat, 
#                         amount_paid=discount_amount,
#                         payment_date=timezone.now().date(), 
#                         collected_by=request.user,
#                         receipt_number=None,
#                         notes=f"خصم تابع للإيصال رقم {receipt_number}"
#                     )

#                 # 🎯 حماية مطلقة: حساب المتبقي الحقيقي بعد الحفظ مباشرة عبر الاستعلام المباشر من الداتابيز لتفادي الـ Setter تماماً
#                 remaining_after = Decimal('0.00')
#                 st_account_after = StudentAccount.objects.filter(student=student, academic_year_id=final_academic_year_id).first()
#                 if st_account_after:
#                     st_account_after.refresh_from_db()
#                     try:
#                         # جلب القيمة نصياً أولاً ثم تحويلها لضمان عدم تفعيل الـ property setter
#                         remaining_after = Decimal(str(st_account_after.total_remaining))
#                     except Exception:
#                         remaining_after = getattr(st_account_after, 'remaining_balance', Decimal('0.00')) or Decimal('0.00')
                
#                 if remaining_after < 0:
#                     remaining_after = Decimal('0.00')

#                 messages.success(request, f"تم تحصيل {amount_to_pay} ج.م بنجاح. رقم الإيصال: {receipt_number or 'لا يوجد'} - المتبقي الحالي: {remaining_after} ج.م")
                
#                 if remaining_after <= 0:
#                     return redirect(reverse('student_list') + f'?page=1&highlight={p_student_id}')
                                
#                 redirect_url = reverse('quick_collection') + f"?student_id={p_student_id}&page_num={current_page}"
#                 if p_academic_year_id:
#                     redirect_url += f"&academic_year={p_academic_year_id}"
                
#                 return redirect(redirect_url)

#             except Exception as e:
#                 messages.error(request, f"خطأ غير متوقع أثناء الحفظ: {str(e)}")

#     # 🎯 التأمين الشامل هنا: جلب آخر إيصال وإذا لم يوجد لا ينهار النظام
#     last_payment = Payment.objects.filter(collected_by=request.user).order_by('-id').first()
    
#     return render(request, 'finance/quick_collection.html', {
#         'years': years, 
#         'categories': categories, 
#         'students': students_list,
#         'default_category': default_category, 
#         'selected_year': selected_year,
#         'selected_student_id': url_student_id, 
#         'active_book': active_book, 
#         'next_serial': next_serial,
#         'next_url': next_url,
#         'last_payment': last_payment, 
#         'remaining_balance': remaining_balance,
#         'total_required': total_required,
#         'total_paid': total_paid,
#         'total_discount': total_discount,
#         'current_page': current_page
#     })
    
    
# @login_required
# @transaction.atomic
# def quick_collection(request):
#     # 1. جلب البيانات الأساسية بسرعة مع الترتيب المفهرس
#     years = AcademicYear.objects.all().order_by('-is_active', '-name')
#     categories = RevenueCategory.objects.all()
    
#     next_url = request.GET.get('next') or request.POST.get('next')
#     current_page = request.GET.get('page_num') or request.POST.get('page_num') or '1'
    
#     # تأمين جلب الفئة الافتراضية بجميع مسمياتها
#     default_category = categories.filter(name__icontains="اساسيه").first() or \
#                        categories.filter(name__icontains="أسا").first() or \
#                        categories.filter(name__icontains="مصروف").first() or \
#                        categories.first()
    
#     selected_year = request.GET.get('academic_year')
#     url_student_id_raw = request.GET.get('student_id') or request.GET.get('student')
#     url_student_id = int(url_student_id_raw) if url_student_id_raw and url_student_id_raw.isdigit() else None
    
#     students_query = Student.objects.all()
#     if selected_year: 
#         students_query = students_query.filter(academic_year_id=selected_year)
    
#     students_list = students_query.only(
#         'id', 'first_name', 'last_name', 'student_code', 'national_id'
#     ).order_by('first_name')

#     # 2. حساب المسلسل القادم لدفتر الإيصالات
#     active_book = ReceiptBook.objects.filter(user=request.user, is_active=True).first()
#     next_serial = None
#     if active_book:
#         from django.db.models import Max
#         max_used = Payment.objects.filter(
#             collected_by=request.user, 
#             receipt_number__gte=active_book.start_serial, 
#             receipt_number__lte=active_book.end_serial
#         ).aggregate(max=Max('receipt_number'))['max']
#         next_serial = (max_used + 1) if max_used else active_book.start_serial

#     # إعداد العدادات المالية الافتراضية السريعة O(1)
#     remaining_balance = Decimal('0.00')
#     total_required = Decimal('0.00')
#     total_paid = Decimal('0.00')
#     total_discount = Decimal('0.00')
    
#     # 3. معالجة طلب الـ GET وعرض بيانات الطالب المالية بأمان تام (للقراءة فقط)
#     if url_student_id:
#         year_filter = selected_year or (years.filter(is_active=True).first().id if years.filter(is_active=True).exists() else None)
        
#         if year_filter:
#             st_account = StudentAccount.objects.filter(student_id=url_student_id, academic_year_id=year_filter).first()
            
#             if st_account:
#                 st_account.refresh_from_db()
                
#                 for field_name in ['required_amount', 'total_amount', 'required_fees', 'total_required', 'amount']:
#                     total_required = getattr(st_account, field_name, Decimal('0.00')) or Decimal('0.00')
#                     if total_required > 0:
#                         break
                
#                 total_paid = getattr(st_account, 'paid_amount', Decimal('0.00')) or Decimal('0.00')
#                 total_discount = getattr(st_account, 'discount_amount', Decimal('0.00')) or Decimal('0.00')
                
#                 # جلب قيمة المتبقي للقراءة فقط لمنع استدعاء أي Setter خاطئ
#                 try:
#                     remaining_balance = Decimal(str(st_account.total_remaining))
#                 except AttributeError:
#                     remaining_balance = getattr(st_account, 'remaining_balance', Decimal('0.00')) or Decimal('0.00')
#             else:
#                 student_obj = Student.objects.filter(id=url_student_id).first()
#                 if student_obj:
#                     total_required = getattr(student_obj, 'required_amount', Decimal('0.00')) or \
#                                      getattr(student_obj, 'total_required', Decimal('0.00')) or Decimal('0.00')
#                     try:
#                         remaining_balance = Decimal(str(student_obj.absolute_remaining))
#                     except AttributeError:
#                         remaining_balance = getattr(student_obj, 'remaining_balance', Decimal('0.00')) or Decimal('0.00')
#                     total_paid = total_required - remaining_balance

#     if remaining_balance < 0:
#         remaining_balance = Decimal('0.00')

#     # 4. معالجة طلب الـ POST وحفظ التحصيل والخصومات
#     if request.method == "POST":
#         p_student_id = request.POST.get('student')
#         category_id = request.POST.get('category')
#         amount_raw = request.POST.get('amount')
#         receipt_number = request.POST.get('receipt_number')
        
#         raw_year_id = request.POST.get('academic_year')
#         p_academic_year_id = int(raw_year_id) if (raw_year_id and raw_year_id.isdigit()) else None
#         discount_amount = Decimal(request.POST.get('hidden_discount_value', '0'))

#         if p_student_id and category_id and amount_raw:
#             try:
#                 category = get_object_or_404(RevenueCategory, id=category_id)
#                 student = get_object_or_404(Student, id=p_student_id)
#                 amount_to_pay = Decimal(amount_raw)
                
#                 final_academic_year_id = p_academic_year_id or (student.academic_year.id if student.academic_year else None)

#                 category_name_clean = category.name.replace("أ", "ا").replace("إ", "ا").replace("ة", "ه")
#                 final_category = category
#                 if any(k in category_name_clean for k in ["اداريه", "فتح ملف", "ايراد حر"]):
#                     final_category, _ = RevenueCategory.objects.get_or_create(name="إيراد حر (رسوم إدارية)")

#                 try:
#                     payment = Payment.objects.create(
#                         academic_year_id=final_academic_year_id,
#                         student=student,
#                         revenue_category=final_category,
#                         amount_paid=amount_to_pay,
#                         payment_date=timezone.now().date(),
#                         collected_by=request.user,
#                         receipt_number=int(receipt_number) if receipt_number else None,
#                         notes=request.POST.get('notes', '')
#                     )
#                 except IntegrityError as e:
#                     if 'receipt_number' in str(e):
#                         with connection.cursor() as cursor:
#                             cursor.execute("SELECT MAX(receipt_number) FROM finance_payment")
#                             max_val = cursor.fetchone()[0] or 0
#                             new_number = max_val + 1
                        
#                         payment = Payment.objects.create(
#                             academic_year_id=final_academic_year_id,
#                             student=student,
#                             revenue_category=final_category,
#                             amount_paid=amount_to_pay,
#                             payment_date=timezone.now().date(),
#                             collected_by=request.user,
#                             receipt_number=new_number,
#                             notes=request.POST.get('notes', '') + " (تصحيح آلي)"
#                         )
#                         receipt_number = new_number
#                     else:
#                         raise e

#                 if discount_amount > 0:
#                     discount_cat, _ = RevenueCategory.objects.get_or_create(name="خصم مصروفات (كوبون)")
#                     Payment.objects.create(
#                         academic_year_id=final_academic_year_id,
#                         student=student,
#                         revenue_category=discount_cat, 
#                         amount_paid=discount_amount,
#                         payment_date=timezone.now().date(), 
#                         collected_by=request.user,
#                         receipt_number=None,
#                         notes=f"خصم تابع للإيصال رقم {receipt_number}"
#                     )

#                 # 🎯 حماية مطلقة: حساب المتبقي الحقيقي بعد الحفظ مباشرة عبر الاستعلام المباشر من الداتابيز لتفادي الـ Setter تماماً
#                 remaining_after = Decimal('0.00')
#                 st_account_after = StudentAccount.objects.filter(student=student, academic_year_id=final_academic_year_id).first()
#                 if st_account_after:
#                     st_account_after.refresh_from_db()
#                     try:
#                         # جلب القيمة نصياً أولاً ثم تحويلها لضمان عدم تفعيل الـ property setter
#                         remaining_after = Decimal(str(st_account_after.total_remaining))
#                     except Exception:
#                         remaining_after = getattr(st_account_after, 'remaining_balance', Decimal('0.00')) or Decimal('0.00')
                
#                 if remaining_after < 0:
#                     remaining_after = Decimal('0.00')

#                 messages.success(request, f"تم تحصيل {amount_to_pay} ج.م بنجاح. المتبقي الحالي: {remaining_after} ج.م")
                
#                 if remaining_after <= 0:
#                     return redirect(reverse('student_list') + f'?page=1&highlight={p_student_id}')
                                
#                 redirect_url = reverse('quick_collection') + f"?student_id={p_student_id}&page_num={current_page}"
#                 if p_academic_year_id:
#                     redirect_url += f"&academic_year={p_academic_year_id}"
                
#                 return redirect(redirect_url)

#             except Exception as e:
#                 messages.error(request, f"خطأ غير متوقع أثناء الحفظ: {str(e)}")

#     # 🎯 التأمين الشامل هنا: جلب آخر إيصال وإذا لم يوجد لا ينهار النظام
#     last_payment = Payment.objects.filter(collected_by=request.user).order_by('-id').first()
    
#     return render(request, 'finance/quick_collection.html', {
#         'years': years, 
#         'categories': categories, 
#         'students': students_list,
#         'default_category': default_category, 
#         'selected_year': selected_year,
#         'selected_student_id': url_student_id, 
#         'active_book': active_book, 
#         'next_serial': next_serial,
#         'next_url': next_url,
#         'last_payment': last_payment, 
#         'remaining_balance': remaining_balance,
#         'total_required': total_required,
#         'total_paid': total_paid,
#         'total_discount': total_discount,
#         'current_page': current_page
#     })


# from django.urls import reverse

# @login_required
# @transaction.atomic
# def quick_collection(request):
#     years = AcademicYear.objects.all().order_by('-is_active', '-name')
#     categories = RevenueCategory.objects.all()
    
#     next_url = request.GET.get('next') or request.POST.get('next')
    
#     default_category = categories.filter(name__icontains="اساسيه").first() or \
#                        categories.filter(name__icontains="مصروف").first()
    
#     selected_year = request.GET.get('academic_year')
#     url_student_id_raw = request.GET.get('student_id') or request.GET.get('student')
#     url_student_id = int(url_student_id_raw) if url_student_id_raw and url_student_id_raw.isdigit() else None
    
#     students_query = Student.objects.all()
#     if selected_year: 
#         students_query = students_query.filter(academic_year_id=selected_year)
    
#     students_list = students_query.only(
#         'id', 'first_name', 'last_name', 'student_code', 'national_id'
#     ).order_by('first_name')

#     active_book = ReceiptBook.objects.filter(user=request.user, is_active=True).first()
#     next_serial = None
#     if active_book:
#         from django.db.models import Max
#         max_used = Payment.objects.filter(
#             collected_by=request.user, 
#             receipt_number__gte=active_book.start_serial, 
#             receipt_number__lte=active_book.end_serial
#         ).aggregate(max=Max('receipt_number'))['max']
#         next_serial = (max_used + 1) if max_used else active_book.start_serial

#     if request.method == "POST":
#         from django.db import IntegrityError, connection
#         from finance.models import StudentAccount 

#         p_student_id = request.POST.get('student')
#         category_id = request.POST.get('category')
#         amount_raw = request.POST.get('amount')
#         receipt_number = request.POST.get('receipt_number')
        
#         raw_year_id = request.POST.get('academic_year')
#         p_academic_year_id = int(raw_year_id) if (raw_year_id and raw_year_id.isdigit()) else None
        
#         discount_amount = Decimal(request.POST.get('hidden_discount_value', '0'))

#         if p_student_id and category_id and amount_raw:
#             try:
#                 category = get_object_or_404(RevenueCategory, id=category_id)
#                 student = get_object_or_404(Student, id=p_student_id)
#                 amount_to_pay = Decimal(amount_raw)
                
#                 final_academic_year_id = p_academic_year_id or (student.academic_year.id if student.academic_year else None)

#                 category_name_clean = category.name.replace("أ", "ا").replace("إ", "ا").replace("ة", "ه")
#                 final_category = category
#                 if any(k in category_name_clean for k in ["اداريه", "فتح ملف", "ايراد حر"]):
#                     final_category, _ = RevenueCategory.objects.get_or_create(name="إيراد حر (رسوم إدارية)")

#                 try:
#                     payment = Payment.objects.create(
#                         academic_year_id=final_academic_year_id,
#                         student=student,
#                         revenue_category=final_category,
#                         amount_paid=amount_to_pay,
#                         payment_date=timezone.now().date(),
#                         collected_by=request.user,
#                         receipt_number=int(receipt_number) if receipt_number else None,
#                         notes=request.POST.get('notes', '')
#                     )
#                 except IntegrityError as e:
#                     if 'receipt_number' in str(e):
#                         with connection.cursor() as cursor:
#                             cursor.execute("SELECT MAX(receipt_number) FROM finance_payment")
#                             max_val = cursor.fetchone()[0] or 0
#                             new_number = max_val + 1
                        
#                         payment = Payment.objects.create(
#                             academic_year_id=final_academic_year_id,
#                             student=student,
#                             revenue_category=final_category,
#                             amount_paid=amount_to_pay,
#                             payment_date=timezone.now().date(),
#                             collected_by=request.user,
#                             receipt_number=new_number,
#                             notes=request.POST.get('notes', '') + " (تصحيح آلي)"
#                         )
#                         receipt_number = new_number
#                     else:
#                         raise e

#                 if discount_amount > 0:
#                     discount_cat, _ = RevenueCategory.objects.get_or_create(name="خصم مصروفات (كوبون)")
#                     Payment.objects.create(
#                         academic_year_id=final_academic_year_id,
#                         student=student,
#                         revenue_category=discount_cat, 
#                         amount_paid=discount_amount,
#                         payment_date=timezone.now().date(), 
#                         collected_by=request.user,
#                         receipt_number=None,
#                         notes=f"خصم تابع للإيصال رقم {receipt_number}"
#                     )

#                 # 💡 التعديل الجوهري: جلب الحساب المالي للسنة الدراسية الصحيحة الخاصة بالإيصال الحالي
#                 st_account = StudentAccount.objects.filter(
#                     student=student, 
#                     academic_year_id=final_academic_year_id
#                 ).first()
                
#                 if st_account: 
#                     st_account.refresh_from_db()
#                     remaining_after = st_account.total_remaining
#                 else:
#                     remaining_after = getattr(student, 'final_remaining', 0)
                
#                 messages.success(request, f"تم تحصيل {amount_to_pay} ج.م بنجاح. المتبقي الحالي: {remaining_after} ج.م")
                
#                 # 🎯 الفحص الصارم: لا يتم الخروج والتحويل لصفحة سجل الطلاب إلا لو تصفّرت المديونية تماماً (0 أو أقل)
#                 if remaining_after <= 0:
#                     return redirect(reverse('student_list') + f'?page=1&success_id={p_student_id}')
                                
#                 # طالما لسه باقي مديونية (أكبر من 0)، يعيد تحميل نفس شاشة التحصيل السريع للاستكمال بدون أي اختفاء
#                 redirect_url = reverse('quick_collection') + f"?student_id={p_student_id}"
#                 if p_academic_year_id:
#                     redirect_url += f"&academic_year={p_academic_year_id}"
                
#                 return redirect(redirect_url)

#             except Exception as e:
#                 messages.error(request, f"خطأ غير متوقع: {str(e)}")

#     last_payment = Payment.objects.filter(collected_by=request.user).order_by('-id').first()
    
#     return render(request, 'finance/quick_collection.html', {
#         'years': years, 
#         'categories': categories, 
#         'students': students_list,
#         'default_category': default_category, 
#         'selected_year': selected_year,
#         'selected_student_id': url_student_id, 
#         'active_book': active_book, 
#         'next_serial': next_serial,
#         'next_url': next_url,
#         'last_payment': last_payment
#     })

    
    
# @staff_member_required
# @transaction.atomic
# def close_daily_accounts_view(request):
#     """إغلاق الخزينة الموحد (ترحيل السجلات بصمت تام)"""
#     if request.method == "POST":
#         now_time = timezone.now()
        
#         # حساب الإجماليات (مع استبعاد الرسوم من الخزينة لتجنب الازدواجية)
#         total_student = Payment.objects.filter(is_closed=False).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
#         total_ledger = GeneralLedger.objects.filter(is_closed=False).exclude(category='fees').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
#         total_expenses = Expense.objects.filter(is_closed=False).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        
#         theoretical_total = (total_student + total_ledger) - total_expenses
        
#         # إذا كانت الخزينة فارغة، نعود بصمت بدون أي رسائل تحذير
#         if theoretical_total <= 0 and not Expense.objects.filter(is_closed=False).exists():
#             return redirect('daily_cashier_summary')

#         # حساب المبلغ الفعلي من مدخلات الكاشير
#         actual_total = Decimal('0.00')
#         denominations = []
#         for key, value in request.POST.items():
#             if key.startswith('denom_'):
#                 count = int(value or 0)
#                 if count > 0:
#                     face_value = Decimal(key.replace('denom_', ''))
#                     actual_total += (face_value * count)
#                     denominations.append(f"{face_value}x{count}")
        
#         variance = actual_total - theoretical_total
        
#         # إنشاء سجل الجرد بصمت
#         closure_id = f"CL-{now_time.strftime('%Y%m%d%H%M')}"
#         closure = DailyClosure.objects.create(
#             closed_by=request.user,
#             total_cash=theoretical_total,
#             actual_cash=actual_total,
#             variance=variance,
#             closure_id=closure_id,
#             notes=f"الفئات: {' | '.join(denominations)} -- ملاحظات: {request.POST.get('notes', '')}"
#         )
        
#         # العودة لصفحة الخزينة بصمت تام (تم إلغاء كافة الرسائل)
#         return redirect('daily_cashier_summary')
    
#     return redirect('daily_cashier_summary')        
   

# @staff_member_required
# @transaction.atomic
# def close_daily_accounts_view(request):
#     """إغلاق الخزينة الموحد (طلاب + مصروفات + عمليات عامة) - بصمت تام"""
#     if request.method == "POST":
#         now_time = timezone.now()
        
#         # 1. جلب العمليات المفتوحة (إيرادات ومصروفات)
#         open_student_payments = Payment.objects.filter(is_closed=False)
#         # تمت إضافة الاستبعاد لحمايتك من الحساب المزدوج بصمت
#         open_ledger_entries = GeneralLedger.objects.filter(is_closed=False).exclude(category='fees')
#         open_expenses = Expense.objects.filter(is_closed=False)

#         # 2. حساب الإجماليات النظرية
#         total_student = open_student_payments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
#         total_ledger = open_ledger_entries.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
#         total_expenses = open_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        
#         # المعادلة: (إجمالي المقبوضات) - (إجمالي المصروفات)
#         theoretical_total = (total_student + total_ledger) - total_expenses
        
#         # إذا كانت الخزينة فارغة، نعود بصمت بدون أي رسائل
#         if theoretical_total <= 0 and not open_expenses.exists():
#             return redirect('daily_cashier_summary')

#         # 3. حساب المبلغ الفعلي من نموذج العد (الفئات النقدية)
#         actual_total = Decimal('0.00')
#         denominations = []
#         for key, value in request.POST.items():
#             if key.startswith('denom_'):
#                 count = int(value or 0)
#                 if count > 0:
#                     try:
#                         face_value = Decimal(key.replace('denom_', ''))
#                         actual_total += (face_value * count)
#                         denominations.append(f"{face_value}x{count}")
#                     except: continue
        
#         actual_total += Decimal(request.POST.get('extra_cash', '0'))
#         variance = actual_total - theoretical_total
        
#         # 4. إنشاء سجل الإغلاق الموحد (مرة واحدة فقط بعد الحساب)
#         closure_id = f"CL-{now_time.strftime('%Y%m%d%H%M')}"
#         closure = DailyClosure.objects.create(
#             closed_by=request.user,
#             total_cash=theoretical_total,
#             actual_cash=actual_total,
#             variance=variance,
#             closure_id=closure_id,
#             notes=f"الفئات: {' | '.join(denominations)} -- ملاحظات: {request.POST.get('notes', '')}"
#         )
        
#         # 5. القفل النهائي لجميع المصادر وربطها بسجل الجرد
#         open_student_payments.update(closure=closure, is_closed=True)
#         open_expenses.update(closure=closure, is_closed=True)
#         open_ledger_entries.update(closure=closure, is_closed=True) 
        
#         # 6. عودة صامتة تماماً (تم إلغاء رسائل التغذية الراجعة)
#         return redirect('daily_cashier_summary')
    
#     return redirect('daily_cashier_summary')


def promote_student_action(student_id, target_year_id, target_grade_id):
    from finance.models import StudentAccount, RevenueCategory
    from decimal import Decimal
    from django.utils import timezone
    from django.db import transaction

    try:
        # 🛡️ استخدام select_for_update بيقفل سجل الطالب في قاعدة البيانات 
        # عشان لو اتنين موظفين ضغطوا ترحيل في نفس الثانية، واحد بس اللي ينفذ
        with transaction.atomic():
            try:
                student = Student.objects.select_for_update().get(id=student_id)
                target_year = AcademicYear.objects.get(id=target_year_id)
                target_grade = Grade.objects.get(id=target_grade_id)
            except (Student.DoesNotExist, AcademicYear.DoesNotExist, Grade.DoesNotExist):
                return False

            # 🚫 منع الترحيل لنفس السنة الحالية (عشان م يحصلش تكرار مديونية)
            if str(student.academic_year_id) == str(target_year_id):
                return False

            # 1️⃣ الحساب المالي الدقيق (الخطوة الأهم)
            # بنحسب المتبقي على الطالب وهو لسه في "السنة القديمة"
            debt_to_carry = student.final_remaining 

            # 2️⃣ تحديث بيانات الطالب للسنة الجديدة
            student.academic_year = target_year
            student.grade = target_grade
            student.enrollment_status = "Promoted" # تحديث حالته لناجح/منقول
            student.classroom = None               # تصفير الفصل لحين توزيعه يدوياً
            student.last_promotion_date = timezone.now().date()

            # 3️⃣ ترحيل المديونية
            # لو الطالب عليه 500 جنيه متبقية، بتتحول لـ "مديونية سابقة" في السنة الجديدة
            # max(0) بتضمن إن لو الطالب ليه فلوس (رصيد دائن) م تتحولش لمديونية غلط
            student.previous_debt = max(Decimal('0.00'), debt_to_carry)
            
            student.save()

            # 4️⃣ تجهيز السجل المالي الجديد
            # بنبحث عن بند "المصروفات الدراسية" عشان نفتح بيه الحساب الجديد
            main_category = RevenueCategory.objects.filter(name__icontains="مصروف").first()

            # إنشاء أو تحديث حساب الطالب في السنة الجديدة بقيمة 0 
            # لحد ما المدير يدخل يعمل "تسكين" ويحدد المصاريف الجديدة
            StudentAccount.objects.update_or_create(
                student=student,
                academic_year=target_year,
                revenue_category=main_category,
                defaults={
                    "total_fees": Decimal("0.00"),
                    "discount": Decimal("0.00")
                }
            )

            return True

    except Exception as e:
        print(f"❌ حدث خطأ أثناء ترحيل الطالب {student_id}: {str(e)}")
        return False
    
    
def student_finance_detail(request, student_id):
    back_url = request.META.get('HTTP_REFERER', '/')
    student = get_object_or_404(Student, id=student_id)
    active_year = student.academic_year
    
    all_installments = StudentInstallment.objects.filter(
        student=student,
        academic_year=active_year
    ).order_by('due_date')
    
    # 1. إجمالي المستحق من الخطة
    total_required = all_installments.aggregate(Sum('amount_due'))['amount_due__sum'] or 0
    
    # 2. إجمالي المسدد فعلياً
    total_paid = Payment.objects.filter(
        student=student,
        academic_year=active_year,
        revenue_category__name__icontains="مصروف"
    ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0

    # 3. إجمالي المتبقي الكلي (المعادلة المطلوبة)
    total_remaining = total_required - total_paid

    # توزيع المبالغ للعرض في الجدول
    temp_pool = total_paid
    for inst in all_installments:
        pay_for_this = min(temp_pool, inst.amount_due)
        inst.display_paid = pay_for_this
        inst.display_remaining = inst.amount_due - pay_for_this
        temp_pool -= pay_for_this

    context = {
        'student': student,
        'back_url': back_url, # نرسل الرابط للـ HTML
        'installments': all_installments,
        'total_required': total_required,
        'total_paid': total_paid,
        'total_remaining': total_remaining, # القيمة الجديدة
    }
    return render(request, 'finance/student_finance_detail.html', context)

   
    
@login_required
def overdue_report(request):
    from django.db.models import Sum
    from finance.models import StudentInstallment, Payment
    
    today = timezone.now().date()
    
    # 1. جلب الأقساط التي حل موعدها ولم تدفع بالكامل (حسب حالة القسط)
    overdue_qs = StudentInstallment.objects.filter(
        due_date__lt=today,
        status__in=['Pending', 'Partial']
    ).select_related('student', 'student__grade')

    overdue_items = []
    total_overdue_sum = 0

    for inst in overdue_qs:
        # 2. التغيير الجوهري: حساب كل ما دفعه الطالب فعلياً من جدول Payment 
        # نجمع كل المبالغ بغض النظر عن الفئة (كتب، مصروفات، بليل...)
        total_paid_from_table = Payment.objects.filter(
            student=inst.student,
            academic_year=inst.academic_year
        ).aggregate(total=Sum('amount_paid'))['total'] or 0

        # 3. تحديث قيم العرض يدوياً (Manual Overriding)
        # هنا نجعل "المسدد" هو ما وجدناه في جدول المدفوعات
        inst.display_paid = total_paid_from_table
        
        # 4. حساب المتبقي الحقيقي: (قيمة القسط - ما تم دفعه لهذا العام)
        # ملاحظة: إذا كان الطالب مسدد أكثر من قيمة هذا القسط (لقسط سابق مثلاً)
        # الحسبة هنا تعتمد على منطقك في توزيع المدفوعات
        inst.display_remaining = max(0, inst.amount_due - total_paid_from_table)

        total_overdue_sum += inst.display_remaining
        overdue_items.append(inst)

    context = {
        'overdue_items': overdue_items,
        'total_overdue': total_overdue_sum,
        'today': today,
    }
    return render(request, 'finance/overdue_report.html', context)


    


def debt_report(request):
    # 1. جلب المدخلات
    year_id = request.GET.get('academic_year')
    search_query = request.GET.get('q', '').strip()
    
    if not year_id:
        active_year = get_active_year()
        year_id = active_year.id if active_year else None
    
    years = AcademicYear.objects.all().order_by('-name')
    
    # 2. بناء الفلاتر
    installments_filter = Q(installments__academic_year_id=year_id) if year_id else Q()
    student_filter = Q()
    if search_query:
        student_filter = (
            Q(first_name__icontains=search_query) | 
            Q(last_name__icontains=search_query) | 
            Q(student_code__icontains=search_query)
        )

    # 3. الاستعلام المجمع بأسماء حقول جديدة لتجنب الـ AttributeError
    # لاحظ تغيير الأسماء إلى (calc_required, calc_paid, calc_old)
    students_with_debt = Student.objects.filter(student_filter).annotate(
        calc_required=Coalesce(
            Sum('installments__amount_due', filter=installments_filter), 
            Decimal('0'), 
            output_field=DecimalField()
        ),
        calc_paid=Coalesce(
            Sum('installments__paid_amount', filter=installments_filter), 
            Decimal('0'), 
            output_field=DecimalField()
        ),
        calc_old=Coalesce(F('previous_debt'), Decimal('0'), output_field=DecimalField())
    ).annotate(
        # حساب المجموع الكلي والمتبقي بأسماء لا تتصادم مع الموديل
        calc_total_req=F('calc_old') + F('calc_required'),
        calc_remaining=F('calc_old') + F('calc_required') - F('calc_paid')
    ).filter(
        calc_remaining__gt=0 
    ).select_related('grade').order_by('-calc_remaining')

    # 4. تجهيز البيانات للقالب
    report_data = []
    total_sum_all_students = 0
    
    for s in students_with_debt:
        report_data.append({
            'student': s,
            'required': s.calc_total_req, 
            'paid': s.calc_paid,
            'remaining': s.calc_remaining,
            'has_old_debt': s.calc_old > 0
        })
        total_sum_all_students += s.calc_remaining

    try:
        selected_year_context = int(year_id) if year_id else None
    except (ValueError, TypeError):
        selected_year_context = None

    return render(request, 'finance/debt_report.html', {
        'report_data': report_data,
        'years': years,
        'selected_year': selected_year_context,
        'total_debts_sum': total_sum_all_students,
        'search_query': search_query,
    })


# =====================================================
# 🔍 AJAX - جلب الطلاب حسب السنة (Select2)
# =====================================================

def get_students_by_year(request):
    query = request.GET.get('q', '')
    year_id = request.GET.get('academic_year', None)
    
    # فلترة الطلاب النشطين
    students = Student.objects.filter(is_active=True)

    # فلترة حسب السنة الدراسية إذا أرسلت
    if year_id and year_id.isdigit():
        students = students.filter(academic_year_id=int(year_id))
    
    # البحث الذكي بالاسم الأول أو الأخير أو الكود
    if query:
        students = students.filter(
            Q(first_name__icontains=query) | 
            Q(last_name__icontains=query) | 
            Q(student_code__icontains=query)
        )

    # تجهيز النتائج لتناسب Select2 (id و text)
    results = [
        {
            'id': student.id,
            'text': f"{student.first_name} {student.last_name} - ({student.student_code})"
        } 
        for student in students[:30] # عرض أول 30 نتيجة لسرعة الأداء
    ]
    
    return JsonResponse({'results': results})
# =====================================================
# 🛡️ صلاحيات
# =====================================================
def superuser_only(user):
    return user.is_authenticated and user.is_superuser


@login_required
def finance_dashboard(request):
    # يُفترض أن دالة get_active_year مستوردة
    active_year = get_active_year()
    if not active_year:
        return render(request, "finance/dashboard.html", {"error": "⚠️ لا توجد سنة نشطة."})

    # إجبار النظام على توقيت مصر
    try:
        import zoneinfo
        egypt_tz = zoneinfo.ZoneInfo("Africa/Cairo")
        local_now = timezone.now().astimezone(egypt_tz)
    except ImportError:
        import pytz
        egypt_tz = pytz.timezone('Africa/Cairo')
        local_now = timezone.now().astimezone(egypt_tz)
        
    today = local_now.date() 

    from treasury.models import GeneralLedger
    from students.models import Student, Grade 
    from finance.models import StudentInstallment, MonthlyClosure, StudentRefund # 🟢 إضافة استيراد المرتجعات

    # ==============================================================
    # 🟢 1. البيانات الحية السريعة (Live Data - لا تدخل الكاش لتبقى لحظية)
    # ==============================================================
    # 🟢 حساب إيراد اليوم الصافي (الإيراد - المرتجعات)
    today_revenue_gross = GeneralLedger.objects.filter(date__date=today).aggregate(total=Sum('amount'))['total'] or 0
    today_refunds = StudentRefund.objects.filter(refund_date=today).aggregate(total=Sum('amount'))['total'] or 0
    today_revenue_all = today_revenue_gross - today_refunds
    
    last_closure = MonthlyClosure.objects.order_by('-month').first()
    carried_balance = last_closure.closing_balance if last_closure else 0
    
    total_students_count = Student.objects.filter(academic_year=active_year).count()

    recent_activities = GeneralLedger.objects.filter(
        date__date=today,
        is_discount=False
    ).select_related('student', 'collected_by').order_by('-date')[:10]


    # ==============================================================
    # 🚀 2. البيانات الثقيلة (تقرأ من الكاش لتفتح في عُشر ثانية)
    # ==============================================================
    cache_key = f"finance_dashboard_heavy_stats_year_{active_year.id}_{today.strftime('%Y%m')}"
    heavy_stats = cache.get(cache_key)

    if not heavy_stats:
        # 🟢 حساب إيراد الشهر الصافي
        month_revenue_gross = GeneralLedger.objects.filter(date__month=today.month, date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0
        month_refunds = StudentRefund.objects.filter(refund_date__month=today.month, refund_date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0
        month_revenue_all = month_revenue_gross - month_refunds

        # 🟢 حساب إيراد العام الصافي
        year_revenue_gross = GeneralLedger.objects.filter(date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0
        year_refunds = StudentRefund.objects.filter(refund_date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0
        year_revenue_all = year_revenue_gross - year_refunds

        total_paid_students = StudentInstallment.objects.filter(academic_year=active_year).aggregate(total=Sum('paid_amount'))['total'] or 0
        total_fees_req = StudentInstallment.objects.filter(academic_year=active_year).aggregate(total=Sum('amount_due'))['total'] or 0
        total_old_debts = Student.objects.filter(academic_year=active_year).aggregate(total=Sum('previous_debt'))['total'] or 0
        
        total_target_all = total_fees_req + total_old_debts
        total_debt_combined = max(total_target_all - total_paid_students, 0)
        total_percentage = round((total_paid_students / total_target_all * 100), 1) if total_target_all > 0 else 0

        installments_agg = StudentInstallment.objects.filter(academic_year=active_year).values('student__grade__name').annotate(
            g_target=Sum('amount_due'), g_paid=Sum('paid_amount')
        )
        debt_agg = Student.objects.filter(academic_year=active_year).values('grade__name').annotate(
            g_old_debt=Sum('previous_debt')
        )

        grades_data = {grade.name: {'target': 0, 'paid': 0, 'old_debt': 0} for grade in Grade.objects.all()}

        for item in installments_agg:
            g_name = item['student__grade__name']
            if g_name in grades_data:
                grades_data[g_name]['target'] = item['g_target'] or 0
                grades_data[g_name]['paid'] = item['g_paid'] or 0

        for item in debt_agg:
            g_name = item['grade__name']
            if g_name in grades_data:
                grades_data[g_name]['old_debt'] = item['g_old_debt'] or 0

        grades_efficiency = []
        for g_name, data in grades_data.items():
            g_total_target = data['target'] + data['old_debt']
            g_paid = data['paid']
            grades_efficiency.append({
                'grade': g_name,
                'target': float(g_total_target),
                'paid': float(g_paid),
                'remaining': float(max(g_total_target - g_paid, 0)),
                'percentage': round((g_paid / g_total_target * 100), 1) if g_total_target > 0 else 0
            })

        heavy_stats = {
            "month_revenue_all": float(month_revenue_all),
            "year_revenue_all": float(year_revenue_all),
            "total_debt_combined": float(total_debt_combined),
            "total_percentage": float(total_percentage),
            "grades_efficiency": grades_efficiency,
        }
        # حفظ في الكاش لمدة 30 دقيقة
        cache.set(cache_key, heavy_stats, 1800)

    # ==============================================================
    # 3. بناء الكونتيكست وإرساله للـ HTML
    # ==============================================================
    context = {
        "active_year": active_year,
        "current_time": local_now,
        "today_revenue_all": today_revenue_all, 
        "carried_balance": carried_balance,
        "last_closure": last_closure,
        "total_students_count": total_students_count,
        "recent_activities": recent_activities,
        
        # استخراج البيانات المخبأة من الكاش
        "month_revenue_all": heavy_stats["month_revenue_all"],
        "year_revenue_all": heavy_stats["year_revenue_all"],
        "total_debt_combined": heavy_stats["total_debt_combined"],
        "total_percentage": heavy_stats["total_percentage"],
        "grades_efficiency": heavy_stats["grades_efficiency"],
    }
    return render(request, 'finance/dashboard.html', context)


# @login_required
# def finance_dashboard(request):
#     # يُفترض أن دالة get_active_year مستوردة
#     active_year = get_active_year()
#     if not active_year:
#         return render(request, "finance/dashboard.html", {"error": "⚠️ لا توجد سنة نشطة."})

#     # إجبار النظام على توقيت مصر
#     try:
#         import zoneinfo
#         egypt_tz = zoneinfo.ZoneInfo("Africa/Cairo")
#         local_now = timezone.now().astimezone(egypt_tz)
#     except ImportError:
#         import pytz
#         egypt_tz = pytz.timezone('Africa/Cairo')
#         local_now = timezone.now().astimezone(egypt_tz)
        
#     today = local_now.date() 

#     from treasury.models import GeneralLedger
#     from students.models import Student, Grade 
#     from finance.models import StudentInstallment, MonthlyClosure

#     # ==============================================================
#     # 🟢 1. البيانات الحية السريعة (Live Data - لا تدخل الكاش لتبقى لحظية)
#     # ==============================================================
#     today_revenue_all = GeneralLedger.objects.filter(date__date=today).aggregate(total=Sum('amount'))['total'] or 0
    
#     last_closure = MonthlyClosure.objects.order_by('-month').first()
#     carried_balance = last_closure.closing_balance if last_closure else 0
    
#     total_students_count = Student.objects.filter(academic_year=active_year).count()

#     recent_activities = GeneralLedger.objects.filter(
#         date__date=today,
#         is_discount=False
#     ).select_related('student', 'collected_by').order_by('-date')[:10]


#     # ==============================================================
#     # 🚀 2. البيانات الثقيلة (تقرأ من الكاش لتفتح في عُشر ثانية)
#     # ==============================================================
#     cache_key = f"finance_dashboard_heavy_stats_year_{active_year.id}_{today.strftime('%Y%m')}"
#     heavy_stats = cache.get(cache_key)

#     if not heavy_stats:
#         # إذا لم يكن الكاش مسخناً، نحسبها ثم نحفظها
#         month_revenue_all = GeneralLedger.objects.filter(date__month=today.month, date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0
#         year_revenue_all = GeneralLedger.objects.filter(date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0

#         total_paid_students = StudentInstallment.objects.filter(academic_year=active_year).aggregate(total=Sum('paid_amount'))['total'] or 0
#         total_fees_req = StudentInstallment.objects.filter(academic_year=active_year).aggregate(total=Sum('amount_due'))['total'] or 0
#         total_old_debts = Student.objects.filter(academic_year=active_year).aggregate(total=Sum('previous_debt'))['total'] or 0
        
#         total_target_all = total_fees_req + total_old_debts
#         total_debt_combined = max(total_target_all - total_paid_students, 0)
#         total_percentage = round((total_paid_students / total_target_all * 100), 1) if total_target_all > 0 else 0

#         installments_agg = StudentInstallment.objects.filter(academic_year=active_year).values('student__grade__name').annotate(
#             g_target=Sum('amount_due'), g_paid=Sum('paid_amount')
#         )
#         debt_agg = Student.objects.filter(academic_year=active_year).values('grade__name').annotate(
#             g_old_debt=Sum('previous_debt')
#         )

#         grades_data = {grade.name: {'target': 0, 'paid': 0, 'old_debt': 0} for grade in Grade.objects.all()}

#         for item in installments_agg:
#             g_name = item['student__grade__name']
#             if g_name in grades_data:
#                 grades_data[g_name]['target'] = item['g_target'] or 0
#                 grades_data[g_name]['paid'] = item['g_paid'] or 0

#         for item in debt_agg:
#             g_name = item['grade__name']
#             if g_name in grades_data:
#                 grades_data[g_name]['old_debt'] = item['g_old_debt'] or 0

#         grades_efficiency = []
#         for g_name, data in grades_data.items():
#             g_total_target = data['target'] + data['old_debt']
#             g_paid = data['paid']
#             grades_efficiency.append({
#                 'grade': g_name,
#                 'target': g_total_target,
#                 'paid': g_paid,
#                 'remaining': max(g_total_target - g_paid, 0),
#                 'percentage': round((g_paid / g_total_target * 100), 1) if g_total_target > 0 else 0
#             })

#         heavy_stats = {
#             "month_revenue_all": month_revenue_all,
#             "year_revenue_all": year_revenue_all,
#             "total_debt_combined": total_debt_combined,
#             "total_percentage": total_percentage,
#             "grades_efficiency": grades_efficiency,
#         }
#         # حفظ في الكاش لمدة 30 دقيقة
#         cache.set(cache_key, heavy_stats, 1800)

#     # ==============================================================
#     # 3. بناء الكونتيكست وإرساله للـ HTML
#     # ==============================================================
#     context = {
#         "active_year": active_year,
#         "current_time": local_now,
#         "today_revenue_all": today_revenue_all, 
#         "carried_balance": carried_balance,
#         "last_closure": last_closure,
#         "total_students_count": total_students_count,
#         "recent_activities": recent_activities,
        
#         # استخراج البيانات المخبأة من الكاش
#         "month_revenue_all": heavy_stats["month_revenue_all"],
#         "year_revenue_all": heavy_stats["year_revenue_all"],
#         "total_debt_combined": heavy_stats["total_debt_combined"],
#         "total_percentage": heavy_stats["total_percentage"],
#         "grades_efficiency": heavy_stats["grades_efficiency"],
#     }
#     return render(request, 'finance/dashboard.html', context)

# @login_required
# def finance_dashboard(request):
#     # يُفترض أن دالة get_active_year مستوردة أو معرفة بالأعلى
#     active_year = get_active_year()
#     if not active_year:
#         return render(request, "finance/dashboard.html", {"error": "⚠️ لا توجد سنة نشطة."})

#     # 🟢 إجبار النظام على استخدام توقيت مصر بدقة
#     try:
#         import zoneinfo
#         egypt_tz = zoneinfo.ZoneInfo("Africa/Cairo")
#         local_now = timezone.now().astimezone(egypt_tz)
#     except ImportError:
#         import pytz
#         egypt_tz = pytz.timezone('Africa/Cairo')
#         local_now = timezone.now().astimezone(egypt_tz)
        
#     today = local_now.date() 

#     from treasury.models import GeneralLedger
#     from students.models import Student, Grade 
#     from finance.models import StudentInstallment, MonthlyClosure
    

#     # 1. إيرادات الخزينة (المحصل الفعلي)
#     today_revenue_all = GeneralLedger.objects.filter(date__date=today).aggregate(total=Sum('amount'))['total'] or 0
#     month_revenue_all = GeneralLedger.objects.filter(date__month=today.month, date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0
    
#     # 🟢 تعديل هام: تم إضافة فلتر السنة هنا حتى لا يجلب إيرادات كل السنوات السابقة منذ إنشاء النظام!
#     year_revenue_all = GeneralLedger.objects.filter(date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0

#     # 🟢 الإضافة الجديدة: جلب رصيد الخزينة المرحل من آخر إغلاق شهري
#     last_closure = MonthlyClosure.objects.order_by('-month').first()
#     carried_balance = last_closure.closing_balance if last_closure else 0

#     # 2. حساب إجمالي المدفوعات الحقيقي من واقع جدول الأقساط
#     total_paid_students = StudentInstallment.objects.filter(
#         academic_year=active_year
#     ).aggregate(total=Sum('paid_amount'))['total'] or 0

#     # 3. حساب المستهدف والمديونيات
#     total_fees_req = StudentInstallment.objects.filter(
#         academic_year=active_year
#     ).aggregate(total=Sum('amount_due'))['total'] or 0
    
#     all_students = Student.objects.filter(academic_year=active_year)
#     total_old_debts = all_students.aggregate(total=Sum('previous_debt'))['total'] or 0
    
#     total_target_all = total_fees_req + total_old_debts
#     total_debt_combined = max(total_target_all - total_paid_students, 0)

#     # ==============================================================
#     # 4. كفاءة الصفوف (🟢 تم تدمير الـ Loop وحلها بـ 3 استعلامات فقط)
#     # ==============================================================
    
#     # أ) تجميع المدفوعات والمستحقات لكل صف باستعلام واحد
#     installments_agg = StudentInstallment.objects.filter(
#         academic_year=active_year
#     ).values('student__grade__name').annotate(
#         g_target=Sum('amount_due'),
#         g_paid=Sum('paid_amount')
#     )
    
#     # ب) تجميع الديون القديمة لكل صف باستعلام واحد
#     debt_agg = all_students.values('grade__name').annotate(
#         g_old_debt=Sum('previous_debt')
#     )

#     # ج) تجهيز القاموس لدمج البيانات بسرعة البرق في الرامات وليس في الداتا بيز
#     grades_data = {}
#     for grade in Grade.objects.all():
#         grades_data[grade.name] = {'target': 0, 'paid': 0, 'old_debt': 0}

#     for item in installments_agg:
#         g_name = item['student__grade__name']
#         if g_name in grades_data:
#             grades_data[g_name]['target'] = item['g_target'] or 0
#             grades_data[g_name]['paid'] = item['g_paid'] or 0

#     for item in debt_agg:
#         g_name = item['grade__name']
#         if g_name in grades_data:
#             grades_data[g_name]['old_debt'] = item['g_old_debt'] or 0

#     # د) حساب النسبة النهائية للـ HTML
#     grades_efficiency = []
#     for g_name, data in grades_data.items():
#         g_total_target = data['target'] + data['old_debt']
#         g_paid = data['paid']
#         grades_efficiency.append({
#             'grade': g_name,
#             'target': g_total_target,
#             'paid': g_paid,
#             'remaining': max(g_total_target - g_paid, 0),
#             'percentage': round((g_paid / g_total_target * 100), 1) if g_total_target > 0 else 0
#         })

#     # 🟢 إضافة select_related لمنع N+1 Queries عند استدعاء اسم الطالب والموظف في الجدول السفلي
#     recent_activities = GeneralLedger.objects.filter(
#         date__date=today,
#         is_discount=False # اختياري: إذا كنت لا تريد عرض الخصومات في سجل الحركة
#     ).select_related('student', 'collected_by').order_by('-date')[:10]

#     context = {
#         "active_year": active_year,
#         "today_revenue_all": today_revenue_all, 
#         "month_revenue_all": month_revenue_all,
#         "year_revenue_all": year_revenue_all,
#         "carried_balance": carried_balance,
#         "last_closure": last_closure,
#         "total_debt_combined": total_debt_combined,
#         "total_percentage": round((total_paid_students / total_target_all * 100), 1) if total_target_all > 0 else 0,
#         "total_students_count": all_students.count(),
#         "grades_efficiency": grades_efficiency,
#         "recent_activities": recent_activities,
#         "current_time": local_now,
#     }
#     return render(request, 'finance/dashboard.html', context)


# @login_required
# def finance_dashboard(request):
#     active_year = get_active_year()
#     if not active_year:
#         return render(request, "finance/dashboard.html", {"error": "⚠️ لا توجد سنة نشطة."})

#     # 🟢 إجبار النظام على استخدام توقيت مصر بدقة
#     from django.utils import timezone
#     try:
#         import zoneinfo
#         egypt_tz = zoneinfo.ZoneInfo("Africa/Cairo")
#         local_now = timezone.now().astimezone(egypt_tz)
#     except ImportError:
#         import pytz
#         egypt_tz = pytz.timezone('Africa/Cairo')
#         local_now = timezone.now().astimezone(egypt_tz)
        
#     today = local_now.date() 

#     from treasury.models import GeneralLedger
#     from students.models import Student, Grade 
#     from finance.models import StudentInstallment, MonthlyClosure  # أضفنا MonthlyClosure هنا
#     from django.db.models import Sum

#     # 1. إيرادات الخزينة (المحصل الفعلي)
#     today_revenue_all = GeneralLedger.objects.filter(date__date=today).aggregate(total=Sum('amount'))['total'] or 0
#     month_revenue_all = GeneralLedger.objects.filter(date__month=today.month, date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0
#     year_revenue_all = GeneralLedger.objects.aggregate(total=Sum('amount'))['total'] or 0

#     # 🟢 الإضافة الجديدة: جلب رصيد الخزينة المرحل من آخر إغلاق شهري
#     last_closure = MonthlyClosure.objects.order_by('-month').first()
#     carried_balance = last_closure.closing_balance if last_closure else 0

#     # 2. حساب إجمالي المدفوعات الحقيقي من واقع جدول الأقساط
#     total_paid_students = StudentInstallment.objects.filter(
#         academic_year=active_year
#     ).aggregate(total=Sum('paid_amount'))['total'] or 0

#     # 3. حساب المستهدف والمديونيات
#     total_fees_req = StudentInstallment.objects.filter(
#         academic_year=active_year
#     ).aggregate(total=Sum('amount_due'))['total'] or 0
    
#     all_students = Student.objects.filter(academic_year=active_year)
#     total_old_debts = all_students.aggregate(total=Sum('previous_debt'))['total'] or 0
    
#     total_target_all = total_fees_req + total_old_debts
    
#     total_debt_combined = max(total_target_all - total_paid_students, 0)

#     # 4. كفاءة الصفوف
#     grades_efficiency = []
#     for grade in Grade.objects.all():
#         g_installments = StudentInstallment.objects.filter(student__grade=grade, academic_year=active_year)
#         if g_installments.exists():
#             g_target_fees = g_installments.aggregate(total=Sum('amount_due'))['total'] or 0
#             g_paid = g_installments.aggregate(total=Sum('paid_amount'))['total'] or 0
            
#             g_old_debt = all_students.filter(grade=grade).aggregate(total=Sum('previous_debt'))['total'] or 0
#             g_total_target = g_target_fees + g_old_debt

#             grades_efficiency.append({
#                 'grade': grade.name,
#                 'target': g_total_target,
#                 'paid': g_paid,
#                 'remaining': max(g_total_target - g_paid, 0),
#                 'percentage': round((g_paid / g_total_target * 100), 1) if g_total_target > 0 else 0
#             })

#     context = {
#         "active_year": active_year,
#         "today_revenue_all": today_revenue_all, 
#         "month_revenue_all": month_revenue_all,
#         "year_revenue_all": year_revenue_all,
#         "carried_balance": carried_balance,  # 🟢 متغير جديد للقالب
#         "last_closure": last_closure,        # 🟢 لإظهار اسم الشهر المغلق في القالب
#         "total_debt_combined": total_debt_combined,
#         "total_percentage": round((total_paid_students / total_target_all * 100), 1) if total_target_all > 0 else 0,
#         "total_students_count": all_students.count(),
#         "grades_efficiency": grades_efficiency,
#         "recent_activities": GeneralLedger.objects.filter(date__date=today).order_by('-date')[:10],
#         "current_time": local_now,
#     }
#     return render(request, 'finance/dashboard.html', context)

from django.urls import reverse

@staff_member_required
@transaction.atomic
def assign_plan(request, student_id=None):
    selected_student = None
    account = None
    # تحديد الطالب المستهدف سواء من الرابط أو من الـ GET parameter
    target_id = student_id or request.GET.get('student_id')
    
    if target_id:
        selected_student = get_object_or_404(Student, id=target_id)
        # جلب حساب الطالب للسنة الدراسية الحالية
        account = StudentAccount.objects.filter(
            student=selected_student, 
            academic_year=selected_student.academic_year
        ).first()

    # فحص إذا كان الطالب مسكناً بالفعل
    student_already_assigned = account and account.installment_plan is not None

    # القيد: الموظف لا يمكنه الدخول على طالب مسكن، الآدمن فقط من يمكنه التعديل
    if student_already_assigned and not request.user.is_superuser:
        messages.warning(request, "⚠️ هذا الطالب مسكن بالفعل. تعديل الخطة متاح لإدارة النظام فقط.")
        return redirect('student_list')

    if request.method == "POST":
        p_student_id = request.POST.get('student') or target_id
        plan_id = request.POST.get('plan_id') 
        discount_raw = request.POST.get('discount', '0')

        if not p_student_id or not plan_id:
            messages.error(request, "⚠️ يرجى اختيار الطالب والبرنامج المالي.")
            return redirect(request.path)

        try:
            student = Student.objects.get(id=p_student_id)
            plan = InstallmentPlan.objects.get(id=plan_id)
            discount_val = Decimal(discount_raw)

            # 1. تحديث الحساب المالي (Update or Create) لضمان عدم التكرار
            account_obj, created = StudentAccount.objects.get_or_create(
                student=student,
                academic_year=student.academic_year
            )
            
            account_obj.installment_plan = plan
            account_obj.total_fees = plan.total_amount
            account_obj.discount = discount_val
            account_obj.save()

            # 2. توليد الأقساط (حذف الأقساط الحالية وإعادة التوليد بناءً على الخطة الجديدة)
            # ملحوظة: يفضل التأكد من عدم وجود مبالغ محصلة قبل الحذف في نظامك
            StudentInstallment.objects.filter(
                student=student, 
                academic_year=student.academic_year
            ).delete()
            
            if hasattr(account_obj, 'generate_installments'):
                account_obj.generate_installments()

            # 3. الربط مع الخزينة (تحصيل الفائدة لمرة واحدة فقط)
            if plan.interest_value > 0:
                category, _ = RevenueCategory.objects.get_or_create(name='رسوم إدارية / فائدة خطة')
                
                # فحص إذا كانت الفائدة قد تم تحصيلها مسبقاً لهذا الطالب لنفس السنة
                interest_exists = Payment.objects.filter(
                    student=student, 
                    academic_year=student.academic_year,
                    revenue_category=category
                ).exists()

                if not interest_exists:
                    Payment.objects.create(
                        student=student,
                        academic_year=student.academic_year,
                        revenue_category=category,
                        amount_paid=plan.interest_value,
                        collected_by=request.user,
                        payment_date=timezone.now().date(),
                        notes=f"تحصيل قيمة الفائدة عند تسكين الخطة: {plan.name}"
                    )
        
            messages.success(request, f"✅ تم حفظ بيانات التسكين بنجاح للطالب {student.get_full_name()}")
            
            # التوجيه لشاشة التحصيل السريع
            target_url = f"{reverse('quick_collection')}?student_id={student.id}"
            return redirect(target_url)

        except Exception as e:
            messages.error(request, f"❌ خطأ تقني: {str(e)}")
            return redirect(request.path)

    # التحضير لعرض الصفحة (GET Request)
    active_year = AcademicYear.objects.filter(is_active=True).first()
    filtered_plans = InstallmentPlan.objects.filter(academic_year=active_year) if active_year else InstallmentPlan.objects.none()

    context = {
        'years': AcademicYear.objects.all().order_by('-id'),
        'plans': filtered_plans,
        'selected_student': selected_student,
        'account': account,
        'active_year': active_year,
        'student_already_assigned': student_already_assigned,
    }
    
    # ضمان وجود return HttpResponse في حالة الـ GET
    return render(request, 'finance/assign_plan.html', context)    

@user_passes_test(lambda u: u.is_superuser)
def generate_installments_view(request, account_id):
    """
    إعادة توليد الأقساط المالية للطالب:
    1. التحقق من صلاحية المدير.
    2. حذف الأقساط غير المدفوعة فقط.
    3. إنشاء أقساط جديدة بناءً على الخطة المحددة.
    """
    try:
        with transaction.atomic():
            # 1. جلب الحساب المالي للطالب
            account = get_object_or_404(StudentAccount, id=account_id)
            student = account.student
            plan = account.installment_plan

            if not plan:
                messages.error(request, "⚠️ الطالب لا يملك خطة دفع مسجلة. يرجى تعيين خطة أولاً.")
                return redirect('student_list')

            # 2. مسح الأقساط غير المدفوعة فقط لضمان عدم حذف أي دفعات تمت بالفعل
            # نستخدم filter مع is_paid=False لضمان الأمان
            StudentInstallment.objects.filter(student=student, is_paid=False).delete()

            # 3. جلب بنود الخطة وتجهيزها للإنشاء الجماعي
            plan_items = plan.items.all() 
            
            installments_to_create = [
                StudentInstallment(
                    student=student,
                    installment_name=item.installment_name,
                    amount=item.amount,
                    due_date=item.due_date,
                    academic_year=student.academic_year,
                    is_paid=False
                )
                for item in plan_items
            ]
            
            # 4. حفظ الأقساط الجديدة دفعة واحدة (Bulk Create)
            if installments_to_create:
                StudentInstallment.objects.bulk_create(installments_to_create)
                messages.success(request, f"✅ تم تحديث الخطة المالية للطالب {student.get_full_name()} وإعادة توليد {len(installments_to_create)} أقساط.")
            else:
                messages.warning(request, "⚠️ الخطة المختارة لا تحتوي على بنود أقساط.")
            
        return redirect('student_list')

    except Exception as e:
        messages.error(request, f"❌ حدث خطأ تقني أثناء التوليد: {str(e)}")
        return redirect('finance_dashboard')    



    
def get_student_balance(request, student_id):
    try:
        from django.http import JsonResponse
        from finance.models import StudentInstallment, StudentAccount, Payment
        from django.db.models import Sum
        from students.models import Student
        from decimal import Decimal

        # 1. جلب بيانات الطالب
        student = Student.objects.get(id=student_id)
        
        # جلب السنة الدراسية النشطة حالياً في النظام
        from finance.models import AcademicYear
        active_year = AcademicYear.objects.filter(is_active=True).first()
        year_filter = active_year.id if active_year else None

        # 2. حساب إجمالي المدفوعات الحية الحالية والخصومات من جدول الـ Payment مباشرة
        # (هذا الجدول هو مصدر الثقة والأمان لأنه معزول عن مشاكل كاش الأقساط والحسابات)
        payment_query = Payment.objects.filter(student_id=student_id, is_cancelled=False)
        if year_filter:
            payment_query = payment_query.filter(academic_year_id=year_filter)

        actual_payments_sum = payment_query.exclude(
            revenue_category__name__icontains="خصم"
        ).aggregate(sum=Sum('amount_paid'))['sum'] or Decimal("0.00")

        actual_discounts_sum = payment_query.filter(
            revenue_category__name__icontains="خصم"
        ).aggregate(sum=Sum('amount_paid'))['sum'] or Decimal("0.00")

        # 3. التحقق من وجود أقساط مسكنة للطالب لبيان إجمالي المطلوب
        installments = StudentInstallment.objects.filter(student_id=student_id)
        
        # جلب الحساب المالي للطالب
        student_account = StudentAccount.objects.filter(student_id=student_id)
        if year_filter:
            student_account = student_account.filter(academic_year_id=year_filter)
        student_account = student_account.first()

        if installments.exists():
            # 🔥 الحل العبقري: المطلوب هو مجموع مبالغ الأقساط المستحقة (amount_due) حياً
            total_required = installments.aggregate(sum=Sum('amount_due'))['sum'] or Decimal("0.00")
            
            # المتبقي الفعلي = إجمالي الأقساط المطلوبة - المدفوعات الحية - الخصومات الحية
            net_remaining = total_required - actual_payments_sum - actual_discounts_sum
        else:
            # 4. إذا لم يتم التسكين بعد، نستخدم الحساب التقليدي الحسابي من الموديل
            if student_account:
                # نعتمد على صافي الرسوم في الحساب (بعد الخصم إن وجد)
                total_fees = getattr(student_account, 'net_fees', Decimal("0.00")) or \
                             getattr(student_account, 'required_amount', Decimal("0.00")) or Decimal("0.00")
                
                old_debt = getattr(student, 'previous_debt', Decimal("0.00")) or \
                           getattr(student, 'old_debt', Decimal("0.00")) or Decimal("0.00")
                
                net_remaining = (total_fees + old_debt) - actual_payments_sum - actual_discounts_sum
            else:
                # خطة الطوارئ האחيرة في حال عدم وجود أي سجل مالي
                net_remaining = getattr(student, 'final_remaining', Decimal("0.00")) or Decimal("0.00")

        # 5. جلب الرسوم الإدارية من خطة الطالب
        admin_fee = 0
        if student_account and student_account.installment_plan:
            admin_fee = student_account.installment_plan.administrative_fee

        # تأمين ألا يرتد المتبقي بالسالب في الواجهة لأي سبب تنسيقي
        if net_remaining < 0:
            net_remaining = Decimal("0.00")

        return JsonResponse({
            "success": True,
            "current_due": float(net_remaining),    # يظهر في المربع الأحمر (المتأخرات/المطلوب حالياً)
            "total_debt": float(net_remaining),     # يظهر في المربع الأزرق (إجمالي المديونية)
            "total_remaining": float(net_remaining),# لضمان عمل الجافا سكريبت في quick_collection.html
            "admin_fee": float(admin_fee)           # تمرير الرسوم الإدارية
        })

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})
    


@user_passes_test(superuser_only)
def print_receipt(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id)
    student = payment.student

    # --- 1. العمليات الحسابية المضافة ---
    # حساب إجمالي ما دفعه الطالب حتى الآن (في جميع العمليات غير الملغاة)
    total_paid = Payment.objects.filter(student=student).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
    
    # حساب إجمالي المطلوب من الطالب (من حسابه المالي المربوط به)
    # ملاحظة: تأكد من مسمى العلاقة لديك، هنا افترضنا وجود finance_account
    total_required = 0
    if hasattr(student, 'finance_account'):
        total_required = student.finance_account.total_fees
    
    # المبلغ المتبقي الإجمالي على الطالب
    remaining_balance = total_required - total_paid

    # --- 2. إنشاء ملف PDF ---
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{payment.id}.pdf"'

    p = canvas.Canvas(response)
    
    # الإعدادات الرأسية
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, 800, "Payment Receipt")
    
    p.setFont("Helvetica", 12)
    student_name = f"{student.first_name} {student.last_name}" if student else "N/A"
    
    p.drawString(100, 770, f"Student: {student_name}")
    p.drawString(100, 750, f"Current Amount: {payment.amount_paid} EGP")
    p.drawString(100, 730, f"Category: {payment.revenue_category.name}")
    p.drawString(100, 710, f"Date: {payment.payment_date}")

    # --- 3. إضافة البيانات المالية الجديدة (شغل عالي) ---
    p.setDash(1, 2) # رسم خط منقط للفصل
    p.line(100, 690, 500, 690)
    p.setDash() # عودة للخط المتصل
    
    p.setFont("Helvetica-Bold", 12)
    p.drawString(100, 670, f"Total Paid to Date: {total_paid} EGP")
    
    # تلوين النص المتبقي بالأحمر (اختياري إذا كانت المكتبة تدعم الألوان لديك)
    p.setFillColorRGB(0.8, 0, 0) # لون أحمر بسيط
    p.drawString(100, 650, f"Remaining Balance: {remaining_balance} EGP")
    p.setFillColorRGB(0, 0, 0) # العودة للأسود

    p.showPage()
    p.save()

    return response

# =====================================================
# 🔒 إقفال الشهر
# =====================================================
# =====================================================
# 📊 API Dashboard Summary
# =====================================================

# تأكد من استيراد الموديلات الخاصة بك
# from .models import Payment, StudentInstallment, Grade, Student, get_active_year

class DashboardSummaryAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year = get_active_year()
        if not year:
            return Response({"error": "لا توجد سنة دراسية نشطة حالياً"}, status=404)

        today = timezone.now().date()
        
        # --- 1. الحسابات المالية الكلية (تم التحديث ليدعم الإضافية) ---
        today_payments_qs = Payment.objects.filter(
            academic_year=year, 
            payment_date=today
        )
        
        total_today = today_payments_qs.aggregate(t=Sum('amount_paid'))['t'] or 0
        
        # تفصيل تحصيل اليوم (تعليم vs باص vs إضافية)
        today_academic = today_payments_qs.filter(
            revenue_category__name__icontains='تعليم'
        ).aggregate(t=Sum('amount_paid'))['t'] or 0
        
        today_extra = today_payments_qs.filter(
            revenue_category__name__icontains='اضافيه'
        ).aggregate(t=Sum('amount_paid'))['t'] or 0
        
        # الباص هو الباقي من الإجمالي بعد خصم التعليم والإضافي
        today_bus = total_today - today_academic - today_extra

        # إجمالي ما تم تحصيله فعلياً خلال السنة
        total_collected = Payment.objects.filter(
            academic_year=year
        ).aggregate(t=Sum('amount_paid'))['t'] or 0

        # --- 2. المديونيات (ستقرأ أرقاماً بمجرد عمل التسكين) ---
        total_due_target = StudentInstallment.objects.filter(
            academic_year=year
        ).aggregate(t=Sum('amount_due'))['t'] or 0
        
        total_remaining = max(0, total_due_target - total_collected)
        
        # --- 3. نظام التنبيهات (المتأخرين) ---
        late_installments = StudentInstallment.objects.filter(
            academic_year=year,
            status='Late',
            due_date__lt=today
        ).select_related('student').order_by('-amount_due')[:5]

        alerts_data = [
            {
                "student": f"{item.student.first_name} {item.student.last_name}",
                "amount": float(item.amount_due),
                "days_late": (today - item.due_date).days,
                "phone": getattr(item.student, 'parent_phone', "") 
            } for item in late_installments
        ]

        # --- 4. تحليل كفاءة الصفوف ---
        grade_analysis = []
        for grade in Grade.objects.all():
            g_target = StudentInstallment.objects.filter(
                academic_year=year, 
                student__grade=grade
            ).aggregate(t=Sum('amount_due'))['t'] or 0
            
            # عرض الصف حتى لو المستهدف 0 لمتابعة عملية التسكين
            g_collected = Payment.objects.filter(
                academic_year=year, 
                student__grade=grade
            ).aggregate(t=Sum('amount_paid'))['t'] or 0
            
            grade_analysis.append({
                "name": grade.name,
                "target": float(g_target),
                "collected": float(g_collected),
                "remaining": float(max(0, g_target - g_collected)),
            })

        # --- 5. الرد النهائي ---
        return Response({
            "total_collected": float(total_collected),
            "total_today": float(total_today),
            "today_academic": float(today_academic),
            "today_bus": float(today_bus),
            "today_extra": float(today_extra),  # الحقل الجديد للداشبورد
            "total_remaining": float(total_remaining),
            "total_target": float(total_due_target),
            "total_students": Student.objects.filter(is_active=True).count(),
            "overdue_installments_count": len(late_installments),
            "alerts": alerts_data,
            "grade_analysis": grade_analysis,
            "recent_payments": [
                {
                    "student_name": f"{p.student.first_name} {p.student.last_name}",
                    "amount_paid": float(p.amount_paid),
                    "category": p.revenue_category.name if p.revenue_category else "عام"
                } for p in Payment.objects.filter(academic_year=year).order_by('-payment_date')[:5]
            ]
        })


@staff_member_required
def installment_plan_list(request):
    """عرض قائمة بخطط التقسيط المتاحة للعام الدراسي النشط فقط"""
    
    # 1. جلب العام الدراسي النشط
    active_year = AcademicYear.objects.filter(is_active=True).first()
    
    # 2. فلترة الخطط لتكون تابعة للعام النشط فقط (مع الاحتفاظ بـ prefetch_related لتحسين الأداء)
    if active_year:
        plans = InstallmentPlan.objects.prefetch_related('items').filter(academic_year=active_year)
    else:
        # في حالة عدم وجود عام دراسي نشط، نرجع قائمة فارغة لتجنب الأخطاء
        plans = InstallmentPlan.objects.none()
        
    context = {
        'plans': plans,
        'active_year': active_year, # تمرير العام النشط للواجهة قد يكون مفيداً لعرضه في العنوان
    }
    
    return render(request, 'finance/plan_list.html', context)  

# @staff_member_required
# def installment_plan_list(request):
#     """عرض قائمة بجميع خطط التقسيط المتاحة في المدرسة"""
#     # جلب جميع الخطط مع بنودها (الأقساط) لتحسين الأداء
#     plans = InstallmentPlan.objects.prefetch_related('items').all()
#     return render(request, 'finance/plan_list.html', {'plans': plans})



def get_financial_dashboard_stats():
    # استخدام annotate لجلب إجمالي مديونية كل طالب في استعلام واحد
    stats = StudentAccount.objects.annotate(
        # إجمالي ما دفعه الطالب من الأقساط المرتبطة به
        actual_paid=Sum('student__installments__paid_amount'),
        # إجمالي الأقساط التي حل موعدها ولم تدفع بالكامل (المتأخرات)
        overdue_amount=Sum(
            'student__installments__amount_due',
            filter=Q(student__installments__due_date__lt=date.today(), 
                     student__installments__status__in=['Pending', 'Partial'])
        )
    ).values('student__user__first_name', 'total_fees', 'actual_paid', 'overdue_amount')
    
    return stats
@transaction.atomic
def trigger_daily_closure(request):
    """إغلاق الخزينة لمدفوعات الطلاب وعمليات الخزينة الموحدة لليوم"""
    if request.method == "POST":
        from treasury.models import GeneralLedger
        from django.db.models import Sum
        from django.contrib import messages  # تأكد من استيراد messages في أعلى الملف
        
        today = timezone.now().date()
        
        # 1. جلب العمليات (طلاب: المفتوحة فقط | خزينة: عمليات اليوم)
        student_payments = Payment.objects.filter(is_closed=False)
        ledger_entries = GeneralLedger.objects.filter(date__date=today)

        # حساب الإجماليات
        total_student = student_payments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
        total_ledger = ledger_entries.aggregate(Sum('amount'))['amount__sum'] or 0
        
        total_to_close = total_student + total_ledger
        
        # التحقق من وجود مبالغ للإغلاق
        if total_to_close == 0:
            messages.warning(request, "لا توجد عمليات مفتوحة لإغلاقها اليوم!")
            return redirect('daily_cashier_summary')

        # 2. إنشاء سجل الإغلاق (Daily Closure)
        closure_id = f"CL-{timezone.now().strftime('%Y%m%d%H%M')}"
        
        # ملاحظة: بما أنك ألغيت اللوجن، request.user قد يكون فارغاً (AnonymousUser)
        # إذا أعطاك خطأ في closed_by، يمكنك وضع None أو مستخدم افتراضي
        closure = DailyClosure.objects.create(
            closed_by=request.user if request.user.is_authenticated else None,
            total_cash=total_to_close,
            closure_id=closure_id
        )

        # 3. تحديث الحسابات وقفل العمليات
        updated_student_count = student_payments.update(closure=closure, is_closed=True)
        updated_ledger_count = ledger_entries.count() 
        
        total_updated = updated_student_count + updated_ledger_count
        
        messages.success(request, f"تم الإغلاق بنجاح برقم {closure_id}. إجمالي العمليات: {total_updated}")
        return redirect('daily_cashier_summary')
    
    return redirect('daily_cashier_summary')

@user_passes_test(is_manager, login_url='/login/')
def manual_finance_enroll(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    
    try:
        with transaction.atomic():
            # سنكتفي بإنشاء السجل بالحد الأدنى من الحقول لمنع أخطاء الأسماء
            account, created = StudentAccount.objects.get_or_create(
                student=student,
                academic_year=student.academic_year,
                defaults={
                    'total_fees': 0,
                    # حذفنا remaining_amount لأنه هو سبب الخطأ في الصورة
                }
            )
            
            if created:
                messages.success(request, f"✅ تم تفعيل الملف المالي لـ {student.first_name} بنجاح.")
            else:
                messages.info(request, "الطالب لديه ملف مالي مفعل بالفعل.")

    except Exception as e:
        # هذا سيظهر لك اسم الحقل الخطأ لو وجد غيره
        messages.error(request, f"❌ حدث خطأ أثناء التفعيل: {str(e)}")

    return redirect(request.META.get('HTTP_REFERER', 'student_list'))

@login_required
@user_passes_test(is_manager, login_url='/login/')
def receipt_books_list(request):
    """صفحة تعرض جميع الدفاتر ونسبة استخدامها مع إمكانية فلترة اليوم فقط"""
    # 1. التحقق مما إذا كان المستخدم ضغط على زر فلترة اليوم
    filter_today = request.GET.get('filter') == 'today'
    today = timezone.now().date()
    
    books = ReceiptBook.objects.select_related('user').all().order_by('-is_active', '-created_at')
    
    books_data = []
    for book in books:
        # جميع الإيصالات المقطوعة من هذا الدفتر
        payments_qs = Payment.objects.filter(
            collected_by=book.user,
            receipt_number__gte=book.start_serial,
            receipt_number__lte=book.end_serial
        )
        
        # حساب الإجمالي وحساب ما تم قطعه اليوم فقط
        total_used_count = payments_qs.count()
        today_used_count = payments_qs.filter(payment_date=today).count()
        
        # إذا تم تفعيل الفلتر ولم يتم استخدام هذا الدفتر اليوم، يتم إخفاؤه
        if filter_today and today_used_count == 0:
            continue
            
        # الرقم المعروض سيعتمد على الفلتر (إما كل الإيصالات أو إيصالات اليوم فقط)
        display_count = today_used_count if filter_today else total_used_count
        
        total_count = (book.end_serial - book.start_serial) + 1
        progress_percentage = (display_count / total_count) * 100 if total_count > 0 else 0
        
        books_data.append({
            'book': book,
            'used_count': display_count,
            'total_count': total_count,
            'progress': round(progress_percentage, 1),
        })
        
    return render(request, 'finance/receipt_books_list.html', {
        'books_data': books_data,
        'filter_today': filter_today # نرسلها للواجهة لتغيير شكل الزر
    })

    context = {
        'book': book,
        'receipts_data': receipts_data,
        'used_count': payments.count(),
        'total_count': len(all_receipts),
        'total_collected': total_collected,
    }
    
    # تأكد أن هذا السطر مكتوب هكذا بالأقواس، وليس return render فقط
    return render(request, 'finance/receipt_book_detail.html', context)



@login_required
@user_passes_test(is_manager, login_url='/login/')
def receipt_book_detail(request, book_id):
    """صفحة تعرض تفاصيل الإيصالات وحالتها داخل دفتر محدد"""
    book = get_object_or_404(ReceiptBook, id=book_id)
    
    # جلب جميع المدفوعات المسجلة من هذا الدفتر
    payments = Payment.objects.filter(
        collected_by=book.user,
        receipt_number__gte=book.start_serial,
        receipt_number__lte=book.end_serial
    ).select_related('student', 'revenue_category').order_by('receipt_number')

    # تحويل البيانات لقاموس لسهولة البحث برقم الإيصال
    used_receipts_map = {p.receipt_number: p for p in payments}
    all_receipts = range(book.start_serial, book.end_serial + 1)
    
    receipts_data = []
    total_collected = Decimal('0.00')
    
    # المرور على كل أوراق الدفتر وتحديد حالتها
    for r_num in all_receipts:
        payment = used_receipts_map.get(r_num)
        if payment:
            total_collected += payment.amount_paid
            
        receipts_data.append({
            'number': r_num,
            'payment': payment,
            'status': 'مستخدم' if payment else 'فارغ'
        })

    context = {
        'book': book,
        'receipts_data': receipts_data,
        'used_count': payments.count(),
        'total_count': len(all_receipts),
        'total_collected': total_collected,
    }
    
    # تأكد أن هذا السطر مكتوب هكذا بالأقواس، وليس return render فقط
    return render(request, 'finance/receipt_book_detail.html', context)



# أضف هذه الدالة في آخر الملف
def archives_list_view(request):
    # 1. جلب السنوات المؤرشفة
    past_years = AcademicYear.objects.filter(is_active=False).order_by('-name')
    
    # 2. استقبال الطلب لسنة معينة
    selected_year_id = request.GET.get('year_id')
    selected_year = None
    students_data = None

    if selected_year_id:
        selected_year = get_object_or_404(AcademicYear, id=selected_year_id)
        students_data = Student.objects.filter(academic_year=selected_year)

    # 3. تجهيز القاموس
    context = {
        'past_years': past_years,
        'selected_year': selected_year,
        'students_data': students_data,
    }
    
    # 4. الإرجاع (تأكد من كتابة context هنا وليس يدوياً)
    return render(request, 'archives/archives_main.html', context)

@login_required
def validate_coupon_advanced(request):
    """
    دالة التحقق المحدثة (تدعم الأقسام والطلاب الخارجيين)
    """
    code = request.GET.get('code')
    student_id = request.GET.get('student_id')
    category_selected = request.GET.get('category', 'all') # استقبال القسم من الجافاسكريبت
    
    if not code or not student_id:
        return JsonResponse({'status': 'error', 'message': '❌ بيانات ناقصة (كود الخصم أو الطالب)'})

    try:
        coupon = Coupon.objects.get(code=code)
        
        # 1. التحقق من القسم المسموح به للكوبون
        if coupon.allowed_category != 'all' and coupon.allowed_category != category_selected:
            msg = f"❌ هذا الكوبون مخصص لـ {coupon.get_allowed_category_display()} ولا يمكن استخدامه هنا."
            return JsonResponse({'status': 'error', 'message': msg})

        # 2. التعامل مع الطالب (مسجل أم خارجي جديد)
        if student_id == 'external_new':
            student = None
        else:
            student = get_object_or_404(Student, id=student_id)

        # 3. التحقق من صلاحية الكوبون
        if coupon.check_validity(student=student):
            discount_info = f"{coupon.discount_value}%" if coupon.discount_type == 'percentage' else f"{coupon.discount_value} ج.م"
            
            return JsonResponse({
                'status': 'success',
                'message': f'✅ تم تطبيق خصم {coupon.get_offer_type_display()}',
                'discount_type': coupon.discount_type,
                'discount_value': float(coupon.discount_value),
                'offer_type': coupon.offer_type,
                'display_msg': f"خصم بمقدار {discount_info}"
            })
        else:
            msg = "❌ هذا الكود غير صالح لهذا الطالب أو انتهت صلاحيته"
            if coupon.offer_type == 'new_student':
                msg = "❌ هذا الخصم مخصص للطلاب الجدد فقط"
            elif coupon.offer_type == 'specific_student':
                msg = "❌ الطالب المختار غير مدرج في قائمة المستفيدين من هذا العرض"
                
            return JsonResponse({'status': 'error', 'message': msg})

    except Coupon.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': '❌ كود الخصم غير موجود'})

@login_required
def create_offer_view(request):
    """
    دالة إنشاء العروض النظيفة (بدون أخطاء الخزائن)
    """
    # 🟢 التعديل السحري هنا: جلب الطلاب النشطين فقط، وتحميل الحقول الضرورية فقط لتوفير 90% من استهلاك الرامات!
    students = Student.objects.filter(is_active=True).only(
        'id', 'first_name', 'last_name', 'student_code'
    ).order_by('first_name') 
    
    if request.method == 'POST':
        code = request.POST.get('code')
        offer_type = request.POST.get('offer_type')
        discount_type = request.POST.get('discount_type')
        discount_value = request.POST.get('discount_value')
        
        # معالجة التواريخ إذا كانت فارغة
        start_date = request.POST.get('start_date') or None
        expiry_date = request.POST.get('expiry_date') or None
        
        usage_limit = request.POST.get('usage_limit', 1)
        allowed_category = request.POST.get('allowed_category', 'all')
        
        try:
            new_coupon = Coupon.objects.create(
                code=code,
                offer_type=offer_type,
                discount_type=discount_type,
                discount_value=discount_value,
                start_date=start_date,
                expiry_date=expiry_date,
                usage_limit=usage_limit,
                allowed_category=allowed_category,
                created_by=request.user
            )

            # إضافة الطلاب المستهدفين إن وجدوا
            if offer_type == 'specific_student':
                target_students = request.POST.getlist('target_students')
                if target_students:
                    new_coupon.target_students.set(target_students)

            messages.success(request, f"✅ تم إنشاء العرض ({code}) بنجاح!")
            return redirect('finance_dashboard') # عدل مسار التوجيه حسب مشروعك

        except Exception as e:
            messages.error(request, f"❌ حدث خطأ أثناء الحفظ: {str(e)}")

    return render(request, 'finance/create_offer.html', {
        'students': students,
    })

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def withdrawn_students_report(request):
    from finance.models import StudentRefund, Payment
    from django.db.models import Sum
    
    # جلب كل سجلات سحب الملفات مع بيانات الطالب والسنة
    withdrawals = StudentRefund.objects.select_related(
        'student', 'student__grade', 'academic_year', 'processed_by'
    ).order_by('-refund_date', '-id')
    
    # تجميع البيانات وإضافة إجمالي ما دفعه الطالب قبل السحب
    withdrawals_data = []
    for w in withdrawals:
        # حساب كل ما دفعه الطالب في هذه السنة
        total_paid = Payment.objects.filter(
            student=w.student, 
            academic_year=w.academic_year, 
            is_cancelled=False
        ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
        
        withdrawals_data.append({
            'student_name': w.student.get_full_name(),
            'student_code': w.student.student_code,
            'grade': w.student.grade.name if w.student.grade else '---',
            'academic_year': w.academic_year.name,
            'total_paid': total_paid,
            'refunded_amount': w.amount,
            'refund_date': w.refund_date,
            'reason': w.reason,
            'processed_by': w.processed_by.get_full_name() or w.processed_by.username if w.processed_by else '---'
        })

    return render(request, 'finance/withdrawn_students.html', {
        'withdrawals_data': withdrawals_data,
        'title': 'أرشيف الطلاب المسحوب ملفاتهم'
    })