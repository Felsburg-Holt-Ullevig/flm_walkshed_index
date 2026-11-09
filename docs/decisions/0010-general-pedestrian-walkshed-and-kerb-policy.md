# 0010. General pedestrian walkshed and kerb policy

Status: Accepted for experimental scope
Date: 2026-11-03

## Context

The initial conservative policy treated unlisted barriers as unknown. Kerb-tagged nodes therefore suppressed many sidewalk and crossing segments, including lowered and flush curbs. The primary analytical product is a simple pedestrian walkshed.

## Decision

Pedestrian policy 0.3 permits traversal of exact `barrier=kerb` nodes for the general pedestrian scenario. Kerb subtype and wheelchair tags alone do not prohibit that traversal or introduce costs. Explicit access restrictions, locked nodes, conditional restrictions and other applicable rules retain precedence.

Wheelchair-specific routing, ratings and accessibility documentation are outside the primary analytical scope. Retain available raw accessibility attributes without additional data collection or dedicated calculations. Existing attributes may be inspected as optional evidence. A dedicated wheelchair routing or rating method requires a separate scope and method decision. Application, interface and exported-document accessibility requirements continue to apply.

## Alternatives considered

- Treat all kerbs as unknown: retained unnecessary fragmentation for general pedestrian travel.
- Introduce a wheelchair routing profile now: outside the primary analytical scope and dependent on additional completeness and method decisions.
- Ignore every barrier: would remove meaningful physical and access restrictions.

## Consequences

Archive policy/configuration 0.2 and retain its generated evidence. Use distinct 0.3 rule/scenario identifiers, targeted tests and regenerated classification/graph/review artifacts. Compare the results without replacing prior expectations. General pedestrian permission does not establish safety, legal access or wheelchair accessibility. Other policy and coverage blockers remain; Gate 3 acceptance is separate.

## Revisit when

The scope explicitly adds a different travel profile, source evidence reveals a kerb-related pedestrian restriction requiring a new rule, or accepted benchmark review identifies an error in the general pedestrian interpretation.
