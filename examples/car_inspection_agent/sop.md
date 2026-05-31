# Vehicle Inspection Report

The Cars24 "Jockey Copilot" inspection, re-expressed as a plain SOP. What used to
be a bespoke app (workflow engine + vision QA + report generator) collapses to
this SOP + an output schema + config. Vision-centric: the agent captures each
angle, extracts damage with confidence, validates evidence quality, then pauses
for a valuation change and the final submit.

## Exterior
- Capture the front of the vehicle including bumper, grille, and headlights [vision] [evidence: front_photo] [produces: front]
- Capture the rear of the vehicle including the boot and tail lights [vision] [evidence: rear_photo] [produces: rear]
- Capture the left side panels, doors, and mirror [vision] [evidence: left_photo] [produces: left_side]
- Capture the right side panels, doors, and mirror [vision] [evidence: right_photo] [produces: right_side]

## Wheels
- Inspect and photograph each tyre tread and sidewall [vision] [evidence: tyre_photo] [produces: tyres] [validate: tread_depth_mm >= 2]

## Interior
- Capture the dashboard, seats, and odometer reading [vision] [evidence: interior_photo] [produces: interior]

## Engine Bay
- Open the bonnet and capture the engine bay and fluid levels [vision] [evidence: engine_photo] [produces: engine_bay] [min_confidence: 0.7]

## Valuation
- Apply damage-based valuation adjustments to the listing price [review: valuation_change] [produces: valuation]

## Submit
- Submit the final inspection report to pricing and QC [reason] [review: final_submit] [produces: final_report]
