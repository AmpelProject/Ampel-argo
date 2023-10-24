<img align="left" src="https://desycloud.desy.de/index.php/s/99Jkcyzn92rRpHF/preview" width="150" height="150"/>
<br>

# AMPEL-argo

Translates Ampel analysis schemas into Argo Workflows templates.

## Usage

(for the deployment at https://ampel-dev.ia.zeuthen.desy.de)

1. Obtain an API token from the [Ampel dashboard](https://ampel.zeuthen.desy.de/live/dashboard/tokens)
2. Validate an Ampel jobfile with
```
curl -k -X 'POST' \
  'https://ampel-dev.ia.zeuthen.desy.de/jobs/v1/lint' \
  -H 'accept: application/json'
  -H "Authorization: Bearer $AMPEL_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "$(yq your_jobfile.yml -o json)" \
  | yq . -P
```
where `AMPEL_TOKEN` is your API token from step 1
3. Create an Argo workflow template from your jobfile (skipping validation)
```
curl -k -X 'POST' \
  'https://ampel-dev.ia.zeuthen.desy.de/jobs/v1?validate=0' \
  -H 'accept: application/json'
  -H "Authorization: Bearer $AMPEL_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "$(yq your_jobfile.yml -o json)" \
  | yq . -P
```
4. Submit a job from your template using the [Argo UI](https://ampel-dev.ia.zeuthen.desy.de/argo/workflow-templates?namespace=ampel) (alternatively, the [Argo CLI](https://argoproj.github.io/argo-workflows/walk-through/argo-cli/))