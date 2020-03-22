CREATE OR REPLACE VIEW "public"."projected_change_in_coverage" AS
 WITH baseline AS (
   SELECT *
     FROM
         stable_endpoint_stats
    WHERE job != 'live'
 ), test AS (
   SELECT
     COUNT(1) AS endpoints_hit
     FROM
         (
           SELECT
             operation_id
     FROM audit_event
      WHERE useragent like 'live-test%'
     EXCEPT
     SELECT
       operation_id
     FROM
         endpoint_coverage
         WHERE tested is true
               ) tested_endpoints
 ), coverage AS (
   SELECT
   baseline.test_hits AS old_coverage,
   (baseline.test_hits::int + test.endpoints_hit::int) AS new_coverage
   FROM baseline, test
 )
 SELECT
   'test_coverage' AS category,
   baseline.total_endpoints,
   coverage.old_coverage,
   coverage.new_coverage,
   (coverage.new_coverage - coverage.old_coverage) AS change_in_number
   FROM baseline, coverage
          ;
