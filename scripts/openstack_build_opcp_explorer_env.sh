#!/bin/bash

# Set variables
NETWORK_NAME="partipolia-network"
SUBNET_NAME="partipolia-subnet"
INSTANCE_NAME="partipolia-instance-main"
KEYPAIR_NAME="partipolia-key1"
FLAVOR_NAME="b3-8"
IMAGE_NAME="Ubuntu 26.04"
EXTERNAL_NETWORK_NAME="Ext-Net"
GATEWAY_NAME="partipolia-gateway"

# Create keypair if it doesn't exist
if ! openstack keypair show "$KEYPAIR_NAME" > /dev/null 2>&1; then
    echo "Creating keypair..."
    openstack keypair create "$KEYPAIR_NAME" > ~/.ssh/"$KEYPAIR_NAME".pem
    chmod 600 ~/.ssh/"$KEYPAIR_NAME".pem
fi

# Create network if it doesn't exist
if ! openstack network show "$NETWORK_NAME" > /dev/null 2>&1; then
    echo "Creating network..."
    NETWORK_ID=$(openstack network create "$NETWORK_NAME" --internal -f value -c id)
    echo "Network UUID: $NETWORK_ID"
    
    # Create subnet
    echo "Creating subnet..."
    openstack subnet create \
        --network "$NETWORK_ID" \
        --subnet-range 192.168.0.0/24 \
        --gateway 192.168.0.1 \
        --dns-nameserver 8.8.8.8 \
        "$SUBNET_NAME"
fi

# Create router/gateway if it doesn't exist
if ! openstack router show "$GATEWAY_NAME" > /dev/null 2>&1; then
    echo "Creating router/gateway..."
    GATEWAY_ID=$(openstack router create "$GATEWAY_NAME" -f value -c id)
    echo "Router UUID: $GATEWAY_ID"
    
    # Get the network ID for the private network
    NETWORK_ID=$(openstack network show "$NETWORK_NAME" -f value -c id)
    
    # Attach the router to the private network
    openstack router add subnet "$GATEWAY_ID" "$SUBNET_NAME"
    
    # Set the external network as the gateway for the router
    # Note: This assumes the external network exists
    if openstack network show "$EXTERNAL_NETWORK_NAME" > /dev/null 2>&1; then
        openstack router set --external-gateway "$EXTERNAL_NETWORK_NAME" "$GATEWAY_ID"
    else
        echo "Warning: External network '$EXTERNAL_NETWORK_NAME' not found. Router created but not connected to external network."
    fi
fi

# Create instance
if ! openstack server show "$INSTANCE_NAME" > /dev/null 2>&1; then
    echo "Creating instance..."
    openstack server create \
        --image "$IMAGE_NAME" \
        --flavor "$FLAVOR_NAME" \
        --key-name "$KEYPAIR_NAME" \
        --network "$NETWORK_NAME" \
        --user-data cloud-init-script.yaml \
        "$INSTANCE_NAME"
fi

# Wait for instance to be active
echo "Waiting for instance to become active..."
while true; do
    STATUS=$(openstack server show "$INSTANCE_NAME" -f value -c status)
    if [ "$STATUS" = "ACTIVE" ]; then
        break
    fi
    sleep 5
done

# Create and associate floating IP
echo "Creating and associating floating IP..."
FLOATING_IP=$(openstack floating ip create "$EXTERNAL_NETWORK_NAME" -f value -c floating_ip_address)
if [ -n "$FLOATING_IP" ]; then
    echo "Associating floating IP $FLOATING_IP with instance $INSTANCE_NAME"
    openstack server add floating ip "$INSTANCE_NAME" "$FLOATING_IP"
else
    echo "Error: Failed to create floating IP"
    exit 1
fi