CREATE OR REFRESH STREAMING TABLE silver_depot_master (
  CONSTRAINT valid_depot_id EXPECT (depot_id IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT valid_depot_coordinates EXPECT (lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180) ON VIOLATION DROP ROW
)
COMMENT 'Typed and quality-checked synthetic depot master.'
AS
SELECT * FROM STREAM bronze_depot_master;

CREATE OR REFRESH STREAMING TABLE silver_location_data (
  CONSTRAINT valid_customer_id EXPECT (customer_id IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT valid_customer_coordinates EXPECT (lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180) ON VIOLATION DROP ROW,
  CONSTRAINT valid_service_minutes EXPECT (service_minutes > 0) ON VIOLATION DROP ROW
)
COMMENT 'Typed and quality-checked synthetic customer locations and service rules.'
AS
SELECT * FROM STREAM bronze_location_data;

CREATE OR REFRESH STREAMING TABLE silver_fleet_assets (
  CONSTRAINT valid_vehicle_id EXPECT (vehicle_id IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT valid_vehicle_capacity EXPECT (capacity_cases > 0) ON VIOLATION DROP ROW
)
COMMENT 'Typed and quality-checked synthetic fleet assets.'
AS
SELECT * FROM STREAM bronze_fleet_assets;

CREATE OR REFRESH STREAMING TABLE silver_drivers (
  CONSTRAINT valid_driver_id EXPECT (driver_id IS NOT NULL) ON VIOLATION FAIL UPDATE
)
COMMENT 'Typed and quality-checked synthetic driver availability.'
AS
SELECT * FROM STREAM bronze_drivers;

CREATE OR REFRESH STREAMING TABLE silver_customer_product_demand (
  CONSTRAINT valid_demand_customer EXPECT (customer_id IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT valid_expected_cases EXPECT (expected_cases >= 0) ON VIOLATION DROP ROW
)
COMMENT 'Typed and quality-checked synthetic customer demand.'
AS
SELECT * FROM STREAM bronze_customer_product_demand;

CREATE OR REFRESH STREAMING TABLE silver_delivery_orders (
  CONSTRAINT valid_order_id EXPECT (order_id IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT valid_delivery_cases EXPECT (demand_cases >= 0) ON VIOLATION DROP ROW
)
COMMENT 'Typed and quality-checked synthetic delivery orders.'
AS
SELECT * FROM STREAM bronze_delivery_orders;

CREATE OR REFRESH STREAMING TABLE silver_cost_parameters (
  CONSTRAINT valid_cost_parameter_set EXPECT (parameter_set_id IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT valid_costs EXPECT (cost_per_mile > 0 AND labor_regular_hour > 0) ON VIOLATION DROP ROW
)
COMMENT 'Typed and quality-checked synthetic route cost parameters.'
AS
SELECT * FROM STREAM bronze_cost_parameters;
