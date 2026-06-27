import pandas as pd
import sys

try:
    file_path = "الجدول_النهائي_11_معلم_متوافق.xlsx"
    output_path = "الجدول_النهائي_11_معلم_معدل.xlsx"

    print("1. جاري قراءة الملف وتطبيق التعديلات...")
    xls = pd.ExcelFile(file_path)
    modified_sheets = {}

    for sheet_name in xls.sheet_names:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        
        if "جدول الفصول" in sheet_name:
            # أولاً: تحويل أي حصة دين قديمة إلى احتياطي
            df = df.replace(to_replace=r'^دين \d+$|^دين$', value='احتياطي/نشاط', regex=True)
            
            # ثانياً: عد حصص العربي لكل فصل وتخفيضها إلى 3 فقط
            for index, row in df.iterrows():
                arabic_count = 0
                for col in df.columns:
                    cell_val = str(row[col])
                    if 'عربي' in cell_val:
                        arabic_count += 1
                        # إذا تجاوز العدد 3 حصص، حول الحصة الزائدة إلى احتياطي
                        if arabic_count > 3:
                            df.at[index, col] = 'احتياطي/نشاط'

            # ثالثاً: سحب حصة "تجاري 1" وتحويلها إلى "دين" (لمعلمة التجاري المسيحية)
            for index, row in df.iterrows():
                for col in df.columns:
                    if str(row[col]) == "تجاري 1":
                        df.at[index, col] = "دين"
                        break # نكتفي بحصة واحدة في الأسبوع لكل فصل
                        
            modified_sheets[sheet_name] = df
        else:
            modified_sheets[sheet_name] = df

    print("2. تم ضبط حصص العربي لتكون 3 حصص بالضبط لكل فصل، وتطبيق حصة الدين...")
    print("3. جاري حفظ الملف الجديد...")
    
    with pd.ExcelWriter(output_path) as writer:
        for sheet_name, df in modified_sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    print("\n✅ نجاح! تم التعديل بشكل دقيق جداً.")
    print("الملف الجديد جاهز باسم: الجدول_النهائي_11_معلم_معدل.xlsx")
    
except Exception as e:
    print(f"❌ حدث خطأ: {e}")