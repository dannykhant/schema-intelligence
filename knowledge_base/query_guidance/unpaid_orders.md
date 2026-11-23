# Unpaid order query guidance
To find orders without successful payment, use NOT EXISTS against payments where payment_status = 'paid'. Decide whether refunded payments should count as unpaid based on the question. Do not infer payment success from orders.status.
