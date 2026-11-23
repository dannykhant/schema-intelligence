# Product pricing semantics
products.current_price is the current listed price and may change over time. order_items.unit_price_at_purchase records the unit price at the time the item was ordered. For historical item-level order value, multiply order_items.quantity by order_items.unit_price_at_purchase, not products.current_price.
