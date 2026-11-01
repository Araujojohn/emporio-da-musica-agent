# Test scorecard

The guarantees this project keeps, each with its proof.

| # | Guarantee | Status | Proof |
|---|---|---|---|
| 1 | Every paid call has a reason: it never ran, or what it depends on changed | yes | requests are keyed by hash in `src/emporio/llm.py`; unchanged requests replay |
| 2 | Recordings are reused: a run with no prompt change is almost free | yes | US$ 0.0006 for the last code-only re-run, `tests/evals/.spend.json` |
| 3 | No mistake is covered twice by the same path, and no eval tests what code guarantees | yes | `tests/evals/comportamento/cases.py`: rules live in unit tests, evals cover model decisions |
| 4 | Daily eval budget enforced in code | yes | `EVAL_BUDGET_USD_PER_DAY` in `src/emporio/llm.py` |
| 5 | The mistakes that matter are listed, each with a test | yes | table below |
| 6 | Each test turns red when its mistake is provoked | yes | `scripts/prove_red.py`, control plus 16 mutations of code; eval checks were seen failing on real runs |
| 7 | A release needs the free suite green at that commit | yes | deploy script runs `pytest` first and refuses a dirty tree; CI runs on every push |
| 8 | The checks run on every real reply | yes | `check` node in `src/emporio/graph.py` runs the guard on all replies |

## Mistakes that matter

| Mistake | Origin | Caught by | Layer |
|---|---|---|---|
| Expired promotion changes a price | data trap | `test_expired_promotion_does_not_change_the_price`, `expired_promotion_is_ignored` | unit, behavior |
| PIX discount stacks on a promotion | manual §6.2 | `test_pix_discount_does_not_stack_with_promotion`, `pix_does_not_stack_with_promotion` | unit, behavior |
| Unavailable product offered as available | data trap | `test_browsing_hides_what_cannot_be_bought`, `browse_under_budget` | unit, behavior |
| Coming soon sold or called out of stock | first eval run | `test_coming_soon_has_no_price_even_with_stock_in_the_csv`, `coming_soon_has_no_price` | unit, behavior |
| Wrong deadline on a return | manual §4 | `test_regret_window_is_seven_calendar_days_from_receipt`, `regret_past_the_deadline` | unit, behavior |
| Another customer's order is revealed | LGPD | `test_contact_of_another_customer_does_not_open_the_order`, `claimed_authority_gets_no_data` | unit, behavior |
| Order existence leaks | LGPD | `test_unknown_order_and_wrong_contact_are_indistinguishable` | unit |
| Invented figure reaches the customer | core risk | `test_unsupported_data_is_caught`, `test_invented_price_gets_one_retry_with_the_reason` | unit, integration |
| Good reply cut by the guard | reading example 1 | `test_product_model_names_are_not_quantities`, `model_name_is_not_an_invented_number` | unit, behavior |
| Stale price quoted from earlier | design | `test_old_tool_results_leave_the_context`, `price_is_read_again_on_follow_up` | integration, behavior |
| Promise of a category with no stock | reading example 5 | `accessories_are_redirected`, `empty_category_is_honest` | behavior |
| Wrong WhatsApp number | manual conflict | `test_contradictions_are_annotated`, `conflicting_whatsapp_is_resolved` | unit, behavior |
| Off-topic answered | brief | `off_topic_is_declined` | behavior |
| A stranger reaches the agent | private demo | `test_without_the_link_nothing_opens`, `test_the_agent_cannot_be_called_without_the_link` | integration |
| Public demo drains the budget | public URL | `test_rate_limit_answers_politely_without_calling_the_model`, `test_daily_budget_stops_the_model` | integration |
| Provider failure shows an error page | operations | `test_provider_failure_reaches_the_customer_as_a_way_out` | integration |

## What is still missing

- Repeated runs of costly cases to measure stability: each case ran once.
- Review of real conversations: there are none yet.
