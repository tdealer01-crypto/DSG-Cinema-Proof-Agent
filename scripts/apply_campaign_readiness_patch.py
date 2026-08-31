from pathlib import Path

path = Path('.github/workflows/deploy-cinema-production.yml')
text = path.read_text(encoding='utf-8')

old = '''            CURRENT_REVISION=$(az containerapp revision list \\
              --resource-group "$RESOURCE_GROUP" --name "$CINEMA_APP" \\
              --query "[?properties.active].name | [0]" --output tsv)
            az containerapp revision restart \\
              --resource-group "$RESOURCE_GROUP" --name "$CINEMA_APP" \\
              --revision "$CURRENT_REVISION" --output none
'''

new = '''            # The active revision list can briefly contain a deactivated revision
            # while Container Apps is converging after the deployment above. Read
            # latestReadyRevisionName from the app on every retry so this persistence
            # proof restarts the revision Azure currently considers ready rather than
            # a stale list entry.
            RESTARTED=false
            for restart_attempt in $(seq 1 12); do
              CURRENT_REVISION=$(az containerapp show \\
                --resource-group "$RESOURCE_GROUP" --name "$CINEMA_APP" \\
                --query properties.latestReadyRevisionName --output tsv 2>/dev/null || true)
              if [[ -n "$CURRENT_REVISION" && "$CURRENT_REVISION" != "null" ]] && \\
                az containerapp revision restart \\
                  --resource-group "$RESOURCE_GROUP" --name "$CINEMA_APP" \\
                  --revision "$CURRENT_REVISION" --output none; then
                RESTARTED=true
                echo "Restarted current ready Cinema revision $CURRENT_REVISION."
                break
              fi
              sleep 5
            done
            if [[ "$RESTARTED" != "true" ]]; then
              echo 'Could not restart a current ready Cinema revision after refreshing Azure revision state.' >&2
              az containerapp revision list \\
                --resource-group "$RESOURCE_GROUP" --name "$CINEMA_APP" \\
                --query "[].{name:name,active:properties.active,state:properties.runningState}" \\
                --output table >&2 || true
              exit 1
            fi
'''

count = text.count(old)
if count != 1:
    raise SystemExit(f'expected exactly one restart block, found {count}')

path.write_text(text.replace(old, new), encoding='utf-8')
print('patched exactly one Azure Container Apps restart block')
