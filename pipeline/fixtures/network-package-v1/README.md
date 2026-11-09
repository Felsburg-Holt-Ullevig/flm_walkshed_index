# Authored network package example

Design fixture only; not a promoted release. The manifest example includes empty QA/GIS/notices descriptors that Task 5.2 must replace with actual validated files. Do not rename it to manifest.json and consume it as complete.

The expected-result.json file contains literal one-origin arithmetic: node 1 at 0 seconds, node 2 at 24.384 seconds, 100 feet on segment 0 plus 50 feet on segment 1, total 150 feet. Segment 1 is forward-only. Coordinates are WGS84 illustrations; lengths are declared metric fixture lengths. The source sha256 describes the literal UTF-8 bytes `literal-f01-v1: AB=100ft both; BC=100ft forward` (no newline), not an acquired OSM source. Code/config/rule hashes identify authored literal definitions, not an executed preparation run.

See the shared contract for direction, zero-budget and missing-origin companions, validation and acceptance status. No file in this directory changes the accepted Phase 4 reference fixture.
