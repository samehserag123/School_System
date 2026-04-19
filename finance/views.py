from django.contrib.auth.views import LoginView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.utils.safestring import mark_safe
from django.contrib import messages
from django.db import transaction
from django.db import transaction
from django.db.models import Sum, Count, Q, F, DecimalField, Max
from django.db.models.functions import TruncMonth, Coalesce
from .models import ReceiptBook # تأكد من وجود هذا الاستيراد في أعلى الملف

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
# 7. App Models (Finance & Students)
# تجميع الاستيرادات بشكل نظيف (بدون تكرار)
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

# -----------------------------------

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

    # 2. منع التكرار
    if MonthlyClosure.objects.filter(month=last_month).exists():
        messages.info(request, "هذا الشهر تم إغلاقه بالفعل.")
        return redirect('finance_dashboard')

    # ==========================================
    # 3. التحقق من الحركات المعلقة (التي لم تدخل جرد يومي)
    # ==========================================
    # الاعتماد على حقل is_closed=False لمعرفة الحركات المعلقة
    pending_revenues_count = Payment.objects.filter(
        payment_date__year=last_month.year,
        payment_date__month=last_month.month,
        is_closed=False  # حركة غير مقفلة
    ).count()

    pending_expenses_count = Expense.objects.filter(
        expense_date__year=last_month.year, 
        expense_date__month=last_month.month,
        is_closed=False  # مصروف غير مقفل
    ).count()

    has_pending = (pending_revenues_count > 0) or (pending_expenses_count > 0)

    if request.method == "POST":
        # منع الحفظ إذا كان هناك حركات معلقة (أمان إضافي للباك-إند)
        if has_pending:
            messages.error(request, f"لا يمكن إغلاق الشهر! يوجد {pending_revenues_count} إيراد معلق و {pending_expenses_count} مصروف معلق لم يتم تقفيلهم في الجرد.")
            return redirect('close_month') # تأكد من أن اسم الرابط صحيح في urls.py

        # 4. حساب الإيرادات (للحركات المقفلة فقط is_closed=True)
        revenues = Payment.objects.filter(
            payment_date__year=last_month.year,
            payment_date__month=last_month.month,
            is_closed=True
        ).aggregate(total=Sum('amount_paid'))['total'] or 0

        # 5. حساب المصروفات (للحركات المقفلة فقط is_closed=True)
        expenses = Expense.objects.filter(
            expense_date__year=last_month.year, 
            expense_date__month=last_month.month,
            is_closed=True
        ).aggregate(total=Sum('amount'))['total'] or 0

        # 6. جلب الرصيد السابق
        previous_closure = MonthlyClosure.objects.order_by('-month').first()
        opening_bal = previous_closure.closing_balance if previous_closure else 0

        # ... (باقي الكود داخل شرط POST) ...
        
        # 7. الحفظ
        MonthlyClosure.objects.create(
            month=last_month,
            opening_balance=opening_bal,
            total_revenues=revenues,
            total_expenses=expenses,
            net_balance=revenues - expenses,
            closing_balance=opening_bal + (revenues - expenses),
            status='closed',
            closed_by=request.user
        )
        
        # رسالة النجاح والتحويل تكون هنا فقط (داخل الـ POST)
        messages.success(request, f"تم إغلاق شهر {last_month.strftime('%B %Y')} بنجاح.")
        return redirect('finance_dashboard')

    # ==========================================
    # هذا الجزء خارج الـ POST (يعمل عند فتح الصفحة فقط)
    # ==========================================
    context = {
        'suggested_month': last_month,
        'has_pending': has_pending,
        'pending_revenues_count': pending_revenues_count,
        'pending_expenses_count': pending_expenses_count,
    }
    
    # ❌ احذف السطرين اللذين وضعتهما هنا:
    # messages.success(request, f"تم إغلاق شهر {last_month.strftime('%B %Y')} بنجاح.")
    # return redirect('finance_dashboard')

    # ✅ واستبدلهما بهذا السطر لكي تفتح الصفحة:
    return render(request, 'finance/close_month.html', context)

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

@login_required
def my_treasury_view(request):
    user = request.user
    
    # 1. جلب التحصيلات الخاصة بالمستخدم الحالي (والتي لم تغلق بعد)
    my_ledgers = GeneralLedger.objects.filter(collected_by=user, is_closed=False).order_by('-date')
    total_collected = my_ledgers.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    
    # 2. جلب المصروفات التي قام بها المستخدم الحالي (والتي لم تغلق بعد)
    my_expenses = Expense.objects.filter(spent_by=user, is_closed=False).order_by('-expense_date')
    total_spent = my_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    
    # 3. حساب صافي التوريد المطلوب منه
    net_required = total_collected - total_spent
    
    context = {
        'my_ledgers': my_ledgers,
        'total_collected': total_collected,
        'my_expenses': my_expenses,
        'total_spent': total_spent,
        'net_required': net_required,
    }
    
    return render(request, 'finance/my_treasury.html', context)


# ✅ 3. تقرير إغلاق الخزينة (إضافة الحماية)
@login_required
@user_passes_test(is_manager)
def daily_closure_report(request):
    today = timezone.now().date()
    
    # 1. جلب كافة الحركات المالية (الإيرادات) غير المغلقة من الخزينة العامة
    base_qs = GeneralLedger.objects.filter(is_closed=False).select_related('collected_by')

    # 2. حساب إجمالي الإيرادات (المقبوضات)
    total_revenues = base_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # --- 3. معالجة المصروفات المعلقة وفصلها ---
    # تهيئة المتغيرات بقيم افتراضية لتجنب أي خطأ في حال كانت الجداول فارغة
    total_expenses = Decimal('0.00')
    petty_expenses = []
    general_expenses = []

    try:
        from finance.models import Expense # تأكد من أن المسار يطابق تطبيقك
        open_expenses = Expense.objects.filter(is_closed=False)
        
        # فصل المصروفات بناءً على النوع المسجل في قاعدة البيانات
        petty_expenses = open_expenses.filter(expense_type='petty')
        general_expenses = open_expenses.filter(expense_type='general')
        
        # حساب إجمالي المصروفات (المدفوعات)
        total_expenses = open_expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    except (ImportError, AttributeError):
        # في حال عدم وجود الموديل أو الحقل تظل القيم أصفاراً
        pass

    # 4. حساب صافي الخزينة الدفتري (الرصيد المفترض وجوده فعلياً)
    total_day = total_revenues - total_expenses

    # 5. تجميع عهدة الموظفين (للجدول الذكي وتصفية الكاش)
    user_summary = []
    user_ids = base_qs.values_list('collected_by', flat=True).distinct()
    active_users = User.objects.filter(id__in=user_ids)
    
    for user in active_users:
        user_receipts = base_qs.filter(collected_by=user)
        # حماية لمنع ازدواجية القيم (تجميع القيمة الأكبر لكل إيصال فريد)
        unique_receipts = user_receipts.values('receipt_number').annotate(amt=Max('amount'))
        user_total = sum(item['amt'] for item in unique_receipts) if unique_receipts else Decimal('0.00')
        
        user_summary.append({
            'user_display': user.get_full_name() or user.username,
            'username': user.username, 
            'total_collected': user_total,
            'receipts_count': user_receipts.values('receipt_number').distinct().count()
        })

    # 6. تفاصيل الحركات الكاملة للنافذة المنبثقة (Modal)
    detailed_entries = base_qs.order_by('-date')

    # 7. بناء السياق النهائي (Context) الموحد لضمان وصول كافة البيانات للـ HTML
    context = {
        'today': today,
        'total_day': total_day,            # يغذي المربع الأزرق (صافي النظام)
        'total_revenues': total_revenues,  # يغذي المربع الأخضر (الإيرادات)
        'total_expenses': total_expenses,  # يغذي المربع الأحمر (المصروفات)
        'petty_expenses': petty_expenses,   # يغذي جدول النثريات
        'general_expenses': general_expenses, # يغذي جدول العموميات
        'user_summary': user_summary,       # يغذي جدول تصفية العهد
        'detailed_entries': detailed_entries, # بيانات الـ Modal للمراجعة
        'denominations': [200, 100, 50, 20, 10, 5, 1],
    }
    
    return render(request, 'treasury/daily_closure.html', context)



@staff_member_required
def daily_closures_archive(request):
    # جلب كافة عمليات الإغلاق مرتبة من الأحدث للأقدم
    closures = DailyClosure.objects.all().order_by('-closure_date')
    return render(request, 'finance/closures_archive.html', {'closures': closures})

@staff_member_required
@transaction.atomic
def close_daily_accounts_view(request):
    """
    الدالة النهائية لإغلاق الخزينة
    """
    if request.method == "POST":
        now_time = timezone.localtime(timezone.now())
        
        open_payments = Payment.objects.filter(is_closed=False)
        open_expenses = Expense.objects.filter(is_closed=False)
        
        # [1] توسيع كلمات الاستبعاد لتشمل احتمالات الأخطاء الإملائية الشائعة
        open_ledger = GeneralLedger.objects.filter(is_closed=False).exclude(
            Q(category__icontains='fees') | 
            Q(category__icontains='مصروف') |
            Q(category__icontains='دراس') |  # تلتقط "دراسي" و "دراسية"
            Q(category__icontains='تحصيل') |
            Q(category__icontains='كورس') |
            Q(category__icontains='طالب') |  # إضافة كلمة طالب
            Q(category__icontains='قسط')
        )

        # [2] حساب الإجماليات
        total_p = open_payments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
        total_l = open_ledger.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        total_e = open_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        
        theoretical_total = (total_p + total_l) - total_e

        # 🚨 [تتبع الأخطاء] 🚨
        # هذه الأسطر ستطبع لك في شاشة الـ Terminal (CMD) الأرقام بالتفصيل
        # لتعرف بالضبط أي جدول يحتوي على الرقم الزائد
        print("\n" + "="*30)
        print("📊 تفاصيل إغلاق الخزينة للتحقق:")
        print(f"1. إجمالي مدفوعات الطلاب (Payment): {total_p}")
        print(f"2. إيرادات أخرى متفرقة (Ledger): {total_l}")
        print(f"3. المصروفات النقدية (Expense): {total_e}")
        print(f"-> الرصيد الدفتري المحسوب: {theoretical_total}")
        print("="*30 + "\n")

        try:
            actual_input = request.POST.get('total_actual_hidden', '0')
            actual_total = Decimal(actual_input) if actual_input else Decimal('0.00')
        except (ValueError, TypeError, Decimal.InvalidOperation):
            actual_total = Decimal('0.00')
            
        closure = DailyClosure.objects.create(
            closed_by=request.user,
            total_cash=theoretical_total,
            actual_cash=actual_total,
            closure_id=f"CL-{now_time.strftime('%Y%m%d%H%M%S')}",
            closure_date=now_time 
        )
        
        open_payments.update(is_closed=True, closure=closure)
        open_expenses.update(is_closed=True, closure=closure)
        GeneralLedger.objects.filter(is_closed=False).update(is_closed=True, closure=closure)

        closure.total_cash = theoretical_total
        closure.variance = actual_total - theoretical_total
        closure.save()

        # تم إزالة كافة الرسائل هنا، العودة ستكون صامتة
        return redirect('daily_cashier_summary')

    return redirect('daily_cashier_summary')

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
    # 1. نستقبل مسار العودة (next) سواء كان من الرابط GET أو من الفورم المخفي POST
    next_url = request.GET.get('next') or request.POST.get('next')

    if request.method == "POST":
        title = request.POST.get('title')
        amount = request.POST.get('amount')
        notes = request.POST.get('notes', '')
        # نستقبل النوع من الحقل المخفي في الـ HTML
        expense_type = request.POST.get('expense_type', 'petty') 
        
        if title and amount:
            try:
                from finance.models import Expense # تأكد من المسار الصحيح للموديل الخاص بك
                Expense.objects.create(
                    title=title,
                    amount=Decimal(amount),
                    spent_by=request.user,
                    notes=notes,
                    expense_type=expense_type
                )
                messages.success(request, f"تم تسجيل المصروف بقيمة {amount} ج.م بنجاح.")
                
                # 2. التوجيه بناءً على مسار العودة
                if next_url:
                    return redirect(next_url)  # سيوجهك إلى my_treasury كما طلبنا في زر الـ HTML
                else:
                    # التوجيه الافتراضي لو لم يتم إرسال next
                    return redirect('daily_cashier_summary') 
                    
            except Exception as e:
                messages.error(request, f"حدث خطأ: {str(e)}")
    
    # === في حالة الـ GET (فتح الصفحة لأول مرة) ===
    # نقرأ نوع الزر الذي ضغط عليه المستخدم من الـ URL (مثل: ?type=general)
    exp_type = request.GET.get('type', 'petty')
    
    # 3. نجهز الـ context لنمرر مسار العودة إلى القالب (Template)
    context = {
        'next_url': next_url
    }
    
    if exp_type == 'general':
        return render(request, 'finance/add_expense_genral.html', context)
    else:
        return render(request, 'finance/add_expense.html', context)
    
    
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
    """
    كشف حساب يجمع كافة المدفوعات المسجلة فعلياً في الجدول
    ويخصمها من المديونية بغض النظر عن نوع البند
    """
    from finance.models import Payment
    try:
        from finance.models import Student
    except ImportError:
        from students.models import Student

    student = get_object_or_404(Student, id=student_id)
    
    # 1. جلب كافة الحركات المالية المسجلة للطالب (التي تظهر في الجدول)
    all_history = Payment.objects.filter(student=student).order_by('-payment_date', '-id')

    # 2. حساب إجمالي المدفوعات الفعلي من الجدول مباشرة (الجمع اللحظي)
    # هذا السطر سيجمع الـ 4 عمليات (1+1+1+1) ويخرج 4.00 جنيه
    actual_paid_from_table = all_history.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')

    # 3. حساب المتبقي الحقيقي
    # (مطلوب العام + مديونية سابقة) - كل ما دفع في الجدول
    total_required = student.total_required_amount
    remaining = total_required - actual_paid_from_table

    context = {
        'student': student,
        'all_history': all_history,
        'total_paid_all': actual_paid_from_table, # القيمة الفعلية من الجدول
        'total_required': total_required, 
        'remaining': remaining, # النتيجة النهائية الصحيحة
    }
    return render(request, 'finance/student_statement_print.html', context)




@login_required
def student_inventory_view(request, student_id):
    # 1. جلب الطالب مع تحسين الاستعلام
    student = get_object_or_404(
        Student.objects.select_related('academic_year', 'grade'), 
        id=student_id
    )
    
    # 2. جلب كافة الأصناف المعرفة لهذا الصف في السنة الحالية
    master_items = InventoryMaster.objects.filter(
        grade=student.grade,
        academic_year=student.academic_year
    )
    
    # 3. إعداد مصفوفة البيانات للعرض (Inventory Status)
    items_status = []
    total_to_pay = Decimal('0.00')
    
    for item in master_items:
        # أ. التحقق من حالة التسليم (هل يوجد سجل استلام لهذا الطالب؟)
        is_delivered = DeliveryRecord.objects.filter(
            student=student, 
            inventory_item=item
        ).exists()
        
        # ب. التحقق المالي (حساب المدفوع للفئة - كتب أو زي)
        category_display = item.get_category_display()
        paid_sum = Payment.objects.filter(
            student=student,
            revenue_category__name__icontains=category_display
        ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
        
        # ج. تحديد هل تم السداد الكامل (بناءً على السعر في Master)
        is_paid = paid_sum >= item.price
        
        # د. حساب المتبقي إذا لم يسدد
        remaining = max(item.price - paid_sum, 0)
        if not is_paid:
            total_to_pay += remaining
            
        items_status.append({
            'id': item.id,
            'name': category_display,
            'price': item.price,
            'paid_amount': paid_sum,
            'remaining': remaining,
            'is_paid': is_paid,
            'is_delivered': is_delivered,
            'remaining_stock': item.get_remaining_stock()
        })
    
    # 4. التجهيز للعرض
    context = {
        'student': student,
        'items_status': items_status, # استبدلنا books و uniform بهذه القائمة الموحدة
        'total_to_pay': total_to_pay,
        'page_title': f"مخزن الطالب: {student.get_full_name()}",
        'active_year': student.academic_year,
        'today': timezone.now().date(), 
    }
    
    return render(request, 'finance/student_inventory.html', context)


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

# @login_required
# def mass_assign_plans(request):

#     active_year = AcademicYear.objects.filter(is_active=True).first()
#     if not active_year:
#         return JsonResponse({
#             "status": "error", 
#             "message": "عفواً! لا توجد سنة دراسية نشطة حالياً."
#         }, status=400)

#     students = Student.objects.filter(is_active=True)
#     initialized_count = 0
    
#     for student in students:
#         _, created = StudentAccount.objects.update_or_create(
#             student=student,
#             academic_year=active_year,  # ✅ التصحيح هنا
#             defaults={
#                 "total_fees": 0
#             }
#         )
#         if created:
#             initialized_count += 1

#     return JsonResponse({
#         "status": "success", 
#         "message": f"✅ تمت التهيئة بنجاح: تم إنشاء {initialized_count} حساب مالي جديد للسنة الدراسية {active_year.name}."
#     })
    
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

# 🛡️ استبدلنا staff_member_required بشرط أن يكون superuser (المدير فقط)
@login_required
@user_passes_test(lambda u: u.is_superuser)
def bulk_promote_students(request):
    if request.method == 'POST':
        student_ids = request.POST.getlist('student_ids')
        target_year_id = request.POST.get('target_year')
        target_grade_id = request.POST.get('target_grade')

        # التأكد من وصول البيانات الأساسية
        if not student_ids or not target_year_id or not target_grade_id:
            messages.error(request, "⚠️ يرجى اختيار الطلاب والسنة والصف الدراسي.")
            return redirect(request.META.get('HTTP_REFERER', 'student_list'))

        # جلب الطلاب النشطين فقط من القائمة المحددة
        eligible_students = Student.objects.filter(id__in=student_ids, is_active=True)
        
        success_count = 0
        fail_count = 0

        try:
            # 💡 لاحظ: شلنا transaction.atomic الشاملة عشان لو طالب واحد فشل ميبوظش البقية
            # الترانزاكشن موجودة بالفعل جوه دالة promote_student_action لكل طالب بشكل منفصل
            for student in eligible_students:
                if promote_student_action(student.id, target_year_id, target_grade_id):
                    success_count += 1
                else:
                    fail_count += 1
            
            # 📢 رسائل التغذية الراجعة
            if success_count > 0:
                messages.success(request, f"🚀 تم ترحيل {success_count} طالب بنجاح للسنة الجديدة.")
            
            if fail_count > 0:
                # الفشل هنا غالباً هيكون بسبب إن الطالب مترحل بالفعل للسنة دي
                messages.warning(request, f"⚠️ فشل ترحيل {fail_count} طالب (تأكد أنهم ليسوا مسجلين بالفعل في السنة المستهدفة).")
                    
        except Exception as e:
            messages.error(request, f"❌ حدث خطأ غير متوقع: {str(e)}")

    return redirect('student_list')

# استيراد الموديلات اللازمة
from .models import Payment, Expense, DailyClosure
from treasury.models import GeneralLedger

@staff_member_required
def daily_cashier_summary(request):
    """
    عرض ملخص الخزينة اليومي الذكي.
    يعتمد فقط على السجلات المفتوحة (is_closed=False) لضمان اختفاء المبالغ بعد الجرد.
    """
    today = timezone.now().date()
    
    # 1. إيرادات الطلاب (المصروفات الأساسية والأنشطة)
    # نأخذ فقط ما لم يتم إغلاقه في الجرد
    payments_today = Payment.objects.filter(is_closed=False)
    
    student_summary = payments_today.values(
        'collected_by__username', 'revenue_category__name'
    ).annotate(
        count=Count('id'),
        total_amount=Sum('amount_paid')
    ).order_by('collected_by__username')

    total_students = payments_today.aggregate(sum=Sum('amount_paid'))['sum'] or Decimal('0.00')

    # 2. إيرادات الخزينة العامة (الكتب، الزي، الكورسات)
    # 💡 التعديل الجوهري: نعتمد على GeneralLedger فقط لأنها تحتوي على خاصية is_closed
    ledger_entries = GeneralLedger.objects.filter(is_closed=False).exclude(category='fees')
    
    ledger_dict = {}
    total_ledger = Decimal('0.00')
    
    for entry in ledger_entries:
        user = entry.collected_by.username if entry.collected_by else "النظام"
        cat = entry.category or 'other_courses'
        
        # توحيد المفتاح للتجميع حسب المستخدم والتصنيف
        key = (user, cat)
        if key not in ledger_dict:
            ledger_dict[key] = {
                'collected_by__username': user,
                'category': cat,
                'count': 0,
                'total_amount': Decimal('0.00')
            }
        
        ledger_dict[key]['count'] += 1
        ledger_dict[key]['total_amount'] += entry.amount
        total_ledger += entry.amount

    # 3. المصروفات المعلقة
    expenses = Expense.objects.filter(is_closed=False)
    total_expenses = expenses.aggregate(sum=Sum('amount'))['sum'] or Decimal('0.00')

    # 4. الحسابات النهائية
    total_day = (total_students + total_ledger) - total_expenses

    context = {
        'today': today,
        'student_summary': student_summary,
        'ledger_summary': list(ledger_dict.values()),
        'total_students': total_students,
        'total_ledger': total_ledger,
        'total_expenses': total_expenses,
        'total_day': total_day,
        'expenses': expenses,
        'detailed_payments': payments_today.select_related('student', 'revenue_category', 'collected_by'),
    }
    
    return render(request, 'finance/daily_summary.html', context)



@staff_member_required
@transaction.atomic
def close_daily_accounts_view(request):
    """إغلاق الخزينة الموحد (ترحيل السجلات بصمت تام)"""
    if request.method == "POST":
        now_time = timezone.now()
        
        # حساب الإجماليات (مع استبعاد الرسوم من الخزينة لتجنب الازدواجية)
        total_student = Payment.objects.filter(is_closed=False).aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
        total_ledger = GeneralLedger.objects.filter(is_closed=False).exclude(category='fees').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        total_expenses = Expense.objects.filter(is_closed=False).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        
        theoretical_total = (total_student + total_ledger) - total_expenses
        
        # إذا كانت الخزينة فارغة، نعود بصمت بدون أي رسائل تحذير
        if theoretical_total <= 0 and not Expense.objects.filter(is_closed=False).exists():
            return redirect('daily_cashier_summary')

        # حساب المبلغ الفعلي من مدخلات الكاشير
        actual_total = Decimal('0.00')
        denominations = []
        for key, value in request.POST.items():
            if key.startswith('denom_'):
                count = int(value or 0)
                if count > 0:
                    face_value = Decimal(key.replace('denom_', ''))
                    actual_total += (face_value * count)
                    denominations.append(f"{face_value}x{count}")
        
        variance = actual_total - theoretical_total
        
        # إنشاء سجل الجرد بصمت
        closure_id = f"CL-{now_time.strftime('%Y%m%d%H%M')}"
        closure = DailyClosure.objects.create(
            closed_by=request.user,
            total_cash=theoretical_total,
            actual_cash=actual_total,
            variance=variance,
            closure_id=closure_id,
            notes=f"الفئات: {' | '.join(denominations)} -- ملاحظات: {request.POST.get('notes', '')}"
        )
        
        # العودة لصفحة الخزينة بصمت تام (تم إلغاء كافة الرسائل)
        return redirect('daily_cashier_summary')
    
    return redirect('daily_cashier_summary')        
   

@staff_member_required
@transaction.atomic
def close_daily_accounts_view(request):
    """إغلاق الخزينة الموحد (طلاب + مصروفات + عمليات عامة) - بصمت تام"""
    if request.method == "POST":
        now_time = timezone.now()
        
        # 1. جلب العمليات المفتوحة (إيرادات ومصروفات)
        open_student_payments = Payment.objects.filter(is_closed=False)
        # تمت إضافة الاستبعاد لحمايتك من الحساب المزدوج بصمت
        open_ledger_entries = GeneralLedger.objects.filter(is_closed=False).exclude(category='fees')
        open_expenses = Expense.objects.filter(is_closed=False)

        # 2. حساب الإجماليات النظرية
        total_student = open_student_payments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
        total_ledger = open_ledger_entries.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        total_expenses = open_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        
        # المعادلة: (إجمالي المقبوضات) - (إجمالي المصروفات)
        theoretical_total = (total_student + total_ledger) - total_expenses
        
        # إذا كانت الخزينة فارغة، نعود بصمت بدون أي رسائل
        if theoretical_total <= 0 and not open_expenses.exists():
            return redirect('daily_cashier_summary')

        # 3. حساب المبلغ الفعلي من نموذج العد (الفئات النقدية)
        actual_total = Decimal('0.00')
        denominations = []
        for key, value in request.POST.items():
            if key.startswith('denom_'):
                count = int(value or 0)
                if count > 0:
                    try:
                        face_value = Decimal(key.replace('denom_', ''))
                        actual_total += (face_value * count)
                        denominations.append(f"{face_value}x{count}")
                    except: continue
        
        actual_total += Decimal(request.POST.get('extra_cash', '0'))
        variance = actual_total - theoretical_total
        
        # 4. إنشاء سجل الإغلاق الموحد (مرة واحدة فقط بعد الحساب)
        closure_id = f"CL-{now_time.strftime('%Y%m%d%H%M')}"
        closure = DailyClosure.objects.create(
            closed_by=request.user,
            total_cash=theoretical_total,
            actual_cash=actual_total,
            variance=variance,
            closure_id=closure_id,
            notes=f"الفئات: {' | '.join(denominations)} -- ملاحظات: {request.POST.get('notes', '')}"
        )
        
        # 5. القفل النهائي لجميع المصادر وربطها بسجل الجرد
        open_student_payments.update(closure=closure, is_closed=True)
        open_expenses.update(closure=closure, is_closed=True)
        open_ledger_entries.update(closure=closure, is_closed=True) 
        
        # 6. عودة صامتة تماماً (تم إلغاء رسائل التغذية الراجعة)
        return redirect('daily_cashier_summary')
    
    return redirect('daily_cashier_summary')


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


    
# def overdue_report(request):
#     active_year = get_active_year() 
#     today = timezone.now().date()
    
#     # 1. جلب معرفات الطلاب المتأخرين "فقط"
#     student_ids = StudentInstallment.objects.filter(
#         academic_year=active_year,
#         due_date__lte=today
#     ).exclude(status__iexact='Paid').values_list('student_id', flat=True).distinct()
    
#     # استخدام قاموس لضمان عدم تكرار أي ID قسط
#     final_items_dict = {} 
#     total_overdue_sum = 0

#     for s_id in student_ids:
#         # حساب الحصالة (إجمالي المدفوعات)
#         total_paid_pool = Payment.objects.filter(
#             student_id=s_id,
#             academic_year=active_year,
#             revenue_category__name__icontains="مصروف"
#         ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0

#         # جلب أقساط الطالب لهذا العام التي حل موعدها
#         student_insts = StudentInstallment.objects.filter(
#             student_id=s_id,
#             academic_year=active_year,
#             due_date__lte=today
#         ).order_by('due_date')

#         temp_pool = total_paid_pool
        
#         for inst in student_insts:
#             # إذا كان القسط تمت إضافته بالفعل (حماية من التكرار)
#             if inst.id in final_items_dict:
#                 continue

#             # توزيع الحصالة
#             payment_for_this = min(temp_pool, inst.amount_due)
#             remaining = inst.amount_due - payment_for_this
#             temp_pool -= payment_for_this

#             # الإضافة فقط إذا كان هناك متبقي
#             if remaining > 0:
#                 inst.display_paid = payment_for_this
#                 inst.display_remaining = remaining
#                 inst.days_overdue = (today - inst.due_date).days if inst.due_date else 0
                
#                 # تخزين في القاموس باستخدام الـ ID كمفتاح فريد
#                 final_items_dict[inst.id] = inst
#                 total_overdue_sum += remaining

#     context = {
#         # تحويل قيم القاموس إلى قائمة للمتصفح
#         'overdue_items': final_items_dict.values(), 
#         'total_overdue': total_overdue_sum,
#         'today': today,
#     }
#     return render(request, 'finance/overdue_report.html', context)

# def overdue_report(request):
#     active_year = get_active_year()
#     today = timezone.now().date()
    
#     overdue_items = StudentInstallment.objects.filter(
#         academic_year=active_year,
#         due_date__lt=today, 
#         status__in=['Late', 'Partial', 'Pending'] 
#     ).select_related('student', 'student__grade').order_by('due_date')

#     for item in overdue_items:
#         # 1. تحديد المبلغ المحصل الفعلي (التعامل مع احتمالية اختلاف أسماء الحقول)
#         paid = getattr(item, 'paid_amount', getattr(item, 'amount_paid', 0)) or 0
#         item.actual_paid = paid  # قيمة المحصل لتظهر في عمود مستقل
        
#         # 2. حساب المتبقي الحقيقي (المطلوب - المحصل)
#         # سيظهر هنا الـ 14,000 ج.م بدلاً من 14,200 ج.م
#         item.actual_remaining = item.amount_due - paid
        
#         # 3. حساب أيام التأخير
#         if item.due_date:
#             delta = today - item.due_date
#             item.days_overdue = delta.days 
#         else:
#             item.days_overdue = 0

#     # 4. إجمالي المتأخرات الفعلي (مجموع المتبقي من كافة الأقساط)
#     total_overdue = sum(item.actual_remaining for item in overdue_items)

#     context = {
#         'overdue_items': overdue_items,
#         'total_overdue': total_overdue,
#         'today': today,
#     }
#     return render(request, 'finance/overdue_report.html', context)



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

# def debt_report(request):
#     # 1. جلب المدخلات من الرابط (السنة وكلمة البحث)
#     year_id = request.GET.get('academic_year')
#     search_query = request.GET.get('q', '').strip() # خانة البحث الجديدة
    
#     # تحديد السنة النشطة تلقائياً لو الموظف ماختارش سنة
#     if not year_id:
#         active_year = get_active_year()
#         year_id = active_year.id if active_year else None
    
#     years = AcademicYear.objects.all().order_by('-name')
    
#     # 2. بناء الفلتر الأساسي (السنة + البحث)
#     # فلتر السنة للأقساط
#     installments_filter = Q(installments__academic_year_id=year_id) if year_id else Q()
    
#     # فلتر البحث (الاسم الأول، الأخير، أو كود الطالب)
#     student_filter = Q()
#     if search_query:
#         student_filter = (
#             Q(first_name__icontains=search_query) | 
#             Q(last_name__icontains=search_query) | 
#             Q(student_code__icontains=search_query)
#         )

#     # 3. الاستعلام المجمع (السرعة القصوى)
#     students_with_debt = Student.objects.filter(student_filter).annotate(
#         total_required=Coalesce(
#             Sum('installments__amount_due', filter=installments_filter), 
#             Decimal('0'), 
#             output_field=DecimalField()
#         ),
#         total_paid_academic=Coalesce(
#             Sum('installments__paid_amount', filter=installments_filter), 
#             Decimal('0'), 
#             output_field=DecimalField()
#         )
#     ).annotate(
#         remaining=F('total_required') - F('total_paid_academic')
#     ).filter(
#         remaining__gt=0 # إظهار المديونين فقط
#     ).select_related('grade').order_by('-remaining')

#     # 4. تحويل النتائج لشكل مفهوم للقالب وحساب الإجمالي العام
#     report_data = []
#     total_sum = 0
#     for s in students_with_debt:
#         report_data.append({
#             'student': s,
#             'required': s.total_required,
#             'paid': s.total_paid_academic,
#             'remaining': s.remaining,
#         })
#         total_sum += s.remaining

#     # 5. معالجة year_id بشكل آمن لتجنب خطأ isdigit مع الأرقام
#     try:
#         # إذا كان المتغير موجوداً، حوله لرقم مباشرة بغض النظر عن نوعه الأصلي
#         selected_year_context = int(year_id) if year_id else None
#     except (ValueError, TypeError):
#         selected_year_context = None

#     return render(request, 'finance/debt_report.html', {
#         'report_data': report_data,
#         'years': years,
#         'selected_year': selected_year_context,
#         'total_debts_sum': total_sum,
#         'search_query': search_query,
#     })

# def print_receipt(request, payment_id):
#     """دالة معاينة إيصال النقدية فور السداد"""
#     payment = get_object_or_404(Payment, id=payment_id)
#     return render(request, 'finance/receipt_thermal.html', {
#         'payment': payment,
#         'today': timezone.now()
#     })


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
@transaction.atomic
def quick_collection(request):
    years = AcademicYear.objects.all()
    categories = RevenueCategory.objects.all()
    
    default_category = categories.filter(name__icontains="اساسيه").first() or \
                       categories.filter(name__icontains="مصروف").first()
    
    selected_year = request.GET.get('academic_year')
    url_student_id_raw = request.GET.get('student_id') or request.GET.get('student')
    
    url_student_id = None
    if url_student_id_raw:
        try:
            url_student_id = int(url_student_id_raw)
        except ValueError:
            pass
    
    students_query = Student.objects.all()
    if selected_year:
        students_query = students_query.filter(academic_year_id=selected_year)

    students_list = list(students_query[:100]) 
    
    if url_student_id:
        try:
            specific_student = Student.objects.get(id=url_student_id)
            if specific_student not in students_list:
                students_list.insert(0, specific_student)
        except Student.DoesNotExist:
            pass

    active_book = ReceiptBook.objects.filter(user=request.user, is_active=True).first()
    next_serial = None
    book_exhausted = False
    
    if active_book:
        max_used = Payment.objects.filter(
            collected_by=request.user,
            receipt_number__gte=active_book.start_serial,
            receipt_number__lte=active_book.end_serial
        ).aggregate(max_val=Max('receipt_number'))['max_val']
        
        next_serial = (max_used + 1) if max_used else active_book.start_serial
        if next_serial > active_book.end_serial:
            book_exhausted = True
            next_serial = None

    if request.method == "POST":
        p_student_id = request.POST.get('student')
        category_id = request.POST.get('category')
        amount_raw = request.POST.get('amount')
        receipt_number_raw = request.POST.get('receipt_number')
        
        # 🔴 استلام قيمة الكوبون من الواجهة
        discount_raw = request.POST.get('hidden_discount_value', '0')

        if not active_book or book_exhausted:
            messages.error(request, "❌ مشكلة في دفتر الإيصالات.")
            return redirect('quick_collection')

        if p_student_id and category_id and amount_raw:
            try:
                cash_collected = Decimal(amount_raw)
                discount_amount = Decimal(discount_raw) if discount_raw else Decimal('0')
                receipt_number = int(receipt_number_raw)
                
                # حماية ضد التكرار (Double Submission)
                if Payment.objects.filter(receipt_number=receipt_number).exists():
                    messages.warning(request, f"⚠️ الإيصال رقم {receipt_number} مسجل مسبقاً! تم منع العملية.")
                    return redirect('quick_collection')
                
                category = get_object_or_404(RevenueCategory, id=category_id)
                student = get_object_or_404(Student, id=p_student_id)
                active_year = student.academic_year
                notes = request.POST.get('notes', '')

                if discount_amount > 0:
                    notes += f" [تم تطبيق خصم إضافي بقيمة {discount_amount} ج.م]"

                # 1. تسجيل الإيصال النقدي (الكاش)
                payment = Payment.objects.create(
                    academic_year=active_year, student=student,
                    revenue_category=category, amount_paid=cash_collected, 
                    payment_date=timezone.now().date(),
                    collected_by=request.user, receipt_number=receipt_number,
                    notes=notes
                )

                # 2. تسجيل الخزينة (بالكاش فقط لضمان العهدة)
                GeneralLedger.objects.create(
                    student=student, amount=cash_collected, category=category.name,
                    receipt_number=str(receipt_number), date=timezone.now(),
                    collected_by=request.user, notes=f"تحصيل سريع: {category.name}"
                )

                # 3. 🔴 الخدعة: تسجيل إيصال "وهمي" بالكوبون (بدون خزينة) لكي يخصمه الموديل من الأقساط
                if discount_amount > 0:
                    # يجب أن تحتوي الفئة على كلمة "المصروفات" لكي يتعرف عليها الموديل ويوزعها
                    discount_cat, _ = RevenueCategory.objects.get_or_create(name="خصم المصروفات (كوبون)")
                    Payment.objects.create(
                        academic_year=active_year, student=student,
                        revenue_category=discount_cat, amount_paid=discount_amount,
                        payment_date=timezone.now().date(),
                        collected_by=request.user, receipt_number=receipt_number,
                        notes=f"قيمة خصم/كوبون تابع للإيصال رقم {receipt_number}"
                    )

                # حساب الأرصدة النهائية للطباعة
                inst_totals = StudentInstallment.objects.filter(student=student, academic_year=active_year).aggregate(
                    total_due=Sum('amount_due'),
                    total_paid=Sum('paid_amount')
                )
                total_req = inst_totals['total_due'] or Decimal('0')
                total_paid_in_insts = inst_totals['total_paid'] or Decimal('0')
                remaining_balance = max(total_req - total_paid_in_insts, Decimal('0'))
                
                messages.success(request, f"تم التحصيل بنجاح ({cash_collected} ج.م كاش" + (f" + {discount_amount} ج.م خصم)." if discount_amount > 0 else ")."))
                
                return render(request, 'finance/receipt_final.html', {
                    'payment': payment, 'total_paid': total_paid_in_insts, 'remaining_balance': remaining_balance
                })

            except Exception as e:
                messages.error(request, f"خطأ: {str(e)}")

    return render(request, 'finance/quick_collection.html', {
        'years': years, 
        'categories': categories, 
        'students': students_list,
        'default_category': default_category, 
        'selected_year': selected_year,
        'selected_student_id': url_student_id, 
        'active_book': active_book,
        'next_serial': next_serial, 
        'book_exhausted': book_exhausted,
    })

# @login_required
# @transaction.atomic
# def quick_collection(request):
#     years = AcademicYear.objects.all()
#     categories = RevenueCategory.objects.all()
    
#     default_category = categories.filter(name__icontains="اساسيه").first() or \
#                        categories.filter(name__icontains="مصروف").first()
    
#     selected_year = request.GET.get('academic_year')
#     url_student_id_raw = request.GET.get('student_id') or request.GET.get('student')
    
#     url_student_id = None
#     if url_student_id_raw:
#         try:
#             url_student_id = int(url_student_id_raw)
#         except ValueError:
#             pass
    
#     students_query = Student.objects.all()
#     if selected_year:
#         students_query = students_query.filter(academic_year_id=selected_year)

#     students_list = list(students_query[:100]) 
    
#     if url_student_id:
#         try:
#             specific_student = Student.objects.get(id=url_student_id)
#             if specific_student not in students_list:
#                 students_list.insert(0, specific_student)
#         except Student.DoesNotExist:
#             pass

#     active_book = ReceiptBook.objects.filter(user=request.user, is_active=True).first()
#     next_serial = None
#     book_exhausted = False
    
#     if active_book:
#         max_used = Payment.objects.filter(
#             collected_by=request.user,
#             receipt_number__gte=active_book.start_serial,
#             receipt_number__lte=active_book.end_serial
#         ).aggregate(max_val=Max('receipt_number'))['max_val']
        
#         next_serial = (max_used + 1) if max_used else active_book.start_serial
#         if next_serial > active_book.end_serial:
#             book_exhausted = True
#             next_serial = None

#     if request.method == "POST":
#         p_student_id = request.POST.get('student')
#         category_id = request.POST.get('category')
#         amount_raw = request.POST.get('amount')
#         receipt_number_raw = request.POST.get('receipt_number')

#         if not active_book or book_exhausted:
#             messages.error(request, "❌ مشكلة في دفتر الإيصالات.")
#             return redirect('quick_collection')

#         if p_student_id and category_id and amount_raw:
#             try:
#                 cash_collected = Decimal(amount_raw)
#                 receipt_number = int(receipt_number_raw)
                
#                 # حماية ضد التكرار
#                 if Payment.objects.filter(receipt_number=receipt_number).exists():
#                     messages.warning(request, f"⚠️ الإيصال رقم {receipt_number} مسجل مسبقاً! تم منع العملية.")
#                     return redirect('quick_collection')
                
#                 category = get_object_or_404(RevenueCategory, id=category_id)
#                 student = get_object_or_404(Student, id=p_student_id)
#                 active_year = student.academic_year
#                 notes = request.POST.get('notes', '')

#                 # 🔴 نقوم بإنشاء الإيصال فقط (والموديل سيتكفل بتوزيع الأقساط تلقائياً من الخلفية)
#                 payment = Payment.objects.create(
#                     academic_year=active_year, 
#                     student=student,
#                     revenue_category=category, 
#                     amount_paid=cash_collected, 
#                     installment=None, # متروك للموديل
#                     payment_date=timezone.now().date(),
#                     collected_by=request.user, 
#                     receipt_number=receipt_number,
#                     notes=notes
#                 )

#                 GeneralLedger.objects.create(
#                     student=student, amount=cash_collected, category=category.name,
#                     receipt_number=str(receipt_number), date=timezone.now(),
#                     collected_by=request.user, notes=f"تحصيل سريع: {category.name}"
#                 )

#                 # حساب الأرصدة النهائية للطباعة
#                 inst_totals = StudentInstallment.objects.filter(student=student, academic_year=active_year).aggregate(
#                     total_due=Sum('amount_due'),
#                     total_paid=Sum('paid_amount')
#                 )
#                 total_req = inst_totals['total_due'] or Decimal('0')
#                 total_paid_in_insts = inst_totals['total_paid'] or Decimal('0')
#                 remaining_balance = max(total_req - total_paid_in_insts, Decimal('0'))
                
#                 messages.success(request, f"تم التحصيل بنجاح ({cash_collected} ج.م).")
                
#                 return render(request, 'finance/receipt_final.html', {
#                     'payment': payment, 'total_paid': total_paid_in_insts, 'remaining_balance': remaining_balance
#                 })

#             except Exception as e:
#                 messages.error(request, f"خطأ: {str(e)}")

#     return render(request, 'finance/quick_collection.html', {
#         'years': years, 
#         'categories': categories, 
#         'students': students_list,
#         'default_category': default_category, 
#         'selected_year': selected_year,
#         'selected_student_id': url_student_id, 
#         'active_book': active_book,
#         'next_serial': next_serial, 
#         'book_exhausted': book_exhausted,
#     })
    
    
        


@login_required
def finance_dashboard(request):
    active_year = get_active_year()
    if not active_year:
        return render(request, "finance/dashboard.html", {"error": "⚠️ لا توجد سنة نشطة."})

    # 🟢 إجبار النظام على استخدام توقيت مصر بدقة
    from django.utils import timezone
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
    from finance.models import StudentInstallment, MonthlyClosure  # أضفنا MonthlyClosure هنا
    from django.db.models import Sum

    # 1. إيرادات الخزينة (المحصل الفعلي)
    today_revenue_all = GeneralLedger.objects.filter(date__date=today).aggregate(total=Sum('amount'))['total'] or 0
    month_revenue_all = GeneralLedger.objects.filter(date__month=today.month, date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0
    year_revenue_all = GeneralLedger.objects.aggregate(total=Sum('amount'))['total'] or 0

    # 🟢 الإضافة الجديدة: جلب رصيد الخزينة المرحل من آخر إغلاق شهري
    last_closure = MonthlyClosure.objects.order_by('-month').first()
    carried_balance = last_closure.closing_balance if last_closure else 0

    # 2. حساب إجمالي المدفوعات الحقيقي من واقع جدول الأقساط
    total_paid_students = StudentInstallment.objects.filter(
        academic_year=active_year
    ).aggregate(total=Sum('paid_amount'))['total'] or 0

    # 3. حساب المستهدف والمديونيات
    total_fees_req = StudentInstallment.objects.filter(
        academic_year=active_year
    ).aggregate(total=Sum('amount_due'))['total'] or 0
    
    all_students = Student.objects.filter(academic_year=active_year)
    total_old_debts = all_students.aggregate(total=Sum('previous_debt'))['total'] or 0
    
    total_target_all = total_fees_req + total_old_debts
    
    total_debt_combined = max(total_target_all - total_paid_students, 0)

    # 4. كفاءة الصفوف
    grades_efficiency = []
    for grade in Grade.objects.all():
        g_installments = StudentInstallment.objects.filter(student__grade=grade, academic_year=active_year)
        if g_installments.exists():
            g_target_fees = g_installments.aggregate(total=Sum('amount_due'))['total'] or 0
            g_paid = g_installments.aggregate(total=Sum('paid_amount'))['total'] or 0
            
            g_old_debt = all_students.filter(grade=grade).aggregate(total=Sum('previous_debt'))['total'] or 0
            g_total_target = g_target_fees + g_old_debt

            grades_efficiency.append({
                'grade': grade.name,
                'target': g_total_target,
                'paid': g_paid,
                'remaining': max(g_total_target - g_paid, 0),
                'percentage': round((g_paid / g_total_target * 100), 1) if g_total_target > 0 else 0
            })

    context = {
        "active_year": active_year,
        "today_revenue_all": today_revenue_all, 
        "month_revenue_all": month_revenue_all,
        "year_revenue_all": year_revenue_all,
        "carried_balance": carried_balance,  # 🟢 متغير جديد للقالب
        "last_closure": last_closure,        # 🟢 لإظهار اسم الشهر المغلق في القالب
        "total_debt_combined": total_debt_combined,
        "total_percentage": round((total_paid_students / total_target_all * 100), 1) if total_target_all > 0 else 0,
        "total_students_count": all_students.count(),
        "grades_efficiency": grades_efficiency,
        "recent_activities": GeneralLedger.objects.filter(date__date=today).order_by('-date')[:10],
        "current_time": local_now,
    }
    return render(request, 'finance/dashboard.html', context)


@staff_member_required
@transaction.atomic
def assign_plan(request, student_id=None):
    selected_student = None
    account = None
    target_id = student_id or request.GET.get('student_id')
    
    # جلب بيانات الطالب والحساب للعرض في الصفحة
    if target_id:
        selected_student = get_object_or_404(Student, id=target_id)
        account = StudentAccount.objects.filter(student=selected_student).first()

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

            # 1. تحديث الحساب المالي (الإجمالي يبقى كاملاً للأقساط)
            account_obj, created = StudentAccount.objects.update_or_create(
                student=student,
                academic_year=student.academic_year,
                defaults={
                    'installment_plan': plan, 
                    'total_fees': plan.total_amount,
                    'discount': discount_val,
                }
            )

            # 2. توليد الأقساط (توزع مديونية الطالب كاملة)
            StudentInstallment.objects.filter(student=student, academic_year=student.academic_year).delete()
            if hasattr(account_obj, 'generate_installments'):
                account_obj.generate_installments()

            # 3. الربط مع الخزينة (المطالبة بقيمة interest_value فقط)
            if plan.interest_value > 0:
                # نستخدم فئة واضحة للرسوم الإدارية لتمييزها عن المصروفات الدراسية
                category, _ = RevenueCategory.objects.get_or_create(name='رسوم إدارية / فائدة خطة')
                
                Payment.objects.create(
                    student=student,
                    academic_year=student.academic_year,
                    revenue_category=category,
                    amount_paid=plan.interest_value,  # شحن الفائدة فقط للخزينة
                    collected_by=request.user,
                    payment_date=timezone.now().date(),
                    notes=f"تحصيل قيمة الفائدة فقط عند تسكين الخطة: {plan.name}"
                )
                msg = f"✅ تم التسكين وتحصيل رسوم فتح الملف ({plan.interest_value} ج.م) في الخزينة."
            else:
                msg = f"✅ تم اعتماد البرنامج المالي بنجاح للطالب {student.get_full_name()}"

            messages.success(request, msg)
            return redirect('student_list')

        except Exception as e:
            messages.error(request, f"❌ خطأ تقني: {str(e)}")
            return redirect(request.path)

    # === التعديل هنا ===
    # 1. جلب العام الدراسي النشط أولاً
    active_year = AcademicYear.objects.filter(is_active=True).first()
    
    # 2. فلترة الخطط لتكون تابعة للعام النشط فقط (أو جلب الكل في حالة عدم وجود عام نشط لتجنب الأخطاء)
    if active_year:
        filtered_plans = InstallmentPlan.objects.filter(academic_year=active_year)
    else:
        filtered_plans = InstallmentPlan.objects.none()

    context = {
        'years': AcademicYear.objects.all().order_by('-id'),
        'plans': filtered_plans, # تمرير الخطط المفلترة هنا
        'selected_student': selected_student,
        'account': account,
        'active_year': active_year,
    }
    
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
        from finance.models import StudentInstallment
        from django.db.models import Sum
        from students.models import Student

        # 1. جلب بيانات الطالب الأساسية
        student = Student.objects.get(id=student_id)
        
        # 2. حساب إجمالي الأقساط (المطلوب سداده فعلياً)
        # إحنا هنعتمد على جدول الأقساط لأنه أدق مكان فيه الحسابات دلوقتي
        installments = StudentInstallment.objects.filter(student_id=student_id)
        
        total_required = installments.aggregate(Sum('amount_due'))['amount_due__sum'] or 0
        total_paid = installments.aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
        
        # 3. المديونية الصافية = (المطلوب + المديونية القديمة) - المدفوع
        # ملاحظة: student.previous_debt قد تكون قيمتها -2.00 كما رأينا في الـ Shell
        old_debt = student.previous_debt or 0
        net_remaining = (total_required + old_debt) - total_paid

        return JsonResponse({
            "success": True,
            "current_due": float(net_remaining),    # الرقم في المربع الأحمر
            "total_debt": float(net_remaining),     # الرقم في المربع الأزرق
            "total_remaining": float(net_remaining) # لضمان عمل الـ JavaScript
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

from django.shortcuts import render, redirect
from django.contrib import messages

@login_required
def create_offer_view(request):
    """
    دالة إنشاء العروض النظيفة (بدون أخطاء الخزائن)
    """
    students = Student.objects.all().order_by('first_name') 
    
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