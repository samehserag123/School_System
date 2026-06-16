import io
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from pypdf import PdfReader, PdfWriter

def main():
    # 1. قائمة الأرقام التسلسلية
    serials = [
        "6524358896", "6524358897", "6524358898", "6524358899", 
        "6524358900", "6524358901", "6524358903", "6524358905", 
        "6524358902", "6524358904", "6524358912", "6524358913"
    ]
    base_url = "https://workplace-stan-howard-nathan.trycloudflare.com/verify/"

    # 2. قراءة الخلفية (ملف التصميم الأصلي)
    bg_path = "Artboard 1 copy 2.pdf"
    try:
        bg_reader = PdfReader(bg_path)
        bg_page = bg_reader.pages[0]
        page_w = float(bg_page.mediabox.width)
        page_h = float(bg_page.mediabox.height)
    except FileNotFoundError:
        print(f"خطأ: لم يتم العثور على ملف التصميم {bg_path}.")
        return

    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_w, page_h))

    # 3. الأبعاد (الكيو أر والمسافة)
    qr_size = 12 * mm               # مقاس الكيو أر 1.2 سم
    max_text_width = 11.5 * mm      # أقصى عرض للرقم
    gap = 1.0 * mm                  # المسافة بين الرسمة والرقم (2 مللي)

    # ==========================================
    # 🎯 الإحداثيات المستقلة (12 نقطة منفصلة تماماً) 🎯
    # (الرقم الأول X يمين وشمال ، الرقم الثاني Y فوق وتحت)
    # ==========================================
    centers = [
        # --- الصف الأول ---
        (54.1 * mm, 225.6 * mm),  # 1. الكيو أر الأول (نقطة الأساس المضبوطة)
        (105.0 * mm, 225.6 * mm), # 2. الكيو أر الثاني
        (155.0 * mm, 225.5 * mm), # 3. الكيو أر الثالث
        
        # --- الصف الثاني ---
        (54.0 * mm, 174.6 * mm),  # 4. الكيو أر الرابع
        (105.1 * mm, 174.6 * mm), # 5. الكيو أر الخامس
        (155.1 * mm, 174.6 * mm), # 6. الكيو أر السادس
        
        # --- الصف الثالث ---
        (53.5 * mm, 122.5 * mm),  # 7. الكيو أر السابع
        (105.0 * mm, 122.5 * mm), # 8. الكيو أر الثامن
        (155.0 * mm, 122.5 * mm), # 9. الكيو أر التاسع
        
        # --- الصف الرابع ---
        (53.5 * mm, 70.5 * mm),   # 10. الكيو أر العاشر
        (105.0 * mm, 70.5 * mm),  # 11. الكيو أر الحادي عشر
        (155.0 * mm, 70.5 * mm)   # 12. الكيو أر الثاني عشر
    ]

    # 4. حلقة التوليد والرسم
    for idx, s in enumerate(serials):
        if idx >= len(centers):
            break
            
        center_x, center_y = centers[idx]
        
        # حسابات الخط
        text_width_1pt = stringWidth(s, "Helvetica-Bold", 1)
        font_size = max_text_width / text_width_1pt
        if font_size > 8: font_size = 8  
            
        text_height_mm = font_size * 0.35 * mm
        total_block_height = qr_size + gap + text_height_mm
        block_bottom_y = center_y - (total_block_height / 2)
        
        draw_x_qr = center_x - (qr_size / 2)
        draw_y_qr = block_bottom_y + text_height_mm + gap
        
        # توليد الكيو أر
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=0)
        qr.add_data(f"{base_url}{s}")
        qr.make(fit=True)
        # خلفية بيضاء لكي يتم مسحها لاحقاً
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        
        img_io = io.BytesIO()
        qr_img.save(img_io, format='PNG')
        img_io.seek(0)
        img_reader = ImageReader(img_io)
        
        # رسم الكيو أر بمسح اللون الأبيض ليكون شفاف (Masking)
        c.drawImage(img_reader, draw_x_qr, draw_y_qr, width=qr_size, height=qr_size, mask=[250, 255, 250, 255, 250, 255])
        
        # رسم الرقم التسلسلي
        c.saveState()
        c.setFont("Helvetica-Bold", font_size)
        c.drawCentredString(center_x, block_bottom_y, s)
        c.restoreState()

    c.save()
    packet.seek(0)

    # 5. الدمج والحفظ
    fg_reader = PdfReader(packet)
    fg_page = fg_reader.pages[0]
    
    # دمج طبقة الأكواد مع ملف التصميم
    bg_page.merge_page(fg_page)

    writer = PdfWriter()
    writer.add_page(bg_page)

    output_filename = "Final_Design_With_Background.pdf"
    with open(output_filename, "wb") as out_pdf:
        writer.write(out_pdf)
        
    print(f"--- تمت العملية بنجاح! الملف جاهز باسم: {output_filename} ---")

if __name__ == "__main__":
    main()