# Date conventions
Order and payment dates use PostgreSQL TIMESTAMP values. For relative date questions, use an explicit reference date or PostgreSQL CURRENT_TIMESTAMP. "Last six months" should normally be interpreted as the interval from CURRENT_TIMESTAMP minus INTERVAL '6 months' through the present. Clarify whether the date condition applies to orders or payments if the question is ambiguous.
