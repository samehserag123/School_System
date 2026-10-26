# -*- coding: utf-8 -*-
"""
find_duplicate_students.py
==========================
سكريبت فحص وفلترة الأسماء المطابقة والمتشابهة بين الطلاب
لكشف الحالات التي تم إعادة إضافتها برقم قومي مختلف أو أخطاء إملائية.
"""
import csv
from difflib import SequenceMatcher
from students.models import Student

OUT_DIR = '/home/sameh123/'
REPORT_PATH = OUT_DIR + 'duplicate_students_report.csv'

def normalize_arabic(text):
    """تنظيف وتوحيد أحرف الاسم العربي لمقارنة دقيقة"""
    if not text:
        return ""
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    text = text.replace('ى', 'ي').replace('ة', 'ه')
    words = text.strip().split()
    return " ".join(words)

print('=' * 60)
print('🔍 بدء عملية فحص الأسماء المكررة والمتطابقة في قاعدة البيانات')
print('=' * 60)

# جلب كافة الطلاب النشطين
students = Student.objects.filter(is_active=True).values('id', 'student_code', 'first_name', 'last_name', 'national_id', 'grade__name')

students_list = []
for s in students:
    full_name = f"{s['first_name']} {s['last_name'] or ''}".strip()
    students_list.append({
        'id': s['id'],
        'code': s['student_code'] or '',
        'name': full_name,
        'norm_name': normalize_arabic(full_name),
        'national_id': s['national_id'] or '',
        'grade': s['grade__name'] or ''
    })

print(f'📊 إجمالي عدد الطلاب الخاضعين للفحص: {len(students_list)} طالب.')

duplicates = []
# مقارنة كل طالب مع بقية الطلاب
for i in range(len(students_list)):
    for j in range(i + 1, len(students_list)):
        s1 = students_list[i]
        s2 = students_list[j]
        
        # حساب نسبة التشابه بين الاسمين
        ratio = SequenceMatcher(None, s1['norm_name'], s2['norm_name']).ratio()
        
        w1 = s1['norm_name'].split()
        w2 = s2['norm_name'].split()
        
        # مطابقة أول 3 أسماء (الاسم الأول + اسم الأب + اسم الجد)
        first_3_match = (len(w1) >= 3 and len(w2) >= 3 and w1[:3] == w2[:3])
        
        # إذا كانت نسبة التشابه أكبر من 85% أو تطابق أول 3 أسماء
        if ratio >= 0.85 or first_3_match:
            # تمييز الاختلاف في الرقم القومي
            nid_diff = "نعم (رقم قومي مختلف)" if s1['national_id'] != s2['national_id'] else "مطابق"
            
            duplicates.append([
                s1['id'], s1['code'], s1['name'], s1['grade'], s1['national_id'],
                s2['id'], s2['code'], s2['name'], s2['grade'], s2['national_id'],
                round(ratio * 100, 1), nid_diff
            ])

print(f'⚠️ تم العثور على {len(duplicates)} حالة اشتباه وتكرار في الأسماء!')

# تصدير النتائج إلى ملف CSV
with open(REPORT_PATH, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow([
        'ID الطالب الأول', 'كود 1', 'اسم الطالب الأول', 'صف 1', 'الرقم القومي 1',
        'ID الطالب الثاني', 'كود 2', 'اسم الطالب الثاني', 'صف 2', 'الرقم القومي 2',
        'نسبة التشابه %', 'اختلاف الرقم القومي'
    ])
    writer.writerows(duplicates)

print(f'📄 تم حفظ تقرير الأسماء المطابقة والمتشابهة في:\n   {REPORT_PATH}')
print('=' * 60)