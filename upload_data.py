import os
import django
import pandas as pd

# 1. تهيئة بيئة Django ليعمل السكربت من الخارج
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from students.models import Student
from django.db import transaction

def start_import():
    # اسم الملف الذي رفعته
    file_path = 'students_data.xlsx - asd.csv' 
    
    try:
        # قراءة البيانات (الملف المرفوع هو CSV)
        df = pd.read_csv(file_path)
        
        students_to_save = []
        print(f"جاري تحضير {len(df)} طالب لإدخالهم لقاعدة البيانات...")

        for index, row in df.iterrows():
            # بناء كائن الطالب بناءً على أعمدة ملفك
            student = Student(
                full_name=row['full_name'],
                national_id=str(row['national_id']),
                registration_number=row['registration_number'],
                date_of_birth=row['date_of_birth'],
                grade=row['grade'],
                specialization=row.get('specialization', ''),
                religion=row.get('religion', ''),
                mother_name=row.get('mother_name', ''),
                phone=row.get('phone', '')
            )
            students_to_save.append(student)

        # الإدخال الجماعي (Bulk Create) لضمان السرعة (ثواني معدودة)
        with transaction.atomic():
            Student.objects.bulk_create(students_to_save)
            
        print(f"✅ مبروك! تم إدخال {len(students_to_save)} طالب بنجاح.")

    except Exception as e:
        print(f"❌ فشل الاستيراد بسبب: {e}")

if __name__ == "__main__":
    start_import()