# Order status definitions
The orders.status column describes the fulfillment lifecycle of an order.
- pending: created but not yet processed
- processing: being prepared
- completed: fulfillment has finished
- cancelled: cancelled and should not be treated as a fulfilled purchase
A completed order is not automatically proof of successful payment. Payment status is stored separately in the payments table.
