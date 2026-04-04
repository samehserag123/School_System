from django.contrib.auth.views import LoginView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.utils.safestring import mark_safe
from django.contrib import messages
from django.db import transaction
# 2. Database Models & Functions
from django.db import transaction
from django.db.models import Sum, Count, Q, F, DecimalField
from django.db.models.functions import TruncMonth, Coalesce

# 3. Time & Math
from django.utils import timezone
from datetime import date
from decimal import Decimal,InvalidOperation
import json

# 4. Authentication & Security
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required

# 5. REST Framework
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

# 6. PDF & Email & Tasks
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

# ✅ 1. كلاس تسجيل الدخول (يجب أن يكون هنا)
class MyLoginView(LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True       

# ✅ 2. دالة التحقق من المدير (تأكد من شرط authenticated)
def is_manager(user):
    # يجب التأكد أن المستخدم سجل دخوله أولاً لتجنب الأخطاء
    return user.is_authenticated and (user.is_superuser or user.is_staff)

# ✅ 3. تقرير إغلاق الخزينة (إضافة الحماية)
@login_required # يمنع الزوار
@user_passes_test(is_manager) # يمنع غير المديرين
def daily_closure_report(request):
    today = timezone.now().date()
    
    # تجميع المبالغ حسب الموظف لليوم الحالي فقط
    user_summary = GeneralLedger.objects.filter(date__date=today).values(
        'collected_by__first_name', 
        'collected_by__last_name',
        'collected_by__username'
    ).annotate(total_collected=Sum('amount')).order_by('-total_collected')
    
    # إجمالي الخزينة العام لليوم
    grand_total = GeneralLedger.objects.filter(date__date=today).aggregate(total=Sum('amount'))['total'] or 0
    
    return render(request, 'treasury/daily_closure.html', {
        'user_summary': user_summary,
        'grand_total': grand_total,
        'today': today
    })

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


from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required

@login_required
def student_statement_print(request, student_id):
    """
    كشف حساب يجمع المدفوعات من جدول Payment 
    ويعرض الإجماليات المحسوبة في موديل الطالب
    """
    from finance.models import Payment
    try:
        from finance.models import Student
    except ImportError:
        from students.models import Student

    student = get_object_or_404(Student, id=student_id)
    
    # جلب كافة الحركات المالية للطالب من جدول Payment
    all_history = Payment.objects.filter(student=student).order_by('-payment_date', '-id')

    context = {
        'student': student,
        'all_history': all_history,
        # هذه القيم يتم حسابها تلقائياً من الـ properties اللي في الموديل عندك (الصورة الأخيرة)
        'total_paid_all': student.current_year_paid, 
        'total_required': student.total_required_amount, 
        'remaining': student.final_remaining, 
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


from django.contrib.auth.decorators import user_passes_test
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

@staff_member_required
def daily_cashier_summary(request):
    """عرض ملخص الخزينة الموحد (طلاب + إيرادات عامة) لليوم"""
    today = timezone.now().date()
    
    # 1. تجميع مدفوعات الطلاب (جدول Payment)
    student_payments = Payment.objects.filter(payment_date=today).values(
        'collected_by__username', 
        'revenue_category__name'
    ).annotate(
        total_amount=Sum('amount_paid'),
        count=Count('id')
    )

    # 2. تجميع عمليات الخزينة الأخرى (جدول GeneralLedger) 
    # استبعاد "المصروفات" لتجنب التكرار إذا كانت تسمع في الجدولين
    ledger_payments = GeneralLedger.objects.filter(date__date=today).exclude(
        category__icontains="المصروفات"
    ).values(
        'collected_by__username',
        'category'
    ).annotate(
        total_amount=Sum('amount'),
        count=Count('id')
    )

    # 3. حساب الإجمالي العام الموحد لليوم
    total_students = Payment.objects.filter(payment_date=today).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
    total_ledger = GeneralLedger.objects.filter(date__date=today).exclude(
        category__icontains="المصروفات"
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    
    total_day = total_students + total_ledger

    return render(request, 'finance/daily_summary.html', {
        'student_summary': student_payments,
        'ledger_summary': ledger_payments,
        'total_day': total_day,
        'today': today
    })


@staff_member_required
@transaction.atomic
def close_daily_accounts_view(request):
    """إغلاق الخزينة الموحد لعمليات الطلاب والعمليات العامة"""
    if request.method == "POST":
        now_time = timezone.now()
        
        # 1. جلب العمليات المفتوحة من المصدرين
        open_student_payments = Payment.objects.filter(is_closed=False)
        open_ledger_entries = GeneralLedger.objects.filter(is_closed=False)

        # 2. حساب الإجمالي النظري الموحد
        total_student = open_student_payments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
        total_ledger = open_ledger_entries.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        
        theoretical_total = total_student + total_ledger
        
        if theoretical_total == 0:
            messages.warning(request, "لا توجد مبالغ مفتوحة في الخزينة لإغلاقها.")
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
        
        # 4. إنشاء سجل الإغلاق الموحد
        closure_id = f"CL-{now_time.strftime('%Y%m%d%H%M')}"
        closure = DailyClosure.objects.create(
            closed_by=request.user,
            total_cash=theoretical_total,
            actual_cash=actual_total,
            variance=variance,
            closure_id=closure_id,
            notes=f"الفئات: {' | '.join(denominations)} -- ملاحظات: {request.POST.get('notes', '')}"
        )
        
        # 5. القفل النهائي للمصدرين (تحديث حالة is_closed)
        open_student_payments.update(closure=closure, is_closed=True)
        # تأكد من وجود حقل is_closed و closure_id في موديل GeneralLedger
        open_ledger_entries.update(is_closed=True) 
        
        # 6. رسالة التأكيد
        if variance == 0:
            messages.success(request, f"تم الإغلاق بنجاح. الخزينة مطابقة (المبلغ: {actual_total} ج.م).")
        else:
            status = "عجز" if variance < 0 else "زيادة"
            messages.warning(request, f"تم الإغلاق بوجود {status} ({abs(variance)} ج.م). رقم الجرد: {closure_id}")
            
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

    
    
def overdue_report(request):
    active_year = get_active_year() 
    today = timezone.now().date()
    
    # 1. جلب معرفات الطلاب المتأخرين "فقط"
    student_ids = StudentInstallment.objects.filter(
        academic_year=active_year,
        due_date__lte=today
    ).exclude(status__iexact='Paid').values_list('student_id', flat=True).distinct()
    
    # استخدام قاموس لضمان عدم تكرار أي ID قسط
    final_items_dict = {} 
    total_overdue_sum = 0

    for s_id in student_ids:
        # حساب الحصالة (إجمالي المدفوعات)
        total_paid_pool = Payment.objects.filter(
            student_id=s_id,
            academic_year=active_year,
            revenue_category__name__icontains="مصروف"
        ).aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0

        # جلب أقساط الطالب لهذا العام التي حل موعدها
        student_insts = StudentInstallment.objects.filter(
            student_id=s_id,
            academic_year=active_year,
            due_date__lte=today
        ).order_by('due_date')

        temp_pool = total_paid_pool
        
        for inst in student_insts:
            # إذا كان القسط تمت إضافته بالفعل (حماية من التكرار)
            if inst.id in final_items_dict:
                continue

            # توزيع الحصالة
            payment_for_this = min(temp_pool, inst.amount_due)
            remaining = inst.amount_due - payment_for_this
            temp_pool -= payment_for_this

            # الإضافة فقط إذا كان هناك متبقي
            if remaining > 0:
                inst.display_paid = payment_for_this
                inst.display_remaining = remaining
                inst.days_overdue = (today - inst.due_date).days if inst.due_date else 0
                
                # تخزين في القاموس باستخدام الـ ID كمفتاح فريد
                final_items_dict[inst.id] = inst
                total_overdue_sum += remaining

    context = {
        # تحويل قيم القاموس إلى قائمة للمتصفح
        'overdue_items': final_items_dict.values(), 
        'total_overdue': total_overdue_sum,
        'today': today,
    }
    return render(request, 'finance/overdue_report.html', context)

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



# @transaction.atomic
# def quick_collection(request):
#     years = AcademicYear.objects.all()
#     categories = RevenueCategory.objects.all()
    
#     selected_year = request.GET.get('academic_year')
#     url_student_id = request.GET.get('student_id')
    
#     students = Student.objects.all()
#     if selected_year:
#         students = students.filter(academic_year_id=selected_year)

#     if request.method == "POST":
#         p_student_id = request.POST.get('student')
#         category_id = request.POST.get('category')
#         amount_raw = request.POST.get('amount')
        
#         if p_student_id and category_id and amount_raw:
#             try:
#                 amount_to_collect = Decimal(amount_raw)
#                 category = get_object_or_404(RevenueCategory, id=category_id)
#                 student = get_object_or_404(Student, id=p_student_id)
                
#                 active_year = student.academic_year

#                 # --- تطبيع المسميات للتحقق من نوع المصروفات ---
#                 cat_name_normalized = category.name.replace('أ', 'ا').replace('إ', 'ا')
#                 parent_name_normalized = ""
#                 if category.parent:
#                     parent_name_normalized = category.parent.name.replace('أ', 'ا').replace('إ', 'ا')

#                 check_keywords = ["مصاريف اساسيه", "مصروفات اساسيه", "تعليم", "دراسه"]
#                 is_academic_fee = any(word in cat_name_normalized for word in check_keywords) or \
#                                  any(word in parent_name_normalized for word in check_keywords)
                
#                 target_installment = None

#                 if is_academic_fee:
#                     # 1. جلب كل الأقساط غير المدفوعة للطالب مرتبة من الأقدم للأحدث
#                     # هذا يضمن أنه لو دفع "بدري" نغلق له أقساط الترم الثاني أيضاً
#                     installments = StudentInstallment.objects.filter(
#                         student=student, 
#                         academic_year=active_year
#                     ).exclude(status__iexact='Paid').order_by('due_date')

#                     if installments.exists():
#                         remaining_balance = amount_to_collect
#                         # نربط الإيصال بأول قسط تأثر بالدفع
#                         target_installment = installments.first()
                        
#                         for inst in installments:
#                             if remaining_balance <= 0: break
                            
#                             # حساب المتبقي المطلوب لسداد هذا القسط تحديداً
#                             current_paid = getattr(inst, 'paid_amount', getattr(inst, 'amount_paid', 0)) or 0
#                             due_val = inst.amount_due - Decimal(str(current_paid))

#                             if remaining_balance >= due_val:
#                                 # حالة سداد كامل للقسط الحالي
#                                 new_paid_val = inst.amount_due
#                                 inst.status = 'Paid'
#                                 remaining_balance -= due_val
#                             else:
#                                 # حالة سداد جزئي وما عاد فيه مبلغ للأقساط اللي بعدها
#                                 new_paid_val = Decimal(str(current_paid)) + remaining_balance
#                                 inst.status = 'Partial'
#                                 remaining_balance = 0
                            
#                             # تحديث الحقل الصحيح في الموديل
#                             if hasattr(inst, 'paid_amount'): inst.paid_amount = new_paid_val
#                             else: inst.amount_paid = new_paid_val
#                             inst.save()

#                 # تسجيل الإيصال (السيجنال سيتولى ترحيل القيد المالي)
#                 payment = Payment.objects.create(
#                     academic_year=active_year, 
#                     student=student,
#                     revenue_category=category,
#                     amount_paid=amount_to_collect,
#                     installment=target_installment,
#                     payment_date=timezone.now().date(),
#                     collected_by=request.user,
#                     notes=request.POST.get('notes', '')
#                 )
                
#                 messages.success(request, f"تم تحصيل {amount_to_collect} ج.م بنجاح للطالب {student.get_full_name()}.")
#                 return render(request, 'finance/receipt_final.html', {'payment': payment})

#             except Exception as e:
#                 messages.error(request, f"حدث خطأ أثناء المعالجة: {str(e)}")

#     return render(request, 'finance/quick_collection.html', {
#         'years': years,
#         'categories': categories,
#         'students': students,
#         'selected_year': selected_year,
#         'selected_student_id': url_student_id,
#     })

@transaction.atomic
def quick_collection(request):
    years = AcademicYear.objects.all()
    categories = RevenueCategory.objects.all()
    default_category = categories.filter(name__icontains="اساسيه").first() or \
                       categories.filter(name__icontains="مصروف").first()
    
    selected_year = request.GET.get('academic_year')
    url_student_id = request.GET.get('student_id')
    
    students = Student.objects.all()
    if selected_year:
        students = students.filter(academic_year_id=selected_year)

    if request.method == "POST":
        p_student_id = request.POST.get('student')
        category_id = request.POST.get('category')
        amount_raw = request.POST.get('amount')
        
        if p_student_id and category_id and amount_raw:
            try:
                amount_to_collect = Decimal(amount_raw)
                category = get_object_or_404(RevenueCategory, id=category_id)
                student = get_object_or_404(Student, id=p_student_id)
                
                # السنة الدراسية للطالب هي المرجع الأدق للأقساط
                active_year = student.academic_year

                # --- التعديل الجوهري: جعل التحقق مرناً ليشمل الهمزات والمسميات المختلفة ---
                cat_name_normalized = category.name.replace('أ', 'ا').replace('إ', 'ا')
                parent_name_normalized = ""
                if category.parent:
                    parent_name_normalized = category.parent.name.replace('أ', 'ا').replace('إ', 'ا')

                check_keywords = ["مصاريف اساسيه", "مصروفات اساسيه", "تعليم"]
                is_academic_fee = any(word in cat_name_normalized for word in check_keywords) or \
                                 any(word in parent_name_normalized for word in check_keywords)
                
                target_installment = None

                if is_academic_fee:
                    # جلب أقساط الطالب التي لم تدفع بالكامل
                    installments = StudentInstallment.objects.filter(
                        student=student, 
                        academic_year=active_year
                    ).exclude(status__iexact='Paid').order_by('due_date')

                    if installments.exists():
                        remaining = amount_to_collect
                        target_installment = installments.first()
                        
                        for inst in installments:
                            if remaining <= 0: break
                            
                            # التعامل مع مسميات الحقول المختلفة
                            current_paid = getattr(inst, 'paid_amount', getattr(inst, 'amount_paid', 0)) or 0
                            due_val = inst.amount_due - Decimal(str(current_paid))

                            if remaining >= due_val:
                                new_paid_val = inst.amount_due
                                inst.status = 'Paid' # سيؤدي لإخفاء القسط من الرادار
                                remaining -= due_val
                            else:
                                new_paid_val = Decimal(str(current_paid)) + remaining
                                inst.status = 'Partial'
                                remaining = 0
                            
                            if hasattr(inst, 'paid_amount'): inst.paid_amount = new_paid_val
                            else: inst.amount_paid = new_paid_val
                            inst.save()

                # تسجيل الإيصال (السيجنال سيتولى ترحيل نسخة واحدة فقط للخزينة)
                payment = Payment.objects.create(
                    academic_year=active_year, 
                    student=student,
                    revenue_category=category,
                    amount_paid=amount_to_collect,
                    installment=target_installment,
                    payment_date=timezone.now().date(),
                    collected_by=request.user,
                    notes=request.POST.get('notes', '')
                )
                
                messages.success(request, f"تم تحصيل {amount_to_collect} ج.م بنجاح للطالب {student.get_full_name()}.")
                return render(request, 'finance/receipt_final.html', {'payment': payment})

            except Exception as e:
                messages.error(request, f"حدث خطأ أثناء المعالجة: {str(e)}")

    return render(request, 'finance/quick_collection.html', {
        'years': years,
        'categories': categories,
        'default_category': default_category,
        'students': students,
        'selected_year': selected_year,
        'selected_student_id': url_student_id,
    })


@login_required
def finance_dashboard(request):
    active_year = get_active_year()
    if not active_year:
        return render(request, "finance/dashboard.html", {"error": "⚠️ لا توجد سنة نشطة."})

    today = timezone.now().date()
    from treasury.models import GeneralLedger
    from students.models import Student, Grade 
    from django.db.models import Sum

    # 1. إيرادات الخزينة (المصدر الوحيد للجزء العلوي من الداشبورد)
    # هذا سيجلب الـ 800 فقط ويمنع تضاعف الرقم لـ 1600
    today_revenue_all = GeneralLedger.objects.filter(
        date__date=today
    ).aggregate(total=Sum('amount'))['total'] or 0

    month_revenue_all = GeneralLedger.objects.filter(
        date__month=today.month, 
        date__year=today.year
    ).aggregate(total=Sum('amount'))['total'] or 0

    year_revenue_all = GeneralLedger.objects.aggregate(total=Sum('amount'))['total'] or 0

    # 2. بيانات الطلاب لحساب المديونيات وكفاءة التحصيل
    all_students = Student.objects.filter(academic_year=active_year)
    
    # تعريف المتغير بشكل صحيح لتجنب NameError
    total_paid_students = sum(s.current_year_paid for s in all_students) # القيمة هنا 800

    # 3. حساب المديونيات
    total_old_debts = all_students.aggregate(total=Sum('previous_debt'))['total'] or 0
    total_fees_req = sum(s.current_year_fees_amount for s in all_students)
    total_target_all = total_old_debts + total_fees_req
    
    # المديونية المتبقية (14200 - 800 = 13400)
    total_debt_combined = max(total_target_all - total_paid_students, 0)

    # 4. كفاءة الصفوف
    grades_efficiency = []
    for grade in Grade.objects.all():
        students_in_grade = all_students.filter(grade=grade)
        if students_in_grade.exists():
            g_target = sum((s.previous_debt or 0) + s.current_year_fees_amount for s in students_in_grade)
            g_paid = sum(s.current_year_paid for s in students_in_grade)
            grades_efficiency.append({
                'grade': grade.name,
                'target': g_target,
                'paid': g_paid,
                'remaining': max(g_target - g_paid, 0),
                'percentage': round((g_paid / g_target * 100), 1) if g_target > 0 else 0
            })

    context = {
        "active_year": active_year,
        "today_revenue_all": today_revenue_all, 
        "month_revenue_all": month_revenue_all,
        "year_revenue_all": year_revenue_all,
        "total_debt_combined": total_debt_combined,
        "total_percentage": round((total_paid_students / total_target_all * 100), 1) if total_target_all > 0 else 0,
        "total_students_count": all_students.count(),
        "grades_efficiency": grades_efficiency,
        "recent_activities": GeneralLedger.objects.filter(date__date=today).order_by('-date')[:10],
    }
    return render(request, 'finance/dashboard.html', context)

@staff_member_required
@transaction.atomic
def assign_plan(request, student_id=None):
    selected_student = None
    account = None
    target_id = student_id or request.GET.get('student_id')
    
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

            # 1. التحقق الأمني: هل توجد مدفوعات فعلية؟
            # نمنع إعادة التعيين إذا كان الطالب قد دفع فعلياً أي قسط
            has_payments = StudentInstallment.objects.filter(
                student=student, 
                academic_year=student.academic_year,
                status='paid' # أو أي حالة تدل على دفع جزء أو كل المبلغ
            ).exists()

            if has_payments:
                messages.error(request, "🚫 لا يمكن تغيير الخطة المالية: الطالب لديه دفعات مسجلة بالفعل!")
                return redirect(request.path)

            # 2. تحديث الحساب المالي
            # التعديل: ابحث بالطالب والسنة معاً في المعايير (Criteria) وليس الـ defaults
            account_obj, created = StudentAccount.objects.update_or_create(
                student=student,
                academic_year=student.academic_year, # انقلها هنا فوق الـ defaults
                defaults={
                    'installment_plan': plan, 
                    'total_fees': plan.total_amount,
                    'discount': discount_val,
                }
            )
            # 3. حذف الأقساط القديمة (للطلبة الذين لم يدفعوا فقط)
            StudentInstallment.objects.filter(
                student=student, 
                academic_year=student.academic_year,
                status='unpaid'
            ).delete()
            
            # 4. توليد الأقساط الجديدة
            if hasattr(account_obj, 'generate_installments'):
                account_obj.generate_installments()
            
            messages.success(request, f"✅ تم اعتماد البرنامج المالي بنجاح للطالب {student.get_full_name()}")
            return redirect('student_list')

        except Exception as e:
            messages.error(request, f"❌ خطأ تقني: {str(e)}")
            return redirect(request.path)

    context = {
        'years': AcademicYear.objects.all().order_by('-id'),
        'plans': InstallmentPlan.objects.all(),
        'selected_student': selected_student,
        'account': account,
    }
    return render(request, 'finance/assign_plan.html', context)


# @user_passes_test(lambda u: u.is_superuser)
# def generate_installments_view(request, account_id):
#     try:
#         with transaction.atomic():
#             account = get_object_or_404(StudentAccount, id=account_id)
#             student = account.student
#             plan = account.installment_plan

#             if not plan:
#                 messages.error(request, "⚠️ الطالب لا يملك خطة دفع مسجلة.")
#                 return redirect('student_list')

#             # 1. جلب أسماء الأقساط المدفوعة فعلياً لتجنب تكرارها
#             # نستخدم الحقل status أو is_paid حسب الموديل عندك
#             paid_installment_names = StudentInstallment.objects.filter(
#                 student=student, 
#                 status='Paid' # أو استخدم الحقل الذي يعبر عن السداد الكامل
#             ).values_list('installment_name', flat=True)

#             # 2. مسح الأقساط غير المدفوعة فقط (أنت قمت بهذا بالفعل وهو صحيح)
#             StudentInstallment.objects.filter(student=student, status='Pending').delete()

#             # 3. إنشاء الأقساط الجديدة مع استبعاد ما تم دفعه سابقاً
#             plan_items = plan.items.all() 
            
#             installments_to_create = []
#             for item in plan_items:
#                 # شرط الأمان: إذا كان القسط مدفوعاً سابقاً بنفس الاسم، لا تنشئه مرة أخرى
#                 if item.installment_name not in paid_installment_names:
#                     installments_to_create.append(
#                         StudentInstallment(
#                             student=student,
#                             installment_name=item.installment_name,
#                             amount_due=item.amount, # تأكد من اسم الحقل amount_due
#                             due_date=item.due_date,
#                             academic_year=student.academic_year,
#                             status='Pending'
#                         )
#                     )
            
#             # 4. الحفظ الجماعي
#             if installments_to_create:
#                 StudentInstallment.objects.bulk_create(installments_to_create)
#                 messages.success(request, f"✅ تم تحديث الخطة المالية للطالب {student.get_full_name()}.")
#             else:
#                 messages.info(request, "ℹ️ لم يتم إضافة أقساط جديدة لأن الطالب سدد جميع بنود هذه الخطة سابقاً.")
            
#         return redirect('student_list')

#     except Exception as e:
#         messages.error(request, f"❌ خطأ تقني: {str(e)}")
#         return redirect('finance_dashboard')

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
        # البحث عن حساب الطالب
        account = StudentAccount.objects.get(student_id=student_id)
        
        # استخدام الخصائص (Properties) التي قمنا بتعريفها في الموديل سابقاً
        # تحويلها لـ float لضمان إرسالها كـ JSON بشكل سليم
        return JsonResponse({
            "success": True,
            "net_fees": float(account.net_fees),        # صافي المطلوب (بعد الخصم)
            "total_paid": float(account.total_paid),    # إجمالي ما دفعه فعلياً للدراسة
            "total_remaining": float(account.total_remaining), # المتبقي عليه حالياً
            "plan_name": account.installment_plan.name if account.installment_plan else "لم يتم اختيار خطة"
        })

    except StudentAccount.DoesNotExist:
        return JsonResponse({
            "success": False,
            "total_remaining": 0.0,
            "plan_name": "لا يوجد حساب مالي"
        })
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})
# =====================================================
# 📑 تقرير المتأخرات
# =====================================================


# =====================================================
# 🧾 طباعة إيصال
# =====================================================
@user_passes_test(superuser_only)
def print_receipt(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{payment.id}.pdf"'

    p = canvas.Canvas(response)
    p.drawString(100, 800, "Payment Receipt")

    student_name = (
        f"{payment.student.first_name} {payment.student.last_name}"
        if payment.student else "N/A"
    )

    p.drawString(100, 770, f"Student: {student_name}")
    p.drawString(100, 750, f"Amount: {payment.amount_paid}")
    p.drawString(100, 730, f"Date: {payment.payment_date}")

    p.showPage()
    p.save()

    return response

# =====================================================
# 🔒 إقفال الشهر
# =====================================================
@user_passes_test(superuser_only)
def close_month(request):
    today = timezone.now().date()
    first_day = today.replace(day=1)

    # نتأكد إن الشهر متقفلش قبل كده
    if MonthlyClosure.objects.filter(month=first_day).exists():
        messages.error(request, "تم إقفال هذا الشهر بالفعل")
        return redirect('finance_dashboard')

    active_year = get_active_year()

    total_collected = Payment.objects.filter(
        academic_year=active_year,
        payment_date__year=today.year,
        payment_date__month=today.month
    ).aggregate(total=Sum('amount_paid'))['total'] or 0

    MonthlyClosure.objects.create(
        month=first_day,
        total_collected=total_collected,
        total_remaining=0
    )

    messages.success(request, "تم إقفال الشهر بنجاح ✅")
    return redirect('finance_dashboard')
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
    """عرض قائمة بجميع خطط التقسيط المتاحة في المدرسة"""
    # جلب جميع الخطط مع بنودها (الأقساط) لتحسين الأداء
    plans = InstallmentPlan.objects.prefetch_related('items').all()
    return render(request, 'finance/plan_list.html', {'plans': plans})



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