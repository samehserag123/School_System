from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.apps import apps
# استيرادات Rest Framework
from rest_framework import generics, filters
# استيراد الموديلات من تطبيق الطلاب
from .models import Student, Grade, ExternalStudent
from .forms import StudentForm
from .serializers import StudentSerializer
from django.urls import reverse
from finance.models import StudentAccount, AcademicYear, DeliveryRecord 
from finance.utils import get_active_year
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from students.models import Classroom
from django.db.models import Sum, F, Q, Count, DecimalField, Value

from finance.models import Payment  # تأكد أن اسم التطبيق عندك هو finance
from .forms import CourseGroupForm
from .models import CourseGroup, CoursePayment
from django.db.models.functions import Coalesce
# الاستيراد من الموديلات (الجداول)
from .models import BookSale, InventoryItem, InventoryRestock, GradePackagePrice, CourseGroup
# الاستيراد من الفورمات (النماذج) - هذا هو السطر الذي ينقصك
from .forms import RestockForm
from .forms import BookSaleForm
import datetime
import json
# تأكد من استيراد الموديلات الصحيحة من تطبيقاتك
from students.models import Student, Grade, Classroom 
from finance.models import StudentInstallment

from django.contrib.auth.decorators import login_required
from treasury.models import GeneralLedger
import uuid # لاستخدامه في توليد رقم فريد
from decimal import Decimal

from datetime import date, timedelta

# students/views.py
from .models import BusRoute, BusSubscription, BusPayment, MiscellaneousRevenue
from .models import RemedialFeeSetting
import time
import traceback
from .forms import RemedialProgramForm  # تأكد من إضافة هذا السطر

from .models import RemedialProgramRecord


def save_remedial_from_registry(request):
    if request.method == 'POST':
        student_id = request.POST.get('student')
        subjects_count = int(request.POST.get('subjects_count', 1))
        notes = request.POST.get('notes', '')
        
        try:
            student = Student.objects.get(id=student_id)
            active_year = get_active_year() 
            fee_per_subject = 150.00 
            total_amount = subjects_count * fee_per_subject
            
            RemedialProgramRecord.objects.create(
                student=student,
                academic_year=active_year,
                subjects_count=subjects_count,
                total_amount=total_amount,
                notes=notes,
                is_paid=False
            )
            # بدلاً من redirect، نرسل رد نجاح بصيغة JSON
            return JsonResponse({'success': True, 'message': f'تم تأكيد البرنامج للطالب {student.first_name} بنجاح.'})
            
        except Student.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'خطأ: لم يتم العثور على الطالب.'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})

    return JsonResponse({'success': False, 'message': 'طلب غير صالح.'})



def manage_remedial_dashboard(request):
    """دالة عرض لوحة تحكم البرنامج العلاجي"""
    active_year = get_active_year() # تأكد من وجود دالة get_active_year لديك
    
    # جلب السجلات مقسمة (مسدد وغير مسدد)
    unpaid_records = RemedialProgramRecord.objects.filter(academic_year=active_year, is_paid=False).order_by('-created_at')
    paid_records = RemedialProgramRecord.objects.filter(academic_year=active_year, is_paid=True).order_by('-created_at')

    context = {
        'unpaid_records': unpaid_records,
        'paid_records': paid_records,
        'active_year': active_year,
    }
    # هنا السيرفر سيبحث عن الملف الجديد الذي أنشأناه
    return render(request, 'students/remedial_dashboard.html', context)

def pay_remedial_record(request, record_id):
    """دالة تأكيد السداد"""
    if request.method == 'POST':
        try:
            record = RemedialProgramRecord.objects.get(id=record_id)
            if not record.is_paid:
                record.is_paid = True
                record.save()
                return JsonResponse({'success': True, 'message': 'تم تسجيل السداد بنجاح ونقل الطالب للأرشيف.'})
            else:
                return JsonResponse({'success': False, 'error': 'هذه المديونية مسددة بالفعل.'})
        except RemedialProgramRecord.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'السجل غير موجود.'})        

def add_remedial_program(request):
    active_year = get_active_year() 
    students = Student.objects.all()
    
    fee_setting = RemedialFeeSetting.objects.filter(academic_year=active_year).first()
    fee_per_subject = fee_setting.fee_per_subject if fee_setting else 150.00

    if request.method == 'POST':
        # ... (نفس كود الحفظ الموجود لديك لا تغيره) ...
        pass # افترض أن كود الحفظ هنا

    # 🌟 السطر الجديد: جلب كل الطلاب المسجلين في البرنامج العلاجي لهذا العام
    remedial_records = RemedialProgramRecord.objects.filter(academic_year=active_year).order_by('-created_at')

    context = {
        'students': students,
        'fee_per_subject': float(fee_per_subject),
        'active_year': active_year,
        'remedial_records': remedial_records, # 🌟 إرسال السجل للصفحة
    }
    return render(request, 'students/add_remedial.html', context)


@login_required
def misc_revenue_view(request):
    if request.method == 'POST':
        try:
            # 🟢 الحماية البنكية: إما أن يحفظ في الجدولين أو يلغي العملية
            with transaction.atomic():
                title = request.POST.get('title')
                revenue_type = request.POST.get('revenue_type')
                amount = Decimal(request.POST.get('amount', 0))
                notes = request.POST.get('notes', '')

                # 1. الحفظ في جدول الإيرادات المتنوعة
                misc_rev = MiscellaneousRevenue.objects.create(
                    title=title,
                    revenue_type=revenue_type,
                    amount=amount,
                    notes=notes,
                    collected_by=request.user
                )

                # 2. محاولة استيراد الخزينة الذكية (بحث في treasury ثم finance)
                try:
                    from treasury.models import GeneralLedger
                except ImportError:
                    from finance.models import GeneralLedger
                
                # 3. التسميع المباشر في الخزينة العامة
                unique_receipt = f"MISC-{misc_rev.id}-{int(time.time())}"
                
                GeneralLedger.objects.create(
                    student=None, # إيراد عام لا يخص طالباً بعينه
                    amount=amount,
                    category='other',  # 🟢 'other' هي الكلمة السرية ليظهر في الجرد كإيراد متنوع
                    notes=f"إيراد متنوع: {title} ({misc_rev.get_revenue_type_display()})",
                    receipt_number=unique_receipt,
                    collected_by=request.user 
                )
                
            
        except Exception as e:
            print(traceback.format_exc())
            messages.error(request, f"⚠️ فشل تسجيل الإيراد! السبب: {str(e)}")
            
        return redirect('misc_revenue')

    # ==========================================
    # تجهيز البيانات للعرض (GET Request)
    # ==========================================
    revenues = MiscellaneousRevenue.objects.all()
    total_revenue = sum(rev.amount for rev in revenues)
    
    # حساب إيرادات اليوم فقط
    today = timezone.now().date()
    today_revenue = sum(rev.amount for rev in revenues if rev.date.date() == today)

    context = {
        'revenues': revenues,
        'total_revenue': total_revenue,
        'today_revenue': today_revenue,
    }
    return render(request, 'finance/misc_revenue.html', context)


@login_required
def bus_dashboard_view(request):
    # ==========================================
    # 1. معالجة طلبات الـ POST (النماذج - Modals)
    # ==========================================
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # أ) إضافة خط سير جديد
        if action == 'add_route':
            try:
                BusRoute.objects.create(
                    name=request.POST.get('name'),
                    driver_name=request.POST.get('driver_name'),
                    driver_phone=request.POST.get('driver_phone'),
                    bus_number=request.POST.get('bus_number'),
                    capacity=request.POST.get('capacity', 20),
                    monthly_price=request.POST.get('monthly_price', 0),
                    term_price=request.POST.get('term_price', 0),
                    yearly_price=request.POST.get('yearly_price', 0),
                )
            except Exception as e:
                messages.error(request, f'خطأ أثناء إضافة الخط: {e}')
            return redirect('bus_dashboard')

        # ب) إضافة اشتراك طالب جديد
        elif action == 'add_subscription':
            try:
                student_id = request.POST.get('student_id')
                route_id = request.POST.get('route_id')
                
                student = get_object_or_404(Student, id=student_id)
                route = get_object_or_404(BusRoute, id=route_id)
                
                BusSubscription.objects.create(
                    student=student,
                    route=route,
                    sub_type=request.POST.get('sub_type'),
                    start_date=request.POST.get('start_date'),
                    end_date=request.POST.get('end_date'),
                    required_amount=request.POST.get('required_amount', 0),
                    notes=request.POST.get('notes', '')
                )
            except Exception as e:
                messages.error(request, f'خطأ أثناء إضافة الاشتراك: {e}')
            return redirect('bus_dashboard')

        # ج) تحصيل مبلغ (سداد) وتسميعه في الخزينة
        elif action == 'add_payment':
            sub_id = request.POST.get('subscription_id')
            amount = request.POST.get('amount_paid')
            
            try:
                # 🟢 الحماية البنكية: إما أن تتم الإضافة في الجدولين، أو يتم التراجع عنهما معاً
                with transaction.atomic():
                    subscription = get_object_or_404(BusSubscription, id=sub_id)
                    
                    # 1. تسجيل الدفع في نظام الباص (لكي تنقص مديونيته)
                    payment = BusPayment.objects.create(
                        subscription=subscription,
                        amount_paid=Decimal(amount),
                        collected_by=request.user,
                    )
                    
                    # 2. محاولة استيراد الخزينة الذكية (بحث في Treasury ثم Finance)
                    try:
                        from treasury.models import GeneralLedger
                    except ImportError:
                        from finance.models import GeneralLedger
                    
                    # 3. التسميع المباشر في الخزينة العامة
                    unique_receipt = f"BUS-{payment.id}-{int(time.time())}"
                    
                    GeneralLedger.objects.create(
                        student=subscription.student,
                        amount=Decimal(amount),
                        category='bus',  # 🟢 شرط التسميع في الجرد كـ "اشتراك باص"
                        notes=f"تحصيل اشتراك باص - خط: {subscription.route.name}",
                        receipt_number=unique_receipt,
                        collected_by=request.user 
                    )
                    
                # لن تظهر هذه الرسالة إلا إذا تمت العملية في الجدولين بنجاح
                
            except Exception as e:
                # طباعة الخطأ كاملاً للمطور في شاشة الدوس (Terminal)
                print(traceback.format_exc())
                # عرض الخطأ صراحة للمستخدم ليعرف السبب الحقيقي
                messages.error(request, f"⚠️ فشل التحصيل والتسميع! السبب: {str(e)}")
                
            return redirect('bus_dashboard')

    # ==========================================
    # 2. تجهيز البيانات للعرض (GET)
    # ==========================================
    routes = BusRoute.objects.all()
    subscriptions = BusSubscription.objects.select_related('student', 'route').all()
    
    # قائمة الطلاب للـ Select2
    students = Student.objects.filter(is_active=True).values('id', 'first_name', 'last_name', 'student_code')
    
    # إحصائيات علوية
    total_bus_students = subscriptions.filter(is_active=True).count()
    total_revenue = sum(sub.total_paid for sub in subscriptions)
    total_debt = sum(sub.remaining_amount for sub in subscriptions if sub.remaining_amount > 0)
    
    context = {
        'routes': routes,
        'subscriptions': subscriptions,
        'students': students,
        'total_bus_students': total_bus_students,
        'total_revenue': total_revenue,
        'total_debt': total_debt,
        'today': timezone.now().date(),
    }
    return render(request, 'students/bus_dashboard.html', context)


def students_analytics_view(request):
    # إجمالي الطلاب مع بيانات المرحلة التعليمية
    all_students = Student.objects.select_related('academic_year', 'grade').all()
    total_students = all_students.count()
    
    # الطلاب المشتركين فعلياً
    enrolled_ids = CourseGroup.objects.values_list('student_id', flat=True).distinct()
    
    # تصنيف القوائم
    enrolled_students = all_students.filter(id__in=enrolled_ids)
    non_enrolled_students = all_students.exclude(id__in=enrolled_ids)
    
    # تحليل المواد
    subject_analysis = CourseGroup.objects.values('course_info__subject__name').annotate(
        total=Count('id')
    ).order_by('-total')

    context = {
        'total_students': total_students,
        'enrolled_students': enrolled_students,
        'non_enrolled_students': non_enrolled_students,
        'subject_analysis': subject_analysis,
        'enrolled_count': enrolled_students.count(),
        'non_enrolled_count': non_enrolled_students.count(),
    }
    return render(request, 'students/analytics_dashboard.html', context)
# في ملف students/views.py

# students/views.py

@login_required
def student_detail_analytics(request, student_id):
    # 1. جلب بيانات الطالب الأساسية
    student = get_object_or_404(Student, id=student_id)
    
    # 2. جلب كل الاشتراكات (المواد) التي سجل فيها هذا الطالب
    enrollments = CourseGroup.objects.filter(student=student).select_related(
        'course_info__subject', 
        'course_info__teacher'
    )
    
    # 3. جلب المواد التي لم يشترك فيها الطالب (اختياري للتحليل)
    subscribed_subjects = enrollments.values_list('course_info__subject_id', flat=True)
    # تأكد من استيراد موديل Subject في أعلى الملف
    from .models import Subject 
    other_subjects = Subject.objects.exclude(id__in=subscribed_subjects)

    context = {
        'student': student,
        'enrollments': enrollments,
        'other_subjects': other_subjects,
        'title': f'تحليل ملف: {student.get_full_name()}'
    }
    return render(request, 'students/student_detail.html', context)

def course_prices_view(request):
    # 1. معالجة الطلب بناءً على النوع (POST أو GET)
    if request.method == 'POST':
        form = CourseGroupForm(request.POST)
        
        # إعداد شكل عرض الطالب (للطالب الداخلي)
        form.fields['student'].queryset = Student.objects.all()
        form.fields['student'].label_from_instance = lambda obj: f"{obj.get_full_name()} | {obj.student_code} | {obj.national_id}"

        if form.is_valid():
            is_external = form.cleaned_data.get('is_external')
            sessions = form.cleaned_data.get('total_sessions') or 4
            course_info = form.cleaned_data.get('course_info')

            # حساب السعر بناءً على عدد الحصص
            price_per_session = course_info.price / 4
            calculated_amount = price_per_session * sessions

            instance = form.save(commit=False)
            instance.required_amount = calculated_amount
            
            if is_external:
                # التعامل مع الطالب الخارجي:
                # نقوم بإنشاء سجل جديد دائماً للسماح بتكرار الأسماء (بدون بحث منعاً للخطأ)
                ext_student = ExternalStudent.objects.create(
                    full_name=form.cleaned_data.get('ext_name'),
                    phone_number=form.cleaned_data.get('ext_phone')
                )
                instance.external_student = ext_student
                instance.student = None
            
            instance.save()
            return redirect('course_prices')
    else:
        # حالة الـ GET (فتح الصفحة لأول مرة)
        form = CourseGroupForm(initial={'total_sessions': 4})
        form.fields['student'].queryset = Student.objects.all()
        form.fields['student'].label_from_instance = lambda obj: f"{obj.get_full_name()} | {obj.student_code} | {obj.national_id}"

    # 2. جلب البيانات الأساسية للجدول
    courses_query = CourseGroup.objects.select_related(
        'student', 'external_student', 
        'course_info__subject', 'course_info__teacher'
    ).all().order_by('-id')

    # 3. الفلترة الزمنية
    time_filter = request.GET.get('time_filter')
    date_from = request.GET.get('date_from') 
    date_to = request.GET.get('date_to')
    now = timezone.now()

    if date_from and date_to:
        courses_query = courses_query.filter(registration_date__range=[date_from, date_to])
        time_filter = 'custom'
    elif time_filter == 'today':
        courses_query = courses_query.filter(registration_date=now.date())
    elif time_filter == 'month':
        courses_query = courses_query.filter(registration_date__gte=now - timedelta(days=30))
    elif time_filter == 'year':
        courses_query = courses_query.filter(registration_date__gte=now - timedelta(days=365))

    # 4. حساب الإجماليات
    total_revenue = sum(course.required_amount for course in courses_query)
    total_collected = sum(course.total_paid for course in courses_query)

    # 5. الترقيم (Pagination)
    paginator = Paginator(courses_query, 15)
    page_number = request.GET.get('page')
    courses_page = paginator.get_page(page_number)

    # 6. جلب قائمة الأسماء الخارجية الفريدة (للبحث السريع في التمبلت)
    # نستخدم values_list للحصول على الأسماء فقط مع حذف التكرار في القائمة المقترحة
    existing_external_names = ExternalStudent.objects.values_list('full_name', flat=True).distinct()

    # 7. تمرير البيانات للتمبلت
    context = {
        'courses': courses_page,
        'form': form,
        'total_revenue': total_revenue,
        'total_collected': total_collected,
        'total_remaining': total_revenue - total_collected,
        'current_filter': time_filter,
        'date_from': date_from,
        'date_to': date_to,
        'existing_external_names': existing_external_names, # الأسماء المقترحة
        'title': 'سجل المجموعات والإيرادات'
    }
    
    return render(request, 'students/course_prices.html', context)


@login_required
def mark_session_attendance(request, enrollment_id):
    if request.method == 'POST':
        from .models import CourseGroup, StudentSession
        enrollment = get_object_or_404(CourseGroup, id=enrollment_id)
        
        # التأكد من وجود رصيد حصص
        if enrollment.remaining_sessions <= 0:
            return JsonResponse({'status': 'error', 'message': 'لا يوجد رصيد حصص كافٍ للطالب!'}, status=400)

        # منع تسجيل حصتين في نفس اليوم لنفس الكورس
        today = timezone.now().date()
        if StudentSession.objects.filter(course_enrollment=enrollment, session_date=today).exists():
             return JsonResponse({'status': 'error', 'message': 'تم تحضير الطالب اليوم بالفعل!'}, status=400)

        # إنشاء سجل الحصة
        StudentSession.objects.create(
            course_enrollment=enrollment,
            session_date=today,
            attendance_status='attended'
        )
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error', 'message': 'Invalid Request'}, status=400)

# 2. دالة جلب التاريخ (تُنفذ عند الضغط على زر الساعة)
@login_required
def session_history_api(request, enrollment_id):
    from .models import CourseGroup
    enrollment = get_object_or_404(CourseGroup, id=enrollment_id)
    sessions = enrollment.sessions.all().order_by('-session_date')
    
    data = [
        {'date': s.session_date.strftime('%Y-%m-%d')} 
        for s in sessions
    ]
    return JsonResponse({'sessions': data})
    
    
@login_required
def collect_fee_view(request, enrollment_id):
    # 1. جلب البيانات الأساسية
    # تأكد من استيراد الموديل الصحيح CourseGroup أو الموديل الذي تستخدمه للالتحاق
    from .models import CourseGroup 
    enrollment = get_object_or_404(CourseGroup, id=enrollment_id)
    
    if request.method == 'POST':
        # 2. استقبال وتحويل المبلغ بدقة
        try:
            amount_paid = Decimal(request.POST.get('amount_paid', '0'))
        except (ValueError, TypeError):
            amount_paid = Decimal('0')
            
        notes = request.POST.get('notes', '')
        
        if amount_paid > 0:
            # 3. تسجيل الدفعة في جدول مدفوعات الكورسات
            from .models import CoursePayment
            course_pay = CoursePayment.objects.create(
                course_enrollment=enrollment,
                amount_paid=amount_paid,
                payment_date=timezone.now(),
                collected_by=request.user, 
                notes=notes
            )
            
            # 4. تسجيل العملية في الخزينة العامة لضبط إحصائيات الداشبورد
            from treasury.models import GeneralLedger
            
            # 🛡️ الحل الجذري لمنع IntegrityError (receipt_number key already exists)
            # يجب تمرير رقم إيصال فريد يميّز هذه الحركة في الخزينة
            GeneralLedger.objects.create(
                student=enrollment.student,
                amount=amount_paid,
                category='كورس',
                # توليد رقم مرجعي فريد يبدأ بـ CP (Course Payment) متبوعاً بمعرف العملية وجزء عشوائي
                receipt_number=f"CP-{course_pay.id}-{uuid.uuid4().hex[:4].upper()}",
                notes=f"تحصيل كورس: {enrollment.course_info.subject.name} - {notes}",
                date=timezone.now(),
                collected_by=request.user 
            )
            
            return redirect('course_prices')
            
    # 5. عرض صفحة التحصيل في حالة الـ GET
    return render(request, 'students/collect_fee.html', {'enrollment': enrollment})


from django.db.models import Q, Value, CharField
from django.db.models.functions import Concat
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
# تأكد من استيراد النماذج (Models) الخاصة بك هنا

def student_registry_view(request):
    # 1. تحديد السنة الدراسية (أرشيف أو حالية)
    year_id = request.GET.get('year_id')
    if year_id:
        target_year = get_object_or_404(AcademicYear, id=year_id)
        base_query = Student.objects.filter(academic_year=target_year)
    else:
        active_year = AcademicYear.objects.filter(is_active=True).first()
        base_query = Student.objects.filter(academic_year=active_year, is_active=True)

    # 2. استقبال قيم الفلاتر من الطلب (Request)
    query = request.GET.get('q', '').strip()
    grade = request.GET.get('grade', '')
    classroom = request.GET.get('classroom', '')
    spec = request.GET.get('spec', '')
    gender = request.GET.get('gender', '')
    religion = request.GET.get('religion', '')
    integ = request.GET.get('integ', '')

    # 3. تطبيق الفلترة المتقدمة للبحث في الأسماء [تعديل جوهري هنا]
    if query:
        # نقوم بدمج الاسم الأول مع اسم العائلة بمسافة بينهما للبحث في الاسم بالكامل
        base_query = base_query.annotate(
            full_name_db=Concat('first_name', Value(' '), 'last_name', output_field=CharField())
        ).filter(
            Q(first_name__icontains=query) | 
            Q(last_name__icontains=query) | 
            Q(full_name_db__icontains=query) | # للبحث في "الاسم الأول + الأخير" معاً
            Q(national_id__icontains=query)    # للبحث بالرقم القومي
        )
    
    # 4. بقية الفلاتر (الصفوف، الفصول، التخصص، إلخ)
    if grade:
        base_query = base_query.filter(grade__name=grade)
    if classroom:
        base_query = base_query.filter(classroom__name=classroom)
    if spec:
        base_query = base_query.filter(specialization=spec)
    if gender:
        gender_map = {'بنين': 'Male', 'بنات': 'Female'}
        base_query = base_query.filter(gender=gender_map.get(gender))
    if religion:
        rel_map = {'مسلم': 'Muslim', 'مسيحي': 'Christian'}
        base_query = base_query.filter(religion=rel_map.get(religion))
    if integ:
        base_query = base_query.filter(integration_status=(integ == 'نعم'))

    # 5. حساب الإحصائيات بناءً على النتائج المفلترة فقط (شاملة كل الصفحات)
    stats = {
        'total': base_query.count(),
        'male': base_query.filter(gender='Male').count(),
        'female': base_query.filter(gender='Female').count(),
        'muslim': base_query.filter(religion='Muslim').count(),
        'christian': base_query.filter(religion='Christian').count(),
        'integration': base_query.filter(integration_status=True).count(),
    }
    
    # 6. نظام الترقيم (Pagination)
    student_list = base_query.order_by('first_name')
    paginator = Paginator(student_list, 20)
    page_number = request.GET.get('page')
    students_page = paginator.get_page(page_number)
    
    context = {
        'students': students_page,
        'stats': stats,
        'all_grades': Grade.objects.all(),
        'all_classrooms': Classroom.objects.all(),
        'all_specs': Student.SPECIALIZATION_CHOICES,
        'current_year': target_year if year_id else active_year,
        'is_archive': bool(year_id),
    }

    # تأكد أن اسم الملف هنا مطابق تماماً لملف الـ HTML الموجود في تطبيقك
    return render(request, 'student_registry.html', context)

def get_pending_sales_api(request, student_id):
    # جلب الأذونات التي لم تدفع بالكامل لهذا الطالب
    sales = BookSale.objects.filter(student_id=student_id).exclude(status='paid')
    
    sales_data = []
    for s in sales:
        if s.remaining_amount > 0: # التأكد باستخدام الـ property التي أنشأتها
            sales_data.append({
                'id': s.id,
                'item_name': s.item.display_name,
                'remaining': float(s.remaining_amount)
            })
            
    return JsonResponse({'sales': sales_data})


def admin_add_restock(request):
    if request.method == 'POST':
        form = RestockForm(request.POST)
        item_id = request.POST.get('item_id')
        
        if form.is_valid() and item_id:
            item = get_object_or_404(InventoryItem, id=item_id)
            restock = form.save(commit=False)
            restock.item = item
            restock.save()
            
            # 🛑 تنبيه: لا تضف سطر (item.stock_quantity += ...) هنا 
            # لأننا نعتمد الآن على الحساب التلقائي في الموديل لمنع التكرار
            
            return redirect('admin_add_restock') 
        
        # في حال كان الفورم غير صحيح
        items = InventoryItem.objects.all().select_related('subject', 'grade', 'uniform')
        return render(request, 'students/admin_restock.html', {'form': form, 'items': items})

    else:
        # حالة الـ GET (عند فتح الصفحة أول مرة)
        form = RestockForm()
    
    # جلب البيانات لعرضها في القائمة المنسدلة (Select) في كل الحالات
    items = InventoryItem.objects.all().select_related('subject', 'grade', 'uniform')
    
    # 🟢 هذا الـ return هو الذي كان ينقصك ويسبب الخطأ
    return render(request, 'students/admin_restock.html', {'form': form, 'items': items})

    
def get_item_history(request, item_id):
    
    
    try:
        item = InventoryItem.objects.get(id=item_id)
        history_list = []

        # --- 🟢 أولاً: جلب تفاصيل الوارد (التوريدات) ---
        # نجلب العمليات من الجدول الجديد الذي أضفته
        restocks = InventoryRestock.objects.filter(item_id=item_id).order_by('-restock_date')
        
        for stock in restocks:
            history_list.append({
                'date': stock.restock_date.strftime('%Y-%m-%d') if stock.restock_date else "---",
                'type': 'وارد (توريد)',
                'color': 'success', # أخضر
                'qty': stock.quantity,
                'note': stock.note or "إضافة كمية للمخزن"
            })

        # إذا لم يكن هناك توريدات مسجلة، نظهر الكمية الأصلية كـ "وارد افتتاحي"
        if not restocks.exists():
            history_list.append({
                'date': "---",
                'type': 'وارد (رصيد أول)',
                'color': 'success',
                'qty': item.stock_quantity,
                'note': "الكمية الأساسية عند تعريف الصنف"
            })

        # --- 🔴 ثانياً: جلب تفاصيل المنصرف (عمليات الصرف) ---
        sales = BookSale.objects.filter(item_id=item_id).order_by('-sale_date')
        
        for sale in sales:
            # دمج الاسم الأول والأخير للطالب
            student_name = f"{sale.student.first_name} {sale.student.last_name}" if sale.student else "---"
            
            history_list.append({
                'date': sale.sale_date.strftime('%Y-%m-%d') if sale.sale_date else "---",
                'type': 'منصرف',
                'color': 'danger', # أحمر
                'qty': sale.quantity,
                'note': f"طالب: {student_name}"
            })

        # ترتيب كل العمليات من الأحدث للأقدم بناءً على التاريخ
        # (اختياري: إذا أردت دمجهم بترتيب زمني واحد)
        # history_list.sort(key=lambda x: x['date'], reverse=True)

        return JsonResponse({'history': history_list})

    except InventoryItem.DoesNotExist:
        return JsonResponse({'history': [], 'error': 'Item not found'})
    
    

def inventory_category_report(request):
    # جلب الأصناف
    inventory_items = InventoryItem.objects.select_related(
        'grade', 'subject', 'uniform'
    ).order_by('item_type')

    summary_dict = {}

    for item in inventory_items:
        # 1. نستخدم display_name كمفتاح للتجميع (مثلاً: "كتاب اكتشف")
        name_key = item.display_name
        
        if name_key not in summary_dict:
            summary_dict[name_key] = {
                'name': name_key,
                'item_type': item.item_type,
                'total_stock': 0,
                'total_sold': 0,
            }
        
        # 2. الجمع التراكمي: نجمع كل الكميات التي لها نفس الاسم
        # item.total_incoming يحسب (الافتتاحي + التوريدات) لهذا السجل
        summary_dict[name_key]['total_stock'] += item.total_incoming
        summary_dict[name_key]['total_sold'] += item.total_sold_count

    # 3. حساب الرصيد المتبقي النهائي بعد التجميع
    for val in summary_dict.values():
        val['total_remaining'] = val['total_stock'] - val['total_sold']

    return render(request, 'students/books/inventory_report.html', {
        'inventory': inventory_items, # للجدول التفصيلي (السفلي)
        'inventory_summary': summary_dict.values() # لجدول الملخص (العلوي)
    })
    
    
def book_sales_list(request):
    # عرض آخر عمليات الصرف أولاً
    sales = BookSale.objects.all().order_by('-sale_date')
    return render(request, 'books/sales_list.html', {'sales': sales})

# ابحث عن دالة add_book_sale وقم بتعديلها لتصبح هكذا:

def add_book_sale(request):
    # جلب السنة الأكاديمية النشطة في البداية لتجنب أخطاء NoneType
    active_year = get_active_year() 
    
    if request.method == 'POST':
        form = BookSaleForm(request.POST)
        if form.is_valid():
            sale = form.save(commit=False)
            inventory_item = sale.item 
            student = sale.student
            requested_qty = sale.quantity

            # 1. التحقق من وجود السنة الأكاديمية للطالب وللنظام
            if not student.academic_year:
                messages.error(request, f"⚠️ الطالب {student.get_full_name()} غير مرتبط بسنة أكاديمية.")
                return render(request, 'books/add_sale.html', {'form': form})
            
            if not student.grade:
                messages.error(request, f"⚠️ الطالب {student.get_full_name()} غير مرتبط بصف دراسي.")
                return render(request, 'books/add_sale.html', {'form': form})

            # 2. جلب السعر بناءً على (الصف + السنة الدراسية للطالب)
            try:
                package = GradePackagePrice.objects.get(
                    grade=student.grade, 
                    academic_year=student.academic_year
                )
                if inventory_item.item_type == 'book':
                    unit_price = package.books_price
                else:
                    unit_price = package.uniform_price
                
                sale.total_amount = unit_price * requested_qty
                # ربط عملية البيع بالسنة الأكاديمية النشطة
                
            except GradePackagePrice.DoesNotExist:
                # استخدام .name بأمان عبر التحقق أو استخدام default
                grade_name = student.grade.name if student.grade else "غير معروف"
                year_name = student.academic_year.name if student.academic_year else "غير محددة"
                messages.error(request, f"⚠️ لم يتم تحديد سعر الباقة لصف {grade_name} في سنة {year_name}")
                return render(request, 'books/add_sale.html', {'form': form})

            # 3. التأكد من توفر الكمية في المخزن
            if requested_qty > inventory_item.remaining_qty:
                messages.error(request, f"⚠️ المخزن غير كافٍ! المتوفر حالياً: {inventory_item.remaining_qty}")
                return render(request, 'books/add_sale.html', {'form': form})
            
            # 4. الربط مع الموظف الحالي (مهم جداً لعملية السداد الآلي في الموديل)
            sale._current_user = request.user 
            
            # 5. الحفظ النهائي
            sale.save()
            
            # 6. رسالة نجاح مخصصة حسب حالة الدفع
            if sale.pay_now > 0:
                messages.success(request, f"✅ تم تسجيل الصرف وتوريد مبلغ {sale.pay_now} ج.م للخزينة للطالب {student.get_full_name()}.")
            else:
                messages.warning(request, f"تم تسجيل إذن الصرف للطالب {student.get_full_name()} بدون سداد مالي.")
            
            # توجيه المستخدم لصفحة الطباعة فوراً
            return redirect('print_book_receipt', sale_id=sale.id)
        
        return render(request, 'books/add_sale.html', {'form': form})

    else:
        form = BookSaleForm()
    
    return render(request, 'books/add_sale.html', {'form': form})

from django.http import JsonResponse
from django.db.models import Sum

def student_financial_api(request, student_id):
    try:
        student = Student.objects.get(id=student_id)
        
        # 1. جلب أسعار الباقات منفصلة
        books_price = 0
        uniform_price = 0
        try:
            active_year = student.academic_year
            package = GradePackagePrice.objects.get(grade=student.grade, academic_year=active_year)
            books_price = package.books_price
            uniform_price = package.uniform_price
        except GradePackagePrice.DoesNotExist:
            pass

        # 2. جلب المبيعات
        sales = BookSale.objects.filter(student=student)
        
        # 3. فصل المبالغ المدفوعة بناءً على نوع الصنف (كتاب أم زي)
        # نفترض أن حق النوع في موديل المخزن اسمه item_type وقيمه 'book' و 'uniform'
        books_paid = sales.filter(item__item_type='book').aggregate(Sum('pay_now'))['pay_now__sum'] or 0
        uniform_paid = sales.filter(item__item_type='uniform').aggregate(Sum('pay_now'))['pay_now__sum'] or 0
        
        # 4. قائمة أسماء الكتب
        received_items = [str(sale.item) for sale in sales if sale.item]

        # إرسال البيانات مفصلة للمتصفح
        return JsonResponse({
            'books_total': float(books_price),
            'books_paid': float(books_paid),
            'uniform_total': float(uniform_price),
            'uniform_paid': float(uniform_paid),
            'received_items': received_items
        })
    except Student.DoesNotExist:
        return JsonResponse({'error': 'Student not found'}, status=404)    


def print_receipt_view(request, sale_id):
    # 1. جلب الفاتورة الأساسية
    sale = get_object_or_404(BookSale, id=sale_id)
    student = sale.student
    
    # 2. معرفة نوع الصنف المطبوع (هل هو كتاب أم زي؟)
    # نفترض أن الحقل اسمه item_type، قم بتعديله إذا كان مختلفاً لديك
    item_type = sale.item.item_type 
    
    # 3. حساب إجمالي الباقة المطلوبة لهذا الصنف فقط
    total_required = 0
    try:
        package = GradePackagePrice.objects.get(grade=student.grade, academic_year=student.academic_year)
        if item_type == 'book':
            total_required = package.books_price
        else:
            total_required = package.uniform_price
    except GradePackagePrice.DoesNotExist:
        pass

    # 4. حساب إجمالي ما دفعه الطالب مسبقاً لهذا القسم تحديداً (كتب أو زي)
    sales_for_category = BookSale.objects.filter(student=student, item__item_type=item_type)
    total_paid = sales_for_category.aggregate(Sum('pay_now'))['pay_now__sum'] or 0

    # 5. حساب المبلغ المتبقي بدقة
    remaining_amount = total_required - total_paid

    # 6. إرسال جميع البيانات إلى صفحة الطباعة
    context = {
        'sale': sale,
        'total_required': total_required,
        'total_paid': total_paid,
        'remaining_amount': remaining_amount,
    }
    
    return render(request, 'books/print_receipt.html', context)


def collect_course_fee_view(request, enrollment_id):
    # جلب بيانات الاشتراك
    enrollment = get_object_or_404(CourseGroup, id=enrollment_id)
    
    if request.method == 'POST':
        amount = request.POST.get('amount_paid')
        notes = request.POST.get('notes')
        
        if amount and float(amount) > 0:
            # تسجيل الدفعة في جدول التحصيلات المنفصل
            CoursePayment.objects.create(
                course_enrollment=enrollment,
                amount_paid=amount,
                collected_by=request.user, # تسجيل الموظف الحالي
                notes=notes
            )
            messages.success(request, f"تم تحصيل {amount} ج.م بنجاح من الطالب {enrollment.student}")
            return redirect('course_prices') # العودة للجدول الرئيسي
        else:
            messages.error(request, "يرجى إدخال مبلغ صحيح")

    context = {
        'enrollment': enrollment,
        'title': 'تحصيل رسوم كورس'
    }
    return render(request, 'students/collect_fee.html', context)


def debt_history(request, student_id):
    # جلب الطالب المطلوب
    student = get_object_or_404(Student, id=student_id)
    
    # جلب الحركات المالية الخاصة بهذا الطالب فقط
    accounts = StudentAccount.objects.filter(student=student).order_by('-created_at')
    payments = Payment.objects.filter(student=student).order_by('-payment_date')
    
    context = {
        "student": student,
        "accounts": accounts,
        "payments": payments,
    }
    return render(request, "debt_history.html", context)


def get_classrooms(request):
    grade_id = request.GET.get('grade_id')
    classrooms = Classroom.objects.filter(grade_id=grade_id).values('id', 'name')
    return JsonResponse(list(classrooms), safe=False)



def student_dashboard(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    
    # جلب كافة الأقساط
    installments = StudentInstallment.objects.filter(student=student).order_by('due_date')
    
    # حسابات إجمالية
    # (تم تحويل القيم إلى float لتفادي أخطاء JSON Serialization مع حقول الـ Decimal في قواعد البيانات)
    total_required = float(installments.aggregate(Sum('amount_due'))['amount_due__sum'] or 0)
    total_paid = float(installments.aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0)
    remaining_balance = total_required - total_paid
    
    # حساب الأقساط المتأخرة (تاريخ استحقاقها مضى ولم تدفع بالكامل)
    today = date.today()
    overdue_installments = installments.filter(due_date__lt=today, paid_amount__lt=F('amount_due'))
    total_overdue = float(sum(i.amount_due - i.paid_amount for i in overdue_installments))

    # تجهيز بيانات الرسم البياني (دائري)
    paid_percentage = (total_paid / total_required * 100) if total_required > 0 else 0
    
    # -------------------------------------------------------------
    # تجهيز بيانات الرسم البياني لـ Chart.js ليتم عرضها في صفحة الطالب
    # -------------------------------------------------------------
    chart_labels = ["إجمالي المدفوع", "إجمالي المتبقي"]
    chart_data = [total_paid, remaining_balance]
    
    context = {
        'student': student,
        'installments': installments,
        'total_required': total_required,
        'total_paid': total_paid,
        'remaining_balance': remaining_balance,
        'total_overdue': total_overdue,
        'paid_percentage': round(paid_percentage, 1),
        
        # تمرير متغيرات الرسم البياني كـ JSON للواجهة الأمامية
        'chart_labels': json.dumps(chart_labels),
        'chart_data': json.dumps(chart_data),
    }
    
    return render(request, "students/student_dashboard.html", context)


from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Subquery, OuterRef
# تأكد أن هذا الموديل مستورد بشكل صحيح كما يظهر في ملفك
from finance.models import StudentInstallment, StudentAccount, AcademicYear
# أضف هذا السطر في أعلى ملف views.py
from django.db.models import Q, F, Value, Sum, Count, Case, When, DecimalField, Subquery, OuterRef, ExpressionWrapper, Exists
from django.db.models.functions import Coalesce, Concat
from django.db.models.functions import Coalesce, Concat
from django.template.loader import render_to_string
from django.http import JsonResponse # تأكد من استيراد JsonResponse


def student_list(request):
    # 1. جلب البيانات الأساسية والفلاتر
    all_years = AcademicYear.objects.all().order_by('-name')
    all_grades = Grade.objects.all().order_by('id')
    
    selected_year_id = request.GET.get('year_id')
    grade_id = request.GET.get('grade_id')
    classroom_id = request.GET.get('classroom_id')
    specialization = request.GET.get('specialization')
    gender = request.GET.get('gender')
    religion = request.GET.get('religion')
    is_disability = request.GET.get('is_disability')
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status')
    
    

    # 2. تحديد السنة الدراسية
    if selected_year_id:
        current_view_year = get_object_or_404(AcademicYear, id=selected_year_id)
        is_archive = not current_view_year.is_active
    else:
        current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
        is_archive = False

    if current_view_year:
        # --- الساب كويري للتحقق من وجود "تسكين/أقساط" ---
        installments_exists_subquery = StudentInstallment.objects.filter(
            student=OuterRef('pk'),
            academic_year=current_view_year
        )

        # --- الساب كويري للمبالغ المدفوعة فعلياً ---
        receipts_subquery = Payment.objects.filter(
            student=OuterRef('pk'),
            academic_year=current_view_year
        ).values('student').annotate(
            total_paid_actual=Sum('amount_paid')
        ).values('total_paid_actual')

        # --- الساب كويري لإجمالي الخصومات ---
        discount_subquery = StudentAccount.objects.filter(
            student=OuterRef('pk'),
            academic_year=current_view_year
        ).values('student').annotate(
            total_discount=Sum('discount')
        ).values('total_discount')

        # --- الساب كويري لأصل الأقساط المستحقة ---
        installments_subquery = StudentInstallment.objects.filter(
            student=OuterRef('pk'),
            academic_year=current_view_year
        ).values('student').annotate(
            total_due=Sum('amount_due')
        ).values('total_due')

        # --- [جديد] الساب كويري لإجمالي غرامات التأخير ---
        late_fees_subquery = StudentInstallment.objects.filter(
            student=OuterRef('pk'),
            academic_year=current_view_year
        ).values('student').annotate(
            total_late=Sum('late_fee')
        ).values('total_late')

        # 3. بناء الاستعلام الأساسي مع Annotation
        base_query = Student.objects.filter(academic_year=current_view_year)
        
        # تطبيق الفلاتر (Grade, Classroom, etc.)
        if grade_id: base_query = base_query.filter(grade_id=grade_id)
        if classroom_id: base_query = base_query.filter(classroom_id=classroom_id)
        if specialization: base_query = base_query.filter(specialization=specialization)
        if gender: base_query = base_query.filter(gender=gender)
        if religion: base_query = base_query.filter(religion=religion)
        if is_disability: base_query = base_query.filter(is_disability=(is_disability == 'true'))

        students_query = base_query.select_related("grade", "classroom").annotate(
            full_name_db=Concat('first_name', Value(' '), 'last_name'),
            is_assigned=Exists(installments_exists_subquery), 
            fees_display=Coalesce(Subquery(installments_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            # جلب الغرامات للعرض
            late_fees_display=Coalesce(Subquery(late_fees_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            total_paid_display=Coalesce(Subquery(receipts_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            discount_display=Coalesce(Subquery(discount_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            old_debt_display=Coalesce(F('previous_debt'), Value(0, output_field=DecimalField()))
        ).annotate(
            # تعديل معادلة المتبقي لتشمل الغرامات: (قديم + أقساط + غرامات) - (مدفوع + خصم)
            calculated_remaining=ExpressionWrapper(
                (F('old_debt_display') + F('fees_display') + F('late_fees_display')) - (F('total_paid_display') + F('discount_display')),
                output_field=DecimalField()
            )
        )

        # تصفية البحث النصي
        if search_query:
            students_query = students_query.filter(
                Q(full_name_db__icontains=search_query) |
                Q(student_code__icontains=search_query) |
                Q(national_id__icontains=search_query)
            )

        # 4. حساب العدادات (الإحصائيات المحدثة)
        stats = students_query.aggregate(
            total=Count('id'),
            assigned=Count(Case(When(is_assigned=True, then=1))),
            debt=Count(Case(When(calculated_remaining__gt=0.01, then=1))),
            paid=Count(Case(When(Q(is_assigned=True) & Q(calculated_remaining__lte=0.01), then=1))),
            total_remaining_sum=Sum('calculated_remaining')
        )

        # 5. تطبيق فلتر الحالة المالي
        if status_filter == 'debt':
            students_query = students_query.filter(calculated_remaining__gt=0.01)
        elif status_filter == 'paid':
            students_query = students_query.filter(is_assigned=True, calculated_remaining__lte=0.01)
        elif status_filter == 'assigned':
            students_query = students_query.filter(is_assigned=True)
        elif status_filter == 'unassigned':
            students_query = students_query.filter(is_assigned=False)

        # الترتيب والترقيم
        students_query = students_query.order_by('first_name', 'id')
        paginator = Paginator(students_query, 20) 
        students_page = paginator.get_page(request.GET.get('page', 1))
        
    else:
        students_page = []
        stats = {'total': 0, 'assigned': 0, 'debt': 0, 'paid': 0, 'total_remaining_sum': 0}

    # 6. تجهيز السياق للقالب
    context = {
        "students": students_page, 
        "all_years": all_years, 
        "all_grades": all_grades, 
        "all_classrooms": Classroom.objects.all(),
        "current_view_year": current_view_year,
        "selected_grade": grade_id,
        "selected_classroom": classroom_id,
        "selected_specialization": specialization,
        "selected_gender": gender,
        "selected_religion": religion,
        "selected_is_disability": is_disability,
        "is_archive": is_archive,
        "total_count": stats.get('total') or 0,
        "assigned_count": stats.get('assigned') or 0,
        "unassigned_count": (stats.get('total') or 0) - (stats.get('assigned') or 0),
        "paid_count": stats.get('paid') or 0,
        "debt_count": stats.get('debt') or 0,
        "remaining": stats.get('total_remaining_sum') or 0,
        "search_query": search_query,
        "status_filter": status_filter,
    }
    return render(request, "students/student_list.html", context)


# def student_list(request):
#     # 1. جلب البيانات الأساسية
#     # 1. جلب البيانات الأساسية
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id')
    
#     # الفلاتر الجديدة
#     selected_year_id = request.GET.get('year_id')
#     grade_id = request.GET.get('grade_id')
#     classroom_id = request.GET.get('classroom_id')
#     specialization = request.GET.get('specialization')
#     gender = request.GET.get('gender')
#     religion = request.GET.get('religion')
#     is_disability = request.GET.get('is_disability')
    
#     search_query = request.GET.get('q', '').strip()
#     status_filter = request.GET.get('status')
    
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id')
#     selected_year_id = request.GET.get('year_id')
#     search_query = request.GET.get('q', '').strip()
#     status_filter = request.GET.get('status') 
#     last_updated_id = request.GET.get('last_id') 

#     # 2. تحديد السنة الدراسية
#     if selected_year_id:
#         current_view_year = get_object_or_404(AcademicYear, id=selected_year_id)
#         is_archive = not current_view_year.is_active
#     else:
#         current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
#         is_archive = False

#     if current_view_year:
#         # --- [جديد] ساب كويري للتحقق من وجود "خطة مصروفات" بغض النظر عن قيمتها ---
#         installments_exists_subquery = StudentInstallment.objects.filter(
#             student=OuterRef('pk'),
#             academic_year=current_view_year
#         )

#         # --- الساب كويري للقيم المالية ---
#         receipts_subquery = Payment.objects.filter(
#             student=OuterRef('pk'),
#             academic_year=current_view_year
#         ).values('student').annotate(
#             total_paid_actual=Sum('amount_paid')
#         ).values('total_paid_actual')

#         discount_subquery = StudentAccount.objects.filter(
#             student=OuterRef('pk'),
#             academic_year=current_view_year
#         ).values('student').annotate(
#             total_discount=Sum('discount')
#         ).values('total_discount')

#         installments_subquery = StudentInstallment.objects.filter(
#             student=OuterRef('pk'),
#             academic_year=current_view_year
#         ).values('student').annotate(
#             total_due=Sum('amount_due')
#         ).values('total_due')

#         # 3. بناء الاستعلام الأساسي مع إضافة حقل is_assigned
#         base_query = Student.objects.filter(academic_year=current_view_year)
#         if grade_id:
#             base_query = base_query.filter(grade_id=grade_id)
#         if classroom_id:
#             base_query = base_query.filter(classroom_id=classroom_id)
#         if specialization:
#             base_query = base_query.filter(specialization=specialization)
#         if gender:
#             base_query = base_query.filter(gender=gender)
#         if religion:
#             base_query = base_query.filter(religion=religion)
#         if is_disability:
#             # تحويل النص 'true'/'false' إلى قيمة منطقية
#             base_query = base_query.filter(is_disability=(is_disability == 'true'))

        
#         students_query = base_query.select_related("grade", "classroom").annotate(
#             full_name_db=Concat('first_name', Value(' '), 'last_name'),
#             # التحقق من التسكين منطقياً (Exists)
#             is_assigned=Exists(installments_exists_subquery), 
#             fees_display=Coalesce(Subquery(installments_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
#             total_paid_display=Coalesce(Subquery(receipts_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
#             discount_display=Coalesce(Subquery(discount_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
#             old_debt_display=Coalesce(F('previous_debt'), Value(0, output_field=DecimalField()))
#         ).annotate(
#             calculated_remaining=ExpressionWrapper(
#                 F('old_debt_display') + F('fees_display') - (F('total_paid_display') + F('discount_display')),
#                 output_field=DecimalField()
#             )
#         )

#         # تصفية البحث (تؤثر على العدادات)
#         if search_query:
#             students_query = students_query.filter(
#                 Q(full_name_db__icontains=search_query) |
#                 Q(student_code__icontains=search_query) |
#                 Q(national_id__icontains=search_query)
#             )

#         # 4. حساب العدادات (Stats) بناءً على المنطق الجديد
#         stats = students_query.aggregate(
#             total=Count('id'),
#             # المسكنين: أي طالب له سجل في الأقساط
#             assigned=Count(Case(When(is_assigned=True, then=1))),
#             debt=Count(Case(When(calculated_remaining__gt=0.01, then=1))),
#             # المسددين: مسكن ومتبقي عليه صفر
#             paid=Count(Case(When(Q(is_assigned=True) & Q(calculated_remaining__lte=0.01), then=1))),
#             total_remaining_sum=Sum('calculated_remaining')
#         )

#         # 5. تطبيق فلتر الحالة (عند الضغط على العدادات)
#         if status_filter == 'debt':
#             students_query = students_query.filter(calculated_remaining__gt=0.01)
#         elif status_filter == 'paid':
#             students_query = students_query.filter(is_assigned=True, calculated_remaining__lte=0.01)
#         elif status_filter == 'assigned':
#             students_query = students_query.filter(is_assigned=True)
#         elif status_filter == 'unassigned':
#             students_query = students_query.filter(is_assigned=False)

#         # الترتيب والترقيم
#         students_query = students_query.order_by('first_name', 'id')
#         paginator = Paginator(students_query, 20) 
#         students_page = paginator.get_page(request.GET.get('page', 1))
        
#     else:
#         students_page = []
#         stats = {'total': 0, 'assigned': 0, 'debt': 0, 'paid': 0, 'total_remaining_sum': 0}

#     context = {
#         "students": students_page, 
#         "all_years": all_years, 
#         "all_grades": all_grades, 
#         "all_classrooms": Classroom.objects.all(),
#         "current_view_year": current_view_year,
#         "selected_grade": grade_id,
#         "selected_classroom": classroom_id,
#         "selected_specialization": specialization,
#         "selected_gender": gender,
#         "selected_religion": religion,
#         "selected_is_disability": is_disability,
#         "is_archive": is_archive,
#         "total_count": stats.get('total') or 0,
#         "assigned_count": stats.get('assigned') or 0,
#         "unassigned_count": (stats.get('total') or 0) - (stats.get('assigned') or 0),
#         "paid_count": stats.get('paid') or 0,
#         "debt_count": stats.get('debt') or 0,
#         "remaining": stats.get('total_remaining_sum') or 0,
#         "search_query": search_query,
#         "status_filter": status_filter,
#     }
#     return render(request, "students/student_list.html", context)

# def student_list(request):
#     # 1. جلب البيانات الأساسية
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id')
#     selected_year_id = request.GET.get('year_id')
#     search_query = request.GET.get('q', '').strip()
#     last_updated_id = request.GET.get('last_id') 

#     # 2. تحديد السنة الدراسية
#     if selected_year_id:
#         current_view_year = get_object_or_404(AcademicYear, id=selected_year_id)
#         is_archive = not current_view_year.is_active
#     else:
#         current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
#         is_archive = False

#     if current_view_year:
#         # --- التعديل الجوهري: حساب المدفوعات من جدول الإيصالات مباشرة ---
#         # استبدل 'Receipt' بالاسم الحقيقي لموديل الإيصالات عندك
#         # التعديل الصحيح داخل views.py
#         receipts_subquery = Payment.objects.filter( # تم تغيير الاسم من Receipt إلى Payment
#             student=OuterRef('pk'),
#             academic_year=current_view_year
#         ).values('student').annotate(
#             total_paid_actual=Sum('amount_paid') # تأكد أن اسم الحقل amount_paid كما في الموديل
#         ).values('total_paid_actual')

#         # استعلام الخصومات من جدول الحسابات
#         discount_subquery = StudentAccount.objects.filter(
#             student=OuterRef('pk'),
#             academic_year=current_view_year
#         ).values('student').annotate(
#             total_discount=Sum('discount')
#         ).values('total_discount')

#         # استعلام الأقساط (نأخذ منه القيمة المطلوبة فقط)
#         installments_subquery = StudentInstallment.objects.filter(
#             student=OuterRef('pk'),
#             academic_year=current_view_year
#         ).values('student').annotate(
#             total_due=Sum('amount_due')
#         )

#         # 3. بناء الاستعلام الأساسي مع الربط الجديد
#         students_query = Student.objects.filter(
#             academic_year=current_view_year
#         ).select_related("grade", "classroom")
        
#         students_query = students_query.annotate(
#             full_name_db=Concat('first_name', Value(' '), 'last_name'),
#             fees_display=Coalesce(Subquery(installments_subquery.values('total_due'), output_field=DecimalField()), Value(0, output_field=DecimalField())),
            
#             # الربط بجدول الإيصالات لضمان التحديث عند المسح
#             total_paid_display=Coalesce(Subquery(receipts_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            
#             discount_display=Coalesce(Subquery(discount_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
#             old_debt_display=Coalesce(F('previous_debt'), Value(0, output_field=DecimalField()))
#         ).annotate(
#             # الحسبة النهائية للمتبقي
#             calculated_remaining=F('old_debt_display') + F('fees_display') - (F('total_paid_display') + F('discount_display'))
#         )

#         # فلتر البحث (Search)
#         if search_query:
#             students_query = students_query.filter(
#                 Q(full_name_db__icontains=search_query) |
#                 Q(student_code__icontains=search_query) |
#                 Q(national_id__icontains=search_query) |
#                 Q(registration_number__icontains=search_query)
#             )

#         # الترتيب الثابت
#         students_query = students_query.order_by('first_name', 'id')

#         # حساب الصفحة تلقائياً للطالب المستهدف
#         page_number = request.GET.get('page', 1)
#         if last_updated_id and not search_query and not request.GET.get('page'):
#             try:
#                 all_ids = list(students_query.values_list('id', flat=True))
#                 target_id = int(last_updated_id)
#                 if target_id in all_ids:
#                     index = all_ids.index(target_id)
#                     page_number = (index // 20) + 1
#             except (ValueError, TypeError):
#                 pass

#         # 4. حساب الإحصائيات (Stats Bar) والمتبقي الكلي للصندوق العلوي
#         stats = students_query.aggregate(
#             total=Count('id'),
#             assigned=Count(Case(When(fees_display__gt=0, then=1), output_field=IntegerField())),
#             debt=Count(Case(When(calculated_remaining__gt=0, then=1), output_field=IntegerField())),
#             paid=Count(Case(When(Q(fees_display__gt=0) & Q(calculated_remaining__lte=0), then=1), output_field=IntegerField())),
#             total_remaining_sum=Sum('calculated_remaining') # حساب المبلغ الإجمالي للصندوق
#         )

#         # 5. الترقيم (Pagination)
#         paginator = Paginator(students_query, 20) 
#         students_page = paginator.get_page(page_number)
        
#     else:
#         students_page = []
#         stats = {'total': 0, 'assigned': 0, 'debt': 0, 'paid': 0, 'total_remaining_sum': 0}

#     # التحضير للإرسال للقالب
#     context = {
#         "students": students_page, 
#         "all_years": all_years, 
#         "all_grades": all_grades, 
#         "current_view_year": current_view_year,
#         "is_archive": is_archive,
#         "total_count": stats.get('total', 0),
#         "assigned_count": stats.get('assigned', 0),
#         "unassigned_count": stats.get('total', 0) - stats.get('assigned', 0),
#         "paid_count": stats.get('paid', 0),
#         "debt_count": stats.get('debt', 0),
#         "remaining": stats.get('total_remaining_sum', 0), # إرسال إجمالي المتبقي للصندوق العلوي
#         "search_query": search_query,
#         "last_updated_id": last_updated_id, 
#     }
#     return render(request, "students/student_list.html", context)


# def student_list(request):
#     # 1. جلب البيانات الأساسية للفلترة والتمرير
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id')
#     selected_year_id = request.GET.get('year_id')
#     search_query = request.GET.get('q', '').strip()
    
#     # استقبال معرف الطالب الأخير للعودة إليه بعد الدفع
#     last_updated_id = request.GET.get('last_id') 

#     # 2. تحديد السنة الدراسية النشطة أو المختارة
#     if selected_year_id:
#         current_view_year = get_object_or_404(AcademicYear, id=selected_year_id)
#         is_archive = not current_view_year.is_active
#     else:
#         current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
#         is_archive = False

#     if current_view_year:
#         # --- استعلام فرعي للخصم (Subquery لضمان السرعة) ---
#         discount_subquery = StudentAccount.objects.filter(
#             student=OuterRef('pk'),
#             academic_year=current_view_year
#         ).values('student').annotate(
#             total_discount=Sum('discount')
#         ).values('total_discount')

#         # --- استعلام فرعي للأقساط (تجنباً للـ 7415 استعلاماً السابقة) ---
#         installments_subquery = StudentInstallment.objects.filter(
#             student=OuterRef('pk'),
#             academic_year=current_view_year
#         ).values('student').annotate(
#             total_due=Sum('amount_due'),
#             total_paid=Sum('paid_amount')
#         )

#         # 3. بناء الاستعلام الأساسي مع تحسين الأداء (Annotate)
#         students_query = Student.objects.filter(
#             academic_year=current_view_year
#         ).select_related("grade", "classroom")
        
#         students_query = students_query.annotate(
#             full_name_db=Concat('first_name', Value(' '), 'last_name'),
            
#             # جلب القيم المالية بضربة واحدة في قاعدة البيانات
#             fees_display=Coalesce(
#                 Subquery(installments_subquery.values('total_due'), output_field=DecimalField()), 
#                 Value(0, output_field=DecimalField())
#             ),
#             total_paid_display=Coalesce(
#                 Subquery(installments_subquery.values('total_paid'), output_field=DecimalField()), 
#                 Value(0, output_field=DecimalField())
#             ),
#             discount_display=Coalesce(
#                 Subquery(discount_subquery, output_field=DecimalField()),
#                 Value(0, output_field=DecimalField())
#             ),
#             old_debt_display=Coalesce(F('previous_debt'), Value(0, output_field=DecimalField()))
#         ).annotate(
#             # الحسبة المالية النهائية لكل طالب (تظهر مباشرة في الجدول)
#             calculated_remaining=F('old_debt_display') + F('fees_display') - (F('total_paid_display') + F('discount_display'))
#         )

#         # 🌟 فلتر البحث (Search)
#         if search_query:
#             students_query = students_query.filter(
#                 Q(full_name_db__icontains=search_query) |
#                 Q(student_code__icontains=search_query) |
#                 Q(national_id__icontains=search_query) |
#                 Q(registration_number__icontains=search_query)
#             )

#         students_query = students_query.order_by('first_name')

#         # 4. حساب الإحصائيات للبطاقات العلوية (Stats Bar)
#         stats = students_query.aggregate(
#             total=Count('id'),
#             assigned=Count(Case(When(fees_display__gt=0, then=1), output_field=IntegerField())),
#             debt=Count(Case(When(calculated_remaining__gt=0, then=1), output_field=IntegerField())),
#             paid=Count(Case(When(Q(fees_display__gt=0) & Q(calculated_remaining__lte=0), then=1), output_field=IntegerField()))
#         )

#         total_count = stats['total'] or 0
#         assigned_count = stats['assigned'] or 0
#         unassigned_count = total_count - assigned_count
#         debt_count = stats['debt'] or 0
#         paid_count = stats['paid'] or 0

#         # 5. الترقيم (Pagination) لضمان استقرار الصفحة ومنع ERR_EMPTY_RESPONSE
#         paginator = Paginator(students_query, 20) 
#         page_number = request.GET.get('page')
#         students_page = paginator.get_page(page_number)
        
#     else:
#         students_page = []
#         total_count = assigned_count = unassigned_count = paid_count = debt_count = 0

#     context = {
#         "students": students_page, 
#         "all_years": all_years, 
#         "all_grades": all_grades, 
#         "current_view_year": current_view_year,
#         "is_archive": is_archive,
#         "total_count": total_count,
#         "assigned_count": assigned_count,
#         "unassigned_count": unassigned_count,
#         "paid_count": paid_count,
#         "debt_count": debt_count,
#         "search_query": search_query,
#         "last_updated_id": last_updated_id, # سيستخدمه JavaScript للذهاب لآخر سطر
#     }
#     return render(request, "students/student_list.html", context)


# def student_list(request):
#     # 1. جلب البيانات الأساسية للفلترة
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id')
#     selected_year_id = request.GET.get('year_id')
#     search_query = request.GET.get('q', '').strip()

#     # 2. تحديد السنة الدراسية النشطة أو المختارة
#     if selected_year_id:
#         current_view_year = get_object_or_404(AcademicYear, id=selected_year_id)
#         is_archive = not current_view_year.is_active
#     else:
#         current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
#         is_archive = False

#     if current_view_year:
#         # --- استعلام فرعي للخصم من جدول حسابات الطلاب ---
#         discount_subquery = StudentAccount.objects.filter(
#             student=OuterRef('pk'),
#             academic_year=current_view_year
#         ).values('student').annotate(
#             total_discount=Sum('discount')
#         ).values('total_discount')

#         # --- استعلام فرعي للأقساط (استخدام المسمى الصحيح StudentInstallment) ---
#         installments_subquery = StudentInstallment.objects.filter(
#             student=OuterRef('pk'),
#             academic_year=current_view_year
#         ).values('student').annotate(
#             total_due=Sum('amount_due'),
#             total_paid=Sum('paid_amount')
#         )

#         # 3. بناء الاستعلام الأساسي مع تحسين الأداء
#         students_query = Student.objects.filter(
#             academic_year=current_view_year
#         ).select_related("grade", "classroom")
        
#         students_query = students_query.annotate(
#             full_name_db=Concat('first_name', Value(' '), 'last_name'),
            
#             # جلب القيم المالية عبر Subqueries لتجنب البطء وتكرار النتائج
#             fees_display=Coalesce(
#                 Subquery(installments_subquery.values('total_due'), output_field=DecimalField()), 
#                 Value(0, output_field=DecimalField())
#             ),
#             total_paid_display=Coalesce(
#                 Subquery(installments_subquery.values('total_paid'), output_field=DecimalField()), 
#                 Value(0, output_field=DecimalField())
#             ),
#             discount_display=Coalesce(
#                 Subquery(discount_subquery, output_field=DecimalField()),
#                 Value(0, output_field=DecimalField())
#             ),
#             old_debt_display=Coalesce(F('previous_debt'), Value(0, output_field=DecimalField()))
#         ).annotate(
#             # الحسبة المالية النهائية لكل طالب
#             calculated_remaining=F('old_debt_display') + F('fees_display') - (F('total_paid_display') + F('discount_display'))
#         )

#         # 🌟 فلتر البحث
#         if search_query:
#             students_query = students_query.filter(
#                 Q(full_name_db__icontains=search_query) |
#                 Q(student_code__icontains=search_query) |
#                 Q(national_id__icontains=search_query) |
#                 Q(registration_number__icontains=search_query)
#             )

#         students_query = students_query.order_by('first_name')

#         # 4. حساب الإحصائيات للبطاقات العلوية (Stats Bar)
#         stats = students_query.aggregate(
#             total=Count('id'),
#             assigned=Count(Case(When(fees_display__gt=0, then=1), output_field=IntegerField())),
#             debt=Count(Case(When(calculated_remaining__gt=0, then=1), output_field=IntegerField())),
#             paid=Count(Case(When(Q(fees_display__gt=0) & Q(calculated_remaining__lte=0), then=1), output_field=IntegerField()))
#         )

#         total_count = stats['total'] or 0
#         assigned_count = stats['assigned'] or 0
#         unassigned_count = total_count - assigned_count
#         debt_count = stats['debt'] or 0
#         paid_count = stats['paid'] or 0

#         # 5. الترقيم (Pagination) لضمان سرعة الصفحة
#         paginator = Paginator(students_query, 20) 
#         page_number = request.GET.get('page')
#         students_page = paginator.get_page(page_number)
        
#     else:
#         students_page = []
#         total_count = assigned_count = unassigned_count = paid_count = debt_count = 0

#     context = {
#         "students": students_page, 
#         "all_years": all_years, 
#         "all_grades": all_grades, 
#         "current_view_year": current_view_year,
#         "is_archive": is_archive,
#         "total_count": total_count,
#         "assigned_count": assigned_count,
#         "unassigned_count": unassigned_count,
#         "paid_count": paid_count,
#         "debt_count": debt_count,
#         "search_query": search_query,
#     }
#     return render(request, "students/student_list.html", context)


# from django.db.models import Q, Value, Sum, F, DecimalField
# from django.db.models.functions import Concat, Coalesce
# from django.shortcuts import render, get_object_or_404
# from django.core.paginator import Paginator
# from django.db.models import Subquery, OuterRef

# def student_list(request):
#     # 1. جلب البيانات الأساسية للفلترة
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id')
#     selected_year_id = request.GET.get('year_id')
#     search_query = request.GET.get('q', '').strip()

#     # 2. تحديد السنة الدراسية النشطة أو المختارة
#     if selected_year_id:
#         current_view_year = get_object_or_404(AcademicYear, id=selected_year_id)
#         is_archive = not current_view_year.is_active
#     else:
#         current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
#         is_archive = False

#     if current_view_year:
#         # --- حل مشكلة التكرار: استعلام فرعي للخصم فقط ---
#         # نستخدم OuterRef لربط الخصم بكل طالب على حدة دون التأثر بعدد الأقساط
#         discount_subquery = StudentAccount.objects.filter(
#             student=OuterRef('pk'),
#             academic_year=current_view_year
#         ).values('student').annotate(
#             total_discount=Sum('discount')
#         ).values('total_discount')

#         # 3. بناء الاستعلام الأساسي
#         students_query = Student.objects.filter(academic_year=current_view_year).select_related("grade", "classroom")
        
#         students_query = students_query.annotate(
#             full_name_db=Concat('first_name', Value(' '), 'last_name'),
            
#             # إجمالي المطلوب والمحصل من جدول الأقساط
#             fees_display=Coalesce(
#                 Sum('installments__amount_due', filter=Q(installments__academic_year=current_view_year)), 
#                 Value(0, output_field=DecimalField())
#             ),
#             total_paid_display=Coalesce(
#                 Sum('installments__paid_amount', filter=Q(installments__academic_year=current_view_year)), 
#                 Value(0, output_field=DecimalField())
#             ),
            
#             # جلب الخصم عبر الـ Subquery لمنع التضاعف (هذا هو الحل)
#             discount_display=Coalesce(
#                 Subquery(discount_subquery, output_field=DecimalField()),
#                 Value(0, output_field=DecimalField())
#             ),
            
#             old_debt_display=Coalesce(F('previous_debt'), Value(0, output_field=DecimalField()))
#         ).annotate(
#             # المتبقي = (القديم + المطلوب) - (المحصل + الخصم)
#             calculated_remaining=F('old_debt_display') + F('fees_display') - (F('total_paid_display') + F('discount_display'))
#         )

#         # 🌟 فلتر البحث (يدعم الاسم والكود والقومي والقيد)
#         if search_query:
#             students_query = students_query.filter(
#                 Q(full_name_db__icontains=search_query) |
#                 Q(student_code__icontains=search_query) |
#                 Q(national_id__icontains=search_query) |
#                 Q(registration_number__icontains=search_query)
#             )

#         students_query = students_query.order_by('first_name')

#         # 4. حساب الإحصائيات بناءً على النتائج المفلترة
#         total_count = students_query.count()
#         assigned_count = students_query.filter(fees_display__gt=0).count()
#         unassigned_count = total_count - assigned_count
#         debt_count = students_query.filter(calculated_remaining__gt=0).count()
#         paid_count = students_query.filter(fees_display__gt=0, calculated_remaining__lte=0).count()

#         # 5. الترقيم
#         paginator = Paginator(students_query, 20) 
#         page_number = request.GET.get('page')
#         students_page = paginator.get_page(page_number)
        
#     else:
#         students_page = []
#         total_count = assigned_count = unassigned_count = paid_count = debt_count = 0

#     context = {
#         "students": students_page, 
#         "all_years": all_years, 
#         "all_grades": all_grades, 
#         "current_view_year": current_view_year,
#         "is_archive": is_archive,
#         "total_count": total_count,
#         "assigned_count": assigned_count,
#         "unassigned_count": unassigned_count,
#         "paid_count": paid_count,
#         "debt_count": debt_count,
#         "search_query": search_query,
#     }
#     return render(request, "students/student_list.html", context)

# def student_list(request):
#     # 1. جلب البيانات الأساسية للفلترة
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id')
#     selected_year_id = request.GET.get('year_id')
#     search_query = request.GET.get('q', '').strip()

#     # 2. تحديد السنة الدراسية النشطة أو المختارة
#     if selected_year_id:
#         current_view_year = get_object_or_404(AcademicYear, id=selected_year_id)
#         is_archive = not current_view_year.is_active
#     else:
#         current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
#         is_archive = False

#     if current_view_year:
#         # 3. بناء الاستعلام مع حساباتك المالية + دمج الاسم الكامل للبحث
#         students_query = Student.objects.filter(academic_year=current_view_year).select_related("grade", "classroom")
        
#         # دمج الاسم الأول والاسم الأخير في حقل واحد يسمى 'full_name_db'
#         # ملاحظة: أضفنا مسافة Value(' ') بينهما لمحاكاة البحث الطبيعي
#         students_query = students_query.annotate(
#             full_name_db=Concat('first_name', Value(' '), 'last_name'),
#             fees_display=Coalesce(
#                 Sum('installments__amount_due', filter=Q(installments__academic_year=current_view_year)), 
#                 Value(0, output_field=DecimalField())
#             ),
#             total_paid_display=Coalesce(
#                 Sum('installments__paid_amount', filter=Q(installments__academic_year=current_view_year)), 
#                 Value(0, output_field=DecimalField())
#             ),
#             old_debt_display=Coalesce(F('previous_debt'), Value(0, output_field=DecimalField()))
#         ).annotate(
#             calculated_remaining=F('old_debt_display') + F('fees_display') - F('total_paid_display')
#         )

#         # 🌟 تعديل فلتر البحث ليدعم الاسم الكامل 🌟
#         if search_query:
#             students_query = students_query.filter(
#                 Q(full_name_db__icontains=search_query) |    # البحث في الاسم المدمج
#                 Q(student_code__icontains=search_query) |    # البحث بكود الطالب
#                 Q(national_id__icontains=search_query) |     # البحث بالرقم القومي
#                 Q(registration_number__icontains=search_query) # البحث برقم القيد
#             )

#         # الترتيب
#         students_query = students_query.order_by('first_name')

#         # 4. حساب الإحصائيات بناءً على نتيجة البحث
#         total_count = students_query.count()
#         assigned_count = students_query.filter(fees_display__gt=0).count()
#         unassigned_count = total_count - assigned_count
#         debt_count = students_query.filter(calculated_remaining__gt=0).count()
#         paid_count = students_query.filter(fees_display__gt=0, calculated_remaining__lte=0).count()

#         # 5. الترقيم
#         paginator = Paginator(students_query, 20) 
#         page_number = request.GET.get('page')
#         students_page = paginator.get_page(page_number)
        
#     else:
#         students_page = []
#         total_count = assigned_count = unassigned_count = paid_count = debt_count = 0

#     context = {
#         "students": students_page, 
#         "all_years": all_years, 
#         "all_grades": all_grades, 
#         "current_view_year": current_view_year,
#         "is_archive": is_archive,
#         "total_count": total_count,
#         "assigned_count": assigned_count,
#         "unassigned_count": unassigned_count,
#         "paid_count": paid_count,
#         "debt_count": debt_count,
#         "search_query": search_query,
#     }
#     return render(request, "students/student_list.html", context)


# def student_list(request):
#     # 1. جلب البيانات الأساسية للفلترة
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id')
#     selected_year_id = request.GET.get('year_id')
    
#     # التقاط كلمة البحث من الرابط
#     search_query = request.GET.get('q', '').strip()

#     # 2. تحديد السنة الدراسية النشطة أو المختارة
#     if selected_year_id:
#         current_view_year = get_object_or_404(AcademicYear, id=selected_year_id)
#         is_archive = not current_view_year.is_active
#     else:
#         current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
#         is_archive = False

#     if current_view_year:
#         # 3. بناء الاستعلام العملاق (Annotate)
#         students_query = Student.objects.filter(academic_year=current_view_year).select_related("grade", "classroom").annotate(
#             # ... (نفس حساباتك الحالية بدون تغيير) ...
#             fees_display=Coalesce(
#                 Sum('installments__amount_due', filter=Q(installments__academic_year=current_view_year)), 
#                 Value(0, output_field=DecimalField())
#             ),
#             total_paid_display=Coalesce(
#                 Sum('installments__paid_amount', filter=Q(installments__academic_year=current_view_year)), 
#                 Value(0, output_field=DecimalField())
#             ),
#             old_debt_display=Coalesce(F('previous_debt'), Value(0, output_field=DecimalField()))
#         ).annotate(
#             calculated_remaining=F('old_debt_display') + F('fees_display') - F('total_paid_display')
#         )

#         # 🌟 الجديد: تطبيق فلتر البحث على الاستعلام إذا كانت هناك كلمة بحث 🌟
#         if search_query:
#             students_query = students_query.filter(
#                 # استبدل first_name و last_name بأسماء الحقول الفعلية في موديل Student عندك
#                 Q(first_name__icontains=search_query) | 
#                 Q(last_name__icontains=search_query) | 
#                 Q(student_code__icontains=search_query)
#             )

#         # الترتيب في النهاية
#         students_query = students_query.order_by('first_name')

#         # 4. حساب الإحصائيات (الآن ستتحدث تلقائياً لتظهر إحصائيات نتيجة البحث فقط!)
#         total_count = students_query.count()
#         assigned_count = students_query.filter(fees_display__gt=0).count()
#         unassigned_count = total_count - assigned_count
#         debt_count = students_query.filter(calculated_remaining__gt=0).count()
#         paid_count = students_query.filter(fees_display__gt=0, calculated_remaining__lte=0).count()

#         # 5. نظام الترقيم (Pagination)
#         paginator = Paginator(students_query, 20) 
#         page_number = request.GET.get('page')
#         students_page = paginator.get_page(page_number)
        
#     else:
#         students_page = []
#         total_count = assigned_count = unassigned_count = paid_count = debt_count = 0

#     context = {
#         "students": students_page, 
#         "all_years": all_years, 
#         "all_grades": all_grades, 
#         "current_view_year": current_view_year,
#         "is_archive": is_archive,
#         "total_count": total_count,
#         "assigned_count": assigned_count,
#         "unassigned_count": unassigned_count,
#         "paid_count": paid_count,
#         "debt_count": debt_count,
#         "search_query": search_query, # تمرير الكلمة للقالب للاحتفاظ بها في حقل الإدخال
#     }
#     return render(request, "students/student_list.html", context)


# def student_list(request):
#     # 1. جلب البيانات الأساسية للفلترة
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id')
#     selected_year_id = request.GET.get('year_id')

#     # 2. تحديد السنة الدراسية النشطة أو المختارة
#     if selected_year_id:
#         current_view_year = get_object_or_404(AcademicYear, id=selected_year_id)
#         is_archive = not current_view_year.is_active
#     else:
#         current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
#         is_archive = False

#     if current_view_year:
#         # 3. بناء الاستعلام العملاق (Annotate) - يقوم بكل الحسابات في ضربة واحدة للقاعدة
#         # السر هنا في استخدام Filter داخل Sum لضمان جلب أقساط السنة المختارة فقط
#         students_query = Student.objects.filter(academic_year=current_view_year).select_related("grade", "classroom").annotate(
            
#             # حساب إجمالي المطلوب (المبلغ المستحق) للسنة الحالية فقط
#             fees_display=Coalesce(
#                 Sum('installments__amount_due', filter=Q(installments__academic_year=current_view_year)), 
#                 Value(0, output_field=DecimalField())
#             ),
            
#             # حساب إجمالي ما دفعه الطالب في السنة الحالية فقط
#             total_paid_display=Coalesce(
#                 Sum('installments__paid_amount', filter=Q(installments__academic_year=current_view_year)), 
#                 Value(0, output_field=DecimalField())
#             ),
            
#             # جلب المديونية القديمة (المخزنة في حقل previous_debt بالموديل)
#             old_debt_display=Coalesce(F('previous_debt'), Value(0, output_field=DecimalField()))
            
#         ).annotate(
#             # المعادلة المحاسبية: (مديونية قديمة + مطلوب حالي) - مدفوع حالي
#             calculated_remaining=F('old_debt_display') + F('fees_display') - F('total_paid_display')
#         ).order_by('first_name')

#         # 4. حساب الإحصائيات (Stats Bar) من الـ Queryset مباشرة دون دوران
#         total_count = students_query.count()
#         # الطالب المسكن هو من لديه مطلوب (fees_display) أكبر من صفر
#         assigned_count = students_query.filter(fees_display__gt=0).count()
#         unassigned_count = total_count - assigned_count
#         # الطالب المديون هو من صافي حسابه أكبر من صفر
#         debt_count = students_query.filter(calculated_remaining__gt=0).count()
#         # الطالب الخالص هو من لديه خطة رسوم وصافي حسابه صفر أو أقل
#         paid_count = students_query.filter(fees_display__gt=0, calculated_remaining__lte=0).count()

#         # 5. نظام الترقيم (Pagination) - سريع جداً لأنه لا يحول البيانات لـ List
#         paginator = Paginator(students_query, 20) 
#         page_number = request.GET.get('page')
#         students_page = paginator.get_page(page_number)
        
#     else:
#         students_page = []
#         total_count = assigned_count = unassigned_count = paid_count = debt_count = 0

#     context = {
#         "students": students_page, 
#         "all_years": all_years, 
#         "all_grades": all_grades, 
#         "current_view_year": current_view_year,
#         "is_archive": is_archive,
#         "total_count": total_count,
#         "assigned_count": assigned_count,
#         "unassigned_count": unassigned_count,
#         "paid_count": paid_count,
#         "debt_count": debt_count,
#     }
#     return render(request, "students/student_list.html", context)



def add_student(request):
    student_id = request.GET.get('id')
    mode = request.GET.get('mode') 
    student = None

    if student_id:
        student = get_object_or_404(Student, id=student_id)

    if request.method == 'POST':
        form = StudentForm(request.POST, request.FILES, instance=student)
        if form.is_valid():
            form.save()
            messages.success(request, "تم حفظ بيانات الطالب بنجاح")
            return redirect('add_student') 
    else:
        form = StudentForm(instance=student)
        
        # --- الجزء المسؤول عن منع التعديل ---
        if mode == 'view':
            for field in form.fields.values():
                field.widget.attrs['disabled'] = True # تعطيل الحقل برمجياً
                field.required = False # إلغاء الإلزامية لتجنب أخطاء التحقق

    is_admin_mode = True if (student and mode == 'view') else False

    return render(request, 'students/add_student.html', {
        'form': form, 
        'student': student,
        'student_admin_mode': is_admin_mode,
        'hide_sidebar': False
    })


from django.contrib.auth.decorators import user_passes_test

@user_passes_test(lambda u: u.is_superuser) # منع أي مستخدم ليس آدمن من الدخول
def promote_student(request, student_id):
    try:
        # تأكيد إضافي داخل الدالة للأمان
        if not request.user.is_superuser:
            messages.error(request, "عذراً، لا تمتلك صلاحية تنفيذ هذا الإجراء الحساس.")
            return redirect("students_list")

        student = get_object_or_404(Student, id=student_id)

        # منطق جلب السنة التالية كما هو في كودك...
        all_years = list(AcademicYear.objects.all().order_by('name'))
        next_year = None
        for i, year in enumerate(all_years):
            if year.id == student.academic_year.id:
                if i + 1 < len(all_years):
                    next_year = all_years[i+1]
                break

        if not next_year:
            messages.warning(request, "لا توجد سنة تالية")
            return redirect("students_list")

        # استدعاء دالة الترحيل
        success = promote_student_action(
            student_id=student.id,
            target_year_id=next_year.id,
            target_grade_id=student.grade.id
        )

        if success:
            messages.success(request, f"تم ترحيل الطالب {student.get_full_name()} بنجاح")
        else:
            messages.error(request, "فشل الترحيل، يرجى مراجعة سجل الأخطاء")

    except Exception as e:
        messages.error(request, f"خطأ غير متوقع: {str(e)}")

    return redirect("students_list")


# def promote_student(request, student_id):
#     try:
#         student = get_object_or_404(Student, id=student_id)

#         # هات السنة الجاية
#         all_years = list(AcademicYear.objects.all().order_by('name'))
#         next_year = None

#         for i, year in enumerate(all_years):
#             if year.id == student.academic_year.id:
#                 if i + 1 < len(all_years):
#                     next_year = all_years[i+1]
#                 break

#         if not next_year:
#             messages.warning(request, "لا توجد سنة تالية")
#             return redirect("students_list")

#         # 🔥 استدعاء الدالة الأساسية فقط
#         success = promote_student_action(
#             student_id=student.id,
#             target_year_id=next_year.id,
#             target_grade_id=student.grade.id  # أو غيرها حسب النظام
#         )

#         if success:
#             messages.success(request, "تم الترحيل بنجاح")
#         else:
#             messages.error(request, "فشل الترحيل")

#     except Exception as e:
#         messages.error(request, str(e))

#     return redirect("students_list")
    
# 

def student_detail_view(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    # جلب الحساب المالي المرتبط (سيتم إنشاؤه تلقائياً بواسطة الـ signal الذي كتبته أنت)
    account = getattr(student, 'account', None) 
    installments = student.installments.all().order_by('due_date')
    
    context = {
        'student': student,
        'account': account,
        'installments': installments,
        'student_admin_mode': True,
    }
    return render(request, 'students/add_student.html', context)


# students/views.py
from treasury.models import GeneralLedger
from .forms import GeneralLedgerForm # تأكد من إنشاء هذا الفورم أولاً

def add_ledger_entry(request):
    if request.method == 'POST':
        # افترضنا أن اسم الفورم هو GeneralLedgerForm
        form = GeneralLedgerForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.collected_by = request.user
            entry.save()
            return redirect('student_list') # أو أي صفحة أخرى
    else:
        form = GeneralLedgerForm()
        
    
    return render(request, 'treasury/treasury_form.html', {'form': form})


def overdue_installments_list(request):
    student_id = request.GET.get('student_id')
    today = timezone.now().date()
    
    query = Q(installments__due_date__lt=today, installments__paid_amount__lt=F('installments__amount_due'))
    
    if student_id:
        students_list = Student.objects.filter(query, id=student_id).distinct()
    else:
        students_list = Student.objects.filter(query).distinct()

    # حساب المديونية لكل طالب في القائمة الكاملة أولاً
    for student in students_list:
        overdue_total = StudentInstallment.objects.filter(
            student=student,
            due_date__lt=today,
            paid_amount__lt=F('amount_due')
        ).aggregate(total=Sum(F('amount_due') - F('paid_amount')))['total'] or 0
        student.total_overdue = overdue_total

    # إعداد نظام الترقيم (مثلاً 10 طلاب لكل صفحة)
    paginator = Paginator(students_list, 10) 
    page_number = request.GET.get('page')
    students_page = paginator.get_page(page_number)

    context = {
        'students': students_page, # نرسل كائن الصفحة بدلاً من القائمة الكاملة
        'today': today,
    }
    return render(request, 'students/overdue_list.html', context)



class StudentListAPI(generics.ListAPIView):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['first_name', 'last_name', 'national_id']


from .models import RemedialProgramRecord

def get_remedial_balance_api(request, student_id):
    """API مخصص لجلب رصيد البرنامج العلاجي فقط"""
    try:
        remedial_qs = RemedialProgramRecord.objects.filter(
            student_id=student_id, 
            is_paid=False
        )
        
        remedial_debt = remedial_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        remedial_notes_list = list(remedial_qs.values_list('notes', flat=True))
        remedial_notes = " - ".join([note for note in remedial_notes_list if note])

        return JsonResponse({
            'success': True,
            'remedial_debt': float(remedial_debt),
            'remedial_notes': remedial_notes,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})