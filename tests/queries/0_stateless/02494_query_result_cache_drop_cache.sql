-- Tags: no-parallel
-- Tag no-parallel: Messes with internal cache

SET allow_experimental_query_result_cache = true;

-- Cache query result in query result cache
SELECT 1 SETTINGS use_query_result_cache = true;
SELECT count(*) FROM system.query_result_cache;

-- No query results are cached after DROP
SYSTEM DROP QUERY RESULT CACHE;
SELECT count(*) FROM system.query_result_cache;
