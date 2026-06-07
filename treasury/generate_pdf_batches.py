import os
from io import BytesIO
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# --- إعدادات المقاسات والآفست (تعدلها بالمللي حسب مقاس ورق الاستيكر عندك) ---
PAGE_WIDTH, PAGE_HEIGHT = A4
QR_WIDTH = 40 * mm   # عرض مربع الكيو أر
QR_HEIGHT = 40 * mm  # ارتفاع مربع الكيو أر
X_START = 20 * mm    # الآفست الأفقي (المسافة من اليسار)
Y_START = 230 * mm   # الآفست الرأسي (المسافة من الأسفل لأول صف)
X_SPACE = 50 * mm    # المسافة بين العمود والتالي
Y_SPACE = 55 * mm    # المسافة بين الصف والتالي

COLUMNS = 3          # عدد الأعمدة في الصفحة الواحدة
ROWS = 5             # عدد الصفوف في الصفحة الواحدة
ITEMS_PER_PAGE = COLUMNS * ROWS  # 15 كيو أر في الصفحة

def create_pdf_batch(start_num, end_num, filename):
    c = canvas.Canvas(filename, pagesize=A4)
    current_num = start_num
    
    while current_num <= end_num:
        # توليد صفحة جديدة
        for row in range(ROWS):
            for col in range(COLUMNS):
                if current_num > end_num:
                    break
                
                # 1. بناء رابط الفحص الخاص بالسيريال الحالي
                url = f"https://sameh123.pythonanywhere.com/verify/{current_num}/"
                
                # 2. توليد صورة الـ QR مباشرة في الذاكرة (RAM) بدون حفظ ملفات مؤقتة
                qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
                qr.add_data(url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                
                # حفظ الصورة في الذاكرة المؤقتة بدلاً من الهارد ديسك
                img_buffer = BytesIO()
                img.save(img_buffer, format='PNG')
                img_buffer.seek(0)
                
                # 3. حساب الآفست (X, Y) للـ QR الحالي على الورقة
                x_pos = X_START + (col * X_SPACE)
                y_pos = Y_START - (row * Y_SPACE)
                
                # 4. رسم الـ QR وكتابة الرقم السيريال تحته مباشرة للتوضيح
                c.drawImage(ImageReader(img_buffer), x_pos, y_pos, width=QR_WIDTH, height=QR_HEIGHT)
                c.setFont("Helvetica", 9)
                c.drawCentredString(x_pos + (QR_WIDTH/2), y_pos - 4*mm, str(current_num))
                
                current_num += 1
                
        c.showPage() # إنهاء الصفحة الحالية والانتقال للتالية
    c.save()
    print(f"تم بنجاح توليد الملف: {filename}")

# --- تشغيل التوليد على دفعات (كل دفعة 500 كيو أر) ---
start_serial = 6524358946
total_items = 5000
batch_size = 500

for i in range(0, total_items, batch_size):
    batch_start = start_serial + i
    batch_end = min(batch_start + batch_size - 1, start_serial + total_items - 1)
    file_name = f"QR_Batch_{batch_start}_to_{batch_end}.pdf"
    create_pdf_batch(batch_start, batch_end, file_name)