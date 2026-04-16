import os
import django
import pandas as pd
from django.apps import apps
from django.db import transaction

# 1. تهيئة بيئة Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from students.models import Student, Grade

def clean_date(value):
    if pd.isna(value) or str(value).strip().lower() == 'nan':
        return None
    try:
        return pd.to_datetime(value, dayfirst=True).date()
    except:
        return None

def clean_national_id(value):
    """تنظيف الرقم القومي والتأكد من أنه 14 حرفاً فقط"""
    if pd.isna(value):
        return ""
    # تحويل الرقم لنص وإزالة أي فاصلة عشرية (مثل .0) والمسافات
    clean_id = str(value).split('.')[0].strip()
    # إذا كان الرقم أطول من 14 حرفاً (بسبب أخطاء الإدخال)، سنأخذ أول 14 فقط
    return clean_id[:14]

def start_import():
    file_path = 'students_data.xlsx'
    if not os.path.exists(file_path):
        possible_files = [f for f in os.listdir('.') if f.endswith(('.xlsx', '.csv'))]
        if not possible_files:
            print("❌ لم يتم العثور على أي ملف بيانات!")
            return
        file_path = possible_files[0]

    try:
        # البحث عن الموديل في تطبيق finance كما اكتشفنا
        AcademicYearModel = apps.get_model('finance', 'AcademicYear')
        
        # جلب العام الدراسي (تأكد من كتابة الاسم 2025/2026 كما طلبت)
        academic_year_obj, _ = AcademicYearModel.objects.get_or_create(
            name="2025/2026", 
            defaults={'is_active': True}
        )

        df = pd.read_csv(file_path) if file_path.endswith('.csv') else pd.read_excel(file_path)
        
        students_to_save = []
        print(f"🔄 جاري استيراد {len(df)} سجل لعام {academic_year_obj.name}...")

        for index, row in df.iterrows():
            full_name = str(row['full_name']).strip()
            name_parts = full_name.split(' ', 1)
            f_name = name_parts[0]
            l_name = name_parts[1] if len(name_parts) > 1 else " "

            grade_name = str(row['grade']).strip()
            grade_obj, _ = Grade.objects.get_or_create(name=grade_name)

            # استخدام الدالة الجديدة لتنظيف الرقم القومي (الحل)
            n_id = clean_national_id(row.get('national_id'))
            
            reg_num = str(row['registration_number']).split('.')[0] if pd.notna(row['registration_number']) else "0"

            student = Student(
                first_name=f_name,
                last_name=l_name,
                national_id=n_id,
                registration_number=reg_num,
                date_of_birth=clean_date(row.get('date_of_birth')),
                grade=grade_obj,
                academic_year=academic_year_obj,
                specialization=str(row.get('specialization', '')).replace('nan', ''),
                religion=str(row.get('religion', '')).replace('nan', ''),
                mother_name=str(row.get('mother_name', '')).replace('nan', ''),
                phone=str(row.get('phone', '')).replace('nan', ''),
                is_active=True
            )
            students_to_save.append(student)

        with transaction.atomic():
            Student.objects.bulk_create(students_to_save)
            
        print(f"✅ مبروك! تم استيراد {len(students_to_save)} طالب بنجاح تام.")

    except Exception as e:
        print(f"❌ فشل الاستيراد بسبب: {e}")

if __name__ == "__main__":
    start_import()