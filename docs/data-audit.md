# Data audit

What I found reading every row of the CSVs and every page of the manual, and what the agent does about it. Case data is fictional, so I treat each finding as something to handle and report to the store, never as something to fix silently.

## Manual contradictions

| # | Finding | Decision |
|---|---|---|
| 1 | WhatsApp is (67) 3341-4444 on §1.2 and (67) 3321-4500 on §7 | Use 3341-4444: it is on the cover and in the company data table. A note is attached to §7 at load time (`policies.py`) |
| 2 | E-mail is `contato@emporiodamusica.com.br` on the cover and `contato@empóriodamusica.com.br` on §1.2 | Use the version without the accent: e-mail addresses with accents often fail |
| 3 | §3 says "up to 12x, minimum installment R$ 100"; §3.1 gives three tiers | §3.1 is more specific and wins (`rules.py`) |
| 4 | §4.2 sends the customer to the manufacturer after 30 days; §8.1 grants a 90-day legal warranty from receipt | Between day 31 and day 90 a person handles it. Telling a customer they have no store warranty there would contradict Brazilian consumer law |
| 5 | §1 claims "more than 300 instruments"; `products.csv` has 65 | The agent never repeats the 300 figure |
| 6 | §1 lists wind and orchestral strings; categories 6, 7 and 8 have no products | The agent says there are none available today instead of implying they exist |
| 7 | §7.1 says to suggest partner stores, but no partner is named | The agent redirects without naming any store |

## Data inconsistencies

| # | Finding | Decision |
|---|---|---|
| 8 | 21 of 25 promotions are expired, including the Takamine GD20 (12%), the suggested test question | Only `is_active = 1` affects a price |
| 9 | Product 130 is `coming_soon` with stock 2, and was sold in orders 3 and 14 | Status beats stock: shown as coming soon, with no price |
| 10 | Product 96 is `active` with stock 0 and product 113 is `discontinued`, both priced under R$ 1,000 | Browsing shows only what can be bought; naming them explains why not and offers alternatives |
| 11 | Orders 3 and 20 have totals that differ from the sum of their items (3450 vs 3498, 1400 vs 1488) | The stored total is what was billed, so it is shown as is |
| 12 | Orders 9, 16 and 18 break the installment minimums of §3.1 | Past orders are left alone; new simulations follow the rule |
| 13 | Customers 11 and 43 share one e-mail | Verification compares against the customer on that order, never searching by e-mail |
| 14 | There is no delivery date, only `estimated_delivery` | The customer's date is used when given; otherwise the estimate, flagged so the agent asks |
| 15 | There is no sales channel, yet §4.1 applies to online purchases only | An order with a tracking code is treated as remote; the rule states the assumption |
| 16 | The newest order is from 2026-03-22, so a real-time clock would make every order look expired | Order age uses `DATA_AS_OF` (2026-03-25); opening hours use the real clock |
| 17 | Order 8 is `shipped` with an estimate of 2026-02-28 | Flagged `is_late`: the agent apologizes and hands off instead of repeating an old date |
