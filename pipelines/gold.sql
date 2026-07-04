CREATE OR REFRESH MATERIALIZED VIEW dim_depots_augmented
COMMENT 'Gold depot dimension for route planning.'
AS
SELECT
  depot_id,
  depot_name,
  region,
  sales_territory,
  CAST(lat AS DOUBLE) AS lat,
  CAST(lng AS DOUBLE) AS lng,
  operating_calendar,
  source_system,
  CAST(is_inferred AS BOOLEAN) AS is_inferred,
  confidence_level,
  generated_run_id
FROM silver_depot_master;

CREATE OR REFRESH MATERIALIZED VIEW dim_customers_augmented
COMMENT 'Gold customer dimension with route-planning service rules.'
AS
SELECT
  customer_id,
  customer_name,
  depot_id,
  region,
  sales_territory,
  CAST(lat AS DOUBLE) AS lat,
  CAST(lng AS DOUBLE) AS lng,
  customer_priority,
  CAST(delivery_frequency AS INT) AS delivery_frequency,
  eligible_delivery_days,
  receiving_window_start,
  receiving_window_end,
  CAST(service_minutes AS INT) AS service_minutes,
  special_handling,
  source_system,
  CAST(is_inferred AS BOOLEAN) AS is_inferred,
  confidence_level,
  generated_run_id
FROM silver_location_data;

CREATE OR REFRESH MATERIALIZED VIEW dim_customer_constraints
COMMENT 'Gold customer service constraints used by scenario validation and the solver.'
AS
SELECT
  customer_id,
  depot_id,
  eligible_delivery_days,
  receiving_window_start,
  receiving_window_end,
  CAST(service_minutes AS INT) AS service_minutes,
  customer_priority,
  special_handling,
  CASE WHEN customer_priority = 'strategic' THEN true ELSE false END AS hard_time_window_flag,
  CASE
    WHEN customer_priority = 'strategic' THEN 1.0
    WHEN customer_priority = 'key' THEN 0.7
    ELSE 0.4
  END AS consistency_weight,
  source_system,
  CAST(is_inferred AS BOOLEAN) AS is_inferred,
  confidence_level,
  generated_run_id
FROM silver_location_data;

CREATE OR REFRESH MATERIALIZED VIEW dim_fleet_assets
COMMENT 'Gold fleet asset dimension with capacity and cost assumptions.'
AS
SELECT
  vehicle_id,
  depot_id,
  vehicle_type,
  CAST(capacity_cases AS INT) AS capacity_cases,
  CAST(fixed_truck_daily_cost AS DOUBLE) AS fixed_truck_daily_cost,
  CAST(cost_per_mile AS DOUBLE) AS cost_per_mile,
  CAST(max_route_minutes AS INT) AS max_route_minutes,
  available_days,
  source_system,
  CAST(is_inferred AS BOOLEAN) AS is_inferred,
  confidence_level,
  generated_run_id
FROM silver_fleet_assets;

CREATE OR REFRESH MATERIALIZED VIEW dim_drivers
COMMENT 'Gold driver dimension with shift and labor assumptions.'
AS
SELECT
  driver_id,
  driver_name,
  depot_id,
  shift_start,
  shift_end,
  CAST(overtime_threshold_minutes AS INT) AS overtime_threshold_minutes,
  CAST(labor_regular_hour AS DOUBLE) AS labor_regular_hour,
  available_days,
  source_system,
  CAST(is_inferred AS BOOLEAN) AS is_inferred,
  confidence_level,
  generated_run_id
FROM silver_drivers;

CREATE OR REFRESH MATERIALIZED VIEW fact_customer_product_demand
COMMENT 'Gold customer demand fact by depot and delivery day.'
AS
SELECT
  customer_id,
  depot_id,
  delivery_day,
  CAST(expected_cases AS INT) AS expected_cases,
  product_family,
  source_system,
  CAST(is_inferred AS BOOLEAN) AS is_inferred,
  confidence_level,
  generated_run_id
FROM silver_customer_product_demand;

CREATE OR REFRESH MATERIALIZED VIEW fact_delivery_orders
COMMENT 'Gold delivery order fact used for baseline reconstruction.'
AS
SELECT
  order_id,
  customer_id,
  depot_id,
  delivery_day,
  route_date,
  CAST(demand_cases AS INT) AS demand_cases,
  product_family,
  source_system,
  CAST(is_inferred AS BOOLEAN) AS is_inferred,
  confidence_level,
  generated_run_id
FROM silver_delivery_orders;

CREATE OR REFRESH MATERIALIZED VIEW cost_parameters
COMMENT 'Gold route cost parameters used by the shared cost function.'
AS
SELECT
  parameter_set_id,
  CAST(cost_per_mile AS DOUBLE) AS cost_per_mile,
  CAST(labor_regular_hour AS DOUBLE) AS labor_regular_hour,
  CAST(overtime_multiplier AS DOUBLE) AS overtime_multiplier,
  CAST(overtime_threshold_minutes AS INT) AS overtime_threshold_minutes,
  CAST(fixed_truck_daily_cost AS DOUBLE) AS fixed_truck_daily_cost,
  CAST(max_route_minutes AS INT) AS max_route_minutes,
  CAST(late_delivery_penalty AS DOUBLE) AS late_delivery_penalty,
  CAST(missed_delivery_penalty AS DOUBLE) AS missed_delivery_penalty,
  CAST(avg_speed_mph AS DOUBLE) AS avg_speed_mph,
  CAST(circuity AS DOUBLE) AS circuity,
  source_system,
  CAST(is_inferred AS BOOLEAN) AS is_inferred,
  confidence_level,
  generated_run_id
FROM silver_cost_parameters;
