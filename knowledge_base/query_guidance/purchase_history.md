# Purchase history query guidance
A customer's product purchase history follows customers -> orders -> order_items -> products. The order_items table is the bridge between orders and products. Use order_items.unit_price_at_purchase for historical prices. Add categories through products.category_id when category information is required.
