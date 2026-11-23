# Payment status definitions
The payments.payment_status column describes a payment transaction.
- paid: payment successfully received
- pending: payment has not been finalized
- failed: payment attempt was unsuccessful
- refunded: money was returned to the customer
A query asking for successfully paid transactions should explicitly consider payment_status = 'paid'. Refunded records must be considered separately when calculating net revenue.
