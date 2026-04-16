param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$Region,

    [Parameter(Mandatory = $true)]
    [string]$ServiceUrl,

    [Parameter(Mandatory = $true)]
    [string]$OidcServiceAccount,

    [Parameter(Mandatory = $false)]
    [string]$TimeZone = "Europe/Copenhagen",

    [Parameter(Mandatory = $false)]
    [string]$JobTriggerToken = ""
)

$endpoint = "$ServiceUrl/jobs/run-digest"
$headers = "Content-Type=application/json"
if ($JobTriggerToken -ne "") {
    $headers = "$headers,X-Job-Trigger-Token=$JobTriggerToken"
}

# Initial trigger at 06:30 local time.
gcloud scheduler jobs create http newsletter-pod-initial `
  --project=$ProjectId `
  --location=$Region `
  --schedule="30 6 * * *" `
  --time-zone=$TimeZone `
  --uri=$endpoint `
  --http-method=POST `
  --headers=$headers `
  --message-body='{"force": false}' `
  --oidc-token-audience=$ServiceUrl `
  --oidc-service-account-email=$OidcServiceAccount

# Rapid retry window: every 5 minutes from 06:35 to 06:59.
gcloud scheduler jobs create http newsletter-pod-rapid-retry `
  --project=$ProjectId `
  --location=$Region `
  --schedule="35-59/5 6 * * *" `
  --time-zone=$TimeZone `
  --uri=$endpoint `
  --http-method=POST `
  --headers=$headers `
  --message-body='{"force": false}' `
  --oidc-token-audience=$ServiceUrl `
  --oidc-service-account-email=$OidcServiceAccount

# Periodic retries every 30 minutes from 07:00 to 23:00.
gcloud scheduler jobs create http newsletter-pod-periodic-retry `
  --project=$ProjectId `
  --location=$Region `
  --schedule="0,30 7-23 * * *" `
  --time-zone=$TimeZone `
  --uri=$endpoint `
  --http-method=POST `
  --headers=$headers `
  --message-body='{"force": false}' `
  --oidc-token-audience=$ServiceUrl `
  --oidc-service-account-email=$OidcServiceAccount
