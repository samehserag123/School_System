from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.apps import apps
# استيرادات Rest Framework
from rest_framework import generics, filters
# استيراد الموديلات من تطبيق الطلاب
from .models import Student, Grade
from .forms import StudentForm
from .serializers import StudentSerializer
from django.urls import reverse
from finance.models import StudentAccount, AcademicYear, DeliveryRecord 
from finance.utils import get_active_year
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from students.models import Classroom
from django.db.models import Sum ,Q, F# تأكد من وجود هذا السطر في أعلى الملف
from finance.models import Payment  # تأكد أن اسم التطبيق عندك هو finance



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
    return render(request, "students/debt_history.html", context)


def get_classrooms(request):
    grade_id = request.GET.get('grade_id')
    classrooms = Classroom.objects.filter(grade_id=grade_id).values('id', 'name')
    return JsonResponse(list(classrooms), safe=False)




def student_list(request):
    all_years = AcademicYear.objects.all().order_by('-name')
    all_grades = Grade.objects.all().order_by('id')
    selected_year_id = request.GET.get('year_id')

    if selected_year_id:
        current_view_year = AcademicYear.objects.filter(id=selected_year_id).first()
    else:
        current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()

    # تهيئة المتغيرات
    # ... الكود السابق (تحديد السنة) ...

    # تهيئة المتغيرات
    total_previous_debt = 0
    paid_count = 0 
    debt_count = 0 
    unassigned_count = 0 
    processed_students = []

    if current_view_year:
        # استرجاع الطلاب للسنة المحددة مع تحسين الاستعلام
        students_query = Student.objects.filter(
            academic_year=current_view_year
        ).select_related(
            "grade", 
            "classroom"
        ).prefetch_related(
            "accounts",
            "all_payments"
        ).order_by('first_name')

        # 🔥 التعديل: حساب إجمالي المديونية القديمة (المبالغ المرحلة فقط)
        # الطريقة دي بتجمع حقل previous_debt الثابت في قاعدة البيانات مباشرة
        from django.db.models import Sum
        total_previous_debt = students_query.aggregate(
            total=Sum('previous_debt')
        )['total'] or 0
        
        # حساب الطلاب غير المسكنين
        unassigned_count = students_query.exclude(
            accounts__academic_year=current_view_year
        ).distinct().count()

        for student in students_query:
            # 1. المديونية القديمة (القيمة الثابتة في الحقل)
            # بنستخدم الحقل مباشرة عشان العداد والجدول يقرأوا من نفس "الخزنة"
            old_debt = student.previous_debt or 0
            total_due = student.total_balance_due

            # 2. حساب إحصائيات الطلاب (Stats)
            # هنا بنعتمد على الموقف الكلي للطالب (هل مسدد ولا لسه مديون)
            if total_due <= 0:
                paid_count += 1
            else:
                debt_count += 1

            # 3. تجهيز بيانات العرض للتمبلت
            student.total_paid_display = student.current_year_paid if hasattr(student, 'current_year_paid') else 0
            student.fees_display = student.current_year_fees_amount
            student.old_debt_display = old_debt # عرض المديونية المرحلة
            student.calculated_remaining = total_due
            
            # الإجمالي المطلوب (القديم الثابت + مصاريف السنة دي)
            student.total_required_display = old_debt + student.current_year_fees_amount
            
            processed_students.append(student)

        # 4. نظام الترقيم (Pagination)
        paginator = Paginator(processed_students, 20) 
        page_number = request.GET.get('page')
        students = paginator.get_page(page_number)

    else:
        students = []

    context = {
        "students": students, 
        "all_years": all_years, 
        "all_grades": all_grades, 
        "current_view_year": current_view_year,
        "total_previous_debt": total_previous_debt, # العداد الأصفر
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

#     students_list = []
#     total_previous_debt = 0
#     paid_count = 0 
#     debt_count = 0 
#     unassigned_count = 0 

#     if current_view_year:
#         # استرجاع الطلاب للسنة المحددة
#         students_query = Student.objects.filter(
#             academic_year=current_view_year
#         ).select_related(
#             "grade", 
#             "classroom"
#         ).prefetch_related(
#             "accounts",
#             "all_payments"
#         ).order_by('first_name')
        
#         # 1. حساب الطلاب غير المسكنين (يعتمد على قاعدة البيانات - شغال تمام)
#         unassigned_count = students_query.exclude(
#             accounts__academic_year=current_view_year
#         ).distinct().count()

#         # مصفوفة مؤقتة لمعالجة البيانات وحساب الإحصائيات برمجياً
#         processed_students = []
        
#         for student in students_query:
#             # 1. المديونية القديمة (المحسوبة اللي بتصفر لما يدفع)
#             prev_debt = student.calculated_previous_debt 
            
#             # 2. المتبقي الكلي (اللي بيطلع -200 أو صفر)
#             total_due = student.total_balance_due

#             # حساب الإحصائيات (Stats)
#             total_previous_debt += prev_debt
            
#             if total_due <= 0:
#                 paid_count += 1
#             else:
#                 debt_count += 1

#             # تجهيز بيانات العرض (لضمان السرعة في التمبلت)
#             # ملاحظة: اتأكد إن الدوال دي موجودة في الموديل بنفس الأسماء
#             student.total_paid_display = student.current_year_paid if hasattr(student, 'current_year_paid') else 0
#             student.fees_display = student.current_year_fees_amount
#             student.old_debt_display = prev_debt
#             student.calculated_remaining = total_due
            
#             # الإجمالي المطلوب (قديم + جديد)
#             student.total_required_display = (student.previous_debt or 0) + student.current_year_fees_amount
            
#             processed_students.append(student)

#         # الـ Pagination يستخدم القائمة المعالجة
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

# def student_list(request):
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id')
#     selected_year_id = request.GET.get('year_id')

#     if selected_year_id:
#         current_view_year = AcademicYear.objects.filter(id=selected_year_id).first()
#     else:
#         current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()

#     students_list = []
#     # تعريف المتغيرات بقيمة مبدئية صفر
#     total_previous_debt = 0
#     total_required = 0
#     paid_count = 0  # مضاف لضمان عدم حدوث خطأ إذا لم يوجد عام
#     debt_count = 0  # مضاف لضمان عدم حدوث خطأ إذا لم يوجد عام
#     unassigned_count = 0 # المتغير الجديد للطلاب غير المسكنين

#     if current_view_year:
#         students_query = Student.objects.filter(
#             academic_year=current_view_year
#         ).select_related(
#             "grade", 
#             "classroom"
#         ).prefetch_related(
#             "accounts",
#             "all_payments"
#         ).order_by('first_name')
        
#         total_previous_debt = sum([
#             s.final_remaining for s in students_query
#         ])
        
#         # total_previous_debt = students_query.aggregate(Sum('previous_debt'))['previous_debt__sum'] or 0

#         # 1. حساب الطلاب غير المسكنين (الجديد) ✅
#         # هم الطلاب الموجودين في السنة الحالية ولكن ليس لديهم سجل في StudentAccount لهذه السنة
#         unassigned_count = students_query.exclude(
#             accounts__academic_year=current_view_year
#         ).count()

#         # 2. حساب عدد المسددين (الجديد) ✅
#         paid_count = students_query.filter(previous_debt=0, accounts__total_fees__lte=0).count() 

#         # 3. حساب عدد المديونين (الجديد) ✅
#         debt_count = students_query.filter(Q(previous_debt__gt=0) | Q(accounts__total_fees__gt=0)).distinct().count()

#         for student in students_query:
#             student.total_paid_display = student.current_year_paid
#             student.fees_display = student.current_year_fees_amount
#             student.old_debt_display = student.previous_debt
#             student.calculated_remaining = (
#                 (student.previous_debt or 0) + student.final_remaining
#             )
#             student.total_required_display = student.total_required_amount
#             students_list.append(student)

#         paginator = Paginator(students_list, 20) 
#         page_number = request.GET.get('page')
#         students = paginator.get_page(page_number)

#     else:
#         students = []

#     context = {
#         "students": students, 
#         "all_years": all_years, 
#         "all_grades": all_grades, 
#         "current_view_year": current_view_year,
#         # ✅ نرسل الإجماليات للتمبلت هنا
#         "total_previous_debt": total_previous_debt,
#         "paid_count": paid_count,                   # العداد الأخضر
#         "debt_count": debt_count,                   # العداد الأحمر
#         "unassigned_count": unassigned_count,       # العداد الجديد (الأسود)
#     }

#     return render(request, "students/student_list.html", context)




def add_student(request):
    student_id = request.GET.get('id')
    mode = request.GET.get('mode') # التأكد إذا كان عرض فقط أو تعديل
    student = None

    if student_id:
        student = get_object_or_404(Student, id=student_id)

    if request.method == 'POST':
        form = StudentForm(request.POST, request.FILES, instance=student)
        if form.is_valid():
            form.save()
            messages.success(request, "تم حفظ بيانات الطالب بنجاح")
            # التعديل هنا: نجعله يعود لصفحة الإضافة بدلاً من السجل
            return redirect('add_student') 
    else:
        form = StudentForm(instance=student)

    # هنا الحل لظهور السايدبار المطور:
    # نرسل student_admin_mode فقط إذا كنا في وضع العرض (view) أو كان الطالب موجوداً
    is_admin_mode = True if (student and mode == 'view') else False

    return render(request, 'students/add_student.html', {
        'form': form, 
        'student': student,
        'student_admin_mode': is_admin_mode, # تفعيل القائمة الجانبية الخاصة بالطالب
        'hide_sidebar': False
    })

def promote_student(request, student_id):
    try:
        student = get_object_or_404(Student, id=student_id)

        # هات السنة الجاية
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

        # 🔥 استدعاء الدالة الأساسية فقط
        success = promote_student_action(
            student_id=student.id,
            target_year_id=next_year.id,
            target_grade_id=student.grade.id  # أو غيرها حسب النظام
        )

        if success:
            messages.success(request, "تم الترحيل بنجاح")
        else:
            messages.error(request, "فشل الترحيل")

    except Exception as e:
        messages.error(request, str(e))

    return redirect("students_list")
    
# def promote_student(request, student_id):
#     from finance.models import AcademicYear 
#     student = get_object_or_404(Student, id=student_id)
    
#     try:
#         current_year = student.academic_year
        
#         # 1. حساب المديونية المتبقية الحالية قبل النقل
#         # 'final_remaining' هي الدالة اللي عملناها في الموديل
#         remaining_debt = student.final_remaining
        
#         # 2. جلب السنوات مرتبة
#         all_years = list(AcademicYear.objects.all().order_by('name'))
#         next_year = None
        
#         for i, year in enumerate(all_years):
#             if year.id == current_year.id:
#                 if i + 1 < len(all_years):
#                     next_year = all_years[i+1]
#                 break

#         if next_year:
#             # --- الجزء الأهم: الترحيل المالي ---
#             # نقل المديونية المتبقية لتصبح "مديونية سابقة" في السنة الجديدة
#             from decimal import Decimal

#             remaining_debt = student.final_remaining

#             student.previous_debt = remaining_debt
            
#             # --- الترحيل الأكاديمي ---
#             student.academic_year = next_year
#             student.enrollment_status = "Promoted" 
            
#             student.save()
            
#             messages.success(request, f"🚀 تم ترحيل الطالب بنجاح. المديونية المترحلة: {remaining_debt} ج.م")
#         else:
#             messages.warning(request, f"تنبيه: لا توجد سنة دراسية مضافة بعد {current_year.name}.")
            
#     except Exception as e:
#         messages.error(request, f"حدث خطأ فني: {str(e)}")
        
#     return redirect(f"/students/add/?id={student_id}&mode=view")


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
class StudentListAPI(generics.ListAPIView):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['first_name', 'last_name', 'national_id']


