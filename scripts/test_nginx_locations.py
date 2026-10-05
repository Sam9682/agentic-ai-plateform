#!/usr/bin/env python3
"""Test script for nginx dynamic location management"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.nginx_manager import (
    insert_location_block,
    remove_location_block,
    generate_location_block,
    read_nginx_config,
    test_nginx_config
)

def test_generate_location():
    """Test location block generation"""
    print("Testing location block generation...")
    block = generate_location_block(2, "ai-staticwebsite", "https://www.swautomorph.com:6217", "https://www.swautomorph.com:6217")
    
    assert "/2/ai-staticwebsite" in block
    # nginx must proxy to the HTTP endpoint (HTTP scheme + HTTP port, the first
    # port of the pair), not the stored HTTPS URL (https://...:6217).
    assert "http://www.swautomorph.com:6216" in block
    assert "https://www.swautomorph.com:6217" not in block
    assert "proxy_pass" in block
    assert "rewrite" in block
    
    print("✓ Location block generation works")
    print(block)

def test_insert_location():
    """Test inserting location block"""
    print("\nTesting location block insertion...")
    
    # Test with sample data
    result = insert_location_block(2, "ai-staticwebsite", "https://www.swautomorph.com:6217",  "https://www.swautomorph.com:6217")
    
    if result:
        print("✓ Location block inserted successfully")
        
        # Verify it's in the config
        config = read_nginx_config()
        if "/2/ai-staticwebsite" in config:
            print("✓ Location block found in config")
        else:
            print("✗ Location block not found in config")
    else:
        print("✗ Failed to insert location block")

def test_remove_location():
    """Test removing location block"""
    print("\nTesting location block removal...")
    
    result = remove_location_block(2, "ai-staticwebsite")
    
    if result:
        print("✓ Location block removed successfully")
        
        # Verify it's removed from config
        config = read_nginx_config()
        if "/2/ai-staticwebsite" not in config:
            print("✓ Location block removed from config")
        else:
            print("✗ Location block still in config")
    else:
        print("✗ Failed to remove location block")

def main():
    print("=== Nginx Dynamic Location Tests ===\n")
    
    try:
        test_generate_location()
        test_insert_location()
        test_remove_location()
        
        print("\n=== All tests completed ===")
        return 0
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
