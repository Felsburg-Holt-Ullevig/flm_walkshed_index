# Larimer inclusive-road pilot authority

This local experimental profile is for the `larimer-inclusive-road-pilot-v1`
comparison only. It is not the default pedestrian policy and is not an
authoritative statewide methodology.

The profile adds default inclusion for `highway=trunk`, recording
`H_TRUNK_ASSUMED_WALKABLE` when no explicit access decision overrides it.
`highway=motorway`, `highway=motorway_link`, and `motorroad=yes` are excluded
with `H_LIMITED_ACCESS` or `H_MOTORROAD_EXCLUDE`, including when generic or
pedestrian access tags would otherwise permit them. Trunk links retain the
baseline ramp behavior. All other access, barrier, direction, geometry,
sidewalk-evidence, and source-node rules remain unchanged.
