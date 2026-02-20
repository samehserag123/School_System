from django.shortcuts import render, redirect
from rest_framework import generics
from .models import Student
from .serializers import StudentSerializer
from rest_framework import filters
from finance.utils import get_active_year
#from django import forms
from django.contrib import messages
from django.shortcuts import render, redirect
from .forms import StudentForm
from finance.utils import generate_installments_for_student

def student_list(request):
    active_year = get_active_year()

    students = Student.objects.filter(
        academic_year=active_year
    ).select_related("grade", "classroom", "installment_plan")

    return render(request, "students/student_list.html", {
        "students": students,
        "active_year": active_year
    })

def add_student(request):

    if request.method == "POST":
        form = StudentForm(request.POST)

        if form.is_valid():
            student = form.save()
            messages.success(request, "تم إضافة الطالب بنجاح")

            # توليد الأقساط
            generate_installments_for_student(student)

            # نرجع لنفس الصفحة فاضية
            return redirect("add_student")

    else:
        form = StudentForm()

    return render(request, "students/add_student.html", {
        "form": form
    })


#def student_list(request):
    #active_year = get_active_year()

    #students = Student.objects.filter(
        #academic_year=active_year
    #)

    #return render(request, "students/list.html", {
        #"students": students,
        #"active_year": active_year
    #})


class StudentListAPI(generics.ListAPIView):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['first_name', 'last_name', 'national_id']


