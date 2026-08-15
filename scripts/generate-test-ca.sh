#!/usr/bin/env bash
# Generate a throwaway private CA plus a local HTTPS server certificate for
# testing Codify's custom-CA plumbing (CUSTOM_CA_BUNDLE /
# WORKER_CA_CERT_HOST_PATH). Certificates are test-only: never ship the CA key
# to a real host or reuse it for production traffic.
#
# Usage:
#   scripts/generate-test-ca.sh [OUTPUT_DIR] [SERVER_NAME ...]
#
# OUTPUT_DIR defaults to ./test-ca. SERVER_NAME defaults to localhost and
# 127.0.0.1; extra names are added as DNS SANs, or IP SANs when they parse as an
# IP literal (e.g. the dev Docker host address).
set -euo pipefail

OUTPUT_DIR="${1:-test-ca}"
shift || true
SERVER_NAMES=("$@")
if [[ ${#SERVER_NAMES[@]} -eq 0 ]]; then
    SERVER_NAMES=(localhost 127.0.0.1)
fi

if [[ -e "${OUTPUT_DIR}/ca.crt" || -e "${OUTPUT_DIR}/ca.key" ]]; then
    echo "Refusing to overwrite an existing CA in ${OUTPUT_DIR}" >&2
    exit 2
fi

mkdir -p "${OUTPUT_DIR}"

CA_CONFIG="${OUTPUT_DIR}/ca-openssl.cnf"
cat >"${CA_CONFIG}" <<'EOF'
[ req ]
default_bits = 2048
distinguished_name = dn
prompt = no
default_md = sha256

[ dn ]
CN = Codify Test Root CA

[ v3_ca ]
basicConstraints = critical,CA:TRUE
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
EOF

openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "${OUTPUT_DIR}/ca.key" \
    -out "${OUTPUT_DIR}/ca.crt" \
    -days 3650 \
    -sha256 \
    -config "${CA_CONFIG}" \
    -extensions v3_ca

SERVER_EXT="${OUTPUT_DIR}/server-ext.cnf"
{
    cat <<'EOF'
[ v3_server ]
basicConstraints = CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[ alt_names ]
EOF
    dns_index=1
    ip_index=1
    for name in "${SERVER_NAMES[@]}"; do
        if [[ "${name}" =~ ^[0-9.]+$ ]] || [[ "${name}" == *:* ]]; then
            echo "IP.${ip_index} = ${name}"
            ip_index=$((ip_index + 1))
        else
            echo "DNS.${dns_index} = ${name}"
            dns_index=$((dns_index + 1))
        fi
    done
} >"${SERVER_EXT}"

openssl req -newkey rsa:2048 -nodes \
    -keyout "${OUTPUT_DIR}/server.key" \
    -out "${OUTPUT_DIR}/server.csr" \
    -sha256 \
    -subj "/CN=${SERVER_NAMES[0]}"

openssl x509 -req \
    -in "${OUTPUT_DIR}/server.csr" \
    -CA "${OUTPUT_DIR}/ca.crt" \
    -CAkey "${OUTPUT_DIR}/ca.key" \
    -CAcreateserial \
    -out "${OUTPUT_DIR}/server.crt" \
    -days 825 \
    -sha256 \
    -extfile "${SERVER_EXT}" \
    -extensions v3_server

chmod 600 "${OUTPUT_DIR}/ca.key" "${OUTPUT_DIR}/server.key"

openssl verify -CAfile "${OUTPUT_DIR}/ca.crt" "${OUTPUT_DIR}/server.crt"

cat <<EOF

Test CA generated in ${OUTPUT_DIR}
  ca.crt      root CA to mount as WORKER_CA_CERT_HOST_PATH / CUSTOM_CA_BUNDLE
  ca.key      root CA private key (test only, keep local)
  server.crt  TLS certificate for a local HTTPS endpoint
  server.key  TLS private key for that endpoint

Local HTTPS smoke (no Docker needed):
  openssl s_server -accept 127.0.0.1:8443 -cert ${OUTPUT_DIR}/server.crt \\
      -key ${OUTPUT_DIR}/server.key -www &
  curl --cacert ${OUTPUT_DIR}/ca.crt https://127.0.0.1:8443/

Worker-container smoke:
  1. Copy ca.crt to the Docker host and set WORKER_CA_CERT_HOST_PATH to it.
  2. Run a task whose Provider/GitLab URL points at the test HTTPS endpoint.
  3. Inside the container, verify:
       curl --cacert /etc/ssl/certs/custom-ca.crt https://<endpoint>/
       git config --get http.sslCAInfo
       python3 -c "import urllib.request; print(urllib.request.urlopen('https://<endpoint>/').status)"
EOF
