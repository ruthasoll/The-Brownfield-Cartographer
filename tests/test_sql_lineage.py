from src.analyzers.sql_lineage import SQLLineageAnalyzer

def test_sql_lineage():
    analyzer = SQLLineageAnalyzer(dialect="postgres")
    sql = """
    CREATE TABLE final_report AS
    SELECT 
        c.customer_id,
        o.order_date,
        p.amount
    FROM raw_customers c
    JOIN raw_orders o ON c.customer_id = o.customer_id
    JOIN raw_payments p ON o.order_id = p.order_id
    WHERE p.status = 'successful'
    """
    transformations = analyzer.extract_lineage(sql, "test.sql")
    
    if not transformations:
        print("FAIL: No transformations extracted")
        return

    trans = transformations[0]
    print(f"Transformation: {trans.name}")
    print(f"Sources: {trans.source_datasets}")
    print(f"Targets: {trans.target_datasets}")

    expected_sources = {"raw_customers", "raw_orders", "raw_payments"}
    expected_targets = {"final_report"}

    if set(trans.source_datasets) == expected_sources and set(trans.target_datasets) == expected_targets:
        print("PASS: SQL lineage extraction verified")
    else:
        print(f"FAIL: Extraction mismatch. Got Sources: {trans.source_datasets}, Targets: {trans.target_datasets}")

if __name__ == "__main__":
    test_sql_lineage()
