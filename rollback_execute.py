# -*- coding: utf-8 -*-
import datetime
from django.db import transaction
from students.models import Student, Grade

print("="*50)
print(" بدء فحص وتحضير سكريبت التراجع عن الترحيل الشامل...")
print("="*50)

target_date = datetime.date(2026, 10, 15)
affected_students = Student.objects.filter(last_promotion_date=target_date)
total_count = affected_students.count()

print(f"📊 عدد الطلاب المطابقين لتاريخ الترحيل (2026-10-15): {total_count}")

if total_count == 0:
    print("⚠️ تنبيه: لا توجد أي سجلات مطابقة لهذا التاريخ!")
else:
    grades = list(Grade.objects.order_by('id').values_list('id', 'name'))
    g_order = [g[0] for g in grades]
    prev_grade_map = {g_order[i]: g_order[i-1] for i in range(1, len(g_order))}
    last_grade = g_order[-1] if g_order else None

    print("\n--- عينة توضيحية لـ 5 طلاب قبل التراجع ---")
    for s in affected_students[:5]:
        print(f" - كود: {s.student_code} | الاسم: {s.first_name} | الصف الحالي ID: {s.grade_id} | الحالة: {s.enrollment_status}")

    print("\n" + "="*50)
    confirm = input("⚠️ هل أنت متأكد تماماً من رغبتك في تنفيذ التراجع الشامل واستعادة الحالات والصفوف؟\nاكتب كلمة YES باللغة الإنجليزية للتأكيد: ")
    
    if confirm.strip() == 'YES':
        print("\n⏳ جاري تنفيذ التراجع وحفظ التغييرات في قاعدة البيانات...")
        try:
            with transaction.atomic():
                updated_count = 0
                for s in affected_students:
                    current_grade = s.grade_id
                    status = s.enrollment_status
                    
                    if current_grade in prev_grade_map and (status == 'Promoted' or status == 'New'):
                        s.grade_id = prev_grade_map[current_grade]
                        s.enrollment_status = 'Promoted'
                    elif status == 'Graduated' and last_grade:
                        s.grade_id = last_grade
                        s.enrollment_status = 'Promoted'
                    elif status == 'Retained':
                        pass
                    
                    s.last_promotion_date = None
                    s.save()
                    updated_count += 1
                    
                print(f"\n✅ تمت عملية التراجع بنجاح تام! تم تحديث وإعادة {updated_count} طالباً إلى حالتهم الصحيحة.")
        except Exception as e:
            print(f"\n❌ حدث خطأ غير متوقع وتم التراجع عن كافة العمليات تلقائياً (Rollback): {e}")
    else:
        print("\n🛡️ تم إلغاء عملية التراجع بناءً على طلبك. لم يتم تعديل أي شيء في قاعدة البيانات.")

print("="*50)
