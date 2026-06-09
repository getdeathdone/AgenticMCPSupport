# VPN Troubleshooting Runbook

## Symptoms

Users report that VPN login fails, MFA completes but the tunnel does not connect, or the client times out during SAML authentication.

## First Checks

Check the current VPN service status and known incidents before asking the user to reinstall the client. If VPN is degraded, tell the user there is an active service issue and reference the incident summary.

## User Steps

Ask the user to confirm MFA approval, restart the VPN client, retry from a different network, and capture the exact error message. If the issue continues, collect the device hostname and user email for endpoint diagnostics.

## Escalation

Escalate to Infrastructure when multiple users are affected, authentication latency is elevated, or SAML errors appear after successful MFA.
