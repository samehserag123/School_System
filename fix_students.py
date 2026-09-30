from students.models import Student, Grade

# 1. جلب كائن الصف الأول منتظم
first_grade = Grade.objects.filter(name__icontains="الاول").first() or Grade.objects.filter(name__icontains="الأول").first()

if first_grade:
    # 2. تعديل الطلاب الذين ليس لديهم صف دراسي فقط (الـ 179 طالباً الجدد)
    updated_count = Student.objects.filter(grade__isnull=True).update(
        grade=first_grade,
        initial_status='New',
        enrollment_status='New'
    )
    print(f"=== تم تعديل {updated_count} طالب جديد فقط وربطهم بـ '{first_grade.name}' وحالة القيد 'مستجد'! ===")
else:
    print("❌ لم يتم العثور على الصف الأول، يرجى التأكد من اسم الصف.")