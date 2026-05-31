# Support Runbook: Payment Failure Triage

This SOP triages a "payment failed at checkout" support ticket. It is headless
(no camera/microphone): it works entirely through MCP tools and pauses for a
human before any message is sent to the customer.

## Intake
- Look up the customer order in the CRM [tool: crm_lookup] [produces: order]
- Fetch the latest payment status from the payments API [tool: payment_status] [produces: payment]

## Diagnose
- Check the service status dashboard for active incidents [tool: status_check] [produces: incident] [decision: incident_active -> prepare_incident_reply | prepare_standard_fix]
- Search the knowledge base for the matching error code [tool: kb_search] [produces: kb]

## Branch
- Prepare incident reply [produces: incident_reply]
- Prepare standard fix [produces: standard_fix]

## Resolve
- Send the resolution response to the customer [review: customer_response] [produces: response]
- Update the ticket with the resolution and close it [tool: ticket_update] [produces: ticket]
