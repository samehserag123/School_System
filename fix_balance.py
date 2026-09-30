from django.db.models import Sum, Case, When, F, Value, DecimalField
from django.db.models.functions import Coalesce
from decimal import Decimal
from core_inventory.models import StockBalance, StockTransaction

correct_balances = (
    StockTransaction.objects.values('item_id', 'warehouse_id')
    .annotate(
        total=Coalesce(
            Sum(
                Case(
                    When(movement_type__in=['IN_OPENING', 'IN_PURCHASE', 'IN_RETURN', 'ADJUST'], then=F('quantity')),
                    When(movement_type__in=['OUT_STUDENT', 'OUT_DEPT', 'OUT_WASTE', 'TRANSFER'], then=-F('quantity')),
                    default=Value(Decimal('0.00')),
                    output_field=DecimalField()
                )
            ),
            Decimal('0.00')
        )
    )
)

created = updated = 0
for row in correct_balances:
    item_id, warehouse_id = row['item_id'], row['warehouse_id']
    correct_qty = row['total'] or Decimal('0.00')
    if not warehouse_id:
        continue

    balance, was_created = StockBalance.objects.get_or_create(
        item_id=item_id, warehouse_id=warehouse_id,
        defaults={'quantity_on_hand': correct_qty}
    )
    if was_created:
        created += 1
    elif balance.quantity_on_hand != correct_qty:
        balance.quantity_on_hand = correct_qty
        balance.save(update_fields=['quantity_on_hand'])
        updated += 1

print(f"✅ تم الإنشاء: {created} سجل جديد | تم التصحيح: {updated} سجل قديم")
