# Payment amount semantics
payments.amount is a positive NUMERIC amount associated with one payment transaction. The payment_status determines how it should be interpreted. A refunded row records the amount returned; subtract it when calculating net payment amount. Do not assume every order has exactly one payment row in a more general schema.
