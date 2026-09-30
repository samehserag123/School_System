import pandas as pd
from datetime import datetime
from students.models import Student, Grade
from finance.models import AcademicYear

file_path = 'سجل الصف الاول الجديد بنات 2026.xlsx'
df = pd.read_excel(file_path, sheet_name='عامة')

active_year = AcademicYear.objects.filter(is_active=True).first()
first_grade = Grade.objects.filter(name__icontains="الأول").first()

gov_map = {
    '01': 'القاهرة', '02': 'الإسكندرية', '03': 'بورسعيد', '04': 'السويس',
    '11': 'دمياط', '12': 'الدقهلية', '13': 'الشرقية', '14': 'القليوبية',
    '15': 'كفر الشيخ', '16': 'الغربية', '17': 'المنوفية', '18': 'البحيرة',
    '19': 'الإسماعيلية', '21': 'الجيزة', '22': 'بني سويف', '23': 'الفيوم',
    '24': 'المنيا', '25': 'أسيوط', '26': 'سوهاج', '27': 'قنا',
    '28': 'أسوان', '29': 'الأقصر', '31': 'البحر الأحمر', '32': 'الوادي الجديد',
    '33': 'مطروح', '34': 'شمال سيناء', '35': 'جنوب سيناء', '88': 'خارج مصر'
}

count = 0
for idx, row in df.iterrows():
    full_name = str(row['الأســـــــــــم']).strip().split()
    first_name = full_name[0] if full_name else ''
    last_name = ' '.join(full_name[1:]) if len(full_name) > 1 else ''

    phones_raw = str(row['التليـــــــفون']).split('/') if pd.notna(row['التليـــــــفون']) else []
    phone = phones_raw[0].strip() if len(phones_raw) > 0 else ''
    whatsapp = phones_raw[1].strip() if len(phones_raw) > 1 else ''

    national_id = str(row['الرقم القومى للطالب']).strip()
    dob, birth_place = None, ''

    if len(national_id) == 14 and national_id.isdigit():
        century = '20' if national_id[0] == '3' else '19'
        year, month, day = century + national_id[1:3], national_id[3:5], national_id[5:7]
        try:
            dob = datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d").date()
        except ValueError:
            dob = None
        birth_place = gov_map.get(national_id[7:9], '')

    branch = str(row['الشعبة']).strip() if pd.notna(row['الشعبة']) else ''
    is_integration = (branch == 'دمج')

    Student.objects.update_or_create(
        national_id=national_id,
        defaults={
            'academic_year': active_year,
            'grade': first_grade,
            'first_name': first_name,
            'last_name': last_name,
            'nationality': str(row['الجنسية']).strip() if pd.notna(row['الجنسية']) else 'مصري',
            'religion': 'Muslim' if str(row['الديانة']).strip() == 'مسلم' else 'Christian',
            'gender': 'Male',
            'registration_number': str(row['رقم القيد']).split('.')[0] if pd.notna(row['رقم القيد']) else '',
            'initial_status': 'Regular',
            'mother_name': str(row['اسم الام']).strip() if pd.notna(row['اسم الام']) else '',
            'father_job': str(row['وظيفة الاب']).strip() if pd.notna(row['وظيفة الاب']) else '',
            'phone': phone,
            'whatsapp_number': whatsapp if len(whatsapp) == 11 and whatsapp.startswith('01') else '',
            'address': str(row['العنوان']).strip() if pd.notna(row['العنوان']) else '',
            'date_of_birth': dob,
            'birth_place': birth_place,
            'integration_status': is_integration,
            'specialization': 'General',
        }
    )
    count += 1

print(f"=== تم إدخال وتحديث {count} طالب بنجاح! ===")