# Category sales query guidance
Category analysis follows categories to products through category_id, then products to order_items through product_id, then order_items to orders through order_id. Use order_items.unit_price_at_purchase * quantity for item-level sales. Apply order and payment rules if the question asks for paid sales rather than ordered item value.
