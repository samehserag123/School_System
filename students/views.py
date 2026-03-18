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

    students_list = []

    if current_view_year:
        students_query = Student.objects.filter(
            academic_year=current_view_year
        ).select_related("grade", "classroom", "account").prefetch_related("all_payments").order_by('first_name')

        for student in students_query:
            # كل اللي جوه هنا لازم يكون واخد مسافة زيادة لجوه (Indent)
            total_paid = student.all_payments.filter(
                academic_year=current_view_year,
                revenue_category__name__icontains="المصروفات الاساسيه"
            ).aggregate(Sum("amount_paid"))["amount_paid__sum"] or 0
            
            old_debt = float(student.previous_debt or 0)
            fees = float(student.current_year_fees_amount or 0)
            
            total_required = fees + old_debt
            remaining = total_required - float(total_paid)

            student.total_paid_display = total_paid
            student.fees_display = fees
            student.old_debt_display = old_debt
            student.calculated_remaining = max(remaining, 0)
            
            students_list.append(student)

        # السطور دي لازم تكون محاذية لـ كلمة for بالظبط (مش جواها)
        paginator = Paginator(students_list, 20) 
        page_number = request.GET.get('page')
        students = paginator.get_page(page_number)
    else:
        students = []

    context = {
        "students": students, 
        "all_years": all_years, 
        "all_grades": all_grades, 
        "current_view_year": current_view_year
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
    
#     if current_view_year:
#         students_query = Student.objects.filter(
#             academic_year=current_view_year
#         ).select_related("grade", "classroom", "account").order_by('first_name')
        
#         for student in students_query:
#             # 1. إجمالي ما دفعه الطالب فعلياً في الخزينة (تاريخياً)
#             total_history_paid = student.all_payments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
            
#             # 2. مديونية الأدمن (اليدوية) + أي مديونيات قديمة مسجلة
#             old_debt_val = float(student.previous_debt or 0) + float(student.get_old_debt_amount or 0)
            
#             # 3. مطلوبات السنة الحالية (لو الطالب متسكن ماليًا)
#             current_fees = float(student.current_year_fees_amount or 0)
            
#             # الحسبة العادلة: (كل اللي عليه) - (كل اللي دفعه)
#             total_balance = (old_debt_val + current_fees) - float(total_history_paid)
            
#             # ده المتغير اللي هيظبط شكل الجدول والأزرار
#             student.net_old_debt = max(total_balance, 0)
            
#             # تحديث المتبقي للعرض (عشان سامح ميبقاش سالب وأحمد ميبقاش صفر)
#             student.calculated_remaining = max(total_balance, 0)
            
#         paginator = Paginator(students_query, 20)
#         students = paginator.get_page(request.GET.get('page'))
#     else:
#         students = []

#     context = {
#         "students": students,
#         "all_years": all_years,
#         "all_grades": all_grades,
#         "current_view_year": current_view_year,
#     }
#     return render(request, "students/student_list.html", context)


# def student_list_view(request):
#     # جلب الطلاب مع تحسين الاستعلام (Optimization)
#     students_list = Student.objects.select_related('account', 'grade', 'classroom').all()

#     # تحديد عدد الطلاب في كل صفحة (مثلاً 50)
#     paginator = Paginator(students_list, 50) 
    
#     page = request.GET.get('page')
#     try:
#         students = paginator.page(page)
#     except PageNotAnInteger:
#         students = paginator.page(1) # إذا لم تكن الصفحة رقم، اعرض الأولى
#     except EmptyPage:
#         students = paginator.page(paginator.num_pages) # إذا تجاوزت الصفحات، اعرض الأخيرة

#     context = {
#         'students': students, # الآن المتغير هو صفحة واحدة من الطلاب
#         'all_years': AcademicYear.objects.all(),
#         # ... باقي المتغيرات الخاصة بك
#     }
#     return render(request, 'your_template_name.html', context)


# from django.db.models import Sum

# def student_list(request):
#     all_years = AcademicYear.objects.all().order_by('-name')
#     all_grades = Grade.objects.all().order_by('id') 

#     selected_year_id = request.GET.get('year_id')
#     if selected_year_id:
#         current_view_year = AcademicYear.objects.filter(id=selected_year_id).first()
#     else:
#         current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
    
#     if current_view_year:
#         students_query = Student.objects.filter(
#             academic_year=current_view_year
#         ).select_related("grade", "classroom", "account").order_by('first_name')
        
#         for student in students_query:
#             # 1. إجمالي مدفوعات الطالب في تاريخه بالكامل (خزينة)
#             history_paid = student.all_payments.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
            
#             # 2. مديونية الأدمن اليدوية (previous_debt)
#             old_debt_val = float(student.previous_debt or 0)
            
#             # 3. مديونية السنة الحالية (إن وجدت في الـ Account)
#             current_fees = float(student.current_year_fees_amount or 0)
            
#             # الحسبة الشاملة (حل لغز الـ 28,200):
#             # نجمع (القديم + الجديد) ونطرح منه (كل اللي اندفع)
#             total_bal = (old_debt_val + current_fees) - float(history_paid)
            
#             # إسناد القيمة لمتغير جديد تماماً للـ HTML
#             student.final_net_debt = max(total_bal, 0)
            
#         paginator = Paginator(students_query, 20)
#         students = paginator.get_page(request.GET.get('page'))
#     else:
#         students = []

#     context = {
#         "students": students,
#         "all_years": all_years,
#         "all_grades": all_grades,
#         "current_view_year": current_view_year,
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
    
#     if current_view_year:
#         # هنا نقوم بجلب الطلاب فقط مع الربط اللازم
#         # الـ Properties (مثل current_remaining) ستعمل تلقائياً عند استدعائها في القالب
#         # نستخدم annotate لجلب إجمالي المدفوعات من قاعدة البيانات مباشرة مع قائمة الطلاب
#        # هنا الـ view نظيف جداً ولن يعطي أي خطأ
#         students_query = Student.objects.filter(
#             academic_year=current_view_year
#         ).select_related("grade", "classroom", "account").order_by('first_name')
        
#         paginator = Paginator(students_query, 20)
#         students = paginator.get_page(request.GET.get('page'))
#     else:
#         students = []

#     context = {
#         "students": students,
#         "all_years": all_years,
#         "all_grades": all_grades,
#         "current_view_year": current_view_year,
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
    from finance.models import AcademicYear 
    student = get_object_or_404(Student, id=student_id)
    
    try:
        current_year = student.academic_year
        
        # 1. جلب كل السنوات مرتبة حسب الاسم (مثلاً 2024 ثم 2025 ثم 2026)
        # الترتيب حسب الاسم 'name' يضمن أن 2025 تأتي بعد 2024
        all_years = list(AcademicYear.objects.all().order_by('name'))
        
        next_year = None
        
        # 2. البحث عن السنة الحالية في القائمة وتحديد التي تليها مباشرة
        for i, year in enumerate(all_years):
            if year.id == current_year.id:
                if i + 1 < len(all_years): # التأكد من وجود سنة تالية في القائمة
                    next_year = all_years[i+1] # هذه هي السنة القادمة (الأحدث)
                break

        if next_year:
            # 3. تحديث بيانات الطالب
            student.academic_year = next_year
            student.enrollment_status = "Promoted" # لظهور "ناجح ومنقول"
            student.save()
            
            messages.success(request, f"🚀 تم ترقية الطالب بنجاح من {current_year.name} إلى {next_year.name}")
        else:
            messages.warning(request, f"تنبيه: لا توجد سنة دراسية مضافة في النظام بعد سنة {current_year.name}. يرجى إضافة السنة القادمة أولاً.")
            
    except Exception as e:
        messages.error(request, f"حدث خطأ فني: {str(e)}")
        
    return redirect(f"/students/add/?id={student_id}&mode=view")

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


