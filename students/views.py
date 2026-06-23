from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.apps import apps
from django.core.cache import cache

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

from finance.models import Payment  # تأكد أن اسم التطبيق عندك هو finance
from .forms import CourseGroupForm
from .models import CourseGroup, CoursePayment
from django.db.models.functions import Coalesce, Concat
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

from django.db.models import CharField

from django.db.models import Subquery, OuterRef
# تأكد أن هذا الموديل مستورد بشكل صحيح كما يظهر في ملفك
from finance.models import StudentInstallment, StudentAccount, AcademicYear
# أضف هذا السطر في أعلى ملف views.py
from django.db.models import Q, F, Value, Sum, Count, Case, When, DecimalField, ExpressionWrapper, Exists

# 1. استيراد الموديلات (جداول قاعدة البيانات) الجديدة
from .models import AttendanceRecord, ReEnrollmentRecord, SubjectConfig, ExamResult

# 2. استيراد الفورمات (النماذج) الجديدة 
from .forms import AttendanceFilterForm, ExamResultFilterForm

# 3. تأكد أيضاً من وجود هذا السطر لإدارة العمليات البنكية المجمعة (التي استخدمناها في الدالة الدورية)
from django.db import transaction

from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from django.views.decorators.csrf import csrf_exempt
import json

@login_required
def student_id_card_view(request, student_code):
    """عرض وطباعة كارنيه الطالب مع الـ QR Code باستخدام كود الطالب"""
    # البحث باستخدام student_code بدلاً من id
    student = get_object_or_404(Student, student_code=student_code)
    return render(request, 'students/student_id_card.html', {'student': student})


@login_required
def security_scanner_view(request):
    """شاشة موظف الأمن التي تفتح الكاميرا لمسح الكارنيهات"""
    return render(request, 'students/security_scanner.html')


@csrf_exempt # للسماح باستقبال البيانات من الجافاسكريبت بسلاسة
@login_required
def api_record_qr_attendance(request):
    """الـ API السري الذي يستقبل كود الطالب من الكاميرا ويسجل حضوره"""
    if request.method == 'POST':
        try:
            # 1. استخراج الكود الممسوح من الكاميرا
            data = json.loads(request.body)
            scanned_code = data.get('student_code')
            
            if not scanned_code:
                return JsonResponse({'status': 'error', 'message': 'لم يتم التعرف على الكود.'}, status=400)
            
            # 2. البحث عن الطالب بهذا الكود
            student = Student.objects.filter(student_code=scanned_code, is_active=True).first()
            if not student:
                return JsonResponse({'status': 'error', 'message': '❌ كود غير صحيح، أو الطالب غير نشط!'})
            
            # 3. تسجيل الحضور في قاعدة البيانات
            today = timezone.now().date()
            active_year = get_active_year()
            
            # استخدمنا get_or_create لكي لا يسجل الطالب مرتين إذا مرر الكارنيه مرتين
            record, created = AttendanceRecord.objects.get_or_create(
                student=student,
                date=today,
                academic_year=active_year,
                defaults={'status': 'present', 'notes': 'تسجيل بوابة (QR)'}
            )
            
            if not created:
                if record.status == 'present':
                    return JsonResponse({
                        'status': 'info', 
                        'message': f'⚠️ الطالب ({student.first_name}) مسجل حضوره بالفعل مسبقاً اليوم!'
                    })
                else:
                    record.status = 'present'
                    record.notes = 'تم التعديل لحاضر عبر البوابة (QR)'
                    record.save()
            
            # 4. إرسال رسالة نجاح لموبايل موظف الأمن
            return JsonResponse({
                'status': 'success', 
                'message': f'✅ تم تسجيل حضور: {student.get_full_name()}',
                'student_name': student.get_full_name(),
                'grade': student.grade.name if student.grade else 'غير محدد'
            })
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'خطأ بالنظام: {str(e)}'})
            
    return JsonResponse({'status': 'error', 'message': 'طلب غير صالح.'}, status=400)


@login_required
def report_class_roster_view(request):
    """تقرير طباعة كشوف الفصول (PDF)"""
    active_year = get_active_year()
    grade_id = request.GET.get('grade')
    classroom_id = request.GET.get('classroom')
    
    students = []
    selected_grade = None
    selected_classroom = None
    
    if grade_id:
        selected_grade = get_object_or_404(Grade, id=grade_id)
        query = Student.objects.filter(academic_year=active_year, grade=selected_grade, is_active=True).order_by('first_name')
        if classroom_id:
            selected_classroom = get_object_or_404(Classroom, id=classroom_id)
            query = query.filter(classroom=selected_classroom)
        students = query.only('student_code', 'first_name', 'last_name', 'religion', 'gender')

    context = {
        'students': students,
        'all_grades': Grade.objects.all(),
        'all_classrooms': Classroom.objects.all(),
        'selected_grade': selected_grade,
        'selected_classroom': selected_classroom,
        'active_year': active_year,
        'title': 'كشف فصل دراسي'
    }
    return render(request, 'students/reports/class_roster.html', context)


@login_required
def report_student_registry_view(request):
    """تقرير طباعة السجل المدني الشامل للطلاب (PDF) - مع دعم الفلترة"""
    active_year = get_active_year()
    
    # استقبال الفلاتر من واجهة المستخدم
    grade_id = request.GET.get('grade_id')
    classroom_id = request.GET.get('classroom_id')
    
    # جلب جميع الطلاب النشطين كبداية
    students = Student.objects.filter(
        academic_year=active_year, is_active=True
    ).select_related('grade', 'classroom')
    
    # عنوان فرعي افتراضي
    filter_title = "الشامل للطلاب النشطين (الكل)"

    # تطبيق الفلاتر وتعديل عنوان التقرير المطبوع
    if grade_id:
        students = students.filter(grade_id=grade_id)
        selected_grade = Grade.objects.filter(id=grade_id).first()
        if selected_grade:
            filter_title = f"الصف: {selected_grade.name}"

    if classroom_id:
        students = students.filter(classroom_id=classroom_id)
        # إذا كنت تستخدم موديل Classroom، يمكنك جلب اسمه هنا (حسب تصميم قاعدة بياناتك)
        # filter_title += f" - الفصل/التخصص"

    # ترتيب نهائي
    students = students.order_by('grade', 'classroom', 'first_name')
    
    context = {
        'students': students,
        'total_count': students.count(),
        'active_year': active_year,
        'all_grades': Grade.objects.all(), # إرسال الصفوف للقائمة المنسدلة
        # إذا كان لديك موديل للفصول Classroom أرسله هنا:
        # 'all_classrooms': Classroom.objects.all(), 
        'filter_title': filter_title,
        'title': 'السجل المدني للطلاب'
    }
    return render(request, 'students/reports/student_registry.html', context)


@login_required
def report_dismissed_students_view(request):
    """تقرير طباعة الطلاب المفصولين (PDF)"""
    active_year = get_active_year()
    
    # جلب سجلات الطلاب المفصولين الذين لم يتم إعادة قيدهم بعد
    dismissed_records = ReEnrollmentRecord.objects.filter(
        academic_year=active_year, status='dismissed'
    ).select_related('student__grade', 'student__classroom').order_by('-dismissal_date')

    context = {
        'records': dismissed_records,
        'total_count': dismissed_records.count(),
        'active_year': active_year,
        'title': 'سجل الطلاب المفصولين أكاديمياً'
    }
    return render(request, 'students/reports/dismissed_students.html', context)


@login_required
def attendance_report_view(request):
    """تقرير إحصائي شامل لحالات الغياب والحضور"""
    active_year = get_active_year()
    
    # 🟢 الحل: التقاط الفلاتر مع التأكد من أنها ليست فارغة ("")
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    # إذا كانت القيمة فارغة أو غير موجودة، اجعلها تاريخ اليوم تلقائياً
    if not date_from:
        date_from = timezone.now().date().strftime('%Y-%m-%d')
    if not date_to:
        date_to = timezone.now().date().strftime('%Y-%m-%d')
        
    grade_id = request.GET.get('grade')
    status_filter = request.GET.get('status')
    
    # جلب السجلات بناءً على التاريخ
    records = AttendanceRecord.objects.filter(
        academic_year=active_year, 
        date__range=[date_from, date_to]
    ).select_related('student', 'student__grade', 'student__classroom')

    # تطبيق باقي الفلاتر
    if grade_id:
        records = records.filter(student__grade_id=grade_id)
    if status_filter:
        records = records.filter(status=status_filter)

    # حساب الإحصائيات العلوية السريعة
    total_records = records.count()
    present_count = records.filter(status='present').count()
    absent_count = records.filter(status='absent').count()
    excused_count = records.filter(status='excused').count()

    context = {
        'records': records.order_by('-date', 'student__first_name'),
        'total_records': total_records,
        'present_count': present_count,
        'absent_count': absent_count,
        'excused_count': excused_count,
        'all_grades': Grade.objects.all(),
        'title': 'التقرير الشامل للغياب والحضور',
    }
    return render(request, 'students/attendance_report.html', context)


@login_required
def take_daily_attendance_view(request):
    """شاشة رصد الحضور والغياب اليومي للفصول (المطورة)"""
    active_year = get_active_year()
    students_data = [] # مصفوفة جديدة لدمج الطالب مع حالة غيابه السابقة
    initial_date = timezone.now().date()
    
    if request.method == 'POST' and request.POST.get('save_attendance'):
        # معالجة حفظ الحضور والغياب دفعة واحدة
        posted_date = request.POST.get('attendance_date')
        posted_term = request.POST.get('attendance_term')
        posted_grade = request.POST.get('grade', '')
        posted_classroom = request.POST.get('classroom', '')
        student_ids = request.POST.getlist('student_ids')
        
        with transaction.atomic():
            for s_id in student_ids:
                status = request.POST.get(f'status_{s_id}', 'present')
                notes = request.POST.get(f'notes_{s_id}', '')
                
                AttendanceRecord.objects.update_or_create(
                    student_id=s_id,
                    date=posted_date,
                    defaults={
                        'academic_year': active_year,
                        'term': posted_term,
                        'status': status,
                        'notes': notes
                    }
                )
        messages.success(request, "✅ تم حفظ كشف الحضور والغياب بنجاح.")
        # 🟢 الإرجاع لنفس الصفحة بنفس الفلاتر ليرى المستخدم النتيجة فوراً
        redirect_url = reverse('take_attendance') + f"?date={posted_date}&grade={posted_grade}&classroom={posted_classroom}&term={posted_term}"
        return redirect(redirect_url)

    # معالجة طلب العرض والفلترة (GET)
    form = AttendanceFilterForm(request.GET or None, initial={'date': initial_date})
    
    if form.is_valid():
        filter_date = form.cleaned_data['date']
        grade_id = form.cleaned_data['grade']
        classroom_id = form.cleaned_data['classroom']
        
        students_query = Student.objects.filter(academic_year=active_year, grade=grade_id, is_active=True)
        if classroom_id:
            students_query = students_query.filter(classroom=classroom_id)
            
        students_list = students_query.only('id', 'first_name', 'last_name', 'student_code').order_by('first_name')

        # 🟢 جلب سجلات الغياب المحفوظة مسبقاً لهذا اليوم (إن وجدت)
        existing_records = AttendanceRecord.objects.filter(
            academic_year=active_year, date=filter_date, student__in=students_list
        ).values('student_id', 'status', 'notes')
        
        # تحويلها لقاموس للبحث السريع
        records_map = {rec['student_id']: rec for rec in existing_records}

        # دمج بيانات الطالب مع حالته المحفوظة
        for student in students_list:
            rec = records_map.get(student.id, {'status': 'present', 'notes': ''})
            students_data.append({
                'student': student,
                'status': rec['status'],
                'notes': rec['notes']
            })

    context = {
        'form': form,
        'students_data': students_data, # إرسال البيانات المدمجة
        'active_year': active_year,
        'title': 'تسجيل الحضور والغياب اليومي'
    }
    return render(request, 'students/take_attendance.html', context)

@login_required
def academic_final_report_view(request):
    """تقرير ذكي شامل لفرز الطلاب الناجحين، طلاب الدور الثاني (الملاحق)، والراسبين باقين للإعادة"""
    active_year = get_active_year()
    grade_id = request.GET.get('grade_id')
    
    results_summary = []
    
    if grade_id:
        # 1. جلب جميع المواد وقواعد النجاح المعتمدة لهذا الصف
        configs = SubjectConfig.objects.filter(grade_id=grade_id, academic_year=active_year)
        configs_map = {c.subject_id: c for c in configs}
        
        # 2. جلب طلاب هذا الصف
        students = Student.objects.filter(academic_year=active_year, grade_id=grade_id, is_active=True)
        
        # 3. جلب كل نتائج الامتحانات الفصلية (ترم أول وثانٍ) لهذا الصف دفعة واحدة لسرعة الصاروخ
        all_results = ExamResult.objects.filter(
            academic_year=active_year, exam_type='term', student__grade_id=grade_id
        )
        
        # تنظيم درجات الطلاب في قاموس ذكي داخل الذاكرة لمنع ضرب قاعدة البيانات
        # الطالب -> المادة -> مجموع التيرمين
        student_marks_matrix = {}
        for res in all_results:
            if res.student_id not in student_marks_matrix:
                student_marks_matrix[res.student_id] = {}
            if res.subject_id not in student_marks_matrix[res.student_id]:
                student_marks_matrix[res.student_id][res.subject_id] = 0
                
            student_marks_matrix[res.student_id][res.subject_id] += res.total_score

        # 4. تحليل حالة كل طالب بناءً على المواد المقررة
        for student in students:
            failed_subjects = []
            passed_count = 0
            
            student_profile = student_marks_matrix.get(student.id, {})
            
            for sub_id, config in configs_map.items():
                total_student_score = student_profile.get(sub_id, 0)
                
                if total_student_score < config.passing_score:
                    failed_subjects.append({
                        'subject_name': config.subject.name,
                        'score': total_student_score,
                        'passing_limit': config.passing_score
                    })
                else:
                    passed_count += 1
            
            # تحديد الحالة النهائية للطالب بناءً على اللائحة
            if len(failed_subjects) == 0:
                final_status = 'passed'
                status_label = "ناجح ومنقول للدور الأول ✅"
            elif 1 <= len(failed_subjects) <= 2:
                final_status = 'second_session'
                status_label = f"له دور ثانٍ في ({len(failed_subjects)}) مواد ⚠️"
            else:
                final_status = 'failed'
                status_label = "راسب وباقٍ للإعادة ❌"
                
            results_summary.append({
                'student': student,
                'failed_subjects': failed_subjects,
                'failed_count': len(failed_subjects),
                'status': final_status,
                'status_label': status_label
            })

    context = {
        'all_grades': Grade.objects.all(),
        'selected_grade': grade_id,
        'results_summary': results_summary,
        'title': 'تقرير النتائج النهائي والكنترول العام'
    }
    return render(request, 'students/academic_final_report.html', context)

@login_required
def manage_reenrollments_view(request):
    """إدارة عمليات إعادة قيد الطلاب المفصولين (أكاديمياً فقط بدون أي ربط مالي)"""
    active_year = get_active_year()
    
    if request.method == 'POST' and request.POST.get('action') == 'process_re_enroll':
        record_id = request.POST.get('record_id')
        
        try:
            with transaction.atomic():
                # 1. جلب سجل الفصل الخاص بالطالب للعام الحالي
                record = ReEnrollmentRecord.objects.get(id=record_id, academic_year=active_year)
                student = record.student
                
                # 2. تحديث السجل إلى "تم إعادة القيد" وتثبيت التاريخ اليوم
                record.status = 're_enrolled'
                record.reenrollment_date = timezone.now().date()
                record.save()
                
                # 3. إعادة حالة الطالب الأكاديمية إلى "مستجد" (أو نشط) ليعود للجداول والقوائم
                student.enrollment_status = 'New'  
                student.is_active = True
                student.save()
                
            messages.success(request, f"✅ تم إعادة قيد الطالب {student.get_full_name()} بنجاح، ويمكنه الآن الحضور ورصد درجاته.")
        except Exception as e:
            messages.error(request, f"⚠️ فشل تنفيذ العملية! السبب: {str(e)}")
        return redirect('manage_reenrollments')

    # جلب كافه الطلاب المفصولين حالياً (بسبب الغياب) والذين ينتظرون إعادة القيد
    pending_records = ReEnrollmentRecord.objects.filter(
        academic_year=active_year, status='dismissed'
    ).select_related('student__grade', 'student__classroom')

    context = {
        'pending_records': pending_records,
        'title': 'إعادة قيد الطلاب المفصولين'
    }
    return render(request, 'students/manage_reenrollments.html', context)

@login_required
def record_exam_marks_view(request):
    """شاشة رصد درجات الامتحانات الشهرية والفصلية والملاحق"""
    active_year = get_active_year()
    students_data = []
    subject_config = None
    
    form = ExamResultFilterForm(request.GET or None)
    
    if form.is_valid():
        exam_type = form.cleaned_data['exam_type']
        term = form.cleaned_data['term']
        month = form.cleaned_data['month']
        grade_id = form.cleaned_data['grade']
        classroom_id = form.cleaned_data['classroom']
        subject_id = form.cleaned_data['subject']
        
        # جلب توزيع درجات المادة المحددة لمعرفة النهايات العظمى في التمبلت
        subject_config = SubjectConfig.objects.filter(
            subject_id=subject_id, grade_id=grade_id, academic_year=active_year
        ).first()
        
        # جلب الطلاب المستهدفين للرصد
        students_query = Student.objects.filter(
            academic_year=active_year, grade=grade_id, is_active=True
        )
        if classroom_id:
            students_query = students_query.filter(classroom=classroom_id)
            
        students = students_query.only('id', 'first_name', 'last_name', 'student_code').order_by('first_name')
        
        # جلب الدرجات المرصودة مسبقاً إن وجدت لتعبئتها تلقائياً داخل الحقول (تجنباً لإعادة الرصد)
        existing_results = ExamResult.objects.filter(
            academic_year=active_year, exam_type=exam_type, term=term, month=month, subject_id=subject_id
        ).values('student_id', 'cultural_score', 'practical_score', 'is_absent')
        
        results_map = {r['student_id']: r for r in existing_results}
        
        for student in students:
            res = results_map.get(student.id, {'cultural_score': 0, 'practical_score': 0, 'is_absent': False})
            students_data.append({
                'student': student,
                'cultural_score': res['cultural_score'],
                'practical_score': res['practical_score'],
                'is_absent': res['is_absent']
            })

    # معالجة حفظ الدرجات المرصودة (POST)
    if request.method == 'POST' and 'save_marks' in request.POST:
        posted_form = ExamResultFilterForm(request.POST)
        if posted_form.is_valid():
            p_exam_type = posted_form.cleaned_data['exam_type']
            p_term = posted_form.cleaned_data['term']
            p_month = posted_form.cleaned_data['month']
            p_subject_id = posted_form.cleaned_data['subject']
            
            student_ids = request.POST.getlist('post_student_ids')
            
            with transaction.atomic():
                for s_id in student_ids:
                    c_score = request.POST.get(f'cultural_{s_id}', 0)
                    p_score = request.POST.get(f'practical_{s_id}', 0)
                    absent = request.POST.get(f'absent_{s_id}') == 'true'
                    
                    ExamResult.objects.update_or_create(
                        student_id=s_id,
                        subject_id=p_subject_id,
                        academic_year=active_year,
                        exam_type=p_exam_type,
                        term=p_term,
                        month=p_month,
                        defaults={
                            'cultural_score': Decimal(c_score) if not absent else 0,
                            'practical_score': Decimal(p_score) if not absent else 0,
                            'is_absent': absent
                        }
                    )
            messages.success(request, "✅ تم حفظ ورصد درجات الطلاب بنجاح.")
            return redirect(reverse('record_marks') + f'?exam_type={p_exam_type}&term={p_term}&month={p_month or ""}&grade={request.POST.get("grade")}&classroom={request.POST.get("classroom") or ""}&subject={p_subject_id}')

    context = {
        'form': form,
        'students_data': students_data,
        'subject_config': subject_config,
        'title': 'كنترول رصد الدرجات التفصيلي'
    }
    return render(request, 'students/record_marks.html', context)


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


@login_required
def manage_remedial_dashboard(request):
    """دالة عرض لوحة تحكم البرنامج العلاجي"""
    active_year = get_active_year() 
    
    # 1. حساب الإجماليات بدقة (للكروت العلوية) - سريعة جداً بفضل الفهرس (Index)
    unpaid_count = RemedialProgramRecord.objects.filter(academic_year=active_year, is_paid=False).count()
    paid_count = RemedialProgramRecord.objects.filter(academic_year=active_year, is_paid=True).count()

    # 2. 🟢 الحل الحاسم: جلب (أحدث 50 حركة فقط) للجدول لتدمير استهلاك المعالج (CPU)
    unpaid_records = RemedialProgramRecord.objects.filter(
        academic_year=active_year, 
        is_paid=False
    ).select_related('student').defer(
        'student__image', 'student__address', 'student__birth_place', 'student__father_job', 'student__mother_name'
    ).order_by('-created_at')[:50]  # <-- سر السرعة هنا

    paid_records = RemedialProgramRecord.objects.filter(
        academic_year=active_year, 
        is_paid=True
    ).select_related('student').defer(
        'student__image', 'student__address', 'student__birth_place', 'student__father_job', 'student__mother_name'
    ).order_by('-created_at')[:50]  # <-- سر السرعة هنا

    context = {
        'unpaid_count': unpaid_count,   # مرر الإجمالي لملف HTML إذا كنت تستخدم كروت إحصائية
        'paid_count': paid_count,       # مرر الإجمالي لملف HTML
        'unpaid_records': unpaid_records,
        'paid_records': paid_records,
        'active_year': active_year,
    }
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


import time
import traceback
from decimal import Decimal
from django.contrib import messages
from django.db import transaction

@login_required
def misc_revenue_view(request):
    if request.method == 'POST':
        try:
            # 🟢 الحماية البنكية: إما أن يحفظ في الجدولين أو يلغي العملية بالكامل
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
                
                # 3. التسميع المباشر في الخزينة العامة برقم إيصال فريد
                unique_receipt = f"MISC-{misc_rev.id}-{int(time.time())}"
                
                GeneralLedger.objects.create(
                    student=None, # إيراد عام لا يخص طالباً بعينه
                    amount=amount,
                    category='other',  # 🟢 'other' هي الكلمة السرية ليظهر في الجرد كإيراد متنوع
                    notes=f"إيراد متنوع: {title} ({misc_rev.get_revenue_type_display()})",
                    receipt_number=unique_receipt,
                    collected_by=request.user 
                )
                
            messages.success(request, f"✅ تم تسجيل الإيراد ({title}) بقيمة {amount} ج.م بنجاح وتوريده للخزينة.")
            
        except Exception as e:
            print(traceback.format_exc())
            messages.error(request, f"⚠️ فشل تسجيل الإيراد! السبب: {str(e)}")
            
        return redirect('misc_revenue')

    # ==========================================
    # تجهيز البيانات للعرض بأعلى كفاءة وسرعة (GET Request)
    # ==========================================
    today = timezone.now().date()
    
    # 🟢 1. حساب الإيراد الإجمالي مباشرة من قاعدة البيانات بدلاً من الـ Loops في بايثون
    total_revenue = MiscellaneousRevenue.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    # 🟢 2. حساب إيرادات اليوم فقط مباشرة من قاعدة البيانات

    today_revenue = MiscellaneousRevenue.objects.filter(date=today).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')    
    # 🟢 3. جلب أحدث 50 عملية إيراد فقط لجدول العرض لمنع انهيار الـ CPU والـ HTML DOM
    # أضفنا select_related لربط الموظف المسؤول بخبطة واحدة ومنع استعلامات N+1 داخل الجدول
    revenues = MiscellaneousRevenue.objects.select_related('collected_by').all().order_by('-date')[:50]

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




@login_required
def students_analytics_view(request):
    # 1. إحصائيات سريعة للعدادات العلوية (خفيفة جداً وسريعة)
    total_students = Student.objects.count()
    enrolled_ids = CourseGroup.objects.values_list('student_id', flat=True).distinct()
    
    enrolled_count = enrolled_ids.count()
    non_enrolled_count = total_students - enrolled_count
    
    # 2. تحميل القوائم بأمان (الحل النهائي للسرعة ⚡)
    # 🟢 أضفنا order_by('-created_at') ثم [:50] لجلب "أحدث" 50 طالباً فقط
    enrolled_students = Student.objects.filter(id__in=enrolled_ids).select_related(
        'academic_year', 'grade'
    ).defer('image', 'address', 'birth_place', 'mother_name', 'father_job').order_by('-created_at')[:50]
    
    non_enrolled_students = Student.objects.exclude(id__in=enrolled_ids).select_related(
        'academic_year', 'grade'
    ).defer('image', 'address', 'birth_place', 'mother_name', 'father_job').order_by('-created_at')[:50]
    
    # 3. تحليل المواد
    subject_analysis = CourseGroup.objects.values('course_info__subject__name').annotate(
        total=Count('id')
    ).order_by('-total')

    context = {
        'total_students': total_students,
        'enrolled_students': enrolled_students,
        'non_enrolled_students': non_enrolled_students,
        'subject_analysis': subject_analysis,
        'enrolled_count': enrolled_count,
        'non_enrolled_count': non_enrolled_count,
    }
    return render(request, 'students/analytics_dashboard.html', context)


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
        
        # 🟢 تحسين 1: جلب الطلاب النشطين مع الحقول المطلوبة للاسم فقط لإنقاذ الرامات والمعالج
        form.fields['student'].queryset = Student.objects.filter(is_active=True).only(
            'id', 'first_name', 'last_name', 'student_code', 'national_id'
        )
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
        # 🟢 تحسين 1: نفس فلترة وتقليص بيانات الطلاب في الـ GET لمنع البطء عند فتح الصفحة
        form.fields['student'].queryset = Student.objects.filter(is_active=True).only(
            'id', 'first_name', 'last_name', 'student_code', 'national_id'
        )
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

    # 🟢 تحسين 2: القضاء على الـ N+1 Queries بحساب الإجماليات مباشرة من قاعدة البيانات في استعلامين سريعين جداً
    total_revenue = courses_query.aggregate(total=Sum('required_amount'))['total'] or Decimal('0.00')
    total_collected = CoursePayment.objects.filter(course_enrollment__in=courses_query).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')

    # 5. الترقيم (Pagination)
    paginator = Paginator(courses_query, 15)
    page_number = request.GET.get('page')
    courses_page = paginator.get_page(page_number)

    # 6. جلب قائمة الأسماء الخارجية الفريدة
    existing_external_names = ExternalStudent.objects.values_list('full_name', flat=True).distinct()

    # 7. تمرير البيانات للتمبلت
    context = {
        'courses': courses_page,
        'form': form,
        'total_revenue': total_revenue,
        'total_collected': total_collected,
        'total_remaining': Decimal(total_revenue) - Decimal(total_collected),
        'current_filter': time_filter,
        'date_from': date_from,
        'date_to': date_to,
        'existing_external_names': existing_external_names, 
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

    # 2. استقبال قيم الفلاتر الدقيقة والمتزامنة من الطلب (Request)
    query = request.GET.get('q', '').strip()
    grade_id = request.GET.get('grade_id', '')          # استقبال الـ ID مباشرة
    classroom_id = request.GET.get('classroom_id', '')  # استقبال الـ ID مباشرة
    spec = request.GET.get('specialization', '')        # متوافق مع اسم الـ المتغير المحدث
    gender = request.GET.get('gender', '')              # يستقبل 'Male' أو 'Female' مباشرة
    religion = request.GET.get('religion', '')          # يستقبل 'Muslim' أو 'Christian' مباشرة
    is_disability = request.GET.get('is_disability', '') # يستقبل 'true' أو 'false' مباشرة

    # 3. تطبيق الفلترة المتقدمة للبحث في الأسماء والرقم القومي
    if query:
        base_query = base_query.annotate(
            full_name_db=Concat('first_name', Value(' '), 'last_name', output_field=CharField())
        ).filter(
            Q(first_name__icontains=query) | 
            Q(last_name__icontains=query) | 
            Q(full_name_db__icontains=query) | 
            Q(national_id__icontains=query)
        )
    
    # 4. بقية الفلاتر المربوطة ديناميكياً بقاعدة البيانات
    if grade_id:
        base_query = base_query.filter(grade_id=grade_id)
    if classroom_id:
        base_query = base_query.filter(classroom_id=classroom_id)
    if spec:
        base_query = base_query.filter(specialization=spec)
    if gender:
        base_query = base_query.filter(gender=gender)
    if religion:
        base_query = base_query.filter(religion=religion)
    if is_disability:
        # تحويل النص القادم من الـ AJAX إلى القيمة البوليانية المتوافقة مع الفيلد في الموديل
        status_bool = True if is_disability == 'true' else False
        base_query = base_query.filter(integration_status=status_bool)

    # 5. حساب الإحصائيات الدقيقة (العدادات) بناءً على النتائج المفلترة الحالية
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
        'all_specs': Student.SPECIALIZATION_CHOICES if hasattr(Student, 'SPECIALIZATION_CHOICES') else [],
        
        # للحفاظ على الخيارات المحددة نشطة داخل الـ Dropdowns بعد تحميل الصفحة
        'selected_grade': grade_id,
        'selected_classroom': classroom_id,
        'selected_specialization': spec,
        'selected_gender': gender,
        'selected_religion': religion,
        'selected_is_disability': is_disability,
        'search_query': query,
        
        'current_year': target_year if year_id else active_year,
        'is_archive': bool(year_id),
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
    # 🟢 استخدام select_related العميق لمنع استعلامات N+1 المخفية ولضمان سرعة العرض
    sales = BookSale.objects.select_related(
        'student', 
        'item__subject', 
        'item__uniform', 
        'item__grade'
    ).order_by('-sale_date')
    
    return render(request, 'books/sales_list.html', {'sales': sales})

def add_book_sale(request):
    # 1. جلب السنة الأكاديمية النشطة (استخدمها في المنطق إن لزم الأمر)
    active_year = get_active_year() 
    
    if request.method == 'POST':
        form = BookSaleForm(request.POST)
        if form.is_valid():
            # ... (كود المعالجة والحفظ الخاص بك ممتاز، اتركه كما هو) ...
            sale = form.save(commit=False)
            # ... [كود التحقق من السنة، الصف، السعر، المخزن] ...
            sale._current_user = request.user 
            sale.save()
            return redirect('print_book_receipt', sale_id=sale.id)
        
        # في حال فشل الـ POST، قم بإعادة تقليص بيانات الطلاب في الـ form المعروض
        form.fields['student'].queryset = Student.objects.filter(is_active=True).only('id', 'first_name', 'last_name')
        return render(request, 'books/add_sale.html', {'form': form})

    else:
        # 🟢 التحسين الجوهري للـ GET:
        # لا تقم بـ BookSaleForm() فارغاً، بل قم بتمرير الـ queryset المقلص
        form = BookSaleForm()
        
        # تقليص بيانات الطلاب المعروضة في القائمة المنسدلة (Dropdown)
        # هذا سيجعل الصفحة تفتح في أجزاء من الثانية بدلاً من الانتظار لثوانٍ
        form.fields['student'].queryset = Student.objects.filter(is_active=True).only(
            'id', 'first_name', 'last_name', 'student_code'
        )
        
        # تقليص بيانات الأصناف (Inventory) لمنع استعلامات إضافية (N+1)
        if 'item' in form.fields:
            form.fields['item'].queryset = InventoryItem.objects.select_related('subject', 'uniform', 'grade')
    
    return render(request, 'books/add_sale.html', {'form': form})
# ابحث عن دالة add_book_sale وقم بتعديلها لتصبح هكذا:

# def add_book_sale(request):
#     # جلب السنة الأكاديمية النشطة في البداية لتجنب أخطاء NoneType
#     active_year = get_active_year() 
    
#     if request.method == 'POST':
#         form = BookSaleForm(request.POST)
#         if form.is_valid():
#             sale = form.save(commit=False)
#             inventory_item = sale.item 
#             student = sale.student
#             requested_qty = sale.quantity

#             # 1. التحقق من وجود السنة الأكاديمية للطالب وللنظام
#             if not student.academic_year:
#                 messages.error(request, f"⚠️ الطالب {student.get_full_name()} غير مرتبط بسنة أكاديمية.")
#                 return render(request, 'books/add_sale.html', {'form': form})
            
#             if not student.grade:
#                 messages.error(request, f"⚠️ الطالب {student.get_full_name()} غير مرتبط بصف دراسي.")
#                 return render(request, 'books/add_sale.html', {'form': form})

#             # 2. جلب السعر بناءً على (الصف + السنة الدراسية للطالب)
#             try:
#                 package = GradePackagePrice.objects.get(
#                     grade=student.grade, 
#                     academic_year=student.academic_year
#                 )
#                 if inventory_item.item_type == 'book':
#                     unit_price = package.books_price
#                 else:
#                     unit_price = package.uniform_price
                
#                 sale.total_amount = unit_price * requested_qty
#                 # ربط عملية البيع بالسنة الأكاديمية النشطة
                
#             except GradePackagePrice.DoesNotExist:
#                 # استخدام .name بأمان عبر التحقق أو استخدام default
#                 grade_name = student.grade.name if student.grade else "غير معروف"
#                 year_name = student.academic_year.name if student.academic_year else "غير محددة"
#                 messages.error(request, f"⚠️ لم يتم تحديد سعر الباقة لصف {grade_name} في سنة {year_name}")
#                 return render(request, 'books/add_sale.html', {'form': form})

#             # 3. التأكد من توفر الكمية في المخزن
#             if requested_qty > inventory_item.remaining_qty:
#                 messages.error(request, f"⚠️ المخزن غير كافٍ! المتوفر حالياً: {inventory_item.remaining_qty}")
#                 return render(request, 'books/add_sale.html', {'form': form})
            
#             # 4. الربط مع الموظف الحالي (مهم جداً لعملية السداد الآلي في الموديل)
#             sale._current_user = request.user 
            
#             # 5. الحفظ النهائي
#             sale.save()
            
#             # 6. رسالة نجاح مخصصة حسب حالة الدفع
#             if sale.pay_now > 0:
#                 messages.success(request, f"✅ تم تسجيل الصرف وتوريد مبلغ {sale.pay_now} ج.م للخزينة للطالب {student.get_full_name()}.")
#             else:
#                 messages.warning(request, f"تم تسجيل إذن الصرف للطالب {student.get_full_name()} بدون سداد مالي.")
            
#             # توجيه المستخدم لصفحة الطباعة فوراً
#             return redirect('print_book_receipt', sale_id=sale.id)
        
#         return render(request, 'books/add_sale.html', {'form': form})

#     else:
#         form = BookSaleForm()
    
#     return render(request, 'books/add_sale.html', {'form': form})

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


@login_required
def student_dashboard(request, student_id=None):
    """
    لوحة التحكم التحليلية للمركز المالي للطالب (النسخة الماسية الاحترافية السريعة).
    """
    # 🟢 1. إذا تم تمرير معرف الطالب (وهذا هو السلوك الصحيح للشاشة المطورّة)
    if student_id:
        # جلب الطالب أو عرض 404
        student = get_object_or_404(Student, id=student_id)
        current_year = student.academic_year 

        # جلب أقساط هذا الطالب المحددة للعام الحالي مرتبة تاريخياً
        installments = StudentInstallment.objects.filter(
            student=student, 
            academic_year=current_year
        ).order_by('due_date')

        # العمليات المالية الصارمة والمباشرة (تطير بسرعة الصاروخ)
        total_required = installments.aggregate(s=Sum('amount_due'))['s'] or Decimal('0.00')
        total_paid = installments.aggregate(s=Sum('paid_amount'))['s'] or Decimal('0.00')
        remaining_balance = total_required - total_paid

        # حساب المتأخرات الفورية الحالية (الأقساط التي حل تاريخ استحقاقها ولم تدفع بالكامل)
        today = timezone.now().date()
        total_overdue = installments.filter(
            due_date__lt=today
        ).aggregate(
            s=Sum(F('amount_due') - F('paid_amount'))
        )['s'] or Decimal('0.00')
        
        # تأمين المتأخرات الفورية ضد الدفع الزائد بالخطأ
        total_overdue = max(Decimal('0.00'), total_overdue)

        # حساب النسبة المئوية للسداد بأمان (تجنب أخطاء القسمة على صفر للمستجدين)
        if total_required > 0:
            paid_percentage = round((total_paid / total_required) * 100)
        else:
            paid_percentage = 0

        # بناء الكونتيكست بالأسماء التي يتوقعها ملف الـ HTML الاحترافي بالحرف
        context = {
            "student": student,
            "installments": installments,
            "total_required": total_required,
            "total_paid": total_paid,
            "total_overdue": total_overdue,
            "remaining_balance": remaining_balance,
            "paid_percentage": paid_percentage,
        }
        
        return render(request, "students/student_dashboard.html", context)
    
    # 🔴 2. في حال تم استدعاء الرابط بدون ID طالب (لمنع حدوث شاشة بيضاء أو انهيار)
    # نقوم بتوجيهه فوراً إلى السجل المالي العام للطلاب المطور والسريع
    return redirect('student_list')



@login_required
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
        # 🟢 الخطوة 1: الاستعلام الأساسي (بسيط وسريع بدون أي حسابات مالية)
        # 🟢 الخطوة 1: الاستعلام الأساسي (بسيط وسريع بدون أي حسابات مالية)
        base_query = Student.objects.filter(academic_year=current_view_year, is_active=True).select_related("grade", "classroom")
        
        # تطبيق فلاتر البحث والنوع والمرحلة 
        if grade_id: base_query = base_query.filter(grade_id=grade_id)
        if classroom_id: base_query = base_query.filter(classroom_id=classroom_id)
        if specialization: base_query = base_query.filter(specialization=specialization)
        if gender: base_query = base_query.filter(gender=gender)
        if religion: base_query = base_query.filter(religion=religion)
        if is_disability: base_query = base_query.filter(is_disability=(is_disability == 'true'))

        if search_query:
            base_query = base_query.annotate(full_name_db=Concat('first_name', Value(' '), 'last_name')).filter(
                Q(full_name_db__icontains=search_query) | Q(student_code__icontains=search_query) | Q(national_id__icontains=search_query)
            )

        # 🟢 تجهيز المعادلات المالية (لن نطبقها الآن لتجنب البطء)
        installments_exists_subquery = StudentInstallment.objects.filter(student=OuterRef('pk'), academic_year=current_view_year)
        receipts_subquery = Payment.objects.filter(student=OuterRef('pk'), academic_year=current_view_year, is_cancelled=False).values('student').annotate(t=Sum('amount_paid')).values('t')
        discount_subquery = StudentAccount.objects.filter(student=OuterRef('pk'), academic_year=current_view_year).values('student').annotate(t=Sum('discount')).values('t')
        installments_subquery = StudentInstallment.objects.filter(student=OuterRef('pk'), academic_year=current_view_year).values('student').annotate(t=Sum('amount_due')).values('t')
        late_fees_subquery = StudentInstallment.objects.filter(student=OuterRef('pk'), academic_year=current_view_year).values('student').annotate(t=Sum('late_fee')).values('t')

        financial_annotations = {
            'is_assigned': Exists(installments_exists_subquery), 
            'fees_display': Coalesce(Subquery(installments_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            'late_fees_display': Coalesce(Subquery(late_fees_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            'total_paid_display': Coalesce(Subquery(receipts_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            'discount_display': Coalesce(Subquery(discount_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
        }

        # 🟢 الخطوة 2: تطبيق فلاتر الحالة بذكاء (الاستغناء عن الحساب المعقد للطلاب المسكنين وغير المسكنين)
        # 🟢 الخطوة 2: تطبيق فلاتر الحالة بذكاء
        if status_filter == 'assigned':
            base_query = base_query.filter(installments__academic_year=current_view_year).distinct()
        elif status_filter == 'unassigned':
            base_query = base_query.exclude(installments__academic_year=current_view_year)
        elif status_filter == 'unassigned':
            base_query = base_query.exclude(studentinstallment__academic_year=current_view_year)
        elif status_filter in ['debt', 'paid']:
            # نضطر للحساب هنا فقط إذا طلب المستخدم فلتر المديونية تحديداً
            base_query = base_query.annotate(**financial_annotations).annotate(
                calculated_remaining_approx=ExpressionWrapper(
                    (Coalesce(F('previous_debt'), Value(0, output_field=DecimalField())) + F('fees_display') + F('late_fees_display')) - 
                    (F('total_paid_display') + F('discount_display')), output_field=DecimalField()
                )
            )
            if status_filter == 'debt':
                base_query = base_query.filter(calculated_remaining_approx__gt=0.01)
            elif status_filter == 'paid':
                base_query = base_query.filter(is_assigned=True, calculated_remaining_approx__lte=0.01)

        # 🟢 الخطوة 3: الترقيم أولاً (هنا السرعة الصاروخية لأن الاستعلام أصبح خفيفاً جداً)
        base_query = base_query.order_by('first_name', 'id')
        paginator = Paginator(base_query, 20) 
        current_page_number = request.GET.get('page', 1)
        students_page = paginator.get_page(current_page_number)

        # استخراج أرقام (IDs) الـ 20 طالباً المعروضين في الصفحة فقط
        page_student_ids = [student.id for student in students_page.object_list]

        # 🟢 الخطوة 4: الحساب لاحقاً (تطبيق المعادلات المعقدة على 20 طالباً فقط!)
        annotated_20_students = Student.objects.filter(id__in=page_student_ids).annotate(**financial_annotations)
        financial_map = {s.id: s for s in annotated_20_students}

        # جلب الحسابات القديمة للـ 20 طالباً
        prev_fees_data = StudentAccount.objects.filter(student_id__in=page_student_ids).exclude(academic_year=current_view_year).values('student').annotate(s=Sum('total_fees'))
        prev_fees_map = {item['student']: item['s'] or Decimal('0.00') for item in prev_fees_data}

        prev_discounts_data = StudentAccount.objects.filter(student_id__in=page_student_ids).exclude(academic_year=current_view_year).values('student').annotate(s=Sum('discount'))
        prev_disc_map = {item['student']: item['s'] or Decimal('0.00') for item in prev_discounts_data}

        prev_payments_data = Payment.objects.filter(student_id__in=page_student_ids, is_cancelled=False).exclude(academic_year=current_view_year).values('student').annotate(s=Sum('amount_paid'))
        prev_paid_map = {item['student']: item['s'] or Decimal('0.00') for item in prev_payments_data}

        # 🟢 الخطوة 5: حقن البيانات في صفحة الـ HTML
        for student in students_page.object_list:
            fin_data = financial_map.get(student.id)
            student.is_assigned = fin_data.is_assigned if fin_data else False
            student.fees_display = fin_data.fees_display if fin_data else Decimal('0.00')
            student.late_fees_display = fin_data.late_fees_display if fin_data else Decimal('0.00')
            student.total_paid_display = fin_data.total_paid_display if fin_data else Decimal('0.00')
            student.discount_display = fin_data.discount_display if fin_data else Decimal('0.00')

            p_fees = prev_fees_map.get(student.id, Decimal('0.00'))
            p_disc = prev_disc_map.get(student.id, Decimal('0.00'))
            p_paid = prev_paid_map.get(student.id, Decimal('0.00'))
            
            student.old_debt_display = max(Decimal('0.00'), (p_fees - p_disc) - p_paid)
            student.calculated_remaining = (
                student.old_debt_display + student.fees_display + student.late_fees_display
            ) - (student.total_paid_display + student.discount_display)

        # 🟢 الخطوة 6: عزل وحماية العدادات العلوية السريعة (Stats) عبر الكاش
        force_refresh = request.GET.get('refresh') == '1'
        cache_key = f"student_stats_year_{selected_year_id}_grade_{grade_id}_class_{classroom_id}_search_{search_query}"
        
        if force_refresh:
            cache.delete(cache_key)

        stats = cache.get(cache_key)

        if not stats:
            # 🚀 تم تدمير المصفوفات هنا واستخدام العلاقات المباشرة (JOINs) مع استبعاد غير النشطين
            base_f = Q(academic_year=current_view_year, is_active=True)
            rel_f = Q(academic_year=current_view_year, student__is_active=True)
            
            if grade_id: 
                base_f &= Q(grade_id=grade_id)
                rel_f &= Q(student__grade_id=grade_id)
            if classroom_id: 
                base_f &= Q(classroom_id=classroom_id)
                rel_f &= Q(student__classroom_id=classroom_id)
            if search_query:
                sq = Q(first_name__icontains=search_query) | Q(last_name__icontains=search_query) | Q(student_code__icontains=search_query)
                base_f &= sq
                rsq = Q(student__first_name__icontains=search_query) | Q(student__last_name__icontains=search_query) | Q(student__student_code__icontains=search_query)
                rel_f &= rsq

            # حساب عدد الطلاب الكلي للفلتر
            total_students = Student.objects.filter(base_f).count()
            
            # استخراج أرقام الطلاب المسكنين (بشكل فريد) لإجراء الحلقات التكرارية السريعة عليها
            assigned_ids = set(StudentInstallment.objects.filter(rel_f).values_list('student_id', flat=True))
            assigned_count = len(assigned_ids)

            # تجميع المبالغ بسرعة فائقة
            total_due = StudentInstallment.objects.filter(rel_f).aggregate(s=Sum('amount_due'))['s'] or Decimal('0.00')
            total_late = StudentInstallment.objects.filter(rel_f).aggregate(s=Sum('late_fee'))['s'] or Decimal('0.00')
            total_paid = Payment.objects.filter(rel_f, is_cancelled=False).aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')
            total_discount = StudentAccount.objects.filter(rel_f).aggregate(s=Sum('discount'))['s'] or Decimal('0.00')
            total_prev_debt = Student.objects.filter(base_f).aggregate(s=Sum('previous_debt'))['s'] or Decimal('0.00')
            
            total_remaining_sum = (total_prev_debt + total_due + total_late) - (total_paid + total_discount)

            paid_c = 0
            debt_c = 0
            
            if assigned_count > 0:
                prev_debts = {s['id']: (s['previous_debt'] or Decimal('0.00')) for s in Student.objects.filter(base_f).values('id', 'previous_debt')}
                req_map = {item['student_id']: (item['total_req'] or Decimal('0')) + (item['total_late'] or Decimal('0')) for item in StudentInstallment.objects.filter(rel_f).values('student_id').annotate(total_req=Sum('amount_due'), total_late=Sum('late_fee'))}
                paid_map = {item['student_id']: (item['total_paid'] or Decimal('0')) for item in Payment.objects.filter(rel_f, is_cancelled=False).values('student_id').annotate(total_paid=Sum('amount_paid'))}
                disc_map = {item['student_id']: (item['total_disc'] or Decimal('0')) for item in StudentAccount.objects.filter(rel_f).values('student_id').annotate(total_disc=Sum('discount'))}

                # دوامة بايثون للحساب في الرامات
                for sid in assigned_ids:
                    balance = (prev_debts.get(sid, Decimal('0')) + req_map.get(sid, Decimal('0'))) - (paid_map.get(sid, Decimal('0')) + disc_map.get(sid, Decimal('0')))
                    if balance > Decimal('0.01'): 
                        debt_c += 1
                    else: 
                        paid_c += 1

            stats = {'total': total_students, 'assigned': assigned_count, 'paid': paid_c, 'debt': debt_c, 'total_remaining_sum': total_remaining_sum}
            cache.set(cache_key, stats, 300)

        total_count = stats.get('total') or 0
        assigned_count = stats.get('assigned') or 0
        paid_count = stats.get('paid') or 0
        debt_count = stats.get('debt') or 0
        total_remaining_sum = stats.get('total_remaining_sum') or 0
        
    else:
        students_page = []
        total_count = assigned_count = paid_count = debt_count = total_remaining_sum = 0

    context = {
        "students": students_page, 
        "all_years": all_years, 
        "all_grades": all_grades, 
        "all_classrooms": Classroom.objects.select_related('grade').all(),
        "current_view_year": current_view_year,
        "selected_grade": grade_id,
        "selected_classroom": classroom_id,
        "selected_specialization": specialization,
        "selected_gender": gender,
        "selected_religion": religion,
        "selected_is_disability": is_disability,
        "is_archive": is_archive,
        "total_count": total_count,
        "assigned_count": assigned_count,
        "unassigned_count": total_count - assigned_count,
        "paid_count": paid_count,
        "debt_count": debt_count,
        "remaining": total_remaining_sum,
        "search_query": search_query,
        "status_filter": status_filter,
    }
    return render(request, "students/student_list.html", context)


# @login_required
# def student_list(request):
#     # 1. جلب البيانات الأساسية والفلاتر
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id')
    
#     selected_year_id = request.GET.get('year_id')
#     grade_id = request.GET.get('grade_id')
#     classroom_id = request.GET.get('classroom_id')
#     specialization = request.GET.get('specialization')
#     gender = request.GET.get('gender')
#     religion = request.GET.get('religion')
#     is_disability = request.GET.get('is_disability')
#     search_query = request.GET.get('q', '').strip()
#     status_filter = request.GET.get('status')
    
#     # 2. تحديد السنة الدراسية
#     if selected_year_id:
#         current_view_year = get_object_or_404(AcademicYear, id=selected_year_id)
#         is_archive = not current_view_year.is_active
#     else:
#         current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
#         is_archive = False

#     if current_view_year:
#         # --- الساب كويري الخاصة بالعام الدراسي المختار الحالي فقط ---
#         installments_exists_subquery = StudentInstallment.objects.filter(
#             student=OuterRef('pk'), academic_year=current_view_year
#         )
#         receipts_subquery = Payment.objects.filter(
#             student=OuterRef('pk'), academic_year=current_view_year, is_cancelled=False
#         ).values('student').annotate(total_paid_actual=Sum('amount_paid')).values('total_paid_actual')

#         discount_subquery = StudentAccount.objects.filter(
#             student=OuterRef('pk'), academic_year=current_view_year
#         ).values('student').annotate(total_discount=Sum('discount')).values('total_discount')

#         installments_subquery = StudentInstallment.objects.filter(
#             student=OuterRef('pk'), academic_year=current_view_year
#         ).values('student').annotate(total_due=Sum('amount_due')).values('total_due')

#         late_fees_subquery = StudentInstallment.objects.filter(
#             student=OuterRef('pk'), academic_year=current_view_year
#         ).values('student').annotate(total_late=Sum('late_fee')).values('total_late')

#         # 3. بناء الاستعلام الأساسي المفلتر للطلاب مع الحسبة التقريبية المعتمدة
#         base_query = Student.objects.filter(academic_year=current_view_year)
        
#         students_query = base_query.select_related("grade", "classroom").annotate(
#             full_name_db=Concat('first_name', Value(' '), 'last_name'),
#             is_assigned=Exists(installments_exists_subquery), 
#             fees_display=Coalesce(Subquery(installments_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
#             late_fees_display=Coalesce(Subquery(late_fees_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
#             total_paid_display=Coalesce(Subquery(receipts_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
#             discount_display=Coalesce(Subquery(discount_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            
#             # نقلنا الحسبة التقريبية هنا لتكون متاحة للفلترة والعدادات معاً بدون تكرار الاستعلام
#             calculated_remaining_approx=ExpressionWrapper(
#                 (Coalesce(F('previous_debt'), Value(0, output_field=DecimalField())) + F('fees_display') + F('late_fees_display')) - 
#                 (F('total_paid_display') + F('discount_display')),
#                 output_field=DecimalField()
#             )
#         )

#         # 4. تطبيق فلاتر البحث والنوع والمرحلة على مستوى الـ QuerySet
#         if grade_id: students_query = students_query.filter(grade_id=grade_id)
#         if classroom_id: students_query = students_query.filter(classroom_id=classroom_id)
#         if specialization: students_query = students_query.filter(specialization=specialization)
#         if gender: students_query = students_query.filter(gender=gender)
#         if religion: students_query = students_query.filter(religion=religion)
#         if is_disability: students_query = students_query.filter(is_disability=(is_disability == 'true'))

#         if search_query:
#             students_query = students_query.filter(
#                 Q(full_name_db__icontains=search_query) | Q(student_code__icontains=search_query) | Q(national_id__icontains=search_query)
#             )

#         # 5. حساب العدادات العلوية السريعة (Stats) عبر الكاش
#         from django.core.cache import cache
#         cache_key = f"student_stats_year_{selected_year_id}_grade_{grade_id}_class_{classroom_id}_search_{search_query}"
#         stats = cache.get(cache_key)

#         if not stats:
#             # هنا ينفذ الاستعلام التقيل مرة واحدة فقط عند إنتاج الكاش
#             stats = students_query.aggregate(
#                 total=Count('id'),
#                 assigned=Count(Case(When(is_assigned=True, then=1))),
#                 debt=Count(Case(When(calculated_remaining_approx__gt=0.01, then=1))),
#                 paid=Count(Case(When(Q(is_assigned=True) & Q(calculated_remaining_approx__lte=0.01), then=1))),
#                 total_remaining_sum=Sum('calculated_remaining_approx')
#             )
#             cache.set(cache_key, stats, 600) # كاش 10 دقائق

#         # تطبيق فلتر الحالة المالي مباشرة على الـ students_query بدون تكرار الـ aggregate
#         if status_filter == 'debt':
#             students_query = students_query.filter(calculated_remaining_approx__gt=0.01)
#         elif status_filter == 'paid':
#             students_query = students_query.filter(is_assigned=True, calculated_remaining_approx__lte=0.01)
#         elif status_filter == 'assigned':
#             students_query = students_query.filter(is_assigned=True)
#         elif status_filter == 'unassigned':
#             students_query = students_query.filter(is_assigned=False)

#         # ترتيب النتائج ثابتاً
#         students_query = students_query.order_by('first_name', 'id')

#         # الترقيم المباشر على مستوى الداتابيز (تطلب 20 طالباً فقط)
#         paginator = Paginator(students_query, 20) 
#         current_page_number = request.GET.get('page', 1)
#         students_page = paginator.get_page(current_page_number)

#         # استخراج الـ IDs للـ 20 طالباً المعروضين في هذه الصفحة فقط!
#         page_student_ids = [student.id for student in students_page.object_list]

#         # جلب وتجميع حسابات السنوات السابقة لـ 20 طالباً فقط
#         prev_fees_data = StudentAccount.objects.filter(student_id__in=page_student_ids).exclude(academic_year=current_view_year).values('student').annotate(s=Sum('total_fees'))
#         prev_fees_map = {item['student']: item['s'] or Decimal('0.00') for item in prev_fees_data}

#         prev_discounts_data = StudentAccount.objects.filter(student_id__in=page_student_ids).exclude(academic_year=current_view_year).values('student').annotate(s=Sum('discount'))
#         prev_disc_map = {item['student']: item['s'] or Decimal('0.00') for item in prev_discounts_data}

#         prev_payments_data = Payment.objects.filter(student_id__in=page_student_ids, is_cancelled=False).exclude(academic_year=current_view_year).values('student').annotate(s=Sum('amount_paid'))
#         prev_paid_map = {item['student']: item['s'] or Decimal('0.00') for item in prev_payments_data}

#         # حقن المعادلات الحسابية الدقيقة الحية للـ 20 طالباً فقط داخل الصفحة الحالية
#         for student in students_page.object_list:
#             p_fees = prev_fees_map.get(student.id, Decimal('0.00'))
#             p_disc = prev_disc_map.get(student.id, Decimal('0.00'))
#             p_paid = prev_paid_map.get(student.id, Decimal('0.00'))
            
#             student.old_debt_display = max(Decimal('0.00'), (p_fees - p_disc) - p_paid)
#             student.calculated_remaining = (
#                 student.old_debt_display + student.fees_display + student.late_fees_display
#             ) - (student.total_paid_display + student.discount_display)

#         # استخلاص الإحصائيات النهائية المتوافقة
#         total_count = stats.get('total') or 0
#         assigned_count = stats.get('assigned') or 0
#         paid_count = stats.get('paid') or 0
#         debt_count = stats.get('debt') or 0
#         total_remaining_sum = stats.get('total_remaining_sum') or 0
        
#     else:
#         students_page = []
#         total_count = assigned_count = paid_count = debt_count = total_remaining_sum = 0

#     context = {
#         "students": students_page, 
#         "all_years": all_years, 
#         "all_grades": all_grades, 
#         "all_classrooms": Classroom.objects.select_related('grade').all(),
#         "current_view_year": current_view_year,
#         "selected_grade": grade_id,
#         "selected_classroom": classroom_id,
#         "selected_specialization": specialization,
#         "selected_gender": gender,
#         "selected_religion": religion,
#         "selected_is_disability": is_disability,
#         "is_archive": is_archive,
#         "total_count": total_count,
#         "assigned_count": assigned_count,
#         "unassigned_count": total_count - assigned_count,
#         "paid_count": paid_count,
#         "debt_count": debt_count,
#         "remaining": total_remaining_sum,
#         "search_query": search_query,
#         "status_filter": status_filter,
#     }
#     return render(request, "students/student_list.html", context)





def add_student(request):
    # 1. التحقق مما إذا كان هناك معرف طالب مرسل للتعديل عبر الرابط
    student_id = request.GET.get('edit_id')
    student = None
    
    if student_id:
        student = get_object_or_404(Student, id=student_id)

    # التقاط معايير البحث الحالية من الرابط للاحتفاظ بها عند العودة
    search_query = request.GET.get('q', '')
    grade_id = request.GET.get('grade_id', '')
    classroom_id = request.GET.get('classroom_id', '')
    specialization = request.GET.get('specialization', '')
    gender = request.GET.get('gender', '')
    religion = request.GET.get('religion', '')
    is_disability = request.GET.get('is_disability', '')
    page = request.GET.get('page', '1')

    if request.method == 'POST':
        form = StudentForm(request.POST, request.FILES, instance=student)
        if form.is_valid():
            saved_student = form.save()
            if student:
                messages.success(request, f"✅ تم تحديث بيانات الطالب {saved_student.get_full_name()} بنجاح.")
                
                # بناء رابط العودة مع الحفاظ على الفلاتر والذهاب لسطر الطالب مباشرة
                registry_url = reverse('student_registry')
                redirect_url = f"{registry_url}?page={page}"
                if search_query: redirect_url += f"&q={search_query}"
                if grade_id: redirect_url += f"&grade_id={grade_id}"
                if classroom_id: redirect_url += f"&classroom_id={classroom_id}"
                if specialization: redirect_url += f"&specialization={specialization}"
                if gender: redirect_url += f"&gender={gender}"
                if religion: redirect_url += f"&religion={religion}"
                if is_disability: redirect_url += f"&is_disability={is_disability}"
                
                # إضافة المرساة (Anchor) لسطر الطالب المعدل
                redirect_url += f"#student-{saved_student.id}"
                return redirect(redirect_url)
            else:
                messages.success(request, f"✅ تم إضافة الطالب الجديد {saved_student.get_full_name()} بنجاح.")
                return redirect('student_registry')
    else:
        form = StudentForm(instance=student)

    grades = Grade.objects.all()
    classrooms = Classroom.objects.all()

    context = {
        'form': form,
        'student': student,
        'grades': grades,
        'classrooms': classrooms,
        'is_edit': student is not None,
        # تمرير المعايير للتمبلت لكي نضعها في زر إلغاء الأمر أو نمررها عبر حقول مخفية إذا لزم الأمر
        'search_params': {
            'q': search_query, 'grade_id': grade_id, 'classroom_id': classroom_id,
            'specialization': specialization, 'gender': gender, 'religion': religion,
            'is_disability': is_disability, 'page': page
        }
    }
    return render(request, 'students/add_student.html', context)


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
    search_query = request.GET.get('q', '').strip()
    student_id = request.GET.get('student_id')
    today = timezone.now().date()
    
    # فلترة الطلاب الذين لديهم متأخرات
    query = Q(installments__due_date__lt=today, installments__paid_amount__lt=F('installments__amount_due'))
    students_query = Student.objects.filter(query)
    
    if student_id:
        students_query = students_query.filter(id=student_id)

    # 🟢 البحث الشامل في قاعدة البيانات بالكامل (أسماء، أكواد، هواتف)
    if search_query:
        students_query = students_query.annotate(
            full_name_db=Concat('first_name', Value(' '), 'last_name', output_field=CharField())
        ).filter(
            Q(full_name_db__icontains=search_query) |
            Q(student_code__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(whatsapp_number__icontains=search_query)
        )

    # حساب المتأخرات بدقة
    students_list = students_query.annotate(
        total_overdue=Sum(
            ExpressionWrapper(
                F('installments__amount_due') - F('installments__paid_amount'),
                output_field=DecimalField()
            ),
            filter=Q(
                installments__due_date__lt=today,
                installments__paid_amount__lt=F('installments__amount_due')
            )
        )
    ).distinct().order_by('-total_overdue')

    # الترقيم (20 طالب في الصفحة)
    paginator = Paginator(students_list, 20) 
    page_number = request.GET.get('page')
    students_page = paginator.get_page(page_number)

    # 🟢 الاستجابة الفورية لطلب الـ AJAX لضمان سرعة البحث أثناء الكتابة
    if request.GET.get('ajax') == '1':
        data = []
        for student in students_page.object_list:
            data.append({
                'full_name': student.get_full_name(),
                'student_code': student.student_code or '-',
                'total_overdue': str(student.total_overdue),
                'phone': student.phone or '',
                'whatsapp_number': student.whatsapp_number or '',
            })
        return JsonResponse({
            'students': data,
            'total_count': paginator.count,
        })

    context = {
        'students': students_page, 
        'today': today,
        'search_query': search_query,
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