CREATE OR REFRESH STREAMING TABLE bronze_depot_master
COMMENT 'Raw synthetic depot master data from UC Volume.'
AS
SELECT *, current_timestamp() AS _ingested_at, _metadata.file_path AS _source_file
FROM STREAM read_files('${raw_path}/depot_master', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze_location_data
COMMENT 'Raw synthetic customer and location data from UC Volume.'
AS
SELECT *, current_timestamp() AS _ingested_at, _metadata.file_path AS _source_file
FROM STREAM read_files('${raw_path}/location_data', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze_fleet_assets
COMMENT 'Raw synthetic fleet asset data from UC Volume.'
AS
SELECT *, current_timestamp() AS _ingested_at, _metadata.file_path AS _source_file
FROM STREAM read_files('${raw_path}/fleet_assets', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze_drivers
COMMENT 'Raw synthetic driver availability and labor data from UC Volume.'
AS
SELECT *, current_timestamp() AS _ingested_at, _metadata.file_path AS _source_file
FROM STREAM read_files('${raw_path}/drivers', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze_customer_product_demand
COMMENT 'Raw synthetic customer demand data from UC Volume.'
AS
SELECT *, current_timestamp() AS _ingested_at, _metadata.file_path AS _source_file
FROM STREAM read_files('${raw_path}/fact_customer_product_demand', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze_delivery_orders
COMMENT 'Raw synthetic delivery order data from UC Volume.'
AS
SELECT *, current_timestamp() AS _ingested_at, _metadata.file_path AS _source_file
FROM STREAM read_files('${raw_path}/fact_delivery_orders', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze_cost_parameters
COMMENT 'Raw synthetic route cost parameters from UC Volume.'
AS
SELECT *, current_timestamp() AS _ingested_at, _metadata.file_path AS _source_file
FROM STREAM read_files('${raw_path}/cost_parameters', format => 'parquet');
