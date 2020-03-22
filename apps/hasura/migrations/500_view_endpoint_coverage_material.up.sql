CREATE MATERIALIZED VIEW "public"."endpoint_coverage_material" AS
 SELECT DISTINCT
   bjs.job_timestamp::date as date,
   ao.bucket as bucket,
   ao.job as job,
   ao.operation_id as operation_id,
   ao.level,
   ao.category,
   ao.k8s_group as group,
   ao.k8s_kind as kind,
   ao.k8s_version as version,
   EXISTS (
     select *
       from audit_event
      where audit_event.operation_id = ao.operation_id
        AND audit_event.bucket = ao.bucket
        AND audit_event.job = ao.job
        AND audit_event.useragent like 'e2e.test%') as tested,
   EXISTS (
     select *
       from audit_event
      where audit_event.operation_id = ao.operation_id
        AND audit_event.bucket = ao.bucket
        AND audit_event.job = ao.job
        AND audit_event.useragent like '%[Conformance]%') as conf_tested,
   EXISTS (
     select *
       from audit_event
      where audit_event.operation_id = ao.operation_id
        AND audit_event.bucket = ao.bucket
        AND audit_event.job = ao.job) as hit
   FROM api_operation_material ao
          LEFT JOIN bucket_job_swagger bjs ON (ao.bucket = bjs.bucket AND ao.job = bjs.job)
     WHERE ao.deprecated IS False and ao.job != 'live'
   GROUP BY ao.operation_id, ao.bucket, ao.job, date, ao.level, ao.category, ao.k8s_group, ao.k8s_kind, ao.k8s_version;

CREATE INDEX idx_endpoint_coverage_material_bucket             ON endpoint_coverage_material                       (bucket);
CREATE INDEX idx_endpoint_coverage_material_job                ON endpoint_coverage_material                          (job);
CREATE INDEX idx_endpoint_coverage_material_operation_id       ON endpoint_coverage_material                 (operation_id);
