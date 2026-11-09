# Domain boundary

Place authoritative walking-cost, spatial aggregation, normalization, and scoring logic here when introduced. Keep it independent of React, the DOM, map engines, storage, and external service response formats. Use explicit validated inputs and structured results/errors. Units and method/data versions must be documented.

No analytical implementation or approved benchmark exists in the foundation. Add meaningful independent/unit fixtures alongside the first calculation. See [methodology](../../docs/methodology.md) and [validation](../../docs/validation.md).

Implemented: `reachability.ts` performs source-node shortest paths and source-oriented interval union on explicit feet/seconds inputs. It has no browser or adapter dependencies. `reachability.test.ts` checks literal expectations; adapter tests also compare four accepted Python references. Worker coordination belongs outside this directory.


`allocation.ts` implements experimental area/representative-point weights, nullable additive totals, paired household rates and unique-union bookkeeping. Geometry measurements and source-format validation are adapter responsibilities; this module imports no GIS, browser, storage or service code. Derived uncertainty remains unquantified.
