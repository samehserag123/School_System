from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from .forms import TreasuryEntryForm
from .models import GeneralLedger
from django.contrib.auth.decorators import login_required

@login_required
def daily_closure_report(request):
    today = timezone.now().date()
    
    # 1. فلترة البيانات: المدير يرى الكل، والموظف يرى عهدته الشخصية فقط
    if request.user.is_superuser:
        # أنت كمدير ترى تجميع لكل الموظفين للمطابقة العامة
        user_summary = GeneralLedger.objects.filter(date__date=today).values(
            'collected_by__first_name', 
            'collected_by__last_name', 
            'collected_by__username'
        ).annotate(total_collected=Sum('amount'))
    else:
        # الموظف يرى إجمالي المبالغ التي حصلها هو فقط اليوم
        user_summary = GeneralLedger.objects.filter(
            date__date=today, 
            collected_by=request.user
        ).values(
            'collected_by__first_name', 
            'collected_by__last_name', 
            'collected_by__username'
        ).annotate(total_collected=Sum('amount'))

    # حساب الإجمالي بناءً على نتيجة الفلترة السابقة
    grand_total = sum(item['total_collected'] for item in user_summary)
    denominations = [200, 100, 50, 20, 10, 5, 1]

    return render(request, 'treasury/daily_closure.html', {
        'user_summary': user_summary,
        'grand_total': grand_total,
        'today': today,
        'denominations': denominations,
    })


def treasury_dashboard(request):
    entries = GeneralLedger.objects.all().order_by('-date')
    today = timezone.now().date()
    today_total = GeneralLedger.objects.filter(date__date=today).aggregate(Sum('amount'))['amount__sum'] or 0
    
    return render(request, 'treasury/dashboard.html', {
        'entries': entries,
        'today_total': today_total,
    })

# 2. إضافة إيراد يدوي (الفورم)
@login_required
def add_treasury_entry(request):
    if request.method == 'POST':
        # نمرر المستخدم الحالي للـ Form عند الحفظ
        form = GeneralLedgerForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.collected_by = request.user  # اختيار الموظف تلقائياً
            entry.save()
            return redirect('treasury_dashboard')
    else:
        # هنا بنخلي القيمة الافتراضية للحقل هي المستخدم اللي فاتح الصفحة
        form = GeneralLedgerForm(initial={'collected_by': request.user})
    
    return render(request, 'treasury/add_entry.html', {'form': form})
# 3. الدالة التي تسببت في الخطأ (تقرير الإيرادات اليومي)
def daily_revenue_report(request):
    today = timezone.now().date()
    # جلب حركات اليوم فقط
    daily_entries = GeneralLedger.objects.filter(date__date=today)
    # حساب الإجمالي حسب الفئات (مصاريف، كتب، إلخ)
    category_totals = daily_entries.values('category').annotate(total=Sum('amount'))
    grand_total = daily_entries.aggregate(Sum('amount'))['amount__sum'] or 0

    return render(request, 'treasury/daily_report.html', {
        'entries': daily_entries,
        'category_totals': category_totals,
        'grand_total': grand_total,
        'today': today
    })