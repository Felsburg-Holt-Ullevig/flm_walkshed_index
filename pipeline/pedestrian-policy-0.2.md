# Provisional pedestrian policy

Version: `pedestrian-policy-0.2`. Scenario: `public-walk-experiment-0.2`.
Status: accepted for experimental use by the developer, November 3, 2026, with imperial units required. No evaluator or routing graph is implemented by this document. Gate 2 source inspection is accepted with its documented limitations. This policy does not establish legal permission, safety, accessibility, or approved CDOT methodology.

The companion [configuration](config/pedestrian-policy.example.toml) identifies the scenario and accepted experimental cost settings. This document is the rule authority; configuration must not introduce unreviewed overrides. A semantic rule change requires a new version and reviewed expectations. Existing source configuration, hashes, canonical data, and inspection products remain unchanged.

## Evaluation contract

Implement a pure Python evaluator in Task 3.2, independent of GIS, file access, environment, and global state. Inputs are validated canonical way ID, ordered node references, raw way tags, and referenced node IDs/tags. Evaluate each way once and each referenced node once; retain source references when producing consecutive-pair candidate records. Geometry validity and lengths are separate graph-builder checks. Preserve IDs as decimal strings and raw tags unchanged.

Return `rule_version`, `scenario_id`, source entity type/ID, `eligibility` (`include`, `exclude`, `unknown`), `direction` (`both`, `forward`, `reverse`, `none`, `unknown`), ordered `reason_codes`, `warnings`, and sidewalk evidence. Node output uses `pass`, `block`, or `unknown` rather than way eligibility/direction. No missing numeric cost becomes zero. Unexpected input types fail validation; unsupported but well-formed tag values produce audit evidence.

For comparisons, use exact, case-sensitive tag values as listed below. Empty values count as present but unsupported, never absent. No trimming, case folding, semicolon splitting, or guessed corrections. Missing keys alone mean absent. A key named below with an unrecognized value is unknown at its stage. Raw tags remain available for future interpretation.

## Ordered way rules

Apply these stages in order. Record every applicable reason and warning, but determine the final disposition with these precedence rules. Decisive exclusions remain exclusions even when another stage is unknown. Otherwise any unknown makes the result unknown; only all-supported stages allow inclusion. Direction is none for exclusions and unknown for unknown results. Maintain proposed direction separately in diagnostics if access prevents inclusion.

1. **Unsupported structure:** absent/empty/unknown highway class, `area=yes`, `indoor` other than absent or `no`, `level` when present, or any `conveying` tag makes the way unknown. Lifecycle classes listed below are excluded even with foot permission. `area=no` is supported; other area values are unknown. No polygon walking, elevators, indoor routing, escalator model, or inferred lifecycle conversion.
2. **Access:** use the foot/access table. Foot is more specific than generic access. Still retain overridden access tags in the audit.
3. **Highway default:** used only when neither foot nor access provides a supported permission/prohibition. Explicit permission can override a limited-access or cycleway default, but cannot override unsupported structure or lifecycle exclusion.
4. **Unresolved restrictions:** any nonempty or empty `foot:conditional`, `access:conditional`, `oneway:conditional`, or `oneway:foot:conditional` makes an otherwise included way unknown. No clock/date parser. `foot:forward`, `foot:backward`, or other unimplemented access/direction variants make it unknown. Report keys matching `foot:*`, `access:*`, `oneway:foot*`, `oneway:*:foot`, or containing `:conditional` as unsupported unless explicitly implemented here. Vehicle-only conditionals also remain conservatively unresolved in this initial experiment. Unrelated name/address/surface tags do not change eligibility.
5. **Pedestrian direction:** use the direction table below. Generic vehicle oneway does not control walking.

### Highway defaults

| Exact highway values | Default | Reason |
|---|---|---|
| footway, pedestrian, path, steps, living_street, residential, service, unclassified, track, road, tertiary, tertiary_link, secondary, secondary_link, primary, primary_link | include | H_DEFAULT_INCLUDE |
| motorway, motorway_link, trunk, trunk_link | exclude | H_LIMITED_ACCESS |
| cycleway, bridleway | unknown | H_FOOT_UNCONFIRMED |
| construction, proposed, abandoned, disused, razed | exclude, regardless of foot | H_LIFECYCLE |
| missing, empty, elevator, corridor, platform, busway, bus_guideway, escape, raceway, and all other values | unknown, regardless of foot | H_UNSUPPORTED |

These are experimental defaults, not jurisdictional access law. Inclusion of roads without sidewalk evidence and steps is a deliberate decision request. `highway=road` is retained as an uncertain physical classification warning `W_ROAD_CLASS`; it follows the stated inclusion default only if accepted. Bridge/tunnel/layer tags are preserved; they neither authorize access nor create geometric connections. Only shared source node IDs can connect, subject to node restrictions. No XY merging, crossing links, gap repair, or automatic sidewalk-to-road connectors.

### Access precedence

| Effective tag | Exact values | Result | Reason |
|---|---|---|---|
| foot, if present | yes, designated | permission | A_FOOT_ALLOW |
| foot, if present | permissive | permission plus W_REVOCABLE | A_FOOT_PERMISSIVE |
| foot, if present | no, private | exclude | A_FOOT_DENY |
| foot, if present | use_sidepath, destination, customers, delivery, agricultural, forestry, and any other value including empty | unknown | A_FOOT_UNSUPPORTED |
| access, only when foot absent | yes, designated | permission | A_ACCESS_ALLOW |
| access, only when foot absent | permissive | permission plus W_REVOCABLE | A_ACCESS_PERMISSIVE |
| access, only when foot absent | no, private | exclude | A_ACCESS_DENY |
| access, only when foot absent | destination, customers, delivery, agricultural, forestry, and any other value including empty | unknown | A_ACCESS_UNSUPPORTED |
| neither present | — | use highway default | A_DEFAULT |

Thus foot=yes overrides access=private in this scenario; foot=private overrides access=yes. Generic access permission also overrides the highway default, subject to structural checks. These choices require explicit experimental acceptance. `vehicle`, `motor_vehicle`, `bicycle`, and their mode-only restrictions do not establish walking permission. A permission does not suppress unresolved conditional restrictions.

### Direction

| Tags | Included way direction | Reason |
|---|---|---|
| oneway:foot absent | both | D_BOTH |
| oneway:foot=no | both | D_BOTH |
| oneway:foot=yes | forward along original ordered references | D_FORWARD |
| oneway:foot=-1 | reverse along original ordered references | D_REVERSE |
| any other oneway:foot value | unknown | D_UNSUPPORTED |

Ignore generic `oneway` and `junction=roundabout` for pedestrian direction, retaining `W_VEHICLE_ONEWAY_IGNORED` when either exists. Do not reverse source geometry or node order. Future graph edges reference the relevant original sequence and orientation.

## Node barriers and restrictions

Evaluate node access with the same foot/access precedence, but an absent access result is neutral. Evaluate conditionals/unsupported access variants as above. Barrier absent or `barrier=no` is pass unless node access excludes or is unknown. `bollard`, `cycle_barrier`, `entrance`, `gate`, `lift_gate`, `swing_gate`, `kissing_gate`, `stile`, `turnstile` are unknown without explicit supported permission. With supported permission they pass with `W_BARRIER_UNVERIFIED`. `wall`, `fence`, `hedge`, `retaining_wall`, `block`, `jersey_barrier` block even with permission. Every other barrier value, including empty, is unknown even with permission. Record B_PASS, B_ACCESS_BLOCK, B_PHYSICAL_BLOCK, B_PERMISSION_PASS, or B_UNRESOLVED as applicable. `locked=yes` at any node blocks; locked=no is supported; any other present value is unknown (B_LOCKED or B_LOCK_UNRESOLVED).

Node restrictions apply even without a barrier tag. A blocked node is unavailable as an origin, destination, or transit junction; conservatively suppress every incident candidate segment from routing. Unknown nodes similarly quarantine every incident segment and make that analysis incomplete. No automatic connection across a blocked node; approaching the barrier partway is not modeled in this first experiment. This conservative loss of terminal approach segments must be reported. Steps use the same proposed walking speed, with W_STEPS; this is not a wheelchair-accessible scenario. Width, surface, incline, wheelchair and kerb information is retained without accessibility claims or cost adjustments.

## Sidewalk evidence is separate from access

Emit independent fields, so contradictory evidence is not lost:

- `geometry_role`: sidewalk only for highway=footway and footway=sidewalk; crossing only for highway=footway and footway=crossing; other_pedestrian for footway/path/steps/pedestrian otherwise; cycleway for cycleway; other otherwise. Other uses of footway=sidewalk produce W_SIDEWALK_CONFLICT without asserting sidewalk geometry.
- `sidewalk_general`: absent → unknown; yes → present_unspecified; both → both; left/right → corresponding one-side; no/none → explicit_none; separate → separately_mapped_asserted; every other value including empty → unsupported.
- `sidewalk_left` and `sidewalk_right`: preserve side-specific values independently: absent → unknown, yes → present, no → explicit_none, separate → separately_mapped_asserted, other → unsupported. `sidewalk:both` uses the same value vocabulary and is retained independently. Contradictions between general/both/side fields produce W_SIDEWALK_CONFLICT; do not collapse them into a favorable category.

Unsupported sidewalk evidence alone does not make access unknown. `sidewalk=separate` is an assertion, not proof that a matching mapped path exists; no proximity matching or connectivity follows. `sidewalk=no` does not itself prohibit walking. A path or cycleway is not automatically a sidewalk. Crossing tags are descriptive evidence, not a delay or permission model. Audit totals report geometry roles and sidewalk fields separately; do not sum overlapping evidence categories into a coverage percentage.

## Candidate disposition, audit totals, and completeness

For each consecutive ordered reference pair, carry way result, both node results, geometry diagnostics and source sequence. A known exclusion/block dominates; otherwise an unknown input yields unknown; otherwise include. Zero geodesic length or same endpoint ID is excluded with G_ZERO_LENGTH (retained in audit); invalid/nonfinite/negative length or missing required reference fails the run. Retain parallel and duplicate source segments, with warnings, until separately reviewed. No deduplication by XY.

Task 3.2 can classify without geometry: emit way/node outputs and defer candidate length checks to Task 3.3. Report explicit not_run for these checks. Reconcile unique ways = included + excluded + unknown, and unique referenced nodes = pass + block + unknown. Later reconcile all ordered-pair candidates in the same three categories. Audit raw source IDs, input/config/rule hashes, counts by highway/reason/sidewalk fields, and separate unique candidate counts from nonexclusive reason counts. Count lengths once per source segment, not once per directed edge. Excluded and unknown records are never discarded from audit products.

An audit with unknowns may finish successfully as `classification_complete_with_unknowns`. It cannot produce a complete experimental walking analysis. A diagnostic graph may contain known included segments only, labeled `incomplete_unknown_policy`; do not label its reachable extent a complete walkshed. For this first version any unknown candidate in the selected routing subset blocks analytical promotion, even if apparently distant from the station. Unsupported relation interpretation is also explicit: retain touching route/restriction evidence; a relation tagged restriction:foot or restriction:foot:conditional, or type=restriction whose except tag does not contain the exact semicolon-delimited token foot, blocks complete routing pending review (R_UNSUPPORTED). Route membership never supplies access. Relation checks are integration checks in Task 3.3, not guessed turn restrictions in the pure evaluator. Other unresolved relation members remain coverage warnings; no relation completeness claim.

## Proposed units and cost scenario

Use international feet for graph lengths, miles for longer distances, miles per hour for speed, and seconds for computation (minutes for displayed travel budgets). Use square feet/acres/square miles for future area presentation; later area methods remain separately subject to approval. User-facing settings, reports, examples, new derived graph fields and tests use these units. Geographic coordinates retain their declared CRS/angular units; do not relabel coordinates as feet.

Preserve the previously agreed speed exactly through conversion: speed_mph = 4500 / 1609.344, approximately 2.796170365068003 mph (display about 2.8 mph). Do not calculate from the rounded display value. The international mile is exactly 5,280 international feet; one international foot is exactly 0.3048 meters. At the existing GIS adapter boundary, convert the recorded geodesic source length with length_ft = source_length_m / 0.3048. Existing canonical files, inspection fields and historical evidence remain in their original declared units and unchanged. No silent relabeling or reinterpretation of source fields, and no US survey-foot conversion.

For an eligible directed segment, base_seconds = length_ft * 3600 / (speed_mph * 5280). Independent examples: 328.0839895013123 ft takes 80 s; 1230.3149606299212 ft takes 300 s. Require finite positive speed and finite nonnegative lengths. Conversion checks use a relative tolerance of 1e-12 and absolute tolerance of 1e-9 feet or seconds, whichever is larger. Steps use the same expression with an explicit limitation. No slope, surface, gate-opening, stair, or turn cost is modeled.

Crossing delays are **deferred/not modeled**, not measured zero. Record crossing_delay_model=not_modeled and label times as distance-derived base travel time. A future approved delay scenario needs a new version. Access connectors are disabled: initial routing origins must be explicitly verified source node IDs. Do not silently snap, inject a zero-cost connector, or adopt the reference tool's 500 m tolerance. If connectors are later accepted, require reviewed geometry/access and charge their geodesic length converted to feet using the expression above; implementation and maximum distance remain deferred to Task 4.1. Partial-edge reachability also belongs to that reviewed routing specification.

## Exact acceptance examples

Unless shown otherwise: highway=residential, no other tags, endpoint nodes unrestricted, positive length. I/E/U mean include/exclude/unknown. Direction is both for I unless specified; none for E; unknown for U. Sidewalk fields default unknown and geometry_role other.

| ID | Changed tags or condition | Expected |
|---|---|---|
| P01 | baseline | I; H_DEFAULT_INCLUDE, A_DEFAULT, D_BOTH |
| P02 | highway=motorway | E; H_LIMITED_ACCESS |
| P03 | highway=trunk, foot=yes | I; A_FOOT_ALLOW |
| P04 | foot=no, access=yes | E; A_FOOT_DENY |
| P05 | foot=yes, access=private | I; A_FOOT_ALLOW |
| P06 | access=private | E; A_ACCESS_DENY |
| P07 | foot=permissive | I; A_FOOT_PERMISSIVE; W_REVOCABLE |
| P08 | access=destination | U; A_ACCESS_UNSUPPORTED |
| P09 | foot=use_sidepath | U; A_FOOT_UNSUPPORTED |
| P10 | foot=YES or empty string (two tests) | U; A_FOOT_UNSUPPORTED |
| P11 | foot=yes, access:conditional=no @ (Mo-Fr) | U; conditional unresolved |
| P12 | highway=cycleway, then same plus foot=designated (two tests) | U, then I; geometry_role cycleway |
| P13 | highway=path | I; other_pedestrian, no sidewalk assertion |
| P14 | highway=steps | I; W_STEPS |
| P15 | highway=construction, foot=yes | E; H_LIFECYCLE |
| P16 | highway missing, then highway=unknown (two tests), foot=yes | U; H_UNSUPPORTED |
| P17 | area=yes, foot=yes | U; S_UNSUPPORTED_STRUCTURE |
| P18 | oneway=yes, junction=roundabout | I both; W_VEHICLE_ONEWAY_IGNORED |
| P19 | oneway:foot=yes | I forward; D_FORWARD |
| P20 | oneway:foot=-1 | I reverse; D_REVERSE |
| P21 | oneway:foot=no, oneway=yes | I both |
| P22 | foot:forward=no, then oneway:foot=true (two tests) | U; unsupported variant, then D_UNSUPPORTED |
| P23 | endpoint barrier=gate without permission | U; B_UNRESOLVED |
| P24 | endpoint barrier=gate, foot=yes | I; B_PERMISSION_PASS; W_BARRIER_UNVERIFIED |
| P25 | endpoint barrier=wall, foot=yes | E; B_PHYSICAL_BLOCK |
| P26 | endpoint barrier=bollard, foot=yes, locked=yes | E; B_LOCKED |
| P27 | endpoint foot=no without barrier | E; B_ACCESS_BLOCK |
| P28 | sidewalk=no | I; explicit_none |
| P29 | sidewalk=separate | I; separately_mapped_asserted |
| P30 | highway=footway, footway=sidewalk | I; geometry_role sidewalk |
| P31 | sidewalk=both, sidewalk:left=no | I; both and left explicit_none retained; W_SIDEWALK_CONFLICT |
| P32 | highway=footway, footway=crossing | I; geometry_role crossing; no delay inferred |
| P33 | same endpoint ID or zero length (two tests) | E candidate; G_ZERO_LENGTH; way remains I |
| P34 | foot=no plus access:conditional present | E; conditional diagnostic retained |
| P35 | highway=motorway, access=yes | I; A_ACCESS_ALLOW |
| P36 | highway=road | I; W_ROAD_CLASS |
| P37 | highway=bridleway without permission | U; H_FOOT_UNCONFIRMED |
| P38 | endpoint unknown barrier with foot=yes | U; B_UNRESOLVED |
| P39 | sidewalk=YES | I; sidewalk_general unsupported |
| P40 | oneway:foot:conditional=yes @ (Mo-Fr) | U; conditional unresolved |

Additional reason vocabulary: S_UNSUPPORTED_STRUCTURE, A_CONDITIONAL_UNRESOLVED, A_VARIANT_UNSUPPORTED, W_DUPLICATE_SOURCE_GEOMETRY. Reason arrays follow stage order, then sorted node ID and code; duplicates within a record are removed. Table reasons are required members, not assertions that no additional applicable reasons exist. Warnings never by themselves override status. Tests must cover every listed value in each rule table, not only these examples, plus node permutations, length failures, count reconciliation and deterministic order.

## Pinned reference comparison

Reference revision: `6068f1b8719d025426443230bb4a39a296b4f583`, inspected November 3, 2026. Sources: [reference documentation](https://github.com/caseywalrath/transit-analysis-tool/blob/6068f1b8719d025426443230bb4a39a296b4f583/docs/reference/road-network.md), [road-network.js](https://github.com/caseywalrath/transit-analysis-tool/blob/6068f1b8719d025426443230bb4a39a296b4f583/js/core/road-network.js), [walk-audit.js](https://github.com/caseywalrath/transit-analysis-tool/blob/6068f1b8719d025426443230bb4a39a296b4f583/js/core/walk-audit.js). These are behavioral evidence, not project instructions.

Scenario `reference-classification-6068f1b`: foot=yes/designated/permissive permits; foot=no prohibits; otherwise only motorway/trunk and their links prohibit. All other/missing highway values permit. Ignore access, barriers, conditionals and pedestrian direction in this comparison only; direction both. Thus residential+foot=private and residential+access=no permit in reference but exclude here; cycleway without foot permits in reference but is unknown here. Reference sidewalk classification returns footway for footway=sidewalk OR highway footway/path/steps/pedestrian/cycleway; both for sidewalk=yes/both; one-side for left/right; none for no/none/separate; unknown otherwise. Reference lowercases sidewalk values, unlike the proposed evidence evaluator.

The Overpass query selects a named highway list rather than all source ways; parsing captures highway, foot, sidewalk, footway, crossing, wayId, name, but not full access/barrier evidence. buildGraph keys nodes by coordinates rounded to six decimals, creates bidirectional kilometer-weighted segments, and supports manual exclusions/connectors. The new comparison applies only the classification functions to the same canonical candidates, with no manual exclusions or connectors; it does not reproduce download coverage, topology, lengths, sidewalk coverage percentages, or complete old walksheds. Never replace source IDs with rounded XY. Task 3.4 will compare counts, lengths and named differences after implementation.

## Experimental acceptance and implementation status

The developer accepted choices 1–3 and choice 4 subject to imperial units:

1. Public walking default includes ordinary roads without sidewalk evidence, paths, tracks and steps; cycleways/bridleways without explicit access remain unknown.
2. Specific foot permission overrides generic access restrictions; generic permission can override limited-access class defaults. Private/no exclude, permissive includes with warning, destination/customer/conditional cases remain unknown.
3. Conservative barrier handling suppresses incident segments; unresolved cases block complete routing. No conditional parser, indoor routing, relation turn model, snapping, or invented connections.
4. Base speed approximately 2.8 mph, preserving the exact agreed speed through the conversion above; no crossing/stair/slope delays modeled; initial origins are verified source nodes. Results remain experimental distance-derived travel times.

Acceptance record: November 3, 2026. The developer replied “Agreed” to choices 1–3 and “We should use imperial units in all instances. Agreed otherwise.” to choice 4. This accepts `pedestrian-policy-0.2` / `public-walk-experiment-0.2` for experimental use. Version 0.2 supersedes the unimplemented 0.1 draft for the units requirement. This does not approve authoritative scoring or publication.

Task 3.1 is complete. Task 3.2 implements the pure evaluator in `pipeline/src/flm_pipeline/pedestrian_policy.py` and the canonical-source audit adapter in `pipeline/src/flm_pipeline/classification.py`. The `classify` command preserves all ways, unique referenced nodes, and ordered-pair candidates in JSONL; it reports raw conditional tags without parsing them and reconciles counts by highway, reason, and sidewalk evidence. Candidate geometry checks, graph assembly, relation restriction interpretation, and routing remain `not_run`. The outputs are experimental classification evidence, not an authoritative method or completed walkshed.
