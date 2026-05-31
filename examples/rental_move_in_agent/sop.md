# Rental Move-In Condition Report

A relatable voice + vision SOP. As the tenant and agent walk the unit, the agent
photographs each area (vision) and asks the tenant to confirm condition (voice).
The output is a deposit-ready condition report; every claim is backed by a photo
or the tenant's spoken confirmation. The agent pauses before submitting.

## Living Room
- Photograph the living room walls, floor, and ceiling [vision] [evidence: living_room_photo] [produces: living_room]
- Ask the tenant about any pre-existing damage in the living room [voice] [produces: living_room_notes]

## Kitchen
- Photograph the kitchen appliances and countertops [vision] [evidence: kitchen_photo] [produces: kitchen]
- Ask the tenant to confirm the appliances are in working condition [voice] [produces: kitchen_notes]

## Bathroom
- Photograph the bathroom fixtures and check for visible leaks [vision] [evidence: bathroom_photo] [produces: bathroom]

## Utility Meters
- Read and photograph the electricity and water meters [vision] [evidence: meter_photo] [produces: meters]
- Ask the tenant to verbally verify the meter readings [voice] [produces: meter_confirmation]

## Finalize
- Submit the move-in condition report for the deposit record [review: final_submit] [produces: condition_report]
