# Azure DevOps — DSG Verified Execution

Status: **preview package in repository; not published to Azure DevOps Marketplace**.

This extension is a distribution surface for the existing DSG ONE service. It does not create a second billing ledger and it does not treat Azure DevOps as the merchant of record.

## Customer path

```text
Azure DevOps Marketplace
  -> install DSG Verified Execution extension
  -> configure DSG_API_KEY as a secret pipeline variable
  -> configure a bounded verification request file
  -> enable DSG_VERIFY_ENABLED=true
  -> Azure Pipeline calls production /verify/evaluate
  -> pipeline shows ALLOW / REVIEW / BLOCK + proof hash
  -> product / upgrade surface: https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/app
```

## Billing boundary

Azure DevOps paid extensions use BYOL: the publisher supplies licensing and billing. The manifest therefore carries both the `Paid` gallery flag and the `__BYOLENFORCED` tag. DSG billing and entitlement remain owned by the existing Cinema revenue service rather than Azure DevOps.

The extension must never create a separate Stripe customer, usage ledger, or proof charge. A customer obtained through Azure DevOps is still entitled and metered by the same DSG backend used by Direct API and other channels.

## Pipeline variables

- `DSG_VERIFY_ENABLED`: set to `true` to enforce verification. Default/unset is a no-op so installing the extension alone cannot unexpectedly break existing pipelines.
- `DSG_API_KEY`: secret DSG key. Required when verification is enabled.
- `DSG_VERIFICATION_REQUEST_PATH`: path to the bounded JSON request in the checked-out workspace.
- `DSG_API_BASE`: optional override. Production default is the current Cinema Azure Container Apps base URL.

The preview decorator currently targets Linux agents because it uses Bash, curl, and jq. Do not advertise Windows/macOS task support until a cross-platform handler is implemented and tested.

## Build the VSIX

A real Marketplace publisher ID is deliberately not committed to the repository. Build from the template only after the owner has a publisher ID:

```bash
export AZURE_DEVOPS_PUBLISHER_ID='your-real-publisher-id'
cp marketplace/azure-devops/vss-extension.template.json /tmp/vss-extension.json
python3 - "$AZURE_DEVOPS_PUBLISHER_ID" /tmp/vss-extension.json <<'PY'
import json, sys
publisher, path = sys.argv[1:]
data = json.load(open(path))
data['publisher'] = publisher
json.dump(data, open(path, 'w'), indent=2)
PY
cp marketplace/azure-devops/dsg-verify.yml /tmp/dsg-verify.yml
(cd /tmp && tfx extension create --manifest-globs vss-extension.json)
```

## External owner actions

Repository automation can build and validate the package. It cannot truthfully create the owner's Marketplace publisher, accept Marketplace terms, supply payout/tax identity, or publish a paid listing without the authenticated owner account.

Before publication, add the final privacy policy, support policy, EULA, pricing copy, publisher ID, and Marketplace assets required by Microsoft. Keep the listing in Preview until a private install proves the decorator behavior on a real Azure Pipeline.
