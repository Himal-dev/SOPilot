# Plant Health Check

A single-plant care SOP. The agent captures a guided shot list (whole plant, then
a close-up of affected leaves), asks the gardener one spoken question about care
habits, diagnoses the likely cause, prepares a care plan, and pauses for approval
before submitting. Every finding is backed by a photo or the spoken answer.

## Identify
- Capture the whole plant in frame [vision] [evidence: whole_plant_photo] [produces: plant]

## Examine
- Capture a close-up of the affected leaves or stems [vision] [evidence: closeup_photo] [produces: symptoms] [min_confidence: 0.6]

## Interview
- Ask the gardener about care habits and recent changes [voice] [evidence: care_habits_audio] [produces: care_habits] [ask: What is your watering routine?; What light and location does the plant get?; Does the pot have drainage and what is the soil like?; Any recent changes or signs of pests such as fertilizer repotting moves or drafts?]

## Diagnose
- Determine the likely cause from the symptoms and care habits [reason] [produces: diagnosis]

## Care Plan
- Prepare a care plan for the gardener [reason] [produces: care_plan]

## Finalize
- Submit the plant care report for the gardener [reason] [review: final_submit] [produces: care_report]
