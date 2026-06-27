import pandas as pd

try:
    file_path = "الجدول_النهائي_11_معلم_معدل.xlsx"
    output_path = "إحصائيات_المواد_والفصول.xlsx"

    print("1. جاري قراءة ملف الجدول وتجهيز البيان الإحصائي...")
    xls = pd.ExcelFile(file_path)
    
    with pd.ExcelWriter(output_path) as writer:
        for sheet_name in xls.sheet_names:
            if "جدول الفصول" in sheet_name:
                print(f"   - جاري تحليل ورقة: {sheet_name}")
                df = pd.read_excel(file_path, sheet_name=sheet_name)
                
                stats_dict = {}
                
                for idx, row in df.iterrows():
                    first_val = row.iloc[0]
                    if pd.isna(first_val):
                        continue
                    
                    first_val_str = str(first_val).strip()
                    # تجاهل صفوف العناوين والترويسات الفارغة
                    if "جدول" in first_val_str or "اسم" in first_val_str or first_val_str == "":
                        continue
                    
                    class_name = first_val_str
                    subjects_in_row = []
                    
                    for val in row.values:
                        if pd.isna(val):
                            continue
                        val_str = str(val).strip()
                        # تجاهل اسم الفصل المكرر وتجاهل أي ترويسات للحصص
                        if val_str != class_name and "اسم" not in val_str and "جدول" not in val_str and not val_str.startswith("ح "):
                            subjects_in_row.append(val_str)
                    
                    # حساب التكرارات (عدد الحصص) لكل مادة في هذا الفصل
                    counts = pd.Series(subjects_in_row).value_counts().to_dict()
                    stats_dict[class_name] = counts
                
                if stats_dict:
                    # تحويل البيانات إلى جدول منسق
                    df_stats = pd.DataFrame(stats_dict).T.fillna(0).astype(int)
                    df_stats.index.name = "اسم الفصل"
                    
                    # تحديد اسم ورقة الحفظ بناءً على الفترة (صباحي / مسائي)
                    sheet_label = "إحصاء الصباحي" if "صباحي" in sheet_name else "إحصاء المسائي"
                    df_stats.to_excel(writer, sheet_name=sheet_label)
                    
    print("\n✅ نجاح! تم استخراج الإحصائية الشاملة للفصول والمواد بنجاح.")
    print(f"تم حفظ النتيجة في ملف إكسل جديد باسم: {output_path}")
    print("يمكنك فتح الملف الآن لرؤية الإحصائيات بالتفصيل.")

except Exception as e:
    print(f"❌ حدث خطأ أثناء حساب الإحصائيات: {e}")