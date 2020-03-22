# Save to ./setup.sh
#   #+name: load kind

if [ ! -z "$DEBUG" ]; then
    set -x
fi
export KUBEMACS_IMAGE="${KUBEMACS_IMAGE:-gcr.io/apisnoop/kubemacs:0.9.32}"
export KUSTOMIZE_PATH="${KUSTOMIZE_PATH:-https://github.com/cncf/apisnoop/deployment/k8s/local}"
export KIND_IMAGE="${KIND_IMAGE:- kindest/node:v1.17.0@sha256:9512edae126da271b66b990b6fff768fbb7cd786c7d39e86bdf55906352fdf62}"
export DEFAULT_NS="${DEFAULT_NS:-ii}"
if read -p "Press enter to destroy your current kind cluster, ^C to abort "; then
    kind delete cluster
fi
docker pull $KIND_IMAGE
docker pull $KUBEMACS_IMAGE
IMAGES=$(kubectl kustomize "$KUSTOMIZE_PATH" | grep image: | sed 's/.*:\ \(.*\)/\1/' | sort | uniq )
echo $IMAGES | xargs -n 1 docker pull
curl https://raw.githubusercontent.com/cncf/apisnoop/master/deployment/k8s/kind-cluster-config.yaml -o kind-cluster-config.yaml
kind create cluster --config kind-cluster-config.yaml --image $KIND_IMAGE
# this caches all container images used by your podspecs
kind load docker-image --nodes kind-worker $KUBEMACS_IMAGE 
echo $IMAGES | xargs -n 1 kind load docker-image
kubectl create ns $DEFAULT_NS
kubectl config set-context $(kubectl config current-context) --namespace=$DEFAULT_NS
kubectl apply -k "$KUSTOMIZE_PATH/kubemacs"
echo "Waiting for Kubemacs StatefulSet to have 1 ready Replica..."
while [ "$(kubectl get statefulset kubemacs -o json | jq .status.readyReplicas)" != 1 ]; do
  sleep 1s
done
kubectl wait --for=condition=Ready pod/kubemacs-0
echo Run the following:
echo kubectl exec -ti kubemacs-0 -- attach
