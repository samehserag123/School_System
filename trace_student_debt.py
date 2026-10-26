# -*- coding: utf-8 -*-
"""
trace_student_debt.py
=====================
تتبع تفصيلي لكيفية تشكل المديونية السابقة للطالبة لي لي سامح عادل إمام
"""
from students.models import Student

print('=' * 60)
print('🔍 بدء تتبع المديونية المالية للطالبة: لي لي سامح عادل إمام')
print('=' * 60)

# البحث عن الطالبة
students = Student.objects.filter(first_name__icontains='لي لي')
print(f"تم العثور على {students.count()} سجل يطابق البحث:\n")

for s in students:
    full_name = f"{s.first_name} {s.last_name or ''}".strip()
    print(f"👤 الطالب/ـة: {full_name}")
    print(f"   • ID الطالب في النظام: {s.pk}")
    print(f"   • الكود (Code): {getattr(s, 'student_code', 'غير محدد')}")
    print(f"   • السنة الدراسية: {s.academic_year}")
    print(f"   • الصف الحالي: {s.grade}")
    print(f"   • الفصل: {s.classroom or 'بدون فصل'}")
    print(f"   • حالة القيد (Status): {s.enrollment_status}")
    print(f"   • نشط (Is Active): {s.is_active}")
    print(f"   • 💳 المديونية السابقة (previous_debt): {s.previous_debt} جنيه")
    
    print('-' * 50)
    print("📋 فحص الجداول والجداول المرتبطة بهذا الطالب تلقائياً:")
    
    # فحص العلاقات المرتبطة بنموذج الطالب (حسابات، مصروفات، مدفوعات مسجلة)
    for rel in s._meta.related_objects:
        accessor = rel.get_accessor_name()
        try:
            related_qs = getattr(s, accessor).all()
            if related_qs.exists():
                print(f"   • وجدنا ارتباطاً في ({accessor}): عدد السجلات = {related_qs.count()}")
                for item in related_qs[:3]:  # عرض عينة من السجلات المرتبطة
                    print(f"     - {item}")
        except Exception:
            pass
            
    print('=' * 60)