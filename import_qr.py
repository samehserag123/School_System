import json
from treasury.models import Product, ScanHistory

# قراءة البيانات المصدّرة
with open('qr_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# تصفية عناصر المنتجات وتواريخ المسح
product_items = [i for i in data if i['model'].endswith('.product')]
scan_items = [i for i in data if i['model'].endswith('.scanhistory')]

id_mapping = {}
added_products = 0
skipped_products = 0

# 1. إضافة المنتجات الجديدة فقط بدون استبدال أو المساس بالبيانات القديمة
for item in product_items:
    old_id = item['pk']
    fields = item['fields']
    serial = fields['serial_number']

    prod, created = Product.objects.get_or_create(
        serial_number=serial,
        defaults={
            'product_name': fields['product_name'],
            'is_original': fields.get('is_original', True),
            'is_active': fields.get('is_active', True),
            'disabled_until': fields.get('disabled_until'),
            'scan_count': fields.get('scan_count', 0),
            'created_at': fields.get('created_at'),
        }
    )
    id_mapping[old_id] = prod.id
    if created:
        added_products += 1
    else:
        skipped_products += 1

# 2. ربط وإضافة تواريخ المسح الخاصة بكل QR
added_scans = 0
for item in scan_items:
    fields = item['fields']
    old_prod_id = fields['product']
    new_prod_id = id_mapping.get(old_prod_id)

    if new_prod_id:
        ScanHistory.objects.get_or_create(
            product_id=new_prod_id,
            scanned_at=fields['scanned_at'],
            ip_address=fields.get('ip_address')
        )
        added_scans += 1

print(f"\n==========================================")
print(f"✅ تم دمج وتغذية الـ QR كود بنجاح وأمان!")
print(f"📦 منتجات جديدة تم إنشاؤها: {added_products}")
print(f"⚠️ منتجات موجودة مسبقاً (تم حفظ بياناتها بدون تعديل): {skipped_products}")
print(f"🔍 تواريخ مسح تم ربطها: {added_scans}")
print(f"==========================================\n")