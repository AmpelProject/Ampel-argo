install with

helm repo add argo https://argoproj.github.io/argo-helm

kubectl create namespace ampel
helm upgrade --install argo argo/argo-workflows -n ampel -f custom-values.yaml --version 0.11.2

get access token with

ARGO_TOKEN=$(kubectl get secret -n ampel $(kubectl get sa -n ampel argo-argo-workflows-server -o=jsonpath='{.secrets[0].name}') -o json | jq -r '.data.token|@base64d')

