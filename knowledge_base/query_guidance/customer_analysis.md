# Customer analysis query guidance
Customer-level analysis usually starts at customers and joins to orders through customer_id. Payment-based spending then joins orders to payments through order_id. Use GROUP BY customer_id and customer attributes. Be careful not to join order_items into payment aggregation without controlling row multiplication.
