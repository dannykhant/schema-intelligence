INSERT INTO customers (customer_id, full_name, email, created_at, is_active) VALUES
(1, 'Ava Chen', 'ava@example.com', '2024-01-10', TRUE),
(2, 'Noah Patel', 'noah@example.com', '2024-02-15', TRUE),
(3, 'Mia Johnson', 'mia@example.com', '2024-03-20', TRUE),
(4, 'Liam Garcia', 'liam@example.com', '2024-04-05', FALSE),
(5, 'Sophia Kim', 'sophia@example.com', '2024-05-12', TRUE),
(6, 'Ethan Brown', 'ethan@example.com', '2024-06-01', TRUE),
(7, 'Isabella Wilson', 'isabella@example.com', '2024-07-18', TRUE),
(8, 'Lucas Martin', 'lucas@example.com', '2024-08-22', TRUE);

INSERT INTO categories (category_id, category_name, description) VALUES
(1, 'Electronics', 'Computers, phones, and electronic accessories'),
(2, 'Home', 'Home appliances and household goods'),
(3, 'Books', 'Printed books and learning materials'),
(4, 'Sports', 'Sports and outdoor equipment');

INSERT INTO products (product_id, category_id, product_name, current_price, is_active) VALUES
(1, 1, 'Wireless Headphones', 89.99, TRUE),
(2, 1, 'USB-C Hub', 39.50, TRUE),
(3, 1, 'Laptop Stand', 45.00, TRUE),
(4, 1, 'Smart Watch', 149.00, TRUE),
(5, 2, 'Coffee Maker', 79.00, TRUE),
(6, 2, 'Desk Lamp', 28.00, TRUE),
(7, 3, 'Database Systems', 65.00, TRUE),
(8, 3, 'Python Basics', 42.00, TRUE),
(9, 4, 'Yoga Mat', 25.00, TRUE),
(10, 4, 'Running Backpack', 54.00, TRUE);

INSERT INTO orders (order_id, customer_id, order_date, status) VALUES
(1, 1, CURRENT_TIMESTAMP - INTERVAL '20 days', 'completed'),
(2, 1, CURRENT_TIMESTAMP - INTERVAL '10 days', 'completed'),
(3, 2, CURRENT_TIMESTAMP - INTERVAL '40 days', 'completed'),
(4, 2, CURRENT_TIMESTAMP - INTERVAL '8 days', 'cancelled'),
(5, 3, CURRENT_TIMESTAMP - INTERVAL '15 days', 'processing'),
(6, 4, CURRENT_TIMESTAMP - INTERVAL '200 days', 'completed'),
(7, 5, CURRENT_TIMESTAMP - INTERVAL '25 days', 'completed'),
(8, 6, CURRENT_TIMESTAMP - INTERVAL '5 days', 'completed'),
(9, 7, CURRENT_TIMESTAMP - INTERVAL '300 days', 'completed'),
(10, 8, CURRENT_TIMESTAMP - INTERVAL '12 days', 'pending'),
(11, 3, CURRENT_TIMESTAMP - INTERVAL '60 days', 'completed'),
(12, 5, CURRENT_TIMESTAMP - INTERVAL '3 days', 'completed');

INSERT INTO order_items
(order_item_id, order_id, product_id, quantity, unit_price_at_purchase) VALUES
(1, 1, 1, 1, 84.99),
(2, 1, 2, 2, 35.00),
(3, 2, 4, 1, 139.00),
(4, 3, 7, 1, 60.00),
(5, 3, 8, 1, 39.00),
(6, 4, 1, 1, 89.99),
(7, 5, 5, 1, 75.00),
(8, 6, 3, 1, 42.00),
(9, 7, 2, 1, 39.50),
(10, 7, 9, 2, 22.00),
(11, 8, 10, 1, 50.00),
(12, 9, 4, 1, 129.00),
(13, 10, 6, 1, 25.00),
(14, 11, 1, 1, 80.00),
(15, 11, 3, 1, 40.00),
(16, 12, 4, 1, 145.00),
(17, 12, 2, 1, 38.00);

INSERT INTO payments
(payment_id, order_id, payment_date, amount, payment_status) VALUES
(1, 1, CURRENT_TIMESTAMP - INTERVAL '20 days', 154.99, 'paid'),
(2, 2, CURRENT_TIMESTAMP - INTERVAL '10 days', 139.00, 'paid'),
(3, 3, CURRENT_TIMESTAMP - INTERVAL '40 days', 99.00, 'paid'),
(4, 4, CURRENT_TIMESTAMP - INTERVAL '8 days', 89.99, 'refunded'),
(5, 5, CURRENT_TIMESTAMP - INTERVAL '15 days', 75.00, 'pending'),
(6, 6, CURRENT_TIMESTAMP - INTERVAL '200 days', 42.00, 'paid'),
(7, 7, CURRENT_TIMESTAMP - INTERVAL '25 days', 83.50, 'paid'),
(8, 8, CURRENT_TIMESTAMP - INTERVAL '5 days', 50.00, 'paid'),
(9, 9, CURRENT_TIMESTAMP - INTERVAL '300 days', 129.00, 'paid'),
(10, 10, CURRENT_TIMESTAMP - INTERVAL '12 days', 25.00, 'failed'),
(11, 11, CURRENT_TIMESTAMP - INTERVAL '60 days', 120.00, 'paid'),
(12, 12, CURRENT_TIMESTAMP - INTERVAL '3 days', 183.00, 'paid');

SELECT setval(pg_get_serial_sequence('customers', 'customer_id'), (SELECT MAX(customer_id) FROM customers));
SELECT setval(pg_get_serial_sequence('categories', 'category_id'), (SELECT MAX(category_id) FROM categories));
SELECT setval(pg_get_serial_sequence('products', 'product_id'), (SELECT MAX(product_id) FROM products));
SELECT setval(pg_get_serial_sequence('orders', 'order_id'), (SELECT MAX(order_id) FROM orders));
SELECT setval(pg_get_serial_sequence('order_items', 'order_item_id'), (SELECT MAX(order_item_id) FROM order_items));
SELECT setval(pg_get_serial_sequence('payments', 'payment_id'), (SELECT MAX(payment_id) FROM payments));
