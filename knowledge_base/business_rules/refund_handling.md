# Refund handling
A payment row with payment_status = 'refunded' represents money returned to the customer. Do not count refunded rows as successful paid transactions. For net payment calculations, subtract refunded amounts from paid amounts. The sample dataset uses separate transaction rows and positive amounts.
