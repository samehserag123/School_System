import os
import subprocess
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

def get_active_cloudflare_url():
    """
    دالة تدخل تلقائياً للوجات دوكر وتجلب رابط الـ trycloudflare الشغال حالياً.
    """
    try:
        # قراءة اللوج من حاوية التانل (تأكد أن اسم السيرفس في compose هو 'tunnel')
        result = subprocess.run(
            ["docker", "compose", "logs", "tunnel"], 
            capture_output=True,
            text=True,
            check=True
        )
        for line in result.stdout.split('\n'):
            if "https://" in line and ".trycloudflare.com" in line:
                words = line.split()
                for word in words:
                    if word.startswith("https://") and "trycloudflare.com" in word:
                        # تنظيف الرابط من أي علامات زائدة
                        clean_url = word.strip().replace('"', '').replace("'", "").strip("│").strip()
                        if clean_url.endswith('/'):
                            clean_url = clean_url[:-1]
                        return clean_url
    except Exception as e:
        print(f"⚠️ لم نتمكن من جلب الرابط تلقائياً من الدوكر: {e}")
    
    # حل بديل أول: وضع الرابط الجديد والنشط حالياً كقيمة افتراضية مباشرة دون تجميد الحاوية
    active_fallback = "https://interim-ontario-welfare-config.trycloudflare.com"
    print(f"🔄 سيتم استخدام الرابط المحدث والنشط حالياً: {active_fallback}")
    return active_fallback

# 1. جلب الرابط النشط للموقع المجاني
base_url = get_active_cloudflare_url()
print(f"✅ الرابط المستخدم في الـ QR Codes هو: {base_url}")

# 2. إعدادات السيريال والمقاسات للـ PDF الجديد
start_serial = 652435889493  # بداية السيريال الجديد
pdf_filename = "QR_Codes_Labels_Print.pdf"

# إنشاء ملف الـ PDF بمقاس A4
c = canvas.Canvas(pdf_filename, pagesize=A4)

# مقاس الـ QR Code (2 سم × 2 سم)
qr_size = 2 * cm

# المسافات البدائية (الإحداثيات تبدأ من الأسفل لليسار في ReportLab)
x_start = 2 * cm
y_start = 25 * cm

# المسافة المتروكة بين كل كود والآخر لسهولة القص والتنظيم
x_spacing = 3 * cm
y_spacing = 3.5 * cm

x_position = x_start
y_position = y_start

print("⏳ جاري توليد الـ QR Codes ورسمها داخل ملف الـ PDF الجديد...")

# توليد 12 كود كمثال (صفين، كل صف يحتوي على 6 كروت متناسقة وثابتة)
for i in range(12):
    current_serial = start_serial + i
    
    # بناء الرابط المباشر الصحيح للمنتج مع السلاش في الآخر لسرعة الاستجابة
    full_url = f"{base_url}/verify/{current_serial}/"
    
    # توليد صورة الـ QR Code في الذاكرة بتفاصيل دقيقة وحواف صغيرة جداً
    qr = qrcode.QRCode(version=1, border=1, box_size=10)
    qr.add_data(full_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    # حفظ مؤقت للصورة لرسمها في الـ PDF
    temp_img_path = f"temp_qr_{current_serial}.png"
    qr_img.save(temp_img_path)
    
    # رسم الـ QR في الـ PDF بالمقاس الثابت والمحدد 2سم × 2سم
    c.drawImage(temp_img_path, x_position, y_position, width=qr_size, height=qr_size)
    
    # كتابة رقم السيريال تحت الكود مباشرة للتوضيح وبحجم خط مناسب ومقروء
    c.setFont("Helvetica", 7)
    c.drawString(x_position + 0.1 * cm, y_position - 0.4 * cm, str(current_serial))
    
    # مسح الصورة المؤقتة فوراً لتنظيف المجلد
    if os.path.exists(temp_img_path):
        os.remove(temp_img_path)
    
    # الانتقال للكود التالي في نفس الصف
    x_position += x_spacing
    
    # إذا اكتمل الصف (6 كروت)، ننتقل لسطر جديد للأسفل ونعيد مؤشر العرض للبداية
    if (i + 1) % 6 == 0:
        x_position = x_start
        y_position -= y_spacing

# حفظ وإغلاق ملف الـ PDF النهائي
c.save()
print(f"🎉 تم بنجاح توليد ملف الـ PDF المظبوط باسم: {pdf_filename}")