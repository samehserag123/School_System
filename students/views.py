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
from django.db.models import Sum ,Q ,F, Value
from finance.models import Payment  # تأكد أن اسم التطبيق عندك هو finance
from .forms import CourseGroupForm
from .models import CourseGroup, CoursePayment
from django.db.models.functions import Coalesce
# الاستيراد من الموديلات (الجداول)
from .models import BookSale, InventoryItem, InventoryRestock, GradePackagePrice, CourseGroup
# الاستيراد من الفورمات (النماذج) - هذا هو السطر الذي ينقصك
from .forms import RestockForm
from .forms import BookSaleForm

# تأكد من استيراد الموديلات الصحيحة من تطبيقاتك
from students.models import Student, Grade, Classroom 
from finance.models import StudentInstallment

from django.contrib.auth.decorators import login_required
from treasury.models import GeneralLedger
import uuid # لاستخدامه في توليد رقم فريد
from decimal import Decimal

from datetime import timedelta

# students/views.py
from django.db.models import Count
from .models import BusRoute, BusSubscription, BusPayment, MiscellaneousRevenue

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.contrib.auth.decorators import login_required
from decimal import Decimal
import time
import traceback


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

# students/views.py
def course_prices_view(request):
    # 1. معالجة الطلب بناءً على النوع (POST أو GET)
    if request.method == 'POST':
        form = CourseGroupForm(request.POST)
        
        # إعداد شكل عرض الطالب فوراً حتى لو فشل التحقق من البيانات
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
                # التعامل مع الطالب الخارجي
                ext_student, created = ExternalStudent.objects.get_or_create(
                    full_name=form.cleaned_data.get('ext_name'),
                    defaults={'phone_number': form.cleaned_data.get('ext_phone')}
                )
                if not created:
                    ext_student.phone_number = form.cleaned_data.get('ext_phone')
                    ext_student.save()

                instance.external_student = ext_student
                instance.student = None
            
            instance.save()
            return redirect('course_prices')
    else:
        # حالة الـ GET (فتح الصفحة لأول مرة)
        form = CourseGroupForm(initial={'total_sessions': 4})
        # تخصيص شكل الاختيار للبحث بالاسم والكود والقومي [cite: 2026-04-09]
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

    # 6. تمرير البيانات للتمبلت
    context = {
        'courses': courses_page,
        'form': form,
        'total_revenue': total_revenue,
        'total_collected': total_collected,
        'total_remaining': total_revenue - total_collected,
        'current_filter': time_filter,
        'date_from': date_from,
        'date_to': date_to,
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


def student_registry_view(request):
    # 1. استقبال معرف السنة من الرابط (إذا جاء من الأرشيف)
    year_id = request.GET.get('year_id')
    
    if year_id:
        # إذا تم اختيار سنة معينة، نجلب بيانات هذه السنة (أرشيف)
        target_year = get_object_or_404(AcademicYear, id=year_id)
        # هنا لا نشترط is_active=True لأننا نبحث في الأرشيف
        base_query = Student.objects.filter(academic_year=target_year)
    else:
        # الحالة الطبيعية: جلب طلاب السنة النشطة الحالية فقط
        active_year = AcademicYear.objects.filter(is_active=True).first()
        base_query = Student.objects.filter(academic_year=active_year, is_active=True)

    # 2. حساب الإحصائيات بناءً على الطلاب المستخرجين (سواء أرشيف أو حالي)
    stats = {
        'total': base_query.count(),
        'male': base_query.filter(gender='Male').count(),
        'female': base_query.filter(gender='Female').count(),
        'muslim': base_query.filter(religion='Muslim').count(),
        'christian': base_query.filter(religion='Christian').count(),
        'integration': base_query.filter(integration_status=True).count(),
    }
    
    # 3. نظام الترقيم (Pagination)
    student_list = base_query.order_by('first_name')
    paginator = Paginator(student_list, 20)
    page_number = request.GET.get('page')
    students_page = paginator.get_page(page_number)
    
    # 4. جلب بيانات الفلاتر (تظل كما هي)
    all_grades = Grade.objects.all()
    all_classrooms = Classroom.objects.all()
    all_specs = Student.SPECIALIZATION_CHOICES
    
    context = {
        'students': students_page,
        'stats': stats,
        'all_grades': all_grades,
        'all_classrooms': all_classrooms,
        'all_specs': all_specs,
        'current_year': target_year if year_id else active_year, # لإظهار اسم السنة في الصفحة
        'is_archive': True if year_id else False, # لتمييز ما إذا كنا في وضع الأرشيف
    }
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

# students/views.py
# students/views.py



def add_book_sale(request):
    if request.method == 'POST':
        form = BookSaleForm(request.POST)
        if form.is_valid():
            sale = form.save(commit=False)
            inventory_item = sale.item 
            student = sale.student
            requested_qty = sale.quantity
            
            # 1. جلب السعر بناءً على (الصف + السنة الدراسية للطالب)
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
                
            except GradePackagePrice.DoesNotExist:
                messages.error(request, f"⚠️ لم يتم تحديد سعر الباقة لصف {student.grade.name} في سنة {student.academic_year.name}")
                return render(request, 'books/add_sale.html', {'form': form})

            # 2. التأكد من توفر الكمية في المخزن
            if requested_qty > inventory_item.remaining_qty:
                messages.error(request, f"⚠️ المخزن غير كافٍ! المتوفر حالياً: {inventory_item.remaining_qty}")
                return render(request, 'books/add_sale.html', {'form': form})
            
            # 3. الربط مع الموظف الحالي (مهم جداً لعملية السداد الآلي في الموديل)
            sale._current_user = request.user 
            
            # 4. الحفظ النهائي (سيقوم الموديل تلقائياً بإنشاء قيد الخزينة بناءً على قيمة pay_now)
            sale.save()
            
            # 5. رسالة نجاح مخصصة حسب حالة الدفع
            if sale.pay_now > 0:
                messages.success(request, f"✅ تم تسجيل الصرف وتوريد مبلغ {sale.pay_now} ج.م للخزينة للطالب {student.get_full_name()}.")
            else:
                messages.warning(request, f"تم تسجيل إذن الصرف للطالب {student.get_full_name()} بدون سداد مالي.")
            
            # توجيه المستخدم لصفحة الطباعة فوراً أو لقائمة المبيعات
            return redirect('print_book_receipt', sale_id=sale.id)
        
        return render(request, 'books/add_sale.html', {'form': form})

    else:
        form = BookSaleForm()
    
    return render(request, 'books/add_sale.html', {'form': form})
# هذه الدالة هي المسؤولة عن فتح الإيصال "فقط" عند الضغط على زر الطابعة في الجدول
def print_receipt_view(request, sale_id):
    sale = get_object_or_404(BookSale, id=sale_id)
    return render(request, 'books/print_receipt.html', {'sale': sale})


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
    total_required = installments.aggregate(Sum('amount_due'))['amount_due__sum'] or 0
    total_paid = installments.aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
    remaining_balance = total_required - total_paid
    
    # حساب الأقساط المتأخرة (تاريخ استحقاقها مضى ولم تدفع بالكامل)
    import datetime
    today = datetime.date.today()
    overdue_installments = installments.filter(due_date__lt=today, paid_amount__lt=F('amount_due'))
    total_overdue = sum(i.amount_due - i.paid_amount for i in overdue_installments)

    # تجهيز بيانات الرسم البياني (دائري)
    paid_percentage = (total_paid / total_required * 100) if total_required > 0 else 0
    
    context = {
        'student': student,
        'installments': installments,
        'total_required': total_required,
        'total_paid': total_paid,
        'remaining_balance': remaining_balance,
        'total_overdue': total_overdue,
        'paid_percentage': round(paid_percentage, 1),
    }
    return render(request, "students/student_dashboard.html", context)


def student_list(request):
    # 1. جلب البيانات الأساسية للفلاتر والأرشيف
    all_years = AcademicYear.objects.all().order_by('-name')
    all_grades = Grade.objects.all().order_by('id')
    selected_year_id = request.GET.get('year_id')

    # 2. تحديد السنة الدراسية المطلوب عرضها (الأرشيف أو الحالية)
    if selected_year_id:
        current_view_year = get_object_or_404(AcademicYear, id=selected_year_id)
        is_archive = not current_view_year.is_active
    else:
        current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
        is_archive = False

    # 3. تصفير العدادات قبل الحساب
    total_previous_debt = 0
    paid_count = 0 
    debt_count = 0 
    unassigned_count = 0 
    processed_students = []

    if current_view_year:
        # استرجاع الطلاب للسنة المحددة
        students_query = Student.objects.filter(
            academic_year=current_view_year
        ).select_related("grade", "classroom").order_by('first_name')

        # حساب إجمالي المديونيات القديمة للسنة بالكامل
        total_previous_debt = students_query.aggregate(total=Sum('previous_debt'))['total'] or 0

        # --- حساب "غير المسكنين" بدقة لجميع طلاب السنة ---
        # الطالب غير المسكن هو من ليس لديه أي سجل في جدول الأقساط لهذه السنة
        unassigned_count = students_query.annotate(
            inst_count=Count('installments')
        ).filter(inst_count=0).count()
        
        # 4. معالجة بيانات كل طالب للحسابات المالية والعدادات
        for student in students_query:
            # حساب الأرقام الحقيقية من جدول الأقساط
            installments_stats = StudentInstallment.objects.filter(student=student).aggregate(
                real_paid=Sum('paid_amount'),
                real_required=Sum('amount_due')
            )
            
            real_paid = installments_stats['real_paid'] or 0
            real_required = installments_stats['real_required'] or 0
            total_due = real_required - real_paid

            # تحديث العدادات (هذه الحسابات ستظل ثابتة لأنها تتم قبل الترقيم)
            if real_required <= 0:
                # هذا الطالب لم يسكن بعد (تم حسابه بالفعل في unassigned_count أعلاه عبر الـ Query)
                pass 
            elif total_due <= 0:
                paid_count += 1
            else:
                debt_count += 1

            # تمرير البيانات المخصصة للكائن ليتم عرضها في الجدول
            student.total_paid_display = real_paid 
            student.fees_display = real_required
            student.old_debt_display = student.previous_debt or 0
            student.calculated_remaining = total_due
            
            processed_students.append(student)

        # 5. نظام الترقيم (Pagination) - يتم بعد حساب كل العدادات
        paginator = Paginator(processed_students, 20) 
        page_number = request.GET.get('page')
        students_page = paginator.get_page(page_number)
    else:
        students_page = []

    # 6. إرسال البيانات للقالب
    context = {
        "students": students_page, 
        "all_years": all_years, 
        "all_grades": all_grades, 
        "current_view_year": current_view_year,
        "is_archive": is_archive,
        "total_previous_debt": total_previous_debt,
        "paid_count": paid_count,
        "debt_count": debt_count,
        "unassigned_count": unassigned_count,
    }
    return render(request, "students/student_list.html", context)

 




# def student_list(request):
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id')
#     selected_year_id = request.GET.get('year_id')

#     if selected_year_id:
#         current_view_year = AcademicYear.objects.filter(id=selected_year_id).first()
#     else:
#         current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()

#     total_previous_debt = 0
#     paid_count = 0 
#     debt_count = 0 
#     unassigned_count = 0 
#     processed_students = []

#     if current_view_year:
#         # استرجاع الطلاب للسنة المحددة
#         students_query = Student.objects.filter(
#             academic_year=current_view_year
#         ).select_related("grade", "classroom").order_by('first_name')

#         from django.db.models import Sum
#         total_previous_debt = students_query.aggregate(total=Sum('previous_debt'))['total'] or 0
        
#         for student in students_query:
#             # 🚀 التعديل الجوهري هنا: سحب الأرقام مباشرة من جدول الأقساط الموثوق
#             # نحسب إجمالي ما دفعه الطالب فعلياً في كل أقساطه
#             real_paid = StudentInstallment.objects.filter(
#                 student=student
#             ).aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
            
#             # نحسب إجمالي المطلوب منه (مجموع مبالغ الأقساط الأصلية)
#             real_required = StudentInstallment.objects.filter(
#                 student=student
#             ).aggregate(Sum('amount_due'))['amount_due__sum'] or 0
            
#             # حساب المتبقي
#             total_due = real_required - real_paid

#             # تحديث الإحصائيات (Stats)
#             if total_due <= 0:
#                 paid_count += 1
#             else:
#                 debt_count += 1

#             # 🎯 تمرير البيانات للـ Template لتظهر في الجدول
#             # student.total_paid_display سيظهر الآن 3174 بدلاً من 65
#             student.total_paid_display = real_paid 
#             student.fees_display = real_required
#             student.old_debt_display = student.previous_debt or 0
#             student.calculated_remaining = total_due
#             student.total_required_display = real_required
            
#             processed_students.append(student)

#         # نظام الترقيم
#         paginator = Paginator(processed_students, 20) 
#         page_number = request.GET.get('page')
#         students = paginator.get_page(page_number)
#     else:
#         students = []

#     context = {
#         "students": students, 
#         "all_years": all_years, 
#         "all_grades": all_grades, 
#         "current_view_year": current_view_year,
#         "total_previous_debt": total_previous_debt,
#         "paid_count": paid_count,
#         "debt_count": debt_count,
#         "unassigned_count": unassigned_count,
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



