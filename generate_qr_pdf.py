import os
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

def generate_product_qrs(start_serial, count=12):
    # الرابط الثابت للسيرفر السحابي
    base_url = "https://sameh123.pythonanywhere.com"
    
    # تحديد مسار مجلد الميديا الأساسي للمشروع
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, 'media')
    
    # التأكد من إنشاء مجلد الميديا لو مش موجود
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    pdf_path = os.path.join(output_dir, "QR_Codes_Labels_Print.pdf")
    
    # إنشاء الـ PDF ومقاسات الكروت
    c = canvas.Canvas(pdf_path, pagesize=A4)
    qr_size = 2 * cm
    x_start, y_start = 2 * cm, 25 * cm
    x_spacing, y_spacing = 3 * cm, 3.5 * cm
    
    x_position, y_position = x_start, y_start
    print(f"⏳ جاري توليد {count} كود QR في مجلد الميديا السحابي...")
    
    for i in range(count):
        current_serial = start_serial + i
        full_url = f"{base_url}/verify/{current_serial}/"
        
        qr = qrcode.QRCode(version=1, border=1, box_size=10)
        qr.add_data(full_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        temp_img_path = f"temp_qr_{current_serial}.png"
        qr_img.save(temp_img_path)
        
        c.drawImage(temp_img_path, x_position, y_position, width=qr_size, height=qr_size)
        c.setFont("Helvetica", 7)
        c.drawString(x_position + 0.1 * cm, y_position - 0.4 * cm, str(current_serial))
        
        if os.path.exists(temp_img_path):
            os.remove(temp_img_path)
            
        x_position += x_spacing
        if (i + 1) % 6 == 0:
            x_position = x_start
            y_position -= y_spacing
            
    c.save()
    print(f"✅ تم بنجاح توليد ملف الـ PDF في مساره الصحيح:\n{pdf_path}")

if __name__ == "__main__":
    generate_product_qrs(start_serial=652435889493, count=12)