from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Sum, Count
from django.utils import timezone
from .forms import TreasuryEntryForm
from .models import GeneralLedger
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from django.db.models import Sum, Max, Count



def students_analytics_view(request):
    total_students = Student.objects.count()
    
    # الطلاب المشتركين وغير المشتركين [cite: 2026-04-09]
    enrolled_ids = CourseGroup.objects.values_list('student_id', flat=True).distinct()
    enrolled_students_count = len(enrolled_ids)
    non_enrolled_count = total_students - enrolled_students_count
    
    # تحليل المواد الأكثر اشتراكاً [cite: 2026-04-09]
    subject_analysis = CourseGroup.objects.values('course_info__subject__name').annotate(
        total=Count('id')
    ).order_by('-total')

    context = {
        'total_students': total_students,
        'enrolled_count': enrolled_students_count,
        'non_enrolled_count': non_enrolled_count,
        'subject_analysis': subject_analysis,
        'title': 'لوحة التحليل الإحصائي الاحترافية'
    }
    return render(request, 'students/analytics_dashboard.html', context)


@login_required
def daily_closure_report(request):
    today = timezone.now().date()

    # 1. جلب كافة الحركات غير المغلقة لليوم
    base_qs = GeneralLedger.objects.filter(
        date__date=today,
        is_closed=False
    )

    # 2. تقسيم الإيرادات لمنع الازدواجية:
    # أ - المصروفات الدراسية (التي تأتي من السجنال وعادة تحمل تصنيف fees)
    school_fees_qs = base_qs.filter(category='fees')
    # ب - الإيرادات الأخرى (زي، كتب، مجموعات) المسجلة يدوياً
    other_revenue_qs = base_qs.exclude(category='fees')

    # 3. حساب الإجماليات باستخدام الحماية من التكرار (رقم الإيصال)
    # للمصروفات
    unique_fees = school_fees_qs.values('receipt_number').annotate(amt=Max('amount'))
    total_fees = sum(item['amt'] for item in unique_fees)

    # للإيرادات الأخرى (بدون استخدام Max لأنها يدوية ولا تتكرر بالسجنال)
    total_other = other_revenue_qs.aggregate(total=Sum('amount'))['total'] or 0

    grand_total = total_fees + total_other

    # 4. ملخص الموظفين
    # 4. ملخص الموظفين - (تم التعديل ليدعم تفاصيل الإيصالات)
    user_summary = []
    # جلب المستخدمين الذين لديهم حركات فعلياً اليوم
    users = User.objects.filter(id__in=base_qs.values_list('collected_by', flat=True).distinct())
    
    for user in users:
        # إجمالي ما حصله الموظف من المصروفات (مع حماية التكرار باستخدام Max)
        u_fees = school_fees_qs.filter(collected_by=user).values('receipt_number').annotate(amt=Max('amount'))
        u_fees_total = sum(item['amt'] for item in u_fees)
        
        # إجمالي ما حصله الموظف من الإيرادات الأخرى (جمع مباشر)
        u_other_total = other_revenue_qs.filter(collected_by=user).aggregate(total=Sum('amount'))['total'] or 0
        
        user_summary.append({
            'user_display': user.get_full_name() or user.username,
            'username': user.username,  # ضروري لربط الـ Modal بالـ JavaScript
            'total_collected': u_fees_total + u_other_total,
            'receipts_count': base_qs.filter(collected_by=user).values('receipt_number').distinct().count()
        })

    # 5. جلب كافة الإيصالات التفصيلية لليوم (مع منع تكرار السجنال في العرض)
    detailed_entries = base_qs.values(
        'collected_by__username', 'receipt_number', 'category', 'amount', 'date'
    ).annotate(actual_amt=Max('amount')).order_by('-date')

    return render(request, 'treasury/daily_closure.html', {
        'user_summary': user_summary,
        'detailed_entries': detailed_entries, # البيانات التفصيلية للنافذة المنبثقة
        'grand_total': grand_total, 
        'today': today,
        'denominations': [200, 100, 50, 20, 10, 5, 1],
    })
    
    
# @login_required
# def daily_closure_report(request):
#     today = timezone.now().date()

#     # 1. الفلتر الأساسي
#     base_qs = GeneralLedger.objects.filter(
#         date__date=today,
#         amount__gt=0,
#         is_closed=False
#     )

#     # 2. 🛡️ الحل العبقري: تجميع المبالغ بناءً على رقم الإيصال الفريد
#     # حتى لو الـ Signal سجل الإيصال 10 مرات، الكود ده هيشوفه "مرة واحدة" بمبلغ واحد
#     unique_receipts = base_qs.values('receipt_number').annotate(
#         actual_amount=Max('amount')
#     )
    
#     # الإجمالي الصافي (ده اللي هيظهر 1 جنيه لو فيه تكرار)
#     grand_total = sum(item['actual_amount'] for item in unique_receipts)

#     # 3. تجميع بيانات الموظفين بدقة (منع التكرار عند كل موظف)
#     summary_raw = base_qs.values('collected_by').annotate(
#         receipts_count=Count('receipt_number', distinct=True)
#     )

#     user_summary = []
#     for item in summary_raw:
#         u_id = item['collected_by']
        
#         # حساب إجمالي الموظف بناءً على إيصالاته الفريدة فقط
#         user_total = sum(
#             r['amt'] for r in base_qs.filter(collected_by_id=u_id)
#             .values('receipt_number').annotate(amt=Max('amount'))
#         )
        
#         if u_id:
#             try:
#                 user_obj = User.objects.get(id=u_id)
#                 display_name = user_obj.get_full_name() or user_obj.username
#             except: display_name = "موظف غير معروف"
#         else:
#             display_name = "إيرادات أخرى (كتب / زي)"

#         user_summary.append({
#             'user_display': display_name,
#             'total_collected': user_total,
#             'receipts_count': item['receipts_count']
#         })

#     return render(request, 'treasury/daily_closure.html', {
#         'user_summary': user_summary,
#         'grand_total': grand_total, 
#         'today': today,
#         'denominations': [200, 100, 50, 20, 10, 5, 1],
#     })

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

# # 2. إضافة إيراد يدوي (الفورم)
# @login_required
# def add_treasury_entry(request):
#     if request.method == 'POST':
#         # 🛡️ تأكد من استخدام اسم الكلاس الصحيح TreasuryEntryForm
#         form = TreasuryEntryForm(request.POST)
#         if form.is_valid():
#             entry = form.save(commit=False)
#             # ربط الحركة بالموظف الذي قام بالإدخال آلياً
#             entry.collected_by = request.user  
#             entry.save()
#             messages.success(request, "تم تسجيل الإيراد بنجاح")
#             return redirect('treasury_dashboard')
#     else:
#         # إرسال مستخدم الجلسة الحالي كقيمة افتراضية للموظف المستلم
#         form = TreasuryEntryForm(initial={'collected_by': request.user})
    
#     return render(request, 'treasury/add_entry.html', {'form': form})


# # 3. الدالة التي تسببت في الخطأ (تقرير الإيرادات اليومي)
# def daily_revenue_report(request):
#     today = timezone.now().date()
#     daily_entries = GeneralLedger.objects.filter(date__date=today)
    
#     # 🛡️ الحساب الصافي بدون تكرار السجنالز
#     unique_data = daily_entries.values('receipt_number', 'category').annotate(amt=Max('amount'))
    
#     # حساب إجمالي الفئات بدقة
#     category_totals = {}
#     grand_total = 0
#     for item in unique_data:
#         cat = item['category']
#         amt = item['amt']
#         category_totals[cat] = category_totals.get(cat, 0) + amt
#         grand_total += amt

#     return render(request, 'treasury/daily_report.html', {
#         'entries': daily_entries,
#         'category_totals': category_totals,
#         'grand_total': grand_total,
#         'today': today
#     })


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
# ... existing code ...