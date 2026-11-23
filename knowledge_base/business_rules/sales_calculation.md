# Sales calculation guidance
For payment-based sales, join orders to payments by order_id and filter payment_status. Exclude cancelled orders for standard completed-order sales. If joining order_items as well, aggregate payments before joining or use separate subqueries to avoid multiplying payment amounts across item rows.
