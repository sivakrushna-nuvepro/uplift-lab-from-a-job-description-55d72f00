# Build and maintain batch ingestion pipelines in Python and Airflow to load daily claims and policy files from insurer SFTP drops into the BigQuery landing zone.

Simulation 1
1. Review fixtures/candidate_brief.json and fixtures/recovery_evidence.json to understand the failed run, delivery manifest, privacy policy, and refresh deadline.
2. Inspect fixtures/insurer_zenith_claims_20250214_partial.csv and fixtures/insurer_zenith_claims_redelivery.csv to distinguish the incomplete delivery from the complete redelivery.
3. Use claims_pipeline/recovery.py to build the privacy-safe recovery decision record from the supplied evidence and redelivery rows.
4. Review sql/curated_claims.sql for the requested curated model transformation.
5. Run python -m unittest discover -s tests -v from the repository root.

Assessment 1
1. Review the candidate scenario in fixtures/candidate_brief.json and the recorded incident evidence in fixtures/recovery_evidence.json.
2. Inspect the complete delivery in fixtures/insurer_zenith_claims_redelivery.csv and its compatibility alias fixtures/zenith_claims_20250214_redelivery.csv.
3. Compare the partial transfer in fixtures/insurer_zenith_claims_20250214_partial.csv and its compatibility alias fixtures/zenith_claims_20250214_partial.csv.
4. Build the privacy-safe recovery record by calling claims_pipeline.recovery.build_decision_record.
5. Run sql/curated_claims.sql to deduplicate claims by latest ingestion and derive the requested amount bucket without projecting direct member identifiers.
6. Validate the solution with python -m unittest discover -s tests -p 'test_*.py'.
