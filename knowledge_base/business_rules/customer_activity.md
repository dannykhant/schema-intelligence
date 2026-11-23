# Customer activity
An active account (customers.is_active = TRUE) is not necessarily a recent purchaser. To identify customers with no recent successful purchases, use a NOT EXISTS subquery over orders joined to payments, apply the requested date condition, and check the relevant order and payment statuses.
