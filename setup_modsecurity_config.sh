#!/bin/bash

# ModSecurity configuration setup function
setup_modsecurity_config() {
    # Main ModSecurity configuration
    sudo tee ${MODSECURITY_CONF_DIR:-/etc/nginx/modsec}/modsecurity.conf > /dev/null << 'EOF'
SecRuleEngine On
SecRequestBodyAccess On
SecRequestBodyLimit 13107200
SecRequestBodyNoFilesLimit 131072
SecRequestBodyInMemoryLimit 131072
SecRequestBodyLimitAction Reject
SecRule REQUEST_HEADERS:Content-Type "text/xml" "id:'200000',phase:1,t:none,t:lowercase,pass,nolog,ctl:requestBodyProcessor=XML"
SecRule REQUEST_HEADERS:Content-Type "application/xml" "id:'200001',phase:1,t:none,t:lowercase,pass,nolog,ctl:requestBodyProcessor=XML"
SecRule REQUEST_HEADERS:Content-Type "text/json" "id:'200002',phase:1,t:none,t:lowercase,pass,nolog,ctl:requestBodyProcessor=JSON"
SecRule REQUEST_HEADERS:Content-Type "application/json" "id:'200003',phase:1,t:none,t:lowercase,pass,nolog,ctl:requestBodyProcessor=JSON"
SecResponseBodyAccess On
SecResponseBodyMimeType text/plain text/html text/xml
SecResponseBodyLimit 524288
SecResponseBodyLimitAction ProcessPartial
SecTmpDir /tmp/
SecDataDir /tmp/
SecAuditEngine RelevantOnly
SecAuditLogRelevantStatus "^(?:5|4(?!04))"
SecAuditLogParts ABIJDEFHZ
SecAuditLogType Serial
SecAuditLog /var/log/nginx/modsec_audit.log
SecArgumentSeparator &
SecCookieFormat 0
SecUnicodeMapFile unicode.mapping 20127
SecStatusEngine On
EOF

    # Main configuration file
    sudo tee ${MODSECURITY_CONF_DIR:-/etc/nginx/modsec}/main.conf > /dev/null << EOF
Include ${MODSECURITY_CONF_DIR:-/etc/nginx/modsec}/modsecurity.conf
Include ${MODSECURITY_RULES_DIR:-/usr/share/modsecurity-crs}/crs-setup.conf
Include ${MODSECURITY_RULES_DIR:-/usr/share/modsecurity-crs}/rules/*.conf
EOF

    # Copy CRS setup file
    sudo cp ${MODSECURITY_RULES_DIR:-/usr/share/modsecurity-crs}/crs-setup.conf.example ${MODSECURITY_RULES_DIR:-/usr/share/modsecurity-crs}/crs-setup.conf
}

# Call the function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_modsecurity_config
fi