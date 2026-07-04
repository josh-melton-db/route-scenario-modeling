from __future__ import annotations

from textwrap import dedent


def metric_view_sql(catalog: str, schema: str) -> list[str]:
    prefix = f"{catalog}.{schema}"
    return [
        dedent(
            f"""
            CREATE OR REPLACE VIEW {prefix}.mv_route_performance
            WITH METRICS
            LANGUAGE YAML
            AS $$
              version: 1.1
              source: {prefix}.scenario_kpis
              comment: "Certified route performance metrics by scenario, depot, and delivery day."
              dimensions:
                - name: Scenario
                  expr: scenario_id
                  comment: "Scenario identifier"
                - name: Depot
                  expr: depot_id
                  comment: "Depot identifier"
                - name: Delivery Day
                  expr: delivery_day
                  comment: "Delivery weekday"
              measures:
                - name: Route Count
                  expr: SUM(route_count)
                  comment: "Number of routes in the plan"
                  synonyms: ["routes", "route count"]
                - name: Total Miles
                  expr: SUM(total_miles)
                  comment: "Total route miles"
                  synonyms: ["miles", "distance"]
                - name: Total Cost
                  expr: SUM(total_cost)
                  comment: "Total route operating cost"
                  synonyms: ["cost", "operating cost"]
            $$
            """
        ).strip(),
        dedent(
            f"""
            CREATE OR REPLACE VIEW {prefix}.mv_scenario_comparison
            WITH METRICS
            LANGUAGE YAML
            AS $$
              version: 1.1
              source: {prefix}.scenario_comparison_summary
              comment: "Certified baseline-vs-scenario KPI deltas for route optimization."
              dimensions:
                - name: Scenario
                  expr: scenario_id
                  comment: "Scenario identifier"
                - name: Scenario Type
                  expr: scenario_type
                  comment: "Business scenario type"
                - name: Depot
                  expr: depot_id
                  comment: "Depot identifier"
              measures:
                - name: Cost Delta
                  expr: SUM(total_cost_delta)
                  comment: "Scenario cost minus baseline cost"
                  synonyms: ["cost change", "savings", "cost delta"]
                - name: Miles Delta
                  expr: SUM(total_miles_delta)
                  comment: "Scenario miles minus baseline miles"
                  synonyms: ["miles change", "distance delta"]
                - name: Impacted Customers
                  expr: SUM(impacted_customer_count)
                  comment: "Customers with route, day, sequence, or service impact"
                  synonyms: ["affected customers", "customer impact"]
            $$
            """
        ).strip(),
        dedent(
            f"""
            CREATE OR REPLACE VIEW {prefix}.mv_customer_service_impact
            WITH METRICS
            LANGUAGE YAML
            AS $$
              version: 1.1
              source: {prefix}.scenario_customer_impact
              comment: "Certified customer-level service impact metrics for scenario comparison."
              dimensions:
                - name: Scenario
                  expr: scenario_id
                  comment: "Scenario identifier"
                - name: Customer
                  expr: customer_name
                  comment: "Customer account"
                - name: Window Risk
                  expr: window_risk
                  comment: "Service-window risk classification"
              measures:
                - name: Impacted Customers
                  expr: COUNT(DISTINCT customer_id)
                  comment: "Distinct customers impacted"
                - name: Average Disruption Score
                  expr: AVG(disruption_score)
                  comment: "Average normalized customer disruption score"
            $$
            """
        ).strip(),
        dedent(
            f"""
            CREATE OR REPLACE VIEW {prefix}.mv_fleet_capacity_utilization
            WITH METRICS
            LANGUAGE YAML
            AS $$
              version: 1.1
              source: {prefix}.optimized_route_metrics
              comment: "Certified fleet and capacity utilization metrics by route."
              dimensions:
                - name: Scenario
                  expr: scenario_id
                  comment: "Scenario identifier"
                - name: Depot
                  expr: depot_id
                  comment: "Depot identifier"
                - name: Delivery Day
                  expr: delivery_day
                  comment: "Delivery weekday"
              measures:
                - name: Average Capacity Utilization
                  expr: AVG(capacity_utilization_pct)
                  comment: "Average route capacity utilization percentage"
                - name: Average Driver Utilization
                  expr: AVG(driver_utilization_pct)
                  comment: "Average driver utilization percentage"
                - name: Overtime Minutes
                  expr: SUM(overtime_minutes)
                  comment: "Total overtime minutes"
            $$
            """
        ).strip(),
        dedent(
            f"""
            CREATE OR REPLACE VIEW {prefix}.mv_depot_network_health
            WITH METRICS
            LANGUAGE YAML
            AS $$
              version: 1.1
              source: {prefix}.scenario_kpis
              comment: "Certified depot network health metrics across scenarios."
              dimensions:
                - name: Depot
                  expr: depot_id
                  comment: "Depot identifier"
                - name: Delivery Day
                  expr: delivery_day
                  comment: "Delivery weekday"
              measures:
                - name: Missed Windows
                  expr: SUM(missed_windows)
                  comment: "Total missed service windows"
                - name: Late Minutes
                  expr: SUM(late_minutes)
                  comment: "Total late delivery minutes"
                - name: Total Cases
                  expr: SUM(total_cases)
                  comment: "Total delivered cases"
            $$
            """
        ).strip(),
    ]


def certification_sql(catalog: str, schema: str) -> list[str]:
    return [
        f"ALTER VIEW {catalog}.{schema}.{name} SET TAGS ('certified' = 'true')"
        for name in [
            "mv_route_performance",
            "mv_scenario_comparison",
            "mv_customer_service_impact",
            "mv_fleet_capacity_utilization",
            "mv_depot_network_health",
        ]
    ]
