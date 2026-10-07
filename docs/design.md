# Design reference

This page documents the data contracts, the data-quality rules, the semantic layer and the evaluation method in
more detail than the README.

## 1. Landing zone

`retail generate` writes one financial year (FY2026: 1 April 2025 to 31 March 2026) for Acme Kitchen Co., a
fictional maker of kitchen and home products with seven stores, two web shops (NZ and AU) and sixteen wholesale
customers. The landing zone is read "as of" 2026-04-01 06:00 UTC; every check that depends on the clock uses that
moment, so results are identical on any day.

| Feed | Files | Cadence | Conventions |
|---|---|---|---|
| ERP material master, customers, stores, FX rates | `erp/*.csv` | daily snapshot | upper-case SAP-style names, `yyyymmdd` dates |
| ERP finance ledger (store takings) | `erp/gl_store_takings_YYYY-MM.csv` | monthly | NZD and local amounts per store-day |
| ERP wholesale sales orders | `erp/sales_orders_YYYY-MM.csv` | monthly | `SALES_DOC`, `ITEM`, `MATERIAL`, `NET_VALUE` |
| Store tills (POS) | `pos/<store>/pos_<store>_YYYY-MM.csv` | monthly per store | one row per transaction line; refunds are `RETURN` lines |
| Web shop | `ecommerce/orders_*.csv`, `order_lines_*.csv` | monthly | last-touch `marketing_channel` on each order |
| 3PL shipments | `logistics/shipments_YYYY-Www.csv` | weekly, 9 days after the week | promised and delivered timestamps |
| Search ads | `marketing/search_ads_*.csv` | monthly | cost in micros, `geo_target` like `NZ-AKL` |
| Social ads | `marketing/social_ads_*.csv` | monthly | `dd/mm/yyyy` dates, region names |
| Display, email, affiliate | `marketing/other_channels_*.csv` | monthly | one row per day, channel and region |

Every file carries `_extracted_at`. `retail ingest` loads each feed into `raw.<feed>` as text, combining files by
column name, and records each file in `raw._ingest_log`.

## 2. Planted failures and the checks that catch them

The generator plants six failures and writes them to `data/ground_truth.json`. `retail dq` reads dbt's run
artifacts and maps each failure to the checks designed for it (`retail_ai/dq/expectations.yaml`). A failure counts
as caught only when a mapped check fires **and**, where the check stores its failing rows, those rows point at the
planted location (store, date, file, column or material).

| Failure | Planted as | Detection checks | What the pipeline does with it |
|---|---|---|---|
| Late file | 3PL week 2026-W12 not delivered | `dbt source freshness` on `raw.logistics_shipments` (error after 8 days); `recon_online_orders_vs_shipments` | Nothing to repair: the alert goes out and on-time figures for that week wait for the file |
| Duplicate rows | Wellington's 14 Nov 2025 lines sent twice | `pos_transaction_line_is_unique`; `recon_pos_raw_vs_finance` | `stg_pos__transaction_lines` keeps the first copy of each line (`row_number()`) |
| Schema drift | `promo_code` column added to web orders from Jan 2026 | `ecom_orders_columns_match_contract` (a generic test that compares the live columns with the contract) | Staging selects columns by name, so values never shift; the new column waits for a modelling decision |
| Currency mix-up | Melbourne's Feb 2026 till file labels AUD as NZD | `assert_pos_currency_matches_store`; `recon_pos_raw_vs_finance` | Staging takes the currency from the store master, so AUD is converted at the day's rate |
| Missing foreign key | wholesale lines for material `MAT-1061`, absent from the master | `erp_sales_order_material_exists` (relationships test) | Revenue is kept; `dim_products` gets an inferred member (category Unknown) and margin excludes the uncosted lines |
| Negative quantity | a Sydney SALE line keyed as a negative quantity | `pos_sale_quantity_is_positive`; `recon_pos_raw_vs_finance` | The line is quarantined in `int_dq__quarantined_pos_lines` and listed in the report |

Detection checks run on the data as delivered and are set to `warn`, so a bad delivery raises an alert without
stopping the build. Checks on the marts are `error`: unique and not-null keys, relationships to every dimension,
accepted values, positive sale quantities, and `recon_pos_mart_vs_finance`, which requires cleaned store revenue to
agree with the finance ledger for every store-day without a quarantined line.

On a clean landing zone (`retail pipeline --clean`) every detection check passes, and the legacy pandas reports
equal the dbt reporting marts row for row (both are asserted in `tests/test_pipeline.py`).

## 3. Semantic layer

Metrics are defined once, in dbt's semantic layer format (`dbt/models/marts/semantic/`), and are validated by
MetricFlow against the warehouse (`mf validate-configs`). Fact models carry measures and foreign entities;
regions, products and channels are small dimension models joined through those entities, which is what allows a
ratio built from two facts (return on ad spend = attributed revenue from orders / spend from ad spend) to be
grouped by the same region or channel on both sides.

| Metric | Definition | Dimensions |
|---|---|---|
| `revenue` | net sales in NZD across store, online and wholesale; refunds subtract; shipping fees and cancelled web orders excluded | date, region, country, sales_channel, product_category |
| `gross_margin` | gross profit / revenue of lines with a known standard cost | date, region, country, sales_channel, product_category |
| `average_order_value` | revenue of sale orders / number of sale orders | date, region, country, sales_channel, marketing_channel |
| `roas` | attributed online revenue (paid channels, last touch) / ad spend | date, region, country, marketing_channel |
| `on_time_delivery_rate` | shipments delivered on or before the promised date / shipments due, by promised date | date, region, country, sales_channel, carrier |

Building blocks are queryable too: `gross_profit`, `costed_revenue`, `units_sold`, `orders`, `order_revenue`,
`ad_spend`, `attributed_revenue`, `shipments_due`, `on_time_shipments`.

### How the MCP server compiles a query

The server reads `dbt/target/semantic_manifest.json` and compiles each request to one SQL statement with the same
semantics MetricFlow uses for this subset (simple and ratio metrics, one-hop dimension joins, `metric_time` at a
grain): per semantic model, aggregate its measures by the requested dimensions; full outer join those aggregates
on the dimensions; divide numerator by denominator for ratios. Filter values are bound as parameters, and every
metric and dimension name is checked against the catalogue. `tests/test_semantic_parity.py` runs every headline
metric by every dimension through both MetricFlow (`mf query`) and the server, and requires identical results.
MetricFlow takes about 6 seconds per query from the command line; the compiled SQL runs in tens of milliseconds,
which is why the server compiles rather than shelling out.

### Read-only SQL guard

`run_readonly_sql` accepts one `SELECT` over the `marts` and `reporting` schemas. DuckDB parses the statement
(`json_serialize_sql`, which refuses anything but `SELECT`), and the server walks the tree: every table must be
schema-qualified and allow-listed (or a CTE of the query), table functions such as `read_csv` are refused, and a
deny list covers functions like `getenv`. Independently, the DuckDB file is opened `READ_ONLY` with external access
disabled and the configuration locked, so even SQL that passed the guard cannot write or read files.

## 4. Evaluation method

* 40 questions in `retail_ai/eval/questions.yaml`, each with a machine-readable spec. 30 are the development set;
  10 are a holdout written at the same time as the others, before any prompt was run, and not used for tuning.
* Reference answers come from `retail_ai/eval/reference.py`: pandas over the generator's clean truth tables,
  independent of dbt and of the semantic layer.
* `retail eval --oracle` (no model, run in CI) sends each spec through the semantic layer and requires it to match
  the reference: this checks both the question set and the warehouse.
* Two systems answer the natural-language questions with the same model:
  * **baseline**: text-to-SQL over the staging layer and reference seeds, given the table documentation and the
    same metric descriptions the semantic layer publishes; one retry on an SQL error or an empty result;
  * **semantic agent**: the analyst agent, calling the MCP server's `query_metric` / `explain_metric` tools.
* Scoring: numbers must be within 0.1% of the reference (fractions also accept a percentage within 0.1 points);
  labels must match after normalising case and punctuation.
* Latency is model time of the live calls plus tool or SQL time; the pause between calls that respects the shared
  rate limit is excluded. Cost is estimated from token counts at the list prices set in `retail_ai/llm.py`.
* Every model response is cached in `eval/cache/` with its token counts and live latency, so
  `retail eval --offline` reproduces the recorded results without a key.
