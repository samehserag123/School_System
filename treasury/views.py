from decimal import Decimal
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum, Max, Count
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User

# استدعاء النماذج (Models) والفورمز من التطبيق الحالي
from .models import GeneralLedger, Product, ScanHistory
from .forms import TreasuryEntryForm

# -- تنبيه: قم بفك التعليق عن هذا السطر وتأكد من المسار الصحيح لتطبيق الطلاب --
# from students.models import Student, CourseGroup 

# دالة مساعدة للتحقق من الصلاحيات (تمنع الخط الأصفر تحت is_manager)
def is_manager(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)




def is_manager(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)

@login_required
@user_passes_test(is_manager)
def daily_closure_report(request):
    today = timezone.now().date()
    
    # 1. جلب كافة الحركات المالية (الإيرادات) غير المغلقة 
    base_qs = GeneralLedger.objects.filter(
        is_closed=False,
        amount__gt=0,
        is_discount=False
    ).select_related('collected_by')

    unique_base = base_qs.values('receipt_number').annotate(amt=Max('amount'))
    total_revenues = sum(item['amt'] for item in unique_base) if unique_base else Decimal('0.00')

    # --- 3. معالجة المصروفات والمرتجعات المعلقة ---
    total_expenses = Decimal('0.00')
    total_refunds = Decimal('0.00') # 🟢 متغير المرتجعات
    petty_expenses = []
    general_expenses = []

    try:
        from finance.models import Expense, StudentRefund # 🟢 استدعاء المرتجعات
        open_expenses = Expense.objects.filter(is_closed=False)
        petty_expenses = open_expenses.filter(expense_type='petty')
        general_expenses = open_expenses.filter(expense_type='general')
        total_expenses = open_expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # 🟢 حساب المرتجعات المفتوحة لخصمها
        total_refunds = StudentRefund.objects.filter(is_closed=False).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    except (ImportError, AttributeError):
        pass

    # 4. 🟢 حساب صافي الخزينة الدفتري (الإيرادات - المصروفات - المرتجعات)
    total_day = Decimal(total_revenues) - (Decimal(total_expenses) + Decimal(total_refunds))

    # 5. تجميع عهدة الموظفين
    user_summary = []
    user_stats = base_qs.values(
        'collected_by__id', 
        'collected_by__username', 
        'collected_by__first_name', 
        'collected_by__last_name'
    ).annotate(
        receipts_count=Count('receipt_number', distinct=True)
    )
    
    for stat in user_stats:
        uid = stat['collected_by__id']
        username = stat['collected_by__username']
        full_name = f"{stat['collected_by__first_name']} {stat['collected_by__last_name']}".strip()
        
        u_receipts = base_qs.filter(collected_by_id=uid).values('receipt_number').annotate(amt=Max('amount'))
        user_total = sum(item['amt'] for item in u_receipts) if u_receipts else Decimal('0.00')
        
        user_summary.append({
            'user_display': full_name or username,
            'username': username, 
            'total_collected': user_total,
            'receipts_count': stat['receipts_count']
        })

    detailed_entries = base_qs.order_by('-date')

    context = {
        'today': today,
        'total_day': total_day,
        'total_revenues': total_revenues,
        'total_expenses': total_expenses,
        'total_refunds': total_refunds, # 🟢 تمرير المرتجعات
        'petty_expenses': petty_expenses,
        'general_expenses': general_expenses,
        'user_summary': user_summary,
        'detailed_entries': detailed_entries,
        'denominations': [200, 100, 50, 20, 10, 5, 1],
    }
    
    return render(request, 'treasury/daily_closure.html', context)


@login_required
def students_analytics_view(request):
    try:
        from students.models import Student, CourseGroup
        total_students = Student.objects.count()
        enrolled_ids = CourseGroup.objects.values_list('student_id', flat=True).distinct()
        enrolled_students_count = len(enrolled_ids)
        non_enrolled_count = total_students - enrolled_students_count
        subject_analysis = CourseGroup.objects.values('course_info__subject__name').annotate(
            total=Count('id')
        ).order_by('-total')
    except ImportError:
        total_students = enrolled_students_count = non_enrolled_count = 0
        subject_analysis = []

    context = {
        'total_students': total_students,
        'enrolled_count': enrolled_students_count,
        'non_enrolled_count': non_enrolled_count,
        'subject_analysis': subject_analysis,
        'title': 'لوحة التحليل الإحصائي الاحترافية'
    }
    return render(request, 'students/analytics_dashboard.html', context)


def treasury_dashboard(request):
    today = timezone.now().date()
    entries = GeneralLedger.objects.all().order_by('-date')
    
    today_qs = GeneralLedger.objects.filter(date__date=today)
    unique_receipts = today_qs.values('receipt_number').annotate(amt=Max('amount'))
    today_total = sum(item['amt'] for item in unique_receipts)
    
    # 🟢 خصم المرتجعات من إجمالي اليوم في الداشبورد الخاص بالخزينة
    try:
        from finance.models import StudentRefund
        today_refunds = StudentRefund.objects.filter(refund_date=today).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        today_total -= today_refunds
    except ImportError:
        pass
    
    return render(request, 'treasury/dashboard.html', {
        'entries': entries,
        'today_total': today_total,
    })


@login_required
def add_treasury_entry(request):
    if request.method == 'POST':
        form = TreasuryEntryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.collected_by = request.user  
            entry.save()
            messages.success(request, "تم تسجيل الإيراد بنجاح")
            return redirect(request.path) 
    else:
        form = TreasuryEntryForm(initial={'collected_by': request.user})
    
    return render(request, 'treasury/add_entry.html', {'form': form})


@login_required
def daily_revenue_report(request):
    today = timezone.now().date()
    daily_entries = GeneralLedger.objects.filter(date__date=today)
    
    unique_data = daily_entries.values('receipt_number', 'category').annotate(amt=Max('amount'))
    
    category_totals = {}
    grand_total = Decimal('0.00')
    for item in unique_data:
        cat = item['category']
        amt = Decimal(item['amt'] or 0)
        category_totals[cat] = category_totals.get(cat, Decimal('0.00')) + amt
        grand_total += amt

    # 🟢 خصم المرتجعات من إجمالي التقرير اليومي
    try:
        from finance.models import StudentRefund
        today_refunds = StudentRefund.objects.filter(refund_date=today).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        grand_total -= today_refunds
    except ImportError:
        pass

    return render(request, 'treasury/daily_report.html', {
        'entries': daily_entries,
        'category_totals': category_totals,
        'grand_total': grand_total,
        'today': today
    })


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def verify_product(request, serial_number):
    try:
        product = Product.objects.get(serial_number=serial_number)
        
        if product.is_currently_disabled:
            context = {
                'status': 'disabled',
                'product': product,
                'serial': serial_number,
                'disabled_until': product.disabled_until
            }
            return render(request, 'verify.html', context)
        
        client_ip = get_client_ip(request)
        ScanHistory.objects.create(
            product=product,
            scanned_at=timezone.now(), 
            ip_address=client_ip
        )
        
        product.scan_count += 1
        product.save()
        
        latest_scan = product.scans.first()
            
        context = {
            'status': 'success',
            'product': product,
            'serial': serial_number,
            'current_scan_time': latest_scan.scanned_at, 
        }
    except Product.DoesNotExist:
        context = {
            'status': 'fail',
            'serial': serial_number
        }
    
    return render(request, 'verify.html', context)


#

def treasury_dashboard(request):
    today = timezone.now().date()
    entries = GeneralLedger.objects.all().order_by('-date')
    
    # 🛡️ تصفية التكرار في العداد الكبير لليوم
    today_qs = GeneralLedger.objects.filter(date__date=today)
    unique_receipts = today_qs.values('receipt_number').annotate(amt=Max('amount'))
    today_total = sum(item['amt'] for item in unique_receipts)
    
    return render(request, 'treasury/dashboard.html', {
        'entries': entries,
        'today_total': today_total,
    })



@login_required
def add_treasury_entry(request):
    if request.method == 'POST':
        # 🛡️ تأكد من استخدام اسم الكلاس الصحيح TreasuryEntryForm
        form = TreasuryEntryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            # ربط الحركة بالموظف الذي قام بالإدخال آلياً
            entry.collected_by = request.user  
            entry.save()
            messages.success(request, "تم تسجيل الإيراد بنجاح")
            # تم التعديل هنا: البقاء في نفس الصفحة بعد الحفظ
            return redirect(request.path) 
    else:
        # إرسال مستخدم الجلسة الحالي كقيمة افتراضية للموظف المستلم
        form = TreasuryEntryForm(initial={'collected_by': request.user})
    
    return render(request, 'treasury/add_entry.html', {'form': form})


# 3. الدالة التي تسببت في الخطأ (تقرير الإيرادات اليومي)
@login_required
def daily_revenue_report(request):
    today = timezone.now().date()
    daily_entries = GeneralLedger.objects.filter(date__date=today)
    
    # 🛡️ الحساب الصافي بدون تكرار السجنالز
    unique_data = daily_entries.values('receipt_number', 'category').annotate(amt=Max('amount'))
    
    # حساب إجمالي الفئات بدقة
    category_totals = {}
    grand_total = 0
    for item in unique_data:
        cat = item['category']
        amt = item['amt']
        category_totals[cat] = category_totals.get(cat, 0) + amt
        grand_total += amt

    return render(request, 'treasury/daily_report.html', {
        'entries': daily_entries,
        'category_totals': category_totals,
        'grand_total': grand_total,
        'today': today
    })


from .models import Product, ScanHistory

def get_client_ip(request):
    """دالة فرعية لجلب عنوان الـ IP الخاص بالزائر"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def verify_product(request, serial_number):
    try:
        product = Product.objects.get(serial_number=serial_number)
        
        # 1. الفحص أولاً: هل الـ QR معطل حالياً؟
        if product.is_currently_disabled:
            context = {
                'status': 'disabled',
                'product': product,
                'serial': serial_number,
                'disabled_until': product.disabled_until
            }
            return render(request, 'verify.html', context)
        
        # 2. تسجيل المسحة الجديدة فوراً (حتى لو تكررت من نفس التليفون)
        client_ip = get_client_ip(request)
        ScanHistory.objects.create(
            product=product,
            scanned_at=timezone.now(), # ضبط الوقت الحالي بدقة بالثواني
            ip_address=client_ip
        )
        
        # 3. تحديث العداد الإجمالي في جدول المنتج
        product.scan_count += 1
        product.save()
        
        # جلب آخر مسحة قمنا بتسجيلها لعرض توقيتها للمستخدم في الصفحة
        latest_scan = product.scans.first()
            
        context = {
            'status': 'success',
            'product': product,
            'serial': serial_number,
            'current_scan_time': latest_scan.scanned_at, # نرسل وقت المسحة الحالية للفرونت إند
        }
    except Product.DoesNotExist:
        context = {
            'status': 'fail',
            'serial': serial_number
        }
    
    return render(request, 'verify.html', context)
