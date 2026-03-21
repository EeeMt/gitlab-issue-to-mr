#!/bin/bash
set -e

# Backend service entrypoint script
# Handles custom CA certificate installation before starting the application

echo "========================================"
echo "GitLab Issue to MR Backend Service"
echo "========================================"

# Custom CA certificate installation
# When a custom CA bundle is provided, install it into the system trust store,
# configure git, Python, Node.js, and Java to use it.
if [ -n "${CUSTOM_CA_BUNDLE}" ] && [ -f "${CUSTOM_CA_BUNDLE}" ]; then
    echo "Installing custom CA certificate from ${CUSTOM_CA_BUNDLE}"
    cp "${CUSTOM_CA_BUNDLE}" /usr/local/share/ca-certificates/custom-ca.crt
    update-ca-certificates --fresh 2>/dev/null || true
    
    # Configure git SSL verification
    git config --global http.sslVerify true
    git config --global http.sslCAInfo "${CUSTOM_CA_BUNDLE}"
    
    # Python requests / httpx pick this up automatically
    export REQUESTS_CA_BUNDLE="${CUSTOM_CA_BUNDLE}"
    export SSL_CERT_FILE="${CUSTOM_CA_BUNDLE}"
    
    # Node.js (if used) picks up extra CA certs from this env var
    export NODE_EXTRA_CA_CERTS="${CUSTOM_CA_BUNDLE}"
    
    # Import into JDK truststore so Java tools verify the CA
    if [ -n "${JAVA_HOME}" ] && [ -x "${JAVA_HOME}/bin/keytool" ]; then
        echo "Importing custom CA into JDK truststore..."
        "${JAVA_HOME}/bin/keytool" -importcert -noprompt -trustcacerts \
            -alias custom-ca \
            -file "${CUSTOM_CA_BUNDLE}" \
            -keystore "${JAVA_HOME}/lib/security/cacerts" \
            -storepass changeit 2>/dev/null || true
        echo "Custom CA imported into JDK truststore"
    fi
    
    echo "Custom CA installed; SSL verification enabled"
else
    echo "No custom CA bundle provided, using system default certificates"
fi

echo "========================================"
echo "Starting backend service..."
echo "========================================"

# Run database migrations if AUTO_MIGRATE is true
if [ "${AUTO_MIGRATE}" = "true" ]; then
    echo "Running database migrations..."
    python3 -m alembic upgrade head
fi

# If command arguments are passed, run them; otherwise default to uvicorn
if [ $# -gt 0 ]; then
    echo "Running custom command: $@"
    exec "$@"
else
    echo "Starting backend service with uvicorn..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
fi
